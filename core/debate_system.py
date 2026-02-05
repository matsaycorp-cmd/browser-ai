# 多AI对抗验证系统

import asyncio
import json
import logging
import re
import time
from enum import Enum

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════

DEBATE_CONFIG = {
    "enabled": True,                    # 是否启用对抗验证
    "min_value_threshold": 500,         # 货值超过此值才启用
    "confidence_threshold": 80,         # 低于此置信度需人工复核
    "timeout_per_agent": 60,            # 每个Agent超时时间(秒)
    "retry_on_failure": True,           # Agent失败时是否重试
    "parallel_critic_verify": False,    # Critic和Verifier是否并行
}


# ══════════════════════════════════════════════════════════════
# 角色定义
# ══════════════════════════════════════════════════════════════

class AgentRole(Enum):
    """Agent角色枚举"""
    FINDER = "finder"        # 发现者：搜索信息
    CRITIC = "critic"        # 批评者：挑错质疑
    VERIFIER = "verifier"    # 验证者：证据验证
    JUDGE = "judge"          # 裁判：最终决策


# ══════════════════════════════════════════════════════════════
# 基类：DebateAgent
# ══════════════════════════════════════════════════════════════

class DebateAgent:
    """对抗Agent基类"""

    def __init__(self, role: AgentRole, controller, name: str):
        """
        初始化Agent。

        Args:
            role: AgentRole枚举
            controller: AI控制器（ChatGPT/Claude/Gemini）
            name: 显示名称
        """
        self.role = role
        self.controller = controller
        self.name = name

    async def execute(self, context: dict) -> dict:
        """
        根据角色执行对应任务。

        Args:
            context: 执行上下文

        Returns:
            结构化结果
        """
        raise NotImplementedError("子类必须实现execute方法")

    def _build_prompt(self, context: dict) -> str:
        """
        根据角色构建prompt。

        Args:
            context: 上下文信息

        Returns:
            构建好的prompt
        """
        raise NotImplementedError("子类必须实现_build_prompt方法")

    async def _send_and_get_response(self, prompt: str, timeout: int = 60) -> str:
        """发送消息并获取响应。"""
        try:
            await asyncio.wait_for(
                self.controller.send_message(prompt),
                timeout=timeout,
            )
            await asyncio.wait_for(
                self.controller.wait_response(),
                timeout=timeout,
            )
            response = await self.controller.get_last_response()
            return response or ""
        except asyncio.TimeoutError:
            logger.error("%s (%s) 响应超时", self.name, self.role.value)
            raise
        except Exception as e:
            logger.error("%s (%s) 执行失败: %s", self.name, self.role.value, e)
            raise

    def _parse_json_response(self, response: str) -> dict:
        """解析JSON响应。"""
        if not response:
            return {"error": "Empty response"}

        # 尝试直接解析
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # 尝试提取JSON块
        patterns = [
            r'```json\s*([\s\S]*?)\s*```',
            r'```\s*([\s\S]*?)\s*```',
            r'\{[\s\S]*\}',
        ]

        for pattern in patterns:
            match = re.search(pattern, response)
            if match:
                try:
                    json_str = match.group(1) if '```' in pattern else match.group(0)
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    continue

        # 解析失败
        logger.warning("%s: 无法解析JSON响应", self.name)
        return {"raw_response": response, "parse_error": True}


# ══════════════════════════════════════════════════════════════
# FinderAgent (发现者)
# ══════════════════════════════════════════════════════════════

class FinderAgent(DebateAgent):
    """发现者Agent - 负责搜索信息"""

    def __init__(self, controller, name: str = "Finder"):
        super().__init__(AgentRole.FINDER, controller, name)

    async def execute(self, context: dict) -> dict:
        """执行搜索任务。"""
        task_type = context.get("task_type", "contact")

        if task_type == "contact":
            return await self.find_contacts(
                context.get("company_name", ""),
                context.get("country", ""),
            )
        elif task_type == "personnel":
            return await self.find_personnel_info(
                context.get("personnel_info", {}),
            )
        else:
            prompt = self._build_prompt(context)
            response = await self._send_and_get_response(prompt)
            return self._parse_json_response(response)

    async def find_contacts(self, company_name: str, country: str) -> dict:
        """搜索公司联系方式。"""
        prompt = f"""请搜索 {company_name} ({country}) 的联系方式。

需要找到：
1. 官方邮箱（优先export/sales/international部门）
2. 电话号码
3. 官方网站
4. 联系人姓名（如能找到）

请列出所有找到的信息，包括来源。

请返回JSON格式：
{{
  "emails": [
    {{"address": "邮箱地址", "department": "部门", "source": "信息来源"}}
  ],
  "phones": [
    {{"number": "电话号码", "type": "类型(总机/直线/手机)", "source": "信息来源"}}
  ],
  "websites": [
    {{"url": "网址", "type": "类型(官网/LinkedIn/其他)", "source": "来源"}}
  ],
  "contacts": [
    {{"name": "姓名", "position": "职位", "email": "邮箱", "source": "来源"}}
  ],
  "company_info": {{
    "full_name": "公司全名",
    "address": "地址",
    "industry": "行业"
  }},
  "search_notes": "搜索过程备注"
}}

只返回JSON，不要其他内容。"""

        logger.info("[%s] 搜索联系方式: %s (%s)", self.name, company_name, country)
        response = await self._send_and_get_response(prompt)
        result = self._parse_json_response(response)
        result["raw_response"] = response
        result["company_name"] = company_name
        result["country"] = country
        return result

    async def find_personnel_info(self, personnel_info: dict) -> dict:
        """搜索人员/公司的详细信息。"""
        info_text = json.dumps(personnel_info, ensure_ascii=False, indent=2)

        prompt = f"""请搜索以下人员/公司的更多信息：

{info_text}

需要找到：
1. 官方网站或平台主页
2. 联系方式
3. 业务范围和专长
4. 客户评价和口碑
5. 公司注册信息（如适用）

请返回JSON格式：
{{
  "official_website": "网址",
  "contact_info": {{
    "email": "邮箱",
    "phone": "电话",
    "address": "地址"
  }},
  "business_scope": ["业务1", "业务2"],
  "reviews": [
    {{"source": "来源", "rating": 评分, "comment": "评价内容"}}
  ],
  "registration": {{
    "found": true/false,
    "company_name": "注册名称",
    "registration_date": "注册日期",
    "status": "状态"
  }},
  "additional_info": "其他发现"
}}

只返回JSON。"""

        logger.info("[%s] 搜索人员信息", self.name)
        response = await self._send_and_get_response(prompt)
        result = self._parse_json_response(response)
        result["raw_response"] = response
        result["original_info"] = personnel_info
        return result

    def _build_prompt(self, context: dict) -> str:
        """构建通用搜索prompt。"""
        query = context.get("query", "")
        return f"请搜索以下信息并返回结构化结果：\n{query}"


# ══════════════════════════════════════════════════════════════
# CriticAgent (批评者)
# ══════════════════════════════════════════════════════════════

class CriticAgent(DebateAgent):
    """批评者Agent - 负责挑错质疑"""

    def __init__(self, controller, name: str = "Critic"):
        super().__init__(AgentRole.CRITIC, controller, name)

    async def execute(self, context: dict) -> dict:
        """执行批评任务。"""
        finder_result = context.get("finder_result", {})
        company_name = context.get("company_name", "")
        country = context.get("country", "")

        return await self.critique(finder_result, company_name, country)

    async def critique(self, finder_result: dict, company_name: str, country: str) -> dict:
        """对发现者的结果进行批评和质疑。"""
        # 格式化finder结果
        result_text = json.dumps(finder_result, ensure_ascii=False, indent=2)

        prompt = f"""你是一个专门挑错的审核员。请严格审查以下为 {company_name} ({country}) 找到的联系方式：

{result_text}

请逐一检查并指出问题：

1. 邮箱域名检查：
   - 域名是否与公司官网匹配？
   - 是否可能是钓鱼/仿冒邮箱？
   - 是否是通用邮箱(gmail/hotmail)而非企业邮箱？

2. 同名公司检查：
   - 是否可能是同名但不同的公司？
   - 国家/地区是否匹配？

3. 信息一致性：
   - 电话区号与公司所在地是否匹配？
   - 多个来源的信息是否矛盾？

4. 可疑信号：
   - 信息是否过于完美/模板化？
   - 是否有AI生成的痕迹？

对每条信息给出状态标记：
- valid: 可能有效 - 未发现明显问题
- uncertain: 需要验证 - 有疑点但不确定
- suspicious: 可疑 - 发现明确问题

请返回JSON格式：
{{
  "critiques": [
    {{
      "item": "被检查的信息",
      "type": "email/phone/website/contact",
      "status": "valid/uncertain/suspicious",
      "issues": ["问题1", "问题2"],
      "risk_level": 0-100
    }}
  ],
  "overall_concerns": ["总体担忧1", "总体担忧2"],
  "recommended_verification": ["建议验证点1", "建议验证点2"],
  "summary": "一句话总结审查结果"
}}

只返回JSON，不要其他内容。"""

        logger.info("[%s] 批评审查: %s", self.name, company_name)
        response = await self._send_and_get_response(prompt)
        result = self._parse_json_response(response)
        result["raw_response"] = response
        return result

    async def critique_personnel(self, personnel_info: dict, finder_result: dict) -> dict:
        """对人员搜索结果进行批评。"""
        info_text = json.dumps(
            {"original": personnel_info, "found": finder_result},
            ensure_ascii=False,
            indent=2,
        )

        prompt = f"""你是一个专门挑错的审核员。请严格审查以下人员/公司信息的真实性：

{info_text}

请检查：

1. 身份真实性：
   - 是否有真实的身份证明？
   - 平台账号是否真实活跃？
   - 是否有虚假评价的迹象？

2. 资质验证：
   - 声称的资质是否可验证？
   - 工作经历是否合理？
   - 技能描述是否可信？

3. 风险信号：
   - 价格是否异常（过低/过高）？
   - 是否有诈骗的常见特征？
   - 沟通方式是否正规？

请返回JSON格式：
{{
  "critiques": [
    {{
      "item": "被检查的信息",
      "category": "identity/qualification/risk",
      "status": "valid/uncertain/suspicious",
      "issues": ["问题1"],
      "risk_level": 0-100
    }}
  ],
  "red_flags": ["危险信号1", "危险信号2"],
  "recommended_verification": ["建议验证点1"],
  "trust_assessment": "初步信任评估"
}}

只返回JSON。"""

        logger.info("[%s] 批评人员信息", self.name)
        response = await self._send_and_get_response(prompt)
        result = self._parse_json_response(response)
        result["raw_response"] = response
        return result

    def _build_prompt(self, context: dict) -> str:
        """构建批评prompt。"""
        data = context.get("data", {})
        return f"请对以下信息进行严格审查：\n{json.dumps(data, ensure_ascii=False)}"


# ══════════════════════════════════════════════════════════════
# VerifierAgent (验证者)
# ══════════════════════════════════════════════════════════════

class VerifierAgent(DebateAgent):
    """验证者Agent - 负责证据验证"""

    def __init__(self, controller, name: str = "Verifier"):
        super().__init__(AgentRole.VERIFIER, controller, name)

    async def execute(self, context: dict) -> dict:
        """执行验证任务。"""
        finder_result = context.get("finder_result", {})
        critic_result = context.get("critic_result", {})
        company_name = context.get("company_name", "")
        country = context.get("country", "")

        return await self.verify(finder_result, critic_result, company_name, country)

    async def verify(
        self,
        finder_result: dict,
        critic_result: dict,
        company_name: str,
        country: str,
    ) -> dict:
        """验证发现者的结果，回应批评者的质疑。"""
        finder_text = json.dumps(finder_result, ensure_ascii=False, indent=2)
        critic_text = json.dumps(critic_result, ensure_ascii=False, indent=2)

        prompt = f"""你是一个证据收集专家。请为以下信息寻找证据支持或反驳：

公司：{company_name} ({country})

待验证信息：
{finder_text}

批评者的质疑：
{critic_text}

请尝试验证：

1. 官网验证：
   - 访问公司官网的联系页面
   - 查找是否列出了这些邮箱/电话
   - 记录官网URL作为证据

2. 公司注册信息：
   - 搜索公司注册资料
   - 验证公司全名和地址
   - 确认是否与搜索目标为同一公司

3. 域名验证：
   - 检查邮箱域名的whois信息
   - 域名所有者是否与公司相关

4. 社交媒体/LinkedIn：
   - 搜索公司官方LinkedIn
   - 验证联系方式是否一致

5. 第三方来源：
   - 行业目录
   - 新闻报道中提到的联系方式

请返回JSON格式：
{{
  "verifications": [
    {{
      "item": "被验证的信息",
      "type": "email/phone/website/contact",
      "verified": true/false/"uncertain",
      "evidence": "证据描述",
      "evidence_url": "证据链接(如有)",
      "confidence": 0-100
    }}
  ],
  "company_confirmed": true/false,
  "company_evidence": "确认公司身份的证据",
  "critic_responses": [
    {{
      "concern": "批评者的质疑",
      "response": "验证结果",
      "resolved": true/false
    }}
  ],
  "additional_findings": ["额外发现1", "额外发现2"],
  "verification_summary": "验证总结"
}}

只返回JSON，不要其他内容。"""

        logger.info("[%s] 验证信息: %s", self.name, company_name)
        response = await self._send_and_get_response(prompt)
        result = self._parse_json_response(response)
        result["raw_response"] = response
        return result

    async def verify_personnel(
        self,
        personnel_info: dict,
        finder_result: dict,
        critic_result: dict,
    ) -> dict:
        """验证人员信息。"""
        context_text = json.dumps(
            {
                "original": personnel_info,
                "found": finder_result,
                "critiques": critic_result,
            },
            ensure_ascii=False,
            indent=2,
        )

        prompt = f"""你是一个证据收集专家。请验证以下人员/公司的真实性：

{context_text}

请尝试验证：

1. 平台账号验证：
   - 账号创建时间和活跃度
   - 历史订单/项目记录
   - 真实评价数量

2. 身份验证：
   - 是否有可验证的身份信息
   - 社交媒体一致性
   - 专业资质证明

3. 业务验证：
   - 是否有真实的业务案例
   - 客户反馈的真实性
   - 行业口碑

请返回JSON格式：
{{
  "verifications": [
    {{
      "item": "被验证的信息",
      "verified": true/false/"uncertain",
      "evidence": "证据描述",
      "confidence": 0-100
    }}
  ],
  "identity_confirmed": true/false/"uncertain",
  "identity_evidence": "身份验证证据",
  "business_legitimacy": "业务合法性评估",
  "verification_summary": "验证总结"
}}

只返回JSON。"""

        logger.info("[%s] 验证人员信息", self.name)
        response = await self._send_and_get_response(prompt)
        result = self._parse_json_response(response)
        result["raw_response"] = response
        return result

    def _build_prompt(self, context: dict) -> str:
        """构建验证prompt。"""
        data = context.get("data", {})
        return f"请验证以下信息的真实性：\n{json.dumps(data, ensure_ascii=False)}"


# ══════════════════════════════════════════════════════════════
# JudgeAgent (裁判)
# ══════════════════════════════════════════════════════════════

class JudgeAgent(DebateAgent):
    """裁判Agent - 负责最终决策"""

    def __init__(self, controller, name: str = "Judge"):
        super().__init__(AgentRole.JUDGE, controller, name)

    async def execute(self, context: dict) -> dict:
        """执行裁判任务。"""
        finder_result = context.get("finder_result", {})
        critic_result = context.get("critic_result", {})
        verifier_result = context.get("verifier_result", {})
        company_name = context.get("company_name", "")

        return await self.judge(finder_result, critic_result, verifier_result, company_name)

    async def judge(
        self,
        finder_result: dict,
        critic_result: dict,
        verifier_result: dict,
        company_name: str,
    ) -> dict:
        """综合三方意见做出最终判定。"""
        finder_text = json.dumps(finder_result, ensure_ascii=False, indent=2)
        critic_text = json.dumps(critic_result, ensure_ascii=False, indent=2)
        verifier_text = json.dumps(verifier_result, ensure_ascii=False, indent=2)

        prompt = f"""你是最终裁判。请综合以下三方意见，做出最终判定：

=== 发现者的结果 ===
{finder_text}

=== 批评者的质疑 ===
{critic_text}

=== 验证者的证据 ===
{verifier_text}

目标公司：{company_name}

请做出最终判定：

1. 对每条信息：
   - 采纳/排除/待定
   - 置信度(0-100)
   - 理由

2. 总体评估：
   - 整体可信度
   - 是否需要人工复核
   - 风险等级

请返回JSON格式：
{{
  "final_decision": {{
    "accepted": [
      {{
        "item": "信息内容",
        "type": "email/phone/website/contact",
        "confidence": 95,
        "reason": "采纳理由"
      }}
    ],
    "rejected": [
      {{
        "item": "信息内容",
        "type": "email/phone/website/contact",
        "reason": "排除理由"
      }}
    ],
    "pending": [
      {{
        "item": "信息内容",
        "type": "email/phone/website/contact",
        "reason": "需要进一步验证的原因"
      }}
    ]
  }},
  "overall_confidence": 0-100,
  "risk_level": "low/medium/high",
  "needs_human_review": true/false,
  "review_reason": "需要人工复核的原因(如适用)",
  "recommended_action": "建议的下一步行动",
  "summary": "一句话总结"
}}

只返回JSON，不要其他内容。"""

        logger.info("[%s] 最终裁决: %s", self.name, company_name)
        response = await self._send_and_get_response(prompt)
        result = self._parse_json_response(response)
        result["raw_response"] = response
        return result

    async def judge_personnel(
        self,
        personnel_info: dict,
        finder_result: dict,
        critic_result: dict,
        verifier_result: dict,
    ) -> dict:
        """对人员验证做出最终判定。"""
        context_text = json.dumps(
            {
                "original": personnel_info,
                "found": finder_result,
                "critiques": critic_result,
                "verification": verifier_result,
            },
            ensure_ascii=False,
            indent=2,
        )

        prompt = f"""你是最终裁判。请综合以下信息，对这个人员/公司做出最终信任判定：

{context_text}

请做出最终判定：

1. 身份可信度：这个人/公司是否真实存在？
2. 业务能力：是否有能力完成验货工作？
3. 风险评估：合作风险有多大？
4. 建议：是否推荐合作？

请返回JSON格式：
{{
  "final_decision": {{
    "identity_trust": {{
      "score": 0-100,
      "assessment": "身份评估"
    }},
    "capability_trust": {{
      "score": 0-100,
      "assessment": "能力评估"
    }},
    "risk_assessment": {{
      "level": "low/medium/high",
      "factors": ["风险因素1", "风险因素2"]
    }}
  }},
  "overall_trust_score": 0-100,
  "recommendation": "strongly_recommend/recommend/cautious/not_recommend",
  "suggested_max_value": "建议最高货值(美元)",
  "needs_human_review": true/false,
  "review_reason": "原因",
  "summary": "一句话总结"
}}

只返回JSON。"""

        logger.info("[%s] 人员最终裁决", self.name)
        response = await self._send_and_get_response(prompt)
        result = self._parse_json_response(response)
        result["raw_response"] = response
        return result

    def _build_prompt(self, context: dict) -> str:
        """构建裁判prompt。"""
        data = context.get("data", {})
        return f"请综合以下信息做出最终判定：\n{json.dumps(data, ensure_ascii=False)}"


# ══════════════════════════════════════════════════════════════
# DebateOrchestrator (对抗编排器)
# ══════════════════════════════════════════════════════════════

class DebateOrchestrator:
    """对抗验证编排器 - 协调多个Agent进行对抗验证"""

    def __init__(self, controllers: dict):
        """
        初始化编排器。

        Args:
            controllers: AI控制器字典 {"chatgpt": ctrl, "claude": ctrl, ...}
        """
        self.controllers = controllers
        self.agents: dict[AgentRole, DebateAgent] = {}
        self.debate_log: list[dict] = []
        self.config = dict(DEBATE_CONFIG)

        # 分配Agent
        self._assign_agents()

    def _assign_agents(self):
        """根据可用控制器分配Agent角色。"""
        available = list(self.controllers.keys())

        if not available:
            logger.warning("没有可用的AI控制器")
            return

        # 默认分配策略
        # Finder: ChatGPT（擅长搜索）
        # Critic: Claude（擅长分析）
        # Verifier: Gemini
        # Judge: Claude（擅长综合判断）

        finder_ai = "chatgpt" if "chatgpt" in available else available[0]
        critic_ai = "claude" if "claude" in available else available[0]
        verifier_ai = "gemini" if "gemini" in available else (
            "chatgpt" if "chatgpt" in available else available[0]
        )
        judge_ai = "claude" if "claude" in available else available[0]

        self.agents[AgentRole.FINDER] = FinderAgent(
            self.controllers[finder_ai],
            f"Finder({finder_ai})",
        )
        self.agents[AgentRole.CRITIC] = CriticAgent(
            self.controllers[critic_ai],
            f"Critic({critic_ai})",
        )
        self.agents[AgentRole.VERIFIER] = VerifierAgent(
            self.controllers[verifier_ai],
            f"Verifier({verifier_ai})",
        )
        self.agents[AgentRole.JUDGE] = JudgeAgent(
            self.controllers[judge_ai],
            f"Judge({judge_ai})",
        )

        logger.info(
            "Agent分配完成: Finder=%s, Critic=%s, Verifier=%s, Judge=%s",
            finder_ai, critic_ai, verifier_ai, judge_ai,
        )

    def reassign_agent(self, role: AgentRole, ai_name: str):
        """重新分配某个角色的AI。"""
        if ai_name not in self.controllers:
            raise ValueError(f"未知的AI: {ai_name}")

        controller = self.controllers[ai_name]
        if role == AgentRole.FINDER:
            self.agents[role] = FinderAgent(controller, f"Finder({ai_name})")
        elif role == AgentRole.CRITIC:
            self.agents[role] = CriticAgent(controller, f"Critic({ai_name})")
        elif role == AgentRole.VERIFIER:
            self.agents[role] = VerifierAgent(controller, f"Verifier({ai_name})")
        elif role == AgentRole.JUDGE:
            self.agents[role] = JudgeAgent(controller, f"Judge({ai_name})")

        logger.info("重新分配 %s 为 %s", role.value, ai_name)

    # ── 对抗流程 ──────────────────────────────────────────

    async def run_debate(self, task_type: str, params: dict) -> dict:
        """
        完整执行一轮对抗验证。

        Args:
            task_type: 任务类型 (contact/personnel)
            params: 任务参数

        Returns:
            完整的对抗结果
        """
        self.debate_log = []
        start_time = time.time()

        logger.info("开始对抗验证: %s", task_type)

        try:
            if task_type == "contact":
                result = await self.run_contact_verification(
                    params.get("company_name", ""),
                    params.get("country", ""),
                )
            elif task_type == "personnel":
                result = await self.run_personnel_verification(
                    params.get("personnel_info", {}),
                )
            else:
                # 通用对抗流程
                result = await self._run_generic_debate(params)

            elapsed = time.time() - start_time
            result["debate_duration"] = elapsed
            result["debate_log"] = self.debate_log

            logger.info("对抗验证完成，耗时 %.1f 秒", elapsed)
            return result

        except Exception as e:
            logger.error("对抗验证失败: %s", e)
            return {
                "error": str(e),
                "debate_log": self.debate_log,
                "overall_confidence": 0,
                "needs_human_review": True,
            }

    async def run_contact_verification(self, company_name: str, country: str) -> dict:
        """
        专门用于联系方式验证的对抗流程。

        Args:
            company_name: 公司名称
            country: 国家

        Returns:
            验证结果
        """
        logger.info("联系方式对抗验证: %s (%s)", company_name, country)

        # 1. Finder 搜索
        finder = self.agents.get(AgentRole.FINDER)
        if not finder:
            raise RuntimeError("Finder Agent未初始化")

        finder_result = await self._execute_with_retry(
            finder,
            {"task_type": "contact", "company_name": company_name, "country": country},
        )
        self._log_debate_round(AgentRole.FINDER, {"company": company_name}, finder_result)

        # 2. Critic 批评
        critic = self.agents.get(AgentRole.CRITIC)
        if not critic:
            raise RuntimeError("Critic Agent未初始化")

        critic_result = await self._execute_with_retry(
            critic,
            {"finder_result": finder_result, "company_name": company_name, "country": country},
        )
        self._log_debate_round(AgentRole.CRITIC, finder_result, critic_result)

        # 3. Verifier 验证
        verifier = self.agents.get(AgentRole.VERIFIER)
        if not verifier:
            raise RuntimeError("Verifier Agent未初始化")

        if self.config.get("parallel_critic_verify"):
            # 并行执行（如果配置允许）
            pass
        else:
            verifier_result = await self._execute_with_retry(
                verifier,
                {
                    "finder_result": finder_result,
                    "critic_result": critic_result,
                    "company_name": company_name,
                    "country": country,
                },
            )
        self._log_debate_round(AgentRole.VERIFIER, critic_result, verifier_result)

        # 4. Judge 裁决
        judge = self.agents.get(AgentRole.JUDGE)
        if not judge:
            raise RuntimeError("Judge Agent未初始化")

        judge_result = await self._execute_with_retry(
            judge,
            {
                "finder_result": finder_result,
                "critic_result": critic_result,
                "verifier_result": verifier_result,
                "company_name": company_name,
            },
        )
        self._log_debate_round(AgentRole.JUDGE, verifier_result, judge_result)

        # 5. 组装最终结果
        return {
            "task_type": "contact",
            "company_name": company_name,
            "country": country,
            "finder_result": finder_result,
            "critic_result": critic_result,
            "verifier_result": verifier_result,
            "judge_result": judge_result,
            "final_decision": judge_result.get("final_decision", {}),
            "overall_confidence": judge_result.get("overall_confidence", 0),
            "risk_level": judge_result.get("risk_level", "unknown"),
            "needs_human_review": judge_result.get("needs_human_review", True),
            "summary": judge_result.get("summary", ""),
        }

    async def run_personnel_verification(self, personnel_info: dict) -> dict:
        """
        用于验货人员的对抗验证。

        Args:
            personnel_info: 人员信息

        Returns:
            验证结果
        """
        logger.info("人员对抗验证")

        # 1. Finder 搜索更多信息
        finder = self.agents.get(AgentRole.FINDER)
        finder_result = await self._execute_with_retry(
            finder,
            {"task_type": "personnel", "personnel_info": personnel_info},
        )
        self._log_debate_round(AgentRole.FINDER, personnel_info, finder_result)

        # 2. Critic 批评
        critic = self.agents.get(AgentRole.CRITIC)
        critic_result = await critic.critique_personnel(personnel_info, finder_result)
        self._log_debate_round(AgentRole.CRITIC, finder_result, critic_result)

        # 3. Verifier 验证
        verifier = self.agents.get(AgentRole.VERIFIER)
        verifier_result = await verifier.verify_personnel(
            personnel_info, finder_result, critic_result,
        )
        self._log_debate_round(AgentRole.VERIFIER, critic_result, verifier_result)

        # 4. Judge 裁决
        judge = self.agents.get(AgentRole.JUDGE)
        judge_result = await judge.judge_personnel(
            personnel_info, finder_result, critic_result, verifier_result,
        )
        self._log_debate_round(AgentRole.JUDGE, verifier_result, judge_result)

        return {
            "task_type": "personnel",
            "personnel_info": personnel_info,
            "finder_result": finder_result,
            "critic_result": critic_result,
            "verifier_result": verifier_result,
            "judge_result": judge_result,
            "final_decision": judge_result.get("final_decision", {}),
            "overall_trust_score": judge_result.get("overall_trust_score", 0),
            "recommendation": judge_result.get("recommendation", "unknown"),
            "needs_human_review": judge_result.get("needs_human_review", True),
            "summary": judge_result.get("summary", ""),
        }

    async def _run_generic_debate(self, params: dict) -> dict:
        """通用对抗流程。"""
        # Finder
        finder = self.agents.get(AgentRole.FINDER)
        finder_result = await self._execute_with_retry(finder, params)
        self._log_debate_round(AgentRole.FINDER, params, finder_result)

        # Critic
        critic = self.agents.get(AgentRole.CRITIC)
        critic_result = await self._execute_with_retry(
            critic,
            {"finder_result": finder_result, **params},
        )
        self._log_debate_round(AgentRole.CRITIC, finder_result, critic_result)

        # Verifier
        verifier = self.agents.get(AgentRole.VERIFIER)
        verifier_result = await self._execute_with_retry(
            verifier,
            {"finder_result": finder_result, "critic_result": critic_result, **params},
        )
        self._log_debate_round(AgentRole.VERIFIER, critic_result, verifier_result)

        # Judge
        judge = self.agents.get(AgentRole.JUDGE)
        judge_result = await self._execute_with_retry(
            judge,
            {
                "finder_result": finder_result,
                "critic_result": critic_result,
                "verifier_result": verifier_result,
                **params,
            },
        )
        self._log_debate_round(AgentRole.JUDGE, verifier_result, judge_result)

        return {
            "finder_result": finder_result,
            "critic_result": critic_result,
            "verifier_result": verifier_result,
            "judge_result": judge_result,
            "overall_confidence": judge_result.get("overall_confidence", 0),
            "needs_human_review": judge_result.get("needs_human_review", True),
        }

    async def _execute_with_retry(self, agent: DebateAgent, context: dict) -> dict:
        """带重试的Agent执行。"""
        timeout = self.config.get("timeout_per_agent", 60)
        retry = self.config.get("retry_on_failure", True)

        try:
            return await asyncio.wait_for(
                agent.execute(context),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, Exception) as e:
            logger.error("%s 执行失败: %s", agent.name, e)
            if retry:
                logger.info("重试 %s...", agent.name)
                try:
                    return await asyncio.wait_for(
                        agent.execute(context),
                        timeout=timeout,
                    )
                except Exception as retry_error:
                    logger.error("%s 重试失败: %s", agent.name, retry_error)

            return {"error": str(e), "agent": agent.name}

    # ── 日志记录 ──────────────────────────────────────────

    def _log_debate_round(self, role: AgentRole, input_data: dict, output_data: dict):
        """记录对抗过程日志。"""
        entry = {
            "timestamp": time.time(),
            "role": role.value,
            "agent_name": self.agents[role].name if role in self.agents else "Unknown",
            "input_summary": self._summarize_data(input_data),
            "output_summary": self._summarize_data(output_data),
            "has_error": "error" in output_data,
        }
        self.debate_log.append(entry)
        logger.debug("对抗日志: %s -> %s", role.value, entry["output_summary"][:100])

    def _summarize_data(self, data: dict) -> str:
        """生成数据摘要。"""
        if not data:
            return "(empty)"

        if "error" in data:
            return f"(error: {data['error']})"

        # 移除原始响应以减小摘要大小
        summary_data = {k: v for k, v in data.items() if k != "raw_response"}
        text = json.dumps(summary_data, ensure_ascii=False)

        if len(text) > 200:
            return text[:200] + "..."
        return text

    def get_debate_transcript(self) -> list[dict]:
        """返回完整的对抗记录。"""
        return list(self.debate_log)

    def get_transcript_text(self) -> str:
        """返回格式化的对抗记录文本。"""
        lines = ["=" * 50, "对抗验证记录", "=" * 50, ""]

        role_icons = {
            "finder": "🔍",
            "critic": "🔴",
            "verifier": "✅",
            "judge": "⚖️",
        }

        for entry in self.debate_log:
            icon = role_icons.get(entry["role"], "▪️")
            agent = entry.get("agent_name", entry["role"])
            status = "❌ 失败" if entry.get("has_error") else "✓ 完成"

            lines.append(f"{icon} {agent} {status}")
            lines.append(f"   输出: {entry['output_summary'][:100]}")
            lines.append("")

        return "\n".join(lines)

    # ── 配置 ──────────────────────────────────────────────

    def update_config(self, **kwargs):
        """更新配置。"""
        self.config.update(kwargs)
        logger.info("对抗验证配置已更新: %s", kwargs)

    def is_enabled(self) -> bool:
        """检查是否启用对抗验证。"""
        return self.config.get("enabled", True)

    def should_run_debate(self, task_type: str, value: float = 0) -> bool:
        """判断是否应该运行对抗验证。"""
        if not self.is_enabled():
            return False

        # 检查货值阈值
        min_value = self.config.get("min_value_threshold", 500)
        if value > 0 and value < min_value:
            return False

        # 检查任务类型
        debate_task_types = ["contact", "contact_discovery", "personnel", "personnel_search"]
        return task_type in debate_task_types
