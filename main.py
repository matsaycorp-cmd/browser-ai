# 主程序入口

import asyncio
import json
import logging
import re

from config.settings import (
    BROWSER_DATA_DIR,
    EXECUTION_MODE,
    MAX_PARALLEL,
    WS_SERVER_URL,
    config_manager,
)
from core.browser_manager import BrowserManager
from core.chatgpt_controller import ChatGPTController, ChatGPTTaskRunner
from core.claude_controller import ClaudeController, ClaudeTaskRunner
from core.debate_system import AgentRole, DebateOrchestrator
from core.decision_engine import DecisionEngine
from core.deepseek_controller import DeepSeekController, DeepSeekTaskRunner
from core.gemini_controller import GeminiController, GeminiTaskRunner
from core.parallel_executor import ParallelExecutor
from core.personnel_searcher import PersonnelEvaluator, PersonnelSearcher
from core.quality_checker import QualityChecker
from core.rate_limiter import RateLimiter
from core.registry_inquiry import RegistryInquiryRunner
from core.task_persistence import TaskPersistence
from core.ws_client import WSClient

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/browser-ai.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# AI名称 → (Controller类, TaskRunner类)
AI_CLASSES = {
    "chatgpt": (ChatGPTController, ChatGPTTaskRunner),
    "claude": (ClaudeController, ClaudeTaskRunner),
    "deepseek": (DeepSeekController, DeepSeekTaskRunner),
    "gemini": (GeminiController, GeminiTaskRunner),
}

# 启动顺序
STARTUP_AI_LIST = ["chatgpt", "claude", "deepseek", "gemini"]


class BrowserAIClient:
    """主客户端：管理浏览器、AI控制器、决策引擎与 WebSocket 通信。"""

    def __init__(self):
        self.browser_manager = BrowserManager(BROWSER_DATA_DIR)
        self.controllers: dict = {}
        self.runners: dict = {}
        self.quality_checker = QualityChecker()
        self.decision_engine = DecisionEngine(self.quality_checker)
        self.rate_limiter = RateLimiter()
        self.parallel_executor: ParallelExecutor | None = None  # 在 setup 后初始化
        self.task_store = TaskPersistence()
        self.ws_client = WSClient(WS_SERVER_URL)
        self.personnel_searcher: PersonnelSearcher | None = None
        self.personnel_evaluator: PersonnelEvaluator | None = None
        self.debate_orchestrator: DebateOrchestrator | None = None
        self.registry_inquiry_runner: RegistryInquiryRunner | None = None

    # ── 启动 ─────────────────────────────────────────────

    async def setup(self):
        """启动浏览器、登录各AI平台、连接 WebSocket。"""
        print("=" * 50)
        print("  Browser-AI 控制程序启动")
        print("=" * 50)

        # 1. 启动浏览器
        await self.browser_manager.start(headless=False)
        print("浏览器已启动")

        # 2. 依次打开各AI平台并检查登录
        for ai_name in STARTUP_AI_LIST:
            print(f"\n正在打开 {ai_name}...")
            session = await self.browser_manager.open_session(ai_name)

            if not session["logged_in"]:
                logged_in = await self.browser_manager.wait_for_login(ai_name)
                if not logged_in:
                    print(f"⚠️  {ai_name} 登录超时，跳过")
                    continue

            # 创建控制器和任务运行器
            ctrl_cls, runner_cls = AI_CLASSES[ai_name]
            controller = ctrl_cls(session["page"])
            self.controllers[ai_name] = controller
            self.runners[ai_name] = runner_cls(controller)
            print(f"✅ {ai_name} 已就绪")

        # 3. 初始化并行执行器
        self.parallel_executor = ParallelExecutor(
            self.controllers, self.runners, self.rate_limiter,
        )
        self.parallel_executor.set_mode(EXECUTION_MODE)
        self.parallel_executor.max_parallel = MAX_PARALLEL

        # 4. 初始化人员搜索器和评估器
        self.personnel_searcher = PersonnelSearcher(
            self.controllers, self.browser_manager,
        )
        # 使用第一个可用的AI控制器作为评估器
        if self.controllers:
            first_ai = next(iter(self.controllers.values()))
            self.personnel_evaluator = PersonnelEvaluator(first_ai)

        # 5. 初始化对抗验证编排器
        if self.controllers:
            self.debate_orchestrator = DebateOrchestrator(self.controllers)
            self.decision_engine.set_debate_orchestrator(self.debate_orchestrator)
            print("✅ 对抗验证系统已初始化")

        # 6. 初始化官方名录查询器
        if self.controllers:
            self.registry_inquiry_runner = RegistryInquiryRunner(self.controllers)
            print("✅ 官方名录查询器已初始化")

        # 7. 连接 WebSocket
        await self.ws_client.connect()

        # 8. 注册消息处理器
        self.ws_client.on("new_task", self.handle_new_task)
        self.ws_client.on("retry_task", self.handle_retry_task)
        self.ws_client.on("review_result", self.handle_review_result)
        self.ws_client.on("config_update", self.handle_config_update)
        self.ws_client.on("personnel_search", self.handle_personnel_search)
        self.ws_client.on("debate_task", self.handle_debate_task)
        self.ws_client.on("registry_inquiry", self.handle_registry_inquiry)

        # 9. 请求服务器配置
        await self.ws_client.request_config()

    # ── 任务处理 ──────────────────────────────────────────

    async def handle_new_task(self, message: dict):
        """处理来自服务器的新任务。"""
        data = message.get("data", {})
        task_id = data.get("task_id", "unknown")
        task_type = data.get("task_type", "")
        params = data.get("params", {})

        print(f"\n📥 收到任务: {task_id} ({task_type})")
        logger.info("收到新任务: %s (%s)", task_id, task_type)

        self.task_store.save_task(task_id, task_type, params)
        await self.execute_task(task_id, task_type, params)

    async def execute_task(
        self,
        task_id: str,
        task_type: str,
        params: dict,
        use_ai: str | None = None,
    ):
        """选择执行模式（单AI / 并行 / 竞速 / 最佳）并执行任务。"""
        mode = self.parallel_executor.get_mode() if self.parallel_executor else "single"
        available = [
            ai for ai in self.runners
            if self.rate_limiter.can_request(ai)
        ]

        # ── 并行模式（需要 >=2 个可用 AI 且非指定单 AI）───
        if mode != "single" and use_ai is None and len(available) >= 2:
            self.task_store.update_task(task_id, status="running")

            # 通知 Telegram
            await self.ws_client.send_status({
                "mode": mode,
                "running_ais": available,
                "task_id": task_id,
            })

            try:
                if mode == "parallel":
                    results = await self.parallel_executor.execute_parallel(
                        task_type, params, available,
                    )
                    # 联系方式类任务合并结果
                    if task_type in ("search_contacts", "search_freight"):
                        merged = self.parallel_executor.merge_contact_results(results)
                        best_entry = max(results, key=lambda r: r["score"])
                        return await self.process_result(
                            task_id, task_type, merged, best_entry["ai"],
                        )
                    # 其他任务取最高分
                    best_entry = max(results, key=lambda r: r["score"])
                    return await self.process_result(
                        task_id, task_type, best_entry["result"], best_entry["ai"],
                    )

                elif mode == "race":
                    best = await self.parallel_executor.execute_race(
                        task_type, params, available,
                    )
                    return await self.process_result(
                        task_id, task_type, best["result"], best["ai"],
                    )

                elif mode == "best":
                    best = await self.parallel_executor.execute_best(
                        task_type, params, available,
                    )
                    return await self.process_result(
                        task_id, task_type, best["result"], best["ai"],
                    )
            except Exception as e:
                logger.error("并行执行 %s 出错: %s，回退单AI", task_id, e)
                # 回退到单AI模式继续

        # ── 单AI执行 ────────────────────────────────────
        ai_name = use_ai or "chatgpt"

        # 指定的 AI 不在 runners 中 → 自动选
        if ai_name not in self.runners:
            ai_name = self.rate_limiter.get_available_ai(list(self.runners.keys()))
        # 指定的 AI 达到速率限制 → 尝试换一个
        elif not self.rate_limiter.can_request(ai_name):
            wait = self.rate_limiter.get_wait_time(ai_name)
            print(f"⚠️  {ai_name} 已达频率限制 (需等待 {wait:.0f}s)，尝试其他AI")
            ai_name = self.rate_limiter.get_available_ai(list(self.runners.keys()))

        # 所有 AI 都达到限制
        if ai_name is None:
            status = self.rate_limiter.get_status()
            min_wait = min(
                self.rate_limiter.get_wait_time(name) for name in self.runners
            )
            print(f"🚫 所有AI均达到频率限制，最短等待 {min_wait:.0f}s")
            logger.warning("所有AI达到频率限制，任务 %s 等待中", task_id)
            await self.ws_client.send_status({
                "event": "rate_limited",
                "task_id": task_id,
                "wait_seconds": round(min_wait),
                "ai_status": status,
            })
            await asyncio.sleep(min_wait + 1)
            return await self.execute_task(task_id, task_type, params, use_ai=use_ai)

        if ai_name not in self.runners:
            print("❌ 没有可用的AI")
            logger.error("无可用AI，任务 %s 放弃", task_id)
            return

        # 频率等待
        await self.rate_limiter.wait_if_needed(ai_name)

        runner = self.runners[ai_name]
        print(f"🤖 使用 {ai_name} 执行任务 {task_id}")

        # 更新持久化状态
        self.task_store.update_task(
            task_id, status="running", current_ai=ai_name,
        )

        try:
            if task_type == "search_contacts":
                result = await runner.search_contacts(
                    params.get("company_name", ""),
                    params.get("country", ""),
                )
            elif task_type == "search_slaughterhouses":
                result = await runner.search_slaughterhouses(
                    params.get("country", ""),
                    params.get("region", ""),
                )
            elif task_type == "search_freight":
                result = await runner.search_freight_forwarders(
                    params.get("country", ""),
                    params.get("cargo_type", "牛副产品"),
                )
            elif task_type == "generate_email":
                result = await runner.generate_email(
                    params.get("company_name", ""),
                    params.get("language", "english"),
                    params.get("product", "bovine gallstones"),
                )
            else:
                print(f"⚠️  未知任务类型: {task_type}")
                return

            self.rate_limiter.record_request(ai_name)
            await self.process_result(task_id, task_type, result, ai_name)

        except Exception as e:
            logger.error("执行任务 %s 出错: %s", task_id, e)
            print(f"❌ 任务执行出错: {e}")
            self.task_store.fail_task(task_id, str(e))

    async def process_result(
        self, task_id: str, task_type: str, result, ai_used: str
    ):
        """评估结果质量并决定下一步。"""
        decision = self.decision_engine.evaluate(
            task_id, task_type, result, ai_used
        )
        action = decision["action"]
        score = decision["score"]
        summary = self.decision_engine.get_attempt_summary(task_id)

        if action == "auto_approve":
            print(f"✅ 自动通过: {task_id} (分数:{score})")
            self.task_store.complete_task(task_id, result)
            await self.ws_client.send_auto_approved(task_id, result, score)

        elif action == "retry":
            next_ai = decision["next_ai"]
            print(f"🔄 重试: {task_id} 使用 {next_ai} (当前分数:{score})")
            task = self.task_store.get_task(task_id)
            retry_count = task["retry_count"] + 1 if task else 1
            self.task_store.update_task(
                task_id, status="pending", current_ai=next_ai,
                retry_count=retry_count,
            )
            await self.execute_task(
                task_id, task_type,
                task["params"] if task else {},
                use_ai=next_ai,
            )

        elif action == "need_review":
            print(f"📱 发送审核: {task_id} (分数:{score})")
            self.task_store.update_task(task_id, status="pending")
            best = self.decision_engine.get_best_result(task_id)
            await self.ws_client.send_need_review(
                task_id, task_type,
                best if best is not None else result,
                score, decision["issues"], summary,
            )

    # ── 人员搜索处理 ────────────────────────────────────

    async def handle_personnel_search(self, message: dict):
        """处理人员搜索任务。"""
        data = message.get("data", {})
        task_id = data.get("task_id", "unknown")
        search_type = data.get("type")  # freight_forwarder/inspection_company/freelancer
        country = data.get("country", "")
        city = data.get("city")

        print(f"\n🔍 收到人员搜索任务: {task_id} ({search_type})")
        logger.info("人员搜索任务: %s, 类型: %s, 地区: %s %s", task_id, search_type, country, city or "")

        if not self.personnel_searcher:
            logger.error("人员搜索器未初始化")
            await self.ws_client.send("personnel_search_error", {
                "search_task_id": task_id,
                "error": "人员搜索器未初始化",
            })
            return

        try:
            # 1. 执行搜索
            print(f"  正在搜索 {search_type}...")
            types = [search_type] if search_type else None
            results = await self.personnel_searcher.search_all(country, city, types)

            # 合并所有类型的结果
            all_results = []
            for type_name, type_results in results.items():
                all_results.extend(type_results)

            print(f"  找到 {len(all_results)} 个结果")

            # 2. AI评估每个结果
            evaluated = []
            if self.personnel_evaluator and all_results:
                print(f"  正在评估结果...")
                evaluated = await self.personnel_evaluator.evaluate_batch(
                    all_results, search_type or "unknown",
                )
            else:
                evaluated = all_results

            # 3. 发送结果到服务器
            await self.ws_client.send("personnel_search_result", {
                "search_task_id": task_id,
                "results": evaluated,
                "total_count": len(evaluated),
                "search_type": search_type,
                "country": country,
                "city": city,
            })

            # 4. 高分结果通知Telegram
            high_score = [r for r in evaluated if r.get("ai_score", 0) >= 70]
            if high_score:
                print(f"  ✅ 发现 {len(high_score)} 个高分结果")
                await self.ws_client.send("notify_personnel_found", {
                    "search_task_id": task_id,
                    "count": len(high_score),
                    "top_result": high_score[0],
                    "search_type": search_type,
                })
            else:
                print(f"  ⚠️  未发现高分结果")

            logger.info("人员搜索完成: %s, 共 %d 个结果, 高分 %d 个",
                        task_id, len(evaluated), len(high_score))

        except Exception as e:
            logger.error("人员搜索失败: %s - %s", task_id, e)
            print(f"  ❌ 搜索失败: {e}")
            await self.ws_client.send("personnel_search_error", {
                "search_task_id": task_id,
                "error": str(e),
            })

    # ── 对抗验证处理 ────────────────────────────────────

    async def handle_debate_task(self, message: dict):
        """处理对抗验证任务。"""
        data = message.get("data", {})
        session_id = data.get("session_id", "unknown")
        task_type = data.get("task_type", "")
        params = data.get("params", {})

        print(f"\n⚔️ 收到对抗验证任务: {session_id} ({task_type})")
        logger.info("对抗验证任务: %s, 类型: %s", session_id, task_type)

        if not self.debate_orchestrator:
            logger.error("对抗验证编排器未初始化")
            await self.ws_client.send("debate_failed", {
                "session_id": session_id,
                "error": "对抗验证系统未初始化",
            })
            return

        try:
            # 1. 通知开始
            await self.ws_client.send("debate_progress", {
                "session_id": session_id,
                "status": "started",
                "message": "对抗验证开始",
            })

            # 2. 根据任务类型执行对抗
            if task_type == "contact_discovery":
                result = await self._debate_contact_discovery(
                    session_id,
                    params.get("company_name", ""),
                    params.get("country", ""),
                    params.get("city"),
                )
            elif task_type == "personnel_verification":
                result = await self._debate_personnel_verification(
                    session_id,
                    params.get("personnel_info", {}),
                )
            elif task_type == "slaughterhouse_verification":
                result = await self._debate_slaughterhouse_verification(
                    session_id,
                    params.get("slaughterhouse_info", {}),
                )
            else:
                raise ValueError(f"未知的对抗任务类型: {task_type}")

            # 3. 发送最终结果
            print(f"  ✅ 对抗验证完成: {session_id}")
            await self.ws_client.send("debate_complete", {
                "session_id": session_id,
                "final_result": result,
            })

        except Exception as e:
            logger.error("对抗验证失败: %s - %s", session_id, e)
            print(f"  ❌ 对抗验证失败: {e}")
            await self.ws_client.send("debate_failed", {
                "session_id": session_id,
                "error": str(e),
            })

    async def _debate_contact_discovery(
        self,
        session_id: str,
        company_name: str,
        country: str,
        city: str | None = None,
    ) -> dict:
        """联系方式发现的对抗验证。"""
        print(f"  📍 联系方式对抗验证: {company_name} ({country})")

        finder = self.debate_orchestrator.agents.get(AgentRole.FINDER)
        critic = self.debate_orchestrator.agents.get(AgentRole.CRITIC)
        verifier = self.debate_orchestrator.agents.get(AgentRole.VERIFIER)
        judge = self.debate_orchestrator.agents.get(AgentRole.JUDGE)

        # === 第1轮：Finder ===
        await self._notify_round_start(session_id, 1, "finder")
        finder_result = await finder.find_contacts(company_name, country)
        await self._notify_round_complete(session_id, 1, "finder", finder_result)

        # === 第2轮：Critic ===
        await self._notify_round_start(session_id, 2, "critic")
        critic_result = await critic.critique(finder_result, company_name, country)
        await self._notify_round_complete(session_id, 2, "critic", critic_result)

        # === 第3轮：Verifier ===
        await self._notify_round_start(session_id, 3, "verifier")
        verifier_result = await verifier.verify(
            finder_result, critic_result, company_name, country,
        )
        await self._notify_round_complete(session_id, 3, "verifier", verifier_result)

        # === 第4轮：Judge ===
        await self._notify_round_start(session_id, 4, "judge")
        judge_result = await judge.judge(
            finder_result, critic_result, verifier_result, company_name,
        )
        await self._notify_round_complete(session_id, 4, "judge", judge_result)

        return {
            "rounds": {
                "finder": finder_result,
                "critic": critic_result,
                "verifier": verifier_result,
                "judge": judge_result,
            },
            "final_decision": judge_result.get("final_decision"),
            "overall_confidence": judge_result.get("overall_confidence"),
            "needs_human_review": judge_result.get("needs_human_review"),
            "summary": judge_result.get("summary", ""),
        }

    async def _debate_personnel_verification(
        self,
        session_id: str,
        personnel_info: dict,
    ) -> dict:
        """验货人员的对抗验证。"""
        name = personnel_info.get("name", "Unknown")
        company = personnel_info.get("company", "")
        country = personnel_info.get("country", "")
        platform = personnel_info.get("platform", "")

        print(f"  👤 人员对抗验证: {name} ({company})")

        finder = self.debate_orchestrator.agents.get(AgentRole.FINDER)
        critic = self.debate_orchestrator.agents.get(AgentRole.CRITIC)
        verifier = self.debate_orchestrator.agents.get(AgentRole.VERIFIER)
        judge = self.debate_orchestrator.agents.get(AgentRole.JUDGE)

        # === 第1轮：Finder 搜索更多信息 ===
        await self._notify_round_start(session_id, 1, "finder")

        finder_prompt = f"""请搜索以下人员/公司的更多信息：

名称：{name}
公司：{company}
国家：{country}
来源平台：{platform}

需要找到：
1. 公司官网或个人主页
2. 社交媒体账号（LinkedIn、Facebook等）
3. 其他平台的评价
4. 新闻报道或公开信息
5. 公司注册信息（如果是公司）

请返回JSON格式：
{{
  "official_sources": ["来源1", ...],
  "social_media": ["账号1", ...],
  "reviews": ["评价1", ...],
  "news": ["新闻1", ...],
  "registration_info": "注册信息",
  "other_findings": ["其他发现", ...]
}}"""

        await finder.controller.send_message(finder_prompt)
        await finder.controller.wait_response()
        finder_response = await finder.controller.get_last_response()
        finder_result = {"raw": finder_response, "parsed": self._parse_json(finder_response)}
        await self._notify_round_complete(session_id, 1, "finder", finder_result)

        # === 第2轮：Critic 质疑可信度 ===
        await self._notify_round_start(session_id, 2, "critic")

        critic_prompt = f"""你是风险评估专家。请严格审查以下验货人员的可信度：

基本信息：
{json.dumps(personnel_info, ensure_ascii=False, indent=2)}

搜索到的额外信息：
{finder_response}

请从以下角度质疑：

1. 身份真实性：
   - 名称是否像真实人名/公司名？
   - 是否有可验证的身份证明？
   - 社交媒体账号是否活跃？

2. 能力可信度：
   - 声称的经验是否合理？
   - 评价是否可能是刷单？
   - 价格是否异常（太低可能是骗子）？

3. 风险信号：
   - 是否有负面信息？
   - 是否有投诉或纠纷？
   - 信息是否前后矛盾？

4. 地理匹配：
   - 位置是否与声称一致？
   - 是否有能力在当地执行任务？

请返回JSON格式：
{{
  "identity_concerns": ["担忧1", ...],
  "capability_concerns": ["担忧1", ...],
  "risk_signals": ["信号1", ...],
  "questions_to_verify": ["需验证问题1", ...],
  "initial_risk_level": "low/medium/high",
  "recommendation": "可信/谨慎/不可信"
}}"""

        await critic.controller.send_message(critic_prompt)
        await critic.controller.wait_response()
        critic_response = await critic.controller.get_last_response()
        critic_result = {"raw": critic_response, "parsed": self._parse_json(critic_response)}
        await self._notify_round_complete(session_id, 2, "critic", critic_result)

        # === 第3轮：Verifier 验证证据 ===
        await self._notify_round_start(session_id, 3, "verifier")

        verifier_prompt = f"""请验证以下关于验货人员的信息：

人员信息：
{json.dumps(personnel_info, ensure_ascii=False, indent=2)}

批评者的质疑：
{critic_response}

请尝试验证：

1. 如果是公司：
   - 搜索公司注册信息
   - 查找官网是否真实存在
   - 验证地址是否真实

2. 如果是个人：
   - LinkedIn是否有此人
   - 平台评价是否真实
   - 历史记录是否合理

3. 对批评者的质疑逐一回应

请返回JSON格式：
{{
  "verifications": [
    {{"item": "被验证项", "result": "verified/unverified/uncertain", "evidence": "证据", "source_url": "来源"}}
  ],
  "identity_confirmed": true/false/"uncertain",
  "overall_assessment": "可信度评估",
  "evidence_strength": "strong/moderate/weak"
}}"""

        await verifier.controller.send_message(verifier_prompt)
        await verifier.controller.wait_response()
        verifier_response = await verifier.controller.get_last_response()
        verifier_result = {"raw": verifier_response, "parsed": self._parse_json(verifier_response)}
        await self._notify_round_complete(session_id, 3, "verifier", verifier_result)

        # === 第4轮：Judge 最终判定 ===
        await self._notify_round_start(session_id, 4, "judge")

        judge_prompt = f"""请作为最终裁判，综合以下信息对验货人员做出判定：

原始信息：
{json.dumps(personnel_info, ensure_ascii=False, indent=2)}

Finder搜索结果：
{finder_response}

Critic质疑：
{critic_response}

Verifier验证：
{verifier_response}

请做出最终判定，返回JSON格式：
{{
  "final_verdict": "approve/reject/need_more_info",
  "confidence": 0-100,
  "risk_level": "low/medium/high",
  "credit_score_suggestion": 0-100,
  "max_cargo_value_suggestion": 建议最高货值美元,
  "requires_deposit": true/false,
  "deposit_amount_suggestion": 建议押金美元,
  "key_risks": ["主要风险1", ...],
  "key_strengths": ["主要优点1", ...],
  "conditions": ["使用条件1", ...],
  "summary": "一句话总结"
}}"""

        await judge.controller.send_message(judge_prompt)
        await judge.controller.wait_response()
        judge_response = await judge.controller.get_last_response()
        judge_result = {"raw": judge_response, "parsed": self._parse_json(judge_response)}
        await self._notify_round_complete(session_id, 4, "judge", judge_result)

        return {
            "rounds": {
                "finder": finder_result,
                "critic": critic_result,
                "verifier": verifier_result,
                "judge": judge_result,
            },
            "final_verdict": judge_result.get("parsed", {}),
        }

    async def _debate_slaughterhouse_verification(
        self,
        session_id: str,
        slaughterhouse_info: dict,
    ) -> dict:
        """屠宰场信息的对抗验证。"""
        name = slaughterhouse_info.get("name", "Unknown")
        country = slaughterhouse_info.get("country", "")
        website = slaughterhouse_info.get("website", "")

        print(f"  🏭 屠宰场对抗验证: {name} ({country})")

        finder = self.debate_orchestrator.agents.get(AgentRole.FINDER)
        critic = self.debate_orchestrator.agents.get(AgentRole.CRITIC)
        verifier = self.debate_orchestrator.agents.get(AgentRole.VERIFIER)
        judge = self.debate_orchestrator.agents.get(AgentRole.JUDGE)

        # === 第1轮：Finder 搜索屠宰场信息 ===
        await self._notify_round_start(session_id, 1, "finder")

        finder_prompt = f"""请搜索以下屠宰场的详细信息：

名称：{name}
国家：{country}
网站：{website}

需要找到：
1. 公司注册信息
2. 出口资质/认证（如SIF、HALAL等）
3. 产品类型（是否有牛产品/牛黄）
4. 规模（员工数、产能）
5. 客户评价或行业口碑
6. 新闻报道
7. 是否有出口到中国/香港的记录

返回JSON格式的搜索结果。"""

        await finder.controller.send_message(finder_prompt)
        await finder.controller.wait_response()
        finder_response = await finder.controller.get_last_response()
        finder_result = {"raw": finder_response, "parsed": self._parse_json(finder_response)}
        await self._notify_round_complete(session_id, 1, "finder", finder_result)

        # === 第2轮：Critic 质疑 ===
        await self._notify_round_start(session_id, 2, "critic")

        critic_prompt = f"""你是屠宰场审核专家。请质疑以下屠宰场的可信度：

屠宰场信息：
{json.dumps(slaughterhouse_info, ensure_ascii=False, indent=2)}

搜索结果：
{finder_response}

请从以下角度质疑：

1. 真实性：是否是真正的屠宰场？网站是否正规？是否有营业执照？

2. 产品匹配：是否确实加工牛产品？是否有能力/意愿提供牛黄？规模是否合理？

3. 出口能力：是否有出口资质？是否有国际贸易经验？

4. 风险信号：是否有质量问题历史？是否有法律纠纷？价格是否合理？

返回JSON格式评估。"""

        await critic.controller.send_message(critic_prompt)
        await critic.controller.wait_response()
        critic_response = await critic.controller.get_last_response()
        critic_result = {"raw": critic_response, "parsed": self._parse_json(critic_response)}
        await self._notify_round_complete(session_id, 2, "critic", critic_result)

        # === 第3轮：Verifier 验证 ===
        await self._notify_round_start(session_id, 3, "verifier")

        verifier_prompt = f"""请验证以下屠宰场信息：

{json.dumps(slaughterhouse_info, ensure_ascii=False, indent=2)}

批评者质疑：
{critic_response}

请验证：
1. 官网真实性
2. 公司注册记录
3. 出口认证（如SIF、HALAL等）
4. 行业协会会员资格
5. 海关出口记录（如能找到）

返回JSON格式验证结果。"""

        await verifier.controller.send_message(verifier_prompt)
        await verifier.controller.wait_response()
        verifier_response = await verifier.controller.get_last_response()
        verifier_result = {"raw": verifier_response, "parsed": self._parse_json(verifier_response)}
        await self._notify_round_complete(session_id, 3, "verifier", verifier_result)

        # === 第4轮：Judge 判定 ===
        await self._notify_round_start(session_id, 4, "judge")

        judge_prompt = f"""综合判定此屠宰场是否值得联系：

信息：{json.dumps(slaughterhouse_info, ensure_ascii=False, indent=2)}
搜索：{finder_response}
质疑：{critic_response}
验证：{verifier_response}

返回JSON格式：
{{
  "verdict": "worth_contact/uncertain/skip",
  "confidence": 0-100,
  "priority": "high/medium/low",
  "estimated_potential": "high/medium/low",
  "key_risks": [...],
  "recommended_approach": "建议的联系方式",
  "summary": "一句话总结"
}}"""

        await judge.controller.send_message(judge_prompt)
        await judge.controller.wait_response()
        judge_response = await judge.controller.get_last_response()
        judge_result = {"raw": judge_response, "parsed": self._parse_json(judge_response)}
        await self._notify_round_complete(session_id, 4, "judge", judge_result)

        return {
            "rounds": {
                "finder": finder_result,
                "critic": critic_result,
                "verifier": verifier_result,
                "judge": judge_result,
            },
            "final_verdict": judge_result.get("parsed", {}),
        }

    async def _notify_round_start(self, session_id: str, round_num: int, agent_role: str):
        """通知轮次开始。"""
        role_names = {
            "finder": "🔍 发现者",
            "critic": "🔴 批评者",
            "verifier": "✅ 验证者",
            "judge": "⚖️ 裁判",
        }
        print(f"    第{round_num}轮: {role_names.get(agent_role, agent_role)} 开始...")

        await self.ws_client.send("debate_round_start", {
            "session_id": session_id,
            "round": round_num,
            "agent": agent_role,
            "status": "running",
        })

    async def _notify_round_complete(
        self,
        session_id: str,
        round_num: int,
        agent_role: str,
        result: dict,
    ):
        """通知轮次完成。"""
        print(f"    第{round_num}轮: {agent_role} 完成")

        # 移除原始响应以减小传输大小
        result_summary = {k: v for k, v in result.items() if k != "raw"}

        await self.ws_client.send("debate_round_complete", {
            "session_id": session_id,
            "round": round_num,
            "agent": agent_role,
            "result": result_summary,
            "status": "completed",
        })

    def _parse_json(self, text: str) -> dict:
        """从AI回复中提取JSON。"""
        if not text:
            return {"parse_error": True, "raw_text": ""}

        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取```json```块
        match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试提取{...}
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # 解析失败，返回原始文本
        return {"raw_text": text[:500], "parse_error": True}

    # ── 官方名录查询处理 ──────────────────────────────────

    async def handle_registry_inquiry(self, message: dict):
        """处理官方屠宰场名录查询任务。

        使用对抗验证系统提高结果可靠性：
        - Finder: 搜索官方机构信息和获取途径
        - Critic: 质疑信息来源可靠性
        - Verifier: 验证URL和联系方式是否有效
        - Judge: 综合判断最佳获取方案
        """
        data = message.get("data", {})
        inquiry_id = data.get("inquiry_id", "unknown")
        country_code = data.get("country_code", "")
        country_name = data.get("country_name", "")
        official_agencies = data.get("official_agencies", [])
        search_results = data.get("search_results", [])
        use_debate = data.get("use_debate", True)  # 默认使用对抗验证

        print(f"\n🏛️ 收到官方名录查询: {inquiry_id} ({country_name})")
        logger.info("官方名录查询: %s, 国家: %s (%s)", inquiry_id, country_name, country_code)

        if not self.registry_inquiry_runner:
            logger.error("官方名录查询器未初始化")
            await self.ws_client.send("registry_inquiry_error", {
                "inquiry_id": inquiry_id,
                "error": "官方名录查询器未初始化",
            })
            return

        try:
            # 1. 通知开始
            await self.ws_client.send("registry_inquiry_progress", {
                "inquiry_id": inquiry_id,
                "status": "started",
                "message": "开始查询官方名录获取途径",
            })

            if use_debate and self.debate_orchestrator:
                # 使用对抗验证系统
                result = await self._registry_inquiry_with_debate(
                    inquiry_id, country_code, country_name,
                    official_agencies, search_results,
                )
            else:
                # 直接使用单AI查询
                result = await self.registry_inquiry_runner.full_inquiry_workflow(
                    country_code, country_name,
                    official_agencies, search_results,
                    generate_email=True,
                    email_language="es" if country_code in ("VE", "AR", "BR", "CO", "MX", "CL", "PE", "UY", "PY") else "en",
                )

            # 2. 发送结果
            print(f"  ✅ 官方名录查询完成: {inquiry_id}")
            await self.ws_client.send("registry_inquiry_complete", {
                "inquiry_id": inquiry_id,
                "result": result,
            })

        except Exception as e:
            logger.error("官方名录查询失败: %s - %s", inquiry_id, e)
            print(f"  ❌ 查询失败: {e}")
            await self.ws_client.send("registry_inquiry_error", {
                "inquiry_id": inquiry_id,
                "error": str(e),
            })

    async def _registry_inquiry_with_debate(
        self,
        inquiry_id: str,
        country_code: str,
        country_name: str,
        official_agencies: list,
        search_results: list,
    ) -> dict:
        """使用对抗验证系统进行官方名录查询。"""
        print(f"  ⚔️ 使用对抗验证系统查询 {country_name} 官方名录")

        finder = self.debate_orchestrator.agents.get(AgentRole.FINDER)
        critic = self.debate_orchestrator.agents.get(AgentRole.CRITIC)
        verifier = self.debate_orchestrator.agents.get(AgentRole.VERIFIER)
        judge = self.debate_orchestrator.agents.get(AgentRole.JUDGE)

        rounds = {}

        # === 第1轮：Finder 搜索官方机构信息 ===
        await self._notify_round_start(inquiry_id, 1, "finder")

        finder_prompt = f"""请搜索{country_name}（{country_code}）官方屠宰场/肉类加工厂名录的获取途径。

已知信息：
- 可能的官方机构：{', '.join(official_agencies) if official_agencies else '未知'}
- 之前找到的相关链接：{search_results[:5] if search_results else '无'}

请搜索并提供：
1. 负责管理屠宰场许可证的官方机构名称
2. 该机构的官方网站URL
3. 屠宰场名录是否公开可下载
4. 如果需要注册，注册页面URL
5. 如果需要申请，申请流程
6. 机构联系方式（邮箱、电话）
7. 是否有其他可获取数据的来源

请返回JSON格式：
{{
    "responsible_agency": "机构名称",
    "agency_website": "官网URL",
    "access_method": "public_download/registration_required/application_required/unknown",
    "registration_url": "注册URL或null",
    "application_process": "申请流程或null",
    "contact_email": "联系邮箱",
    "contact_phone": "联系电话",
    "alternative_sources": ["其他来源"],
    "found_urls": ["找到的相关URL"],
    "confidence": 0.0-1.0
}}"""

        await finder.controller.send_message(finder_prompt)
        await finder.controller.wait_response()
        finder_response = await finder.controller.get_last_response()
        finder_result = {"raw": finder_response, "parsed": self._parse_json(finder_response)}
        rounds["finder"] = finder_result
        await self._notify_round_complete(inquiry_id, 1, "finder", finder_result)

        # === 第2轮：Critic 质疑信息可靠性 ===
        await self._notify_round_start(inquiry_id, 2, "critic")

        critic_prompt = f"""你是政府数据获取专家。请严格审查以下关于{country_name}官方屠宰场名录的信息：

搜索结果：
{finder_response}

请从以下角度质疑：

1. 机构真实性：
   - 这是否是真正的政府机构？
   - 网站URL是否是官方域名（.gov, .gob等）？
   - 机构名称是否准确？

2. 信息准确性：
   - 获取方式是否正确？
   - 注册/申请流程是否真实？
   - 联系方式是否有效？

3. 可行性评估：
   - 外国公司能否获取这些数据？
   - 是否需要当地代理？
   - 是否有语言障碍？

4. 风险评估：
   - 信息是否可能过时？
   - 是否有其他更可靠的来源？

请返回JSON格式：
{{
    "agency_concerns": ["对机构的质疑"],
    "access_concerns": ["对获取方式的质疑"],
    "url_concerns": ["对URL的质疑"],
    "contact_concerns": ["对联系方式的质疑"],
    "feasibility_issues": ["可行性问题"],
    "questions_to_verify": ["需要验证的问题"],
    "risk_level": "low/medium/high",
    "overall_assessment": "整体评估"
}}"""

        await critic.controller.send_message(critic_prompt)
        await critic.controller.wait_response()
        critic_response = await critic.controller.get_last_response()
        critic_result = {"raw": critic_response, "parsed": self._parse_json(critic_response)}
        rounds["critic"] = critic_result
        await self._notify_round_complete(inquiry_id, 2, "critic", critic_result)

        # === 第3轮：Verifier 验证URL和联系方式 ===
        await self._notify_round_start(inquiry_id, 3, "verifier")

        verifier_prompt = f"""请验证以下关于{country_name}官方屠宰场名录的信息：

Finder搜索结果：
{finder_response}

Critic质疑：
{critic_response}

请验证：

1. 验证官方机构：
   - 搜索确认机构名称是否正确
   - 确认是否是负责屠宰场监管的部门

2. 验证网站URL：
   - 确认域名是否为官方域名
   - 确认网站是否可访问
   - 确认网站是否有屠宰场相关内容

3. 验证联系方式：
   - 邮箱域名是否匹配官方网站
   - 电话区号是否正确

4. 验证获取方式：
   - 如果声称公开下载，确认是否真的可以下载
   - 如果需要注册，确认注册页面是否存在

5. 回应Critic的质疑

请返回JSON格式：
{{
    "agency_verification": {{"verified": true/false, "evidence": "证据"}},
    "website_verification": {{"verified": true/false, "status": "状态", "has_registry_content": true/false}},
    "contact_verification": {{"email_valid": true/false, "phone_valid": true/false, "notes": "备注"}},
    "access_verification": {{"method_confirmed": true/false, "actual_method": "实际方式", "notes": "备注"}},
    "critic_responses": ["对质疑的回应"],
    "verification_confidence": 0.0-1.0
}}"""

        await verifier.controller.send_message(verifier_prompt)
        await verifier.controller.wait_response()
        verifier_response = await verifier.controller.get_last_response()
        verifier_result = {"raw": verifier_response, "parsed": self._parse_json(verifier_response)}
        rounds["verifier"] = verifier_result
        await self._notify_round_complete(inquiry_id, 3, "verifier", verifier_result)

        # === 第4轮：Judge 综合判断最佳方案 ===
        await self._notify_round_start(inquiry_id, 4, "judge")

        judge_prompt = f"""请作为最终裁判，综合判断获取{country_name}官方屠宰场名录的最佳方案：

Finder搜索：
{finder_response}

Critic质疑：
{critic_response}

Verifier验证：
{verifier_response}

请做出最终判断：

1. 最可靠的官方机构是？
2. 最佳获取方式是？
3. 具体步骤是什么？
4. 预计需要多长时间？
5. 是否需要准备什么材料？
6. 有什么替代方案？

请返回JSON格式：
{{
    "recommended_agency": "推荐的官方机构",
    "agency_website": "确认的官网URL",
    "recommended_method": "推荐的获取方式",
    "access_steps": ["步骤1", "步骤2", ...],
    "estimated_time": "预计时间",
    "required_documents": ["所需材料"],
    "contact_info": {{
        "email": "联系邮箱",
        "phone": "联系电话",
        "address": "地址"
    }},
    "alternative_approaches": ["替代方案"],
    "success_probability": 0.0-1.0,
    "risk_factors": ["风险因素"],
    "special_notes": "特别说明",
    "final_recommendation": "最终建议（一句话总结）"
}}"""

        await judge.controller.send_message(judge_prompt)
        await judge.controller.wait_response()
        judge_response = await judge.controller.get_last_response()
        judge_result = {"raw": judge_response, "parsed": self._parse_json(judge_response)}
        rounds["judge"] = judge_result
        await self._notify_round_complete(inquiry_id, 4, "judge", judge_result)

        # === 生成询问邮件（如果有联系方式）===
        inquiry_email = None
        judge_parsed = judge_result.get("parsed", {})
        contact_email = judge_parsed.get("contact_info", {}).get("email")

        if contact_email and self.registry_inquiry_runner:
            agency = judge_parsed.get("recommended_agency", f"{country_name}官方机构")
            lang = "es" if country_code in ("VE", "AR", "CO", "MX", "CL", "PE", "UY", "PY") else "pt" if country_code == "BR" else "en"
            inquiry_email = await self.registry_inquiry_runner.generate_inquiry_email(
                agency, country_name, lang
            )

        return {
            "country_code": country_code,
            "country_name": country_name,
            "debate_rounds": rounds,
            "final_result": judge_result.get("parsed", {}),
            "inquiry_email": inquiry_email,
            "debate_summary": {
                "finder_confidence": finder_result.get("parsed", {}).get("confidence"),
                "critic_risk_level": critic_result.get("parsed", {}).get("risk_level"),
                "verifier_confidence": verifier_result.get("parsed", {}).get("verification_confidence"),
                "judge_success_probability": judge_result.get("parsed", {}).get("success_probability"),
            }
        }

    # ── 服务器指令处理 ───────────────────────────────────

    async def handle_retry_task(self, message: dict):
        """处理服务器发来的重试指令。"""
        data = message.get("data", {})
        task_id = data.get("task_id", "unknown")
        task_type = data.get("task_type", "")
        params = data.get("params", {})
        use_ai = data.get("use_ai")

        print(f"\n🔄 收到重试指令: {task_id} → {use_ai or '自动选择'}")
        self.decision_engine.reset_task(task_id)
        await self.execute_task(task_id, task_type, params, use_ai=use_ai)

    async def handle_review_result(self, message: dict):
        """处理审核结果。"""
        data = message.get("data", {})
        task_id = data.get("task_id", "unknown")
        approved = data.get("approved", False)

        if approved:
            print(f"✅ 审核通过: {task_id}")
            logger.info("任务 %s 审核通过", task_id)
        else:
            reason = data.get("reason", "")
            print(f"❌ 审核拒绝: {task_id} ({reason})")
            logger.info("任务 %s 审核拒绝: %s", task_id, reason)
            self.decision_engine.reset_task(task_id)

    async def handle_config_update(self, message: dict):
        """处理服务器下发的配置更新。"""
        data = message.get("data", {})
        if not data:
            return

        print("⚙️ 收到配置更新")
        logger.info("收到服务器配置更新: %s", list(data.keys()))

        # 更新全局配置管理器
        config_manager.batch_update(data)

        # 同步到各组件
        if "rate_limits" in data:
            self.rate_limiter.reload_config(data["rate_limits"])

        if "execution_mode" in data or "max_parallel" in data:
            if self.parallel_executor:
                self.parallel_executor.reload_config(
                    execution_mode=data.get("execution_mode"),
                    max_parallel=data.get("max_parallel"),
                )

        if any(k in data for k in ("auto_approve_score", "min_pass_score", "max_retry_rounds", "ai_retry_order")):
            self.decision_engine.reload_config(
                auto_approve_score=data.get("auto_approve_score"),
                min_pass_score=data.get("min_pass_score"),
                max_retry_rounds=data.get("max_retry_rounds"),
                ai_retry_order=data.get("ai_retry_order"),
            )

    # ── 任务恢复 ──────────────────────────────────────────

    async def recover_tasks(self):
        """启动时检查并恢复未完成的任务。"""
        pending = self.task_store.get_pending_tasks()
        if not pending:
            return
        print(f"\n🔄 发现 {len(pending)} 个未完成任务，正在恢复...")
        logger.info("恢复 %d 个未完成任务", len(pending))
        for task in pending:
            await self.execute_task(
                task["task_id"],
                task["task_type"],
                task.get("params", {}),
                use_ai=task.get("current_ai"),
            )

    # ── 主循环 & 关闭 ────────────────────────────────────

    async def run(self):
        """启动并进入主循环。"""
        await self.setup()

        mode = self.parallel_executor.get_mode() if self.parallel_executor else "single"
        print("\n" + "=" * 50)
        print("  Browser-AI 就绪")
        print(f"  可用AI: {', '.join(self.controllers.keys()) or '无'}")
        print(f"  执行模式: {mode}")
        print("=" * 50 + "\n")

        # 恢复上次未完成的任务
        await self.recover_tasks()

        await self.ws_client.run()

    async def shutdown(self):
        """关闭所有资源。"""
        print("\n正在关闭...")
        await self.ws_client.disconnect()
        await self.browser_manager.close()
        print("已关闭")


async def main():
    client = BrowserAIClient()
    try:
        await client.run()
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断")
    finally:
        await client.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
