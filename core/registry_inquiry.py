"""
官方屠宰场名录智能查询模块

当自动搜索找不到可直接下载的官方屠宰场列表时，
帮助分析获取途径并生成获取指南。
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ── 提示词模板 ────────────────────────────────────────────────

ANALYZE_REGISTRY_PROMPT = """
你是一个专业的国际贸易数据分析专家，专门研究各国食品安全和畜牧业监管机构。

任务：分析如何获取{country_name}（{country_code}）的官方屠宰场/肉类加工厂名录。

已知信息：
- 可能的官方机构：{agencies}
- 之前搜索到的相关链接：
{search_results}

请分析并回答：

1. 负责管理屠宰场/肉类加工厂许可证的官方机构是哪个？
2. 该机构的官方网站是什么？
3. 获取屠宰场名录的方式是什么？（公开下载/需注册/需申请/需付费）
4. 如果需要注册，注册页面URL是什么？
5. 如果需要申请，申请流程是怎样的？
6. 预计获取数据需要多长时间？
7. 该机构的联系方式（邮箱、电话、地址）
8. 是否有其他可能的数据来源？

请以JSON格式回答，格式如下：
```json
{{
    "responsible_agency": "负责机构全称",
    "agency_website": "官网URL",
    "access_method": "public_download | registration_required | application_required | purchase_required | unknown",
    "registration_url": "注册页面URL，如不适用则为null",
    "application_process": "申请流程描述，如不适用则为null",
    "estimated_time": "预计获取时间，如：即时/1-3个工作日/需要审批约2周",
    "contact_info": {{
        "email": "联系邮箱",
        "phone": "联系电话",
        "address": "办公地址"
    }},
    "alternative_sources": ["其他可能的数据来源列表"],
    "confidence": 0.8,
    "ai_reasoning": "你的分析推理过程"
}}
```

注意：
- confidence 范围 0.0-1.0，表示你对这些信息的确信程度
- 如果某项信息不确定，请明确说明
- 优先考虑官方来源，其次考虑行业协会
"""

GENERATE_EMAIL_PROMPT = """
请帮我生成一封向{agency_name}询问屠宰场名录的正式邮件。

背景：我是一家中国进口公司，希望获取{country}的官方注册屠宰场/肉类加工厂名录，
以便寻找合规的供应商进行肉类进口业务合作。

要求：
1. 语言：{language}
2. 语气：正式、专业、礼貌
3. 内容：
   - 简要自我介绍
   - 说明需要什么数据（官方注册屠宰场名录）
   - 说明用途（进口贸易合规需求）
   - 询问获取方式
   - 表示感谢

请以JSON格式回答：
```json
{{
    "subject": "邮件主题",
    "body": "邮件正文",
    "language": "{language}"
}}
```
"""

CHECK_REGISTRATION_PROMPT = """
请分析以下注册页面的要求：

URL: {registration_url}

请根据你对该国政府/机构网站的了解，分析：

1. 是否需要当地公司身份才能注册？
2. 是否需要政府颁发的身份证件？
3. 是否需要行业许可证？
4. 注册是否免费？
5. 注册步骤是什么？
6. 外国公司/个人是否可以注册？
7. 如果有限制，有什么可能的变通方法？

请以JSON格式回答：
```json
{{
    "requires_local_company": true/false,
    "requires_government_id": true/false,
    "requires_industry_license": true/false,
    "registration_free": true/false,
    "registration_steps": ["步骤1", "步骤2", ...],
    "can_foreign_register": true/false,
    "workaround_suggestions": ["建议1", "建议2", ...]
}}
```
"""


# ── 辅助函数 ──────────────────────────────────────────────────

def extract_json_from_response(text: str) -> Optional[dict]:
    """从AI响应中提取JSON对象。"""
    # 尝试匹配 ```json ... ``` 格式
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试匹配 { ... } 格式
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def format_search_results(results: list) -> str:
    """格式化搜索结果列表。"""
    if not results:
        return "（无搜索结果）"

    formatted = []
    for i, item in enumerate(results[:10], 1):  # 最多显示10条
        if isinstance(item, dict):
            url = item.get('url', item.get('link', ''))
            title = item.get('title', '')
            formatted.append(f"  {i}. {title}\n     {url}")
        else:
            formatted.append(f"  {i}. {item}")

    return "\n".join(formatted)


# ── 语言代码映射 ──────────────────────────────────────────────

LANGUAGE_NAMES = {
    "es": "西班牙语",
    "en": "英语",
    "pt": "葡萄牙语",
    "fr": "法语",
    "de": "德语",
    "zh": "中文",
    "ru": "俄语",
    "ar": "阿拉伯语"
}


# ── 主类 ──────────────────────────────────────────────────────

class RegistryInquiryRunner:
    """官方屠宰场名录智能查询运行器。

    当自动搜索找不到可直接下载的官方屠宰场列表时，
    使用AI帮助分析获取途径并生成获取指南。
    """

    def __init__(self, controllers: dict):
        """
        初始化查询运行器。

        Args:
            controllers: AI控制器字典，如 {"chatgpt": ChatGPTController, ...}
        """
        self.controllers = controllers
        self.preferred_ai = "chatgpt"  # 默认使用ChatGPT
        self.inquiry_history = []

    def set_preferred_ai(self, ai_name: str):
        """设置首选AI。"""
        if ai_name in self.controllers:
            self.preferred_ai = ai_name
            logger.info(f"首选AI已设置为: {ai_name}")
        else:
            logger.warning(f"未知AI: {ai_name}，保持使用 {self.preferred_ai}")

    async def _send_to_ai(self, prompt: str, ai_name: str = None) -> str:
        """向AI发送请求并获取响应。"""
        ai = ai_name or self.preferred_ai

        if ai not in self.controllers:
            raise ValueError(f"AI控制器 '{ai}' 不可用")

        controller = self.controllers[ai]
        logger.info(f"向 {ai} 发送查询请求...")

        try:
            response = await controller.send_message(prompt)
            logger.info(f"收到 {ai} 响应 ({len(response)} 字符)")
            return response
        except Exception as e:
            logger.error(f"{ai} 请求失败: {e}")
            raise

    async def analyze_registry_access(
        self,
        country_code: str,
        country_name: str,
        official_agencies: list,
        search_results: list
    ) -> dict:
        """
        分析如何获取某国官方屠宰场名录。

        Args:
            country_code: 国家代码，如 "VE"
            country_name: 国家名称，如 "委内瑞拉"
            official_agencies: 官方机构列表，如 ["INSAI", "SIGESAI"]
            search_results: 之前搜索到的相关链接

        Returns:
            {
                "responsible_agency": "负责机构名称",
                "agency_website": "官网URL",
                "access_method": "public_download | registration_required | ...",
                "registration_url": "注册页面URL（如适用）",
                "application_process": "申请流程描述",
                "estimated_time": "预计获取时间",
                "contact_info": {"email": "", "phone": "", "address": ""},
                "alternative_sources": ["其他可能的数据来源"],
                "confidence": 0.0-1.0,
                "ai_reasoning": "AI分析推理过程"
            }
        """
        logger.info(f"分析 {country_name}({country_code}) 屠宰场名录获取途径")

        # 构建提示词
        prompt = ANALYZE_REGISTRY_PROMPT.format(
            country_name=country_name,
            country_code=country_code,
            agencies=", ".join(official_agencies) if official_agencies else "未知",
            search_results=format_search_results(search_results)
        )

        # 发送请求
        response = await self._send_to_ai(prompt)

        # 解析响应
        result = extract_json_from_response(response)

        if not result:
            logger.warning("无法解析AI响应为JSON，返回原始响应")
            result = {
                "responsible_agency": "解析失败",
                "agency_website": None,
                "access_method": "unknown",
                "registration_url": None,
                "application_process": None,
                "estimated_time": "未知",
                "contact_info": {"email": None, "phone": None, "address": None},
                "alternative_sources": [],
                "confidence": 0.0,
                "ai_reasoning": response
            }

        # 记录查询历史
        self.inquiry_history.append({
            "type": "analyze_registry_access",
            "country_code": country_code,
            "country_name": country_name,
            "timestamp": datetime.now().isoformat(),
            "result": result
        })

        # 打印分析结果摘要
        self._print_analysis_summary(result, country_name)

        return result

    def _print_analysis_summary(self, result: dict, country_name: str):
        """打印分析结果摘要。"""
        print(f"\n{'='*60}")
        print(f"📋 {country_name} 屠宰场名录获取分析")
        print(f"{'='*60}")

        print(f"\n🏛️ 负责机构: {result.get('responsible_agency', '未知')}")
        print(f"🌐 官方网站: {result.get('agency_website', '未知')}")

        access_method = result.get('access_method', 'unknown')
        access_labels = {
            "public_download": "✅ 公开下载",
            "registration_required": "📝 需要注册",
            "application_required": "📄 需要申请",
            "purchase_required": "💰 需要付费",
            "unknown": "❓ 未知"
        }
        print(f"📥 获取方式: {access_labels.get(access_method, access_method)}")

        if result.get('registration_url'):
            print(f"🔗 注册页面: {result['registration_url']}")

        if result.get('application_process'):
            print(f"📋 申请流程: {result['application_process']}")

        print(f"⏱️ 预计时间: {result.get('estimated_time', '未知')}")

        contact = result.get('contact_info', {})
        if any(contact.values()):
            print(f"\n📞 联系方式:")
            if contact.get('email'):
                print(f"   邮箱: {contact['email']}")
            if contact.get('phone'):
                print(f"   电话: {contact['phone']}")
            if contact.get('address'):
                print(f"   地址: {contact['address']}")

        alternatives = result.get('alternative_sources', [])
        if alternatives:
            print(f"\n🔄 其他来源:")
            for alt in alternatives:
                print(f"   • {alt}")

        confidence = result.get('confidence', 0)
        confidence_bar = "█" * int(confidence * 10) + "░" * (10 - int(confidence * 10))
        print(f"\n📊 置信度: [{confidence_bar}] {confidence*100:.0f}%")

        print(f"{'='*60}\n")

    async def generate_inquiry_email(
        self,
        agency_name: str,
        country: str,
        language: str = "es"
    ) -> dict:
        """
        生成向官方机构询问屠宰场名录的邮件。

        Args:
            agency_name: 机构名称
            country: 国家名称
            language: 邮件语言代码 (es/en/pt/fr等)

        Returns:
            {
                "subject": "邮件主题",
                "body": "邮件正文",
                "language": "语言"
            }
        """
        logger.info(f"生成向 {agency_name} 询问的{LANGUAGE_NAMES.get(language, language)}邮件")

        # 构建提示词
        prompt = GENERATE_EMAIL_PROMPT.format(
            agency_name=agency_name,
            country=country,
            language=LANGUAGE_NAMES.get(language, language)
        )

        # 发送请求
        response = await self._send_to_ai(prompt)

        # 解析响应
        result = extract_json_from_response(response)

        if not result:
            logger.warning("无法解析AI响应为JSON")
            result = {
                "subject": f"Solicitud de información - Listado de mataderos registrados",
                "body": response,
                "language": language
            }

        # 记录历史
        self.inquiry_history.append({
            "type": "generate_inquiry_email",
            "agency_name": agency_name,
            "country": country,
            "language": language,
            "timestamp": datetime.now().isoformat(),
            "result": result
        })

        # 打印邮件内容
        self._print_email(result)

        return result

    def _print_email(self, result: dict):
        """打印生成的邮件。"""
        print(f"\n{'='*60}")
        print("📧 生成的询问邮件")
        print(f"{'='*60}")
        print(f"\n语言: {result.get('language', '未知')}")
        print(f"\n主题: {result.get('subject', '')}")
        print(f"\n{'─'*40}")
        print(result.get('body', ''))
        print(f"{'─'*40}")
        print(f"{'='*60}\n")

    async def check_registration_requirements(
        self,
        registration_url: str
    ) -> dict:
        """
        分析注册页面，了解注册要求。

        Args:
            registration_url: 注册页面URL

        Returns:
            {
                "requires_local_company": bool,
                "requires_government_id": bool,
                "requires_industry_license": bool,
                "registration_free": bool,
                "registration_steps": ["步骤列表"],
                "can_foreign_register": bool,
                "workaround_suggestions": ["绕过限制的建议"]
            }
        """
        logger.info(f"分析注册要求: {registration_url}")

        # 构建提示词
        prompt = CHECK_REGISTRATION_PROMPT.format(
            registration_url=registration_url
        )

        # 发送请求
        response = await self._send_to_ai(prompt)

        # 解析响应
        result = extract_json_from_response(response)

        if not result:
            logger.warning("无法解析AI响应为JSON")
            result = {
                "requires_local_company": None,
                "requires_government_id": None,
                "requires_industry_license": None,
                "registration_free": None,
                "registration_steps": [],
                "can_foreign_register": None,
                "workaround_suggestions": [],
                "raw_response": response
            }

        # 记录历史
        self.inquiry_history.append({
            "type": "check_registration_requirements",
            "registration_url": registration_url,
            "timestamp": datetime.now().isoformat(),
            "result": result
        })

        # 打印分析结果
        self._print_registration_analysis(result, registration_url)

        return result

    def _print_registration_analysis(self, result: dict, url: str):
        """打印注册要求分析结果。"""
        print(f"\n{'='*60}")
        print("🔐 注册要求分析")
        print(f"{'='*60}")
        print(f"\n🔗 URL: {url}")

        def bool_icon(val):
            if val is True:
                return "✅ 是"
            elif val is False:
                return "❌ 否"
            return "❓ 未知"

        print(f"\n📋 要求:")
        print(f"   需要当地公司: {bool_icon(result.get('requires_local_company'))}")
        print(f"   需要政府ID: {bool_icon(result.get('requires_government_id'))}")
        print(f"   需要行业许可: {bool_icon(result.get('requires_industry_license'))}")
        print(f"   注册免费: {bool_icon(result.get('registration_free'))}")
        print(f"   外国可注册: {bool_icon(result.get('can_foreign_register'))}")

        steps = result.get('registration_steps', [])
        if steps:
            print(f"\n📝 注册步骤:")
            for i, step in enumerate(steps, 1):
                print(f"   {i}. {step}")

        suggestions = result.get('workaround_suggestions', [])
        if suggestions:
            print(f"\n💡 变通建议:")
            for sug in suggestions:
                print(f"   • {sug}")

        print(f"{'='*60}\n")

    async def full_inquiry_workflow(
        self,
        country_code: str,
        country_name: str,
        official_agencies: list = None,
        search_results: list = None,
        generate_email: bool = True,
        email_language: str = "es"
    ) -> dict:
        """
        执行完整的查询工作流程。

        1. 分析名录获取途径
        2. 如果需要注册，分析注册要求
        3. 生成询问邮件（可选）

        Args:
            country_code: 国家代码
            country_name: 国家名称
            official_agencies: 官方机构列表
            search_results: 之前的搜索结果
            generate_email: 是否生成询问邮件
            email_language: 邮件语言

        Returns:
            完整的查询结果
        """
        print(f"\n{'#'*60}")
        print(f"#  开始 {country_name} 屠宰场名录智能查询")
        print(f"{'#'*60}\n")

        workflow_result = {
            "country_code": country_code,
            "country_name": country_name,
            "timestamp": datetime.now().isoformat(),
            "steps": []
        }

        # Step 1: 分析获取途径
        print("📍 步骤 1/3: 分析名录获取途径...")
        analysis = await self.analyze_registry_access(
            country_code,
            country_name,
            official_agencies or [],
            search_results or []
        )
        workflow_result["analysis"] = analysis
        workflow_result["steps"].append("analyze_registry_access")

        # Step 2: 如果需要注册，分析注册要求
        if analysis.get("access_method") == "registration_required" and analysis.get("registration_url"):
            print("📍 步骤 2/3: 分析注册要求...")
            registration = await self.check_registration_requirements(
                analysis["registration_url"]
            )
            workflow_result["registration_requirements"] = registration
            workflow_result["steps"].append("check_registration_requirements")
        else:
            print("📍 步骤 2/3: 跳过（无需注册或无注册URL）")
            workflow_result["registration_requirements"] = None

        # Step 3: 生成询问邮件
        if generate_email and analysis.get("responsible_agency"):
            print("📍 步骤 3/3: 生成询问邮件...")
            email = await self.generate_inquiry_email(
                analysis["responsible_agency"],
                country_name,
                email_language
            )
            workflow_result["inquiry_email"] = email
            workflow_result["steps"].append("generate_inquiry_email")
        else:
            print("📍 步骤 3/3: 跳过（未要求生成邮件或无机构信息）")
            workflow_result["inquiry_email"] = None

        # 生成总结
        self._print_workflow_summary(workflow_result)

        return workflow_result

    def _print_workflow_summary(self, result: dict):
        """打印工作流程总结。"""
        print(f"\n{'#'*60}")
        print(f"#  查询工作流程完成")
        print(f"{'#'*60}")

        analysis = result.get("analysis", {})

        print(f"\n📊 总结:")
        print(f"   国家: {result['country_name']} ({result['country_code']})")
        print(f"   负责机构: {analysis.get('responsible_agency', '未知')}")
        print(f"   获取方式: {analysis.get('access_method', '未知')}")
        print(f"   置信度: {analysis.get('confidence', 0)*100:.0f}%")

        print(f"\n📝 完成步骤: {', '.join(result['steps'])}")

        # 下一步建议
        access_method = analysis.get("access_method", "unknown")
        print(f"\n💡 建议下一步:")

        if access_method == "public_download":
            print("   1. 访问官方网站下载名录")
            if analysis.get("agency_website"):
                print(f"      URL: {analysis['agency_website']}")

        elif access_method == "registration_required":
            print("   1. 访问注册页面进行注册")
            if analysis.get("registration_url"):
                print(f"      URL: {analysis['registration_url']}")
            reg = result.get("registration_requirements", {})
            if reg and not reg.get("can_foreign_register"):
                print("   ⚠️ 注意: 可能不支持外国注册，考虑联系当地代理")

        elif access_method == "application_required":
            print("   1. 发送询问邮件了解申请流程")
            print("   2. 准备所需申请材料")

        else:
            print("   1. 发送生成的询问邮件")
            print("   2. 等待官方回复")

        print(f"{'#'*60}\n")

    def get_inquiry_history(self) -> list:
        """获取查询历史记录。"""
        return self.inquiry_history

    def export_history(self, filepath: str = None) -> str:
        """导出查询历史到JSON文件。"""
        if not filepath:
            filepath = f"./logs/registry_inquiry_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.inquiry_history, f, ensure_ascii=False, indent=2)

        logger.info(f"查询历史已导出到: {filepath}")
        return filepath


# ── 交互式菜单 ────────────────────────────────────────────────

async def interactive_menu(controllers: dict):
    """交互式查询菜单。"""
    runner = RegistryInquiryRunner(controllers)

    while True:
        print(f"\n{'='*60}")
        print("🏛️ 官方屠宰场名录智能查询")
        print(f"{'='*60}")
        print("1. 分析某国名录获取途径")
        print("2. 生成询问邮件")
        print("3. 分析注册页面要求")
        print("4. 执行完整查询流程")
        print("5. 查看查询历史")
        print("6. 导出历史记录")
        print("0. 返回")
        print(f"{'='*60}")

        choice = input("请选择 (0-6): ").strip()

        if choice == "1":
            code = input("国家代码 (如 VE): ").strip().upper()
            name = input("国家名称 (如 委内瑞拉): ").strip()
            agencies = input("已知机构 (逗号分隔，可跳过): ").strip()
            agencies_list = [a.strip() for a in agencies.split(",")] if agencies else []

            if code and name:
                await runner.analyze_registry_access(code, name, agencies_list, [])

        elif choice == "2":
            agency = input("机构名称: ").strip()
            country = input("国家名称: ").strip()
            lang = input("语言代码 (es/en/pt，默认es): ").strip() or "es"

            if agency and country:
                await runner.generate_inquiry_email(agency, country, lang)

        elif choice == "3":
            url = input("注册页面URL: ").strip()
            if url:
                await runner.check_registration_requirements(url)

        elif choice == "4":
            code = input("国家代码 (如 VE): ").strip().upper()
            name = input("国家名称 (如 委内瑞拉): ").strip()
            agencies = input("已知机构 (逗号分隔，可跳过): ").strip()
            agencies_list = [a.strip() for a in agencies.split(",")] if agencies else []
            lang = input("邮件语言 (es/en/pt，默认es): ").strip() or "es"

            if code and name:
                await runner.full_inquiry_workflow(
                    code, name, agencies_list, [], True, lang
                )

        elif choice == "5":
            history = runner.get_inquiry_history()
            if history:
                print(f"\n📜 查询历史 ({len(history)}条):")
                for i, item in enumerate(history, 1):
                    print(f"  {i}. [{item['timestamp']}] {item['type']}")
            else:
                print("\n（暂无查询历史）")

        elif choice == "6":
            filepath = runner.export_history()
            print(f"✅ 已导出到: {filepath}")

        elif choice == "0":
            break

        else:
            print("无效选择")


# ── 主入口 ────────────────────────────────────────────────────

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║         🏛️ 官方屠宰场名录智能查询工具                      ║
    ║                                                           ║
    ║   分析如何获取各国官方屠宰场/肉类加工厂名录                  ║
    ╚═══════════════════════════════════════════════════════════╝

    ⚠️  请通过 start.py 启动，以自动初始化AI控制器
    """)
