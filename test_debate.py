#!/usr/bin/env python3
"""对抗验证测试工具 - 测试多AI对抗验证流程。"""

import asyncio
import json
from datetime import datetime

from config.settings import BROWSER_DATA_DIR, DEBATE_CONFIG
from core.browser_manager import BrowserManager
from core.chatgpt_controller import ChatGPTController
from core.claude_controller import ClaudeController
from core.debate_system import AgentRole, DebateOrchestrator
from core.deepseek_controller import DeepSeekController

# 预设测试用例
TEST_CASES = [
    {
        "company_name": "JBS S.A.",
        "country": "Brazil",
        "city": "São Paulo",
    },
    {
        "company_name": "Minerva Foods",
        "country": "Brazil",
    },
    {
        "company_name": "Marfrig Global Foods",
        "country": "Brazil",
    },
    {
        "company_name": "Frigorifico Gorina",
        "country": "Argentina",
    },
    {
        "company_name": "Swift Argentina",
        "country": "Argentina",
    },
]


class DebateTestRunner:
    """对抗验证测试运行器"""

    def __init__(self):
        self.browser_manager = None
        self.controllers = {}
        self.orchestrator = None
        self.test_results = []

    async def setup(self):
        """初始化测试环境。"""
        print("=" * 60)
        print("🔧 初始化对抗验证测试环境")
        print("=" * 60)

        # 初始化浏览器
        self.browser_manager = BrowserManager(BROWSER_DATA_DIR)
        await self.browser_manager.launch(headless=False)
        print("✅ 浏览器已启动")

        # 初始化控制器
        print("\n📱 初始化AI控制器...")

        ai_configs = {
            "chatgpt": ("https://chat.openai.com", ChatGPTController),
            "claude": ("https://claude.ai", ClaudeController),
            "deepseek": ("https://chat.deepseek.com", DeepSeekController),
        }

        for name, (url, controller_cls) in ai_configs.items():
            try:
                page = await self.browser_manager.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

                is_logged_in = await self.browser_manager.check_login(name, page)
                status = "✅ 已登录" if is_logged_in else "⚠️ 未登录"
                print(f"  {name}: {status}")

                if is_logged_in:
                    self.controllers[name] = controller_cls(page)
                else:
                    await page.close()

            except Exception as e:
                print(f"  {name}: ❌ 初始化失败 ({e})")

        if not self.controllers:
            print("\n❌ 没有可用的AI控制器")
            return False

        # 初始化编排器
        self.orchestrator = DebateOrchestrator(self.controllers)
        print("\n✅ 对抗验证编排器已初始化")

        # 显示Agent分配
        print("\n📋 Agent分配:")
        for role in AgentRole:
            agent = self.orchestrator.agents.get(role)
            if agent:
                print(f"  {role.value}: {agent.name}")

        return True

    async def test_single_agent(self, agent_name: str, test_input: dict) -> dict:
        """测试单个Agent。"""
        print(f"\n{'='*60}")
        print(f"🧪 测试 {agent_name.upper()} Agent")
        print(f"{'='*60}")

        start_time = datetime.now()

        try:
            if agent_name == "finder":
                agent = self.orchestrator.agents.get(AgentRole.FINDER)
                result = await agent.find_contacts(
                    test_input["company_name"],
                    test_input["country"],
                )

            elif agent_name == "critic":
                agent = self.orchestrator.agents.get(AgentRole.CRITIC)
                result = await agent.critique(
                    test_input["finder_result"],
                    test_input["company_name"],
                    test_input["country"],
                )

            elif agent_name == "verifier":
                agent = self.orchestrator.agents.get(AgentRole.VERIFIER)
                result = await agent.verify(
                    test_input["finder_result"],
                    test_input["critic_result"],
                    test_input["company_name"],
                    test_input["country"],
                )

            elif agent_name == "judge":
                agent = self.orchestrator.agents.get(AgentRole.JUDGE)
                result = await agent.judge(
                    test_input["finder_result"],
                    test_input["critic_result"],
                    test_input["verifier_result"],
                    test_input["company_name"],
                )

            else:
                raise ValueError(f"未知Agent: {agent_name}")

            duration = (datetime.now() - start_time).total_seconds()

            print(f"\n⏱️ 耗时: {duration:.1f}秒")
            print("\n📤 输出:")

            # 格式化输出
            if isinstance(result, dict):
                output = json.dumps(result, ensure_ascii=False, indent=2)
                print(output[:2000])
                if len(output) > 2000:
                    print("... (输出已截断)")
            else:
                print(str(result)[:2000])

            return {"success": True, "result": result, "duration": duration}

        except Exception as e:
            print(f"\n❌ 错误: {e}")
            return {"success": False, "error": str(e)}

    async def test_full_debate(
        self,
        company_name: str,
        country: str,
        city: str | None = None,
    ) -> dict:
        """测试完整对抗流程。"""
        print(f"\n{'='*60}")
        print(f"🔄 完整对抗测试: {company_name} ({country})")
        print(f"{'='*60}")

        total_start = datetime.now()
        rounds = {}

        finder = self.orchestrator.agents.get(AgentRole.FINDER)
        critic = self.orchestrator.agents.get(AgentRole.CRITIC)
        verifier = self.orchestrator.agents.get(AgentRole.VERIFIER)
        judge = self.orchestrator.agents.get(AgentRole.JUDGE)

        # === Round 1: Finder ===
        print(f"\n{'─'*40}")
        print("🔍 Round 1: FINDER")
        print(f"{'─'*40}")

        start = datetime.now()
        try:
            finder_result = await finder.find_contacts(company_name, country)
            rounds["finder"] = {
                "result": finder_result,
                "duration": (datetime.now() - start).total_seconds(),
                "success": True,
            }
            print(f"⏱️ 耗时: {rounds['finder']['duration']:.1f}秒")
            self._print_finder_summary(finder_result)
        except Exception as e:
            print(f"❌ Finder失败: {e}")
            rounds["finder"] = {"error": str(e), "success": False}
            finder_result = {"error": str(e)}

        # === Round 2: Critic ===
        print(f"\n{'─'*40}")
        print("🔴 Round 2: CRITIC")
        print(f"{'─'*40}")

        start = datetime.now()
        try:
            critic_result = await critic.critique(finder_result, company_name, country)
            rounds["critic"] = {
                "result": critic_result,
                "duration": (datetime.now() - start).total_seconds(),
                "success": True,
            }
            print(f"⏱️ 耗时: {rounds['critic']['duration']:.1f}秒")
            self._print_critic_summary(critic_result)
        except Exception as e:
            print(f"❌ Critic失败: {e}")
            rounds["critic"] = {"error": str(e), "success": False}
            critic_result = {"error": str(e)}

        # === Round 3: Verifier ===
        print(f"\n{'─'*40}")
        print("✅ Round 3: VERIFIER")
        print(f"{'─'*40}")

        start = datetime.now()
        try:
            verifier_result = await verifier.verify(
                finder_result, critic_result, company_name, country,
            )
            rounds["verifier"] = {
                "result": verifier_result,
                "duration": (datetime.now() - start).total_seconds(),
                "success": True,
            }
            print(f"⏱️ 耗时: {rounds['verifier']['duration']:.1f}秒")
            self._print_verifier_summary(verifier_result)
        except Exception as e:
            print(f"❌ Verifier失败: {e}")
            rounds["verifier"] = {"error": str(e), "success": False}
            verifier_result = {"error": str(e)}

        # === Round 4: Judge ===
        print(f"\n{'─'*40}")
        print("⚖️ Round 4: JUDGE")
        print(f"{'─'*40}")

        start = datetime.now()
        try:
            judge_result = await judge.judge(
                finder_result, critic_result, verifier_result, company_name,
            )
            rounds["judge"] = {
                "result": judge_result,
                "duration": (datetime.now() - start).total_seconds(),
                "success": True,
            }
            print(f"⏱️ 耗时: {rounds['judge']['duration']:.1f}秒")
            self._print_judge_summary(judge_result)
        except Exception as e:
            print(f"❌ Judge失败: {e}")
            rounds["judge"] = {"error": str(e), "success": False}
            judge_result = {"error": str(e)}

        # === 总结 ===
        total_duration = (datetime.now() - total_start).total_seconds()

        print(f"\n{'='*60}")
        print("📊 对抗验证总结")
        print(f"{'='*60}")
        print(f"公司: {company_name}")
        print(f"国家: {country}")
        print(f"总耗时: {total_duration:.1f}秒")
        print("\n各轮耗时:")
        for role, data in rounds.items():
            if data.get("success"):
                print(f"  {role}: {data['duration']:.1f}秒 ✅")
            else:
                print(f"  {role}: 失败 ❌")

        if isinstance(judge_result, dict) and "error" not in judge_result:
            confidence = judge_result.get("overall_confidence", "N/A")
            needs_review = judge_result.get("needs_human_review", "N/A")
            risk_level = judge_result.get("risk_level", "N/A")
            print(f"\n最终置信度: {confidence}")
            print(f"风险等级: {risk_level}")
            print(f"需人工复核: {needs_review}")

        return {
            "company": company_name,
            "country": country,
            "rounds": rounds,
            "total_duration": total_duration,
            "status": "success" if all(r.get("success") for r in rounds.values()) else "partial",
        }

    def _print_finder_summary(self, result: dict):
        """打印Finder摘要。"""
        if not isinstance(result, dict):
            return

        emails = result.get("emails", [])
        phones = result.get("phones", [])
        websites = result.get("websites", [])
        contacts = result.get("contacts", [])

        print(f"📧 找到邮箱: {len(emails)}个")
        for e in emails[:3]:
            if isinstance(e, dict):
                print(f"   • {e.get('address', e)}")
            else:
                print(f"   • {e}")

        print(f"📞 找到电话: {len(phones)}个")
        for p in phones[:3]:
            if isinstance(p, dict):
                print(f"   • {p.get('number', p)}")
            else:
                print(f"   • {p}")

        print(f"🌐 找到网站: {len(websites)}个")
        print(f"👤 找到联系人: {len(contacts)}个")

    def _print_critic_summary(self, result: dict):
        """打印Critic摘要。"""
        if not isinstance(result, dict):
            return

        critiques = result.get("critiques", [])
        valid = sum(1 for c in critiques if isinstance(c, dict) and c.get("status") == "valid")
        uncertain = sum(1 for c in critiques if isinstance(c, dict) and c.get("status") == "uncertain")
        suspicious = sum(1 for c in critiques if isinstance(c, dict) and c.get("status") == "suspicious")

        print(f"🟢 有效: {valid}项")
        print(f"🟡 待验证: {uncertain}项")
        print(f"🔴 可疑: {suspicious}项")

        concerns = result.get("overall_concerns", [])
        if concerns:
            print("⚠️ 主要担忧:")
            for c in concerns[:3]:
                print(f"   • {c}")

        verification_points = result.get("recommended_verification", [])
        if verification_points:
            print("📋 建议验证:")
            for v in verification_points[:3]:
                print(f"   • {v}")

    def _print_verifier_summary(self, result: dict):
        """打印Verifier摘要。"""
        if not isinstance(result, dict):
            return

        verifications = result.get("verifications", [])
        verified = sum(1 for v in verifications if isinstance(v, dict) and v.get("verified") is True)
        unverified = sum(1 for v in verifications if isinstance(v, dict) and v.get("verified") is False)
        uncertain = sum(1 for v in verifications if isinstance(v, dict) and v.get("verified") == "uncertain")

        print(f"✅ 已验证: {verified}项")
        print(f"❌ 未验证: {unverified}项")
        print(f"❓ 不确定: {uncertain}项")

        company_confirmed = result.get("company_confirmed")
        if company_confirmed is not None:
            status = "✅ 已确认" if company_confirmed else "❌ 未确认"
            print(f"🏢 公司身份: {status}")

        additional = result.get("additional_findings", [])
        if additional:
            print("📌 额外发现:")
            for a in additional[:3]:
                print(f"   • {a}")

    def _print_judge_summary(self, result: dict):
        """打印Judge摘要。"""
        if not isinstance(result, dict):
            return

        decision = result.get("final_decision", {})
        accepted = decision.get("accepted", [])
        rejected = decision.get("rejected", [])
        pending = decision.get("pending", [])

        print(f"\n📋 最终判定:")
        print(f"✅ 采纳: {len(accepted)}项")
        for item in accepted[:3]:
            if isinstance(item, dict):
                confidence = item.get("confidence", "?")
                print(f"   • {item.get('item', item)} ({confidence}%)")

        print(f"❌ 排除: {len(rejected)}项")
        for item in rejected[:3]:
            if isinstance(item, dict):
                print(f"   • {item.get('item', item)}: {item.get('reason', '?')}")

        print(f"⏳ 待定: {len(pending)}项")

        summary = result.get("summary")
        if summary:
            print(f"\n💬 总结: {summary}")

    async def run_batch_test(self, test_cases: list) -> list:
        """批量测试。"""
        print(f"\n{'='*60}")
        print(f"🧪 批量测试: {len(test_cases)}个案例")
        print(f"{'='*60}")

        results = []

        for i, case in enumerate(test_cases, 1):
            print(f"\n[{i}/{len(test_cases)}] {case['company_name']} ({case['country']})")

            try:
                result = await self.test_full_debate(
                    case["company_name"],
                    case["country"],
                    case.get("city"),
                )
            except Exception as e:
                result = {
                    "company": case["company_name"],
                    "country": case["country"],
                    "status": "failed",
                    "error": str(e),
                }

            results.append(result)

            # 休息避免限流
            if i < len(test_cases):
                print("\n⏳ 等待5秒后继续...")
                await asyncio.sleep(5)

        # 打印批量测试总结
        self._print_batch_summary(results)

        return results

    def _print_batch_summary(self, results: list):
        """打印批量测试总结。"""
        print(f"\n{'='*60}")
        print("📊 批量测试总结")
        print(f"{'='*60}")

        success = sum(1 for r in results if r.get("status") == "success")
        partial = sum(1 for r in results if r.get("status") == "partial")
        failed = sum(1 for r in results if r.get("status") == "failed")

        print(f"✅ 完全成功: {success}/{len(results)}")
        print(f"⚠️ 部分成功: {partial}/{len(results)}")
        print(f"❌ 失败: {failed}/{len(results)}")

        successful_results = [r for r in results if r.get("total_duration")]
        if successful_results:
            durations = [r["total_duration"] for r in successful_results]
            avg_duration = sum(durations) / len(durations)
            min_duration = min(durations)
            max_duration = max(durations)
            print(f"\n⏱️ 耗时统计:")
            print(f"   平均: {avg_duration:.1f}秒")
            print(f"   最短: {min_duration:.1f}秒")
            print(f"   最长: {max_duration:.1f}秒")

    async def cleanup(self):
        """清理资源。"""
        if self.browser_manager:
            await self.browser_manager.close()
            print("\n✅ 浏览器已关闭")


async def interactive_menu():
    """交互式测试菜单。"""
    runner = DebateTestRunner()

    try:
        if not await runner.setup():
            print("\n❌ 初始化失败，请检查AI登录状态")
            input("\n按 Enter 键退出...")
            return

        while True:
            print(f"\n{'='*60}")
            print("🧪 对抗验证测试菜单")
            print(f"{'='*60}")
            print("1. 测试单个公司（手动输入）")
            print("2. 测试预设案例（JBS）")
            print("3. 批量测试所有预设案例")
            print("4. 单独测试 Finder Agent")
            print("5. 单独测试 Critic Agent（模拟数据）")
            print("6. 单独测试 Verifier Agent（模拟数据）")
            print("7. 单独测试 Judge Agent（模拟数据）")
            print("8. 查看Agent配置")
            print("9. 查看预设测试用例")
            print("0. 退出")
            print(f"{'='*60}")

            choice = input("请选择 (0-9): ").strip()

            if choice == "1":
                company = input("公司名称: ").strip()
                country = input("国家: ").strip()
                city = input("城市（可选，直接回车跳过）: ").strip() or None

                if company and country:
                    await runner.test_full_debate(company, country, city)
                else:
                    print("⚠️ 公司名称和国家为必填项")

            elif choice == "2":
                await runner.test_full_debate("JBS S.A.", "Brazil", "São Paulo")

            elif choice == "3":
                await runner.run_batch_test(TEST_CASES)

            elif choice == "4":
                company = input("公司名称 (默认: JBS S.A.): ").strip() or "JBS S.A."
                country = input("国家 (默认: Brazil): ").strip() or "Brazil"
                await runner.test_single_agent("finder", {
                    "company_name": company,
                    "country": country,
                })

            elif choice == "5":
                print("\n使用模拟Finder数据测试Critic...")
                mock_finder = {
                    "emails": [
                        {"address": "export@jbs.com.br", "source": "官网"},
                        {"address": "sales@jbs-foods.com", "source": "搜索"},
                    ],
                    "phones": [
                        {"number": "+55 11 3144-4000", "source": "官网"},
                    ],
                    "websites": [
                        {"url": "https://jbs.com.br", "type": "官网"},
                    ],
                }
                await runner.test_single_agent("critic", {
                    "finder_result": mock_finder,
                    "company_name": "JBS S.A.",
                    "country": "Brazil",
                })

            elif choice == "6":
                print("\n使用模拟数据测试Verifier...")
                mock_finder = {
                    "emails": [{"address": "export@jbs.com.br", "source": "官网"}],
                    "phones": [{"number": "+55 11 3144-4000", "source": "官网"}],
                }
                mock_critic = {
                    "critiques": [
                        {"item": "export@jbs.com.br", "type": "email", "status": "valid", "issues": [], "risk_level": 20},
                        {"item": "+55 11 3144-4000", "type": "phone", "status": "uncertain", "issues": ["需验证区号"], "risk_level": 40},
                    ],
                    "overall_concerns": ["需验证是否为正确部门"],
                    "recommended_verification": ["检查官网联系页面"],
                }
                await runner.test_single_agent("verifier", {
                    "finder_result": mock_finder,
                    "critic_result": mock_critic,
                    "company_name": "JBS S.A.",
                    "country": "Brazil",
                })

            elif choice == "7":
                print("\n使用模拟数据测试Judge...")
                await runner.test_single_agent("judge", {
                    "finder_result": {
                        "emails": [{"address": "export@jbs.com.br", "source": "官网"}],
                        "phones": [{"number": "+55 11 3144-4000", "source": "官网"}],
                    },
                    "critic_result": {
                        "critiques": [
                            {"item": "export@jbs.com.br", "status": "valid", "risk_level": 20},
                        ],
                    },
                    "verifier_result": {
                        "verifications": [
                            {"item": "export@jbs.com.br", "verified": True, "confidence": 85},
                        ],
                        "company_confirmed": True,
                    },
                    "company_name": "JBS S.A.",
                })

            elif choice == "8":
                print(f"\n{'='*60}")
                print("📋 当前Agent配置")
                print(f"{'='*60}")
                print(json.dumps(DEBATE_CONFIG, ensure_ascii=False, indent=2))
                print(f"\n当前Agent分配:")
                for role in AgentRole:
                    agent = runner.orchestrator.agents.get(role)
                    if agent:
                        print(f"  {role.value}: {agent.name}")

            elif choice == "9":
                print(f"\n{'='*60}")
                print("📋 预设测试用例")
                print(f"{'='*60}")
                for i, case in enumerate(TEST_CASES, 1):
                    city = case.get("city", "")
                    city_str = f", {city}" if city else ""
                    print(f"  {i}. {case['company_name']} ({case['country']}{city_str})")

            elif choice == "0":
                print("\n👋 退出测试...")
                break

            else:
                print("\n⚠️ 无效选择，请重试")

            input("\n按 Enter 键继续...")

    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")

    finally:
        await runner.cleanup()


if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║           🔄 多AI对抗验证测试工具                          ║
    ║                                                           ║
    ║   测试 Finder → Critic → Verifier → Judge 完整流程        ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    asyncio.run(interactive_menu())
