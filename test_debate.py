import asyncio
import json
from datetime import datetime
from core.debate_system import (
    DebateOrchestrator,
    FinderAgent,
    CriticAgent,
    VerifierAgent,
    JudgeAgent,
    AgentRole,
    DEBATE_CONFIG
)
from core.browser_manager import BrowserManager
from core.chatgpt_controller import ChatGPTController
from core.claude_controller import ClaudeController
from core.deepseek_controller import DeepSeekController

class DebateTestRunner:
    """对抗验证测试运行器"""

    def __init__(self):
        self.browser_manager = None
        self.controllers = {}
        self.orchestrator = None
        self.test_results = []

    async def setup(self):
        """初始化"""
        print("=" * 60)
        print("🔧 初始化对抗验证测试环境")
        print("=" * 60)

        # 初始化浏览器
        self.browser_manager = BrowserManager()
        await self.browser_manager.initialize()

        # 初始化控制器
        print("\n📱 初始化AI控制器...")

        self.controllers = {
            "chatgpt": ChatGPTController(self.browser_manager),
            "claude": ClaudeController(self.browser_manager),
            "deepseek": DeepSeekController(self.browser_manager)
        }

        # 检查登录状态
        for name, controller in self.controllers.items():
            logged_in = await controller.check_login()
            status = "✅ 已登录" if logged_in else "❌ 未登录"
            print(f"  {name}: {status}")

        # 初始化编排器
        self.orchestrator = DebateOrchestrator(self.controllers)
        print("\n✅ 初始化完成")

    async def test_single_agent(self, agent_name, test_input):
        """测试单个Agent"""
        print(f"\n{'='*60}")
        print(f"🧪 测试 {agent_name} Agent")
        print(f"{'='*60}")

        start_time = datetime.now()

        try:
            if agent_name == "finder":
                result = await self.orchestrator.finder.find_contacts(
                    test_input["company_name"],
                    test_input["country"],
                    test_input.get("city")
                )
            elif agent_name == "critic":
                result = await self.orchestrator.critic.critique(
                    test_input["finder_result"],
                    test_input["company_name"],
                    test_input["country"]
                )
            elif agent_name == "verifier":
                result = await self.orchestrator.verifier.verify(
                    test_input["finder_result"],
                    test_input["critic_result"],
                    test_input["company_name"],
                    test_input["country"]
                )
            elif agent_name == "judge":
                result = await self.orchestrator.judge.judge(
                    test_input["finder_result"],
                    test_input["critic_result"],
                    test_input["verifier_result"],
                    test_input["company_name"]
                )
            else:
                raise ValueError(f"未知Agent: {agent_name}")

            duration = (datetime.now() - start_time).total_seconds()

            print(f"\n⏱️ 耗时: {duration:.1f}秒")
            print(f"\n📤 输出:")
            print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])

            return {"success": True, "result": result, "duration": duration}

        except Exception as e:
            print(f"\n❌ 错误: {e}")
            return {"success": False, "error": str(e)}

    async def test_full_debate(self, company_name, country, city=None):
        """测试完整对抗流程"""
        print(f"\n{'='*60}")
        print(f"🔄 完整对抗测试: {company_name} ({country})")
        print(f"{'='*60}")

        total_start = datetime.now()
        rounds = {}

        # === Round 1: Finder ===
        print(f"\n{'─'*40}")
        print("🔍 Round 1: FINDER")
        print(f"{'─'*40}")

        start = datetime.now()
        finder_result = await self.orchestrator.finder.find_contacts(
            company_name, country, city
        )
        rounds["finder"] = {
            "result": finder_result,
            "duration": (datetime.now() - start).total_seconds()
        }

        print(f"⏱️ 耗时: {rounds['finder']['duration']:.1f}秒")
        self._print_finder_summary(finder_result)

        # === Round 2: Critic ===
        print(f"\n{'─'*40}")
        print("🔴 Round 2: CRITIC")
        print(f"{'─'*40}")

        start = datetime.now()
        critic_result = await self.orchestrator.critic.critique(
            finder_result, company_name, country
        )
        rounds["critic"] = {
            "result": critic_result,
            "duration": (datetime.now() - start).total_seconds()
        }

        print(f"⏱️ 耗时: {rounds['critic']['duration']:.1f}秒")
        self._print_critic_summary(critic_result)

        # === Round 3: Verifier ===
        print(f"\n{'─'*40}")
        print("✅ Round 3: VERIFIER")
        print(f"{'─'*40}")

        start = datetime.now()
        verifier_result = await self.orchestrator.verifier.verify(
            finder_result, critic_result, company_name, country
        )
        rounds["verifier"] = {
            "result": verifier_result,
            "duration": (datetime.now() - start).total_seconds()
        }

        print(f"⏱️ 耗时: {rounds['verifier']['duration']:.1f}秒")
        self._print_verifier_summary(verifier_result)

        # === Round 4: Judge ===
        print(f"\n{'─'*40}")
        print("⚖️ Round 4: JUDGE")
        print(f"{'─'*40}")

        start = datetime.now()
        judge_result = await self.orchestrator.judge.judge(
            finder_result, critic_result, verifier_result, company_name
        )
        rounds["judge"] = {
            "result": judge_result,
            "duration": (datetime.now() - start).total_seconds()
        }

        print(f"⏱️ 耗时: {rounds['judge']['duration']:.1f}秒")
        self._print_judge_summary(judge_result)

        # === 总结 ===
        total_duration = (datetime.now() - total_start).total_seconds()

        print(f"\n{'='*60}")
        print("📊 对抗验证总结")
        print(f"{'='*60}")
        print(f"公司: {company_name}")
        print(f"国家: {country}")
        print(f"总耗时: {total_duration:.1f}秒")
        print(f"\n各轮耗时:")
        for role, data in rounds.items():
            print(f"  {role}: {data['duration']:.1f}秒")

        if isinstance(judge_result, dict):
            confidence = judge_result.get("overall_confidence", "N/A")
            needs_review = judge_result.get("needs_human_review", "N/A")
            print(f"\n最终置信度: {confidence}")
            print(f"需人工复核: {needs_review}")

        return {
            "company": company_name,
            "country": country,
            "rounds": rounds,
            "total_duration": total_duration
        }

    def _print_finder_summary(self, result):
        """打印Finder摘要"""
        if isinstance(result, dict):
            emails = result.get("emails", [])
            phones = result.get("phones", [])
            print(f"📧 找到邮箱: {len(emails)}个")
            for e in emails[:3]:
                if isinstance(e, dict):
                    print(f"   • {e.get('address', e)}")
                else:
                    print(f"   • {e}")
            print(f"📞 找到电话: {len(phones)}个")

    def _print_critic_summary(self, result):
        """打印Critic摘要"""
        if isinstance(result, dict):
            critiques = result.get("critiques", [])
            valid = sum(1 for c in critiques if c.get("status") == "valid")
            suspicious = sum(1 for c in critiques if c.get("status") == "suspicious")
            print(f"🟢 有效: {valid}项")
            print(f"🔴 可疑: {suspicious}项")

            concerns = result.get("overall_concerns", [])
            if concerns:
                print("⚠️ 主要担忧:")
                for c in concerns[:3]:
                    print(f"   • {c}")

    def _print_verifier_summary(self, result):
        """打印Verifier摘要"""
        if isinstance(result, dict):
            verifications = result.get("verifications", [])
            verified = sum(1 for v in verifications if v.get("verified") == True)
            unverified = sum(1 for v in verifications if v.get("verified") == False)
            print(f"✅ 已验证: {verified}项")
            print(f"❌ 未验证: {unverified}项")

    def _print_judge_summary(self, result):
        """打印Judge摘要"""
        if isinstance(result, dict):
            decision = result.get("final_decision", {})
            accepted = decision.get("accepted", [])
            rejected = decision.get("rejected", [])

            print(f"\n📋 最终判定:")
            print(f"✅ 采纳: {len(accepted)}项")
            for item in accepted[:3]:
                if isinstance(item, dict):
                    print(f"   • {item.get('item', item)} ({item.get('confidence', '?')}%)")

            print(f"❌ 排除: {len(rejected)}项")
            for item in rejected[:3]:
                if isinstance(item, dict):
                    print(f"   • {item.get('item', item)}: {item.get('reason', '?')}")

    async def run_batch_test(self, test_cases):
        """批量测试"""
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
                    case.get("city")
                )
                result["status"] = "success"
            except Exception as e:
                result = {
                    "company": case["company_name"],
                    "country": case["country"],
                    "status": "failed",
                    "error": str(e)
                }

            results.append(result)

            # 休息一下避免限流
            await asyncio.sleep(5)

        # 打印批量测试总结
        self._print_batch_summary(results)

        return results

    def _print_batch_summary(self, results):
        """打印批量测试总结"""
        print(f"\n{'='*60}")
        print("📊 批量测试总结")
        print(f"{'='*60}")

        success = sum(1 for r in results if r["status"] == "success")
        failed = len(results) - success

        print(f"✅ 成功: {success}/{len(results)}")
        print(f"❌ 失败: {failed}/{len(results)}")

        if success > 0:
            durations = [r["total_duration"] for r in results if r["status"] == "success"]
            avg_duration = sum(durations) / len(durations)
            print(f"⏱️ 平均耗时: {avg_duration:.1f}秒")

    async def cleanup(self):
        """清理"""
        if self.browser_manager:
            await self.browser_manager.close()


# === 测试用例 ===

TEST_CASES = [
    {
        "company_name": "JBS S.A.",
        "country": "Brazil",
        "city": "São Paulo"
    },
    {
        "company_name": "Minerva Foods",
        "country": "Brazil"
    },
    {
        "company_name": "Marfrig Global Foods",
        "country": "Brazil"
    },
    {
        "company_name": "Frigorifico Gorina",
        "country": "Argentina"
    },
    {
        "company_name": "Swift Argentina",
        "country": "Argentina"
    }
]


# === 交互式菜单 ===

async def interactive_menu():
    """交互式测试菜单"""
    runner = DebateTestRunner()

    try:
        await runner.setup()

        while True:
            print(f"\n{'='*60}")
            print("🧪 对抗验证测试菜单")
            print(f"{'='*60}")
            print("1. 测试单个公司（手动输入）")
            print("2. 测试预设案例（JBS）")
            print("3. 批量测试所有预设案例")
            print("4. 单独测试Finder Agent")
            print("5. 单独测试Critic Agent")
            print("6. 单独测试Verifier Agent")
            print("7. 单独测试Judge Agent")
            print("8. 查看Agent配置")
            print("9. 退出")
            print(f"{'='*60}")

            choice = input("请选择 (1-9): ").strip()

            if choice == "1":
                company = input("公司名称: ").strip()
                country = input("国家: ").strip()
                city = input("城市（可选，直接回车跳过）: ").strip() or None

                if company and country:
                    await runner.test_full_debate(company, country, city)

            elif choice == "2":
                await runner.test_full_debate("JBS S.A.", "Brazil", "São Paulo")

            elif choice == "3":
                await runner.run_batch_test(TEST_CASES)

            elif choice == "4":
                company = input("公司名称: ").strip() or "JBS S.A."
                country = input("国家: ").strip() or "Brazil"
                await runner.test_single_agent("finder", {
                    "company_name": company,
                    "country": country
                })

            elif choice == "5":
                print("需要先运行Finder获取结果，使用模拟数据...")
                mock_finder = {
                    "emails": [
                        {"address": "export@jbs.com.br", "source": "官网"},
                        {"address": "sales@jbs-foods.com", "source": "搜索"}
                    ],
                    "phones": [{"number": "+55 11 3144-4000", "source": "官网"}]
                }
                await runner.test_single_agent("critic", {
                    "finder_result": mock_finder,
                    "company_name": "JBS S.A.",
                    "country": "Brazil"
                })

            elif choice == "6":
                print("使用模拟数据测试Verifier...")
                mock_finder = {
                    "emails": [{"address": "export@jbs.com.br", "source": "官网"}],
                    "phones": []
                }
                mock_critic = {
                    "critiques": [
                        {"item": "export@jbs.com.br", "status": "valid", "issues": []}
                    ]
                }
                await runner.test_single_agent("verifier", {
                    "finder_result": mock_finder,
                    "critic_result": mock_critic,
                    "company_name": "JBS S.A.",
                    "country": "Brazil"
                })

            elif choice == "7":
                print("使用模拟数据测试Judge...")
                await runner.test_single_agent("judge", {
                    "finder_result": {"emails": [{"address": "test@jbs.com.br"}]},
                    "critic_result": {"critiques": [{"item": "test@jbs.com.br", "status": "valid"}]},
                    "verifier_result": {"verifications": [{"item": "test@jbs.com.br", "verified": True}]},
                    "company_name": "JBS S.A."
                })

            elif choice == "8":
                print(f"\n当前Agent配置:")
                print(json.dumps(DEBATE_CONFIG, ensure_ascii=False, indent=2))

            elif choice == "9":
                print("退出测试...")
                break

            else:
                print("无效选择，请重试")

    finally:
        await runner.cleanup()


# === 主入口 ===

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║           🔄 多AI对抗验证测试工具                          ║
    ║                                                           ║
    ║   测试 Finder → Critic → Verifier → Judge 完整流程        ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    asyncio.run(interactive_menu())
