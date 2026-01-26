# 主程序入口

import asyncio
import logging

from config.settings import BROWSER_DATA_DIR, WS_SERVER_URL
from core.browser_manager import BrowserManager
from core.chatgpt_controller import ChatGPTController, ChatGPTTaskRunner
from core.claude_controller import ClaudeController, ClaudeTaskRunner
from core.decision_engine import DecisionEngine
from core.deepseek_controller import DeepSeekController, DeepSeekTaskRunner
from core.quality_checker import QualityChecker
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
}

# 启动顺序
STARTUP_AI_LIST = ["chatgpt", "claude", "deepseek"]


class BrowserAIClient:
    """主客户端：管理浏览器、AI控制器、决策引擎与 WebSocket 通信。"""

    def __init__(self):
        self.browser_manager = BrowserManager(BROWSER_DATA_DIR)
        self.controllers: dict = {}
        self.runners: dict = {}
        self.quality_checker = QualityChecker()
        self.decision_engine = DecisionEngine(self.quality_checker)
        self.ws_client = WSClient(WS_SERVER_URL)

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

        # 3. 连接 WebSocket
        await self.ws_client.connect()

        # 4. 注册消息处理器
        self.ws_client.on("new_task", self.handle_new_task)
        self.ws_client.on("retry_task", self.handle_retry_task)
        self.ws_client.on("review_result", self.handle_review_result)

    # ── 任务处理 ──────────────────────────────────────────

    async def handle_new_task(self, message: dict):
        """处理来自服务器的新任务。"""
        data = message.get("data", {})
        task_id = data.get("task_id", "unknown")
        task_type = data.get("task_type", "")
        params = data.get("params", {})

        print(f"\n📥 收到任务: {task_id} ({task_type})")
        logger.info("收到新任务: %s (%s)", task_id, task_type)

        await self.execute_task(task_id, task_type, params)

    async def execute_task(
        self,
        task_id: str,
        task_type: str,
        params: dict,
        use_ai: str | None = None,
    ):
        """选择 AI 并执行具体任务。"""
        ai_name = use_ai or "chatgpt"

        # 回退：指定的 AI 不可用时选第一个可用的
        if ai_name not in self.runners:
            available = list(self.runners.keys())
            if not available:
                print("❌ 没有可用的AI")
                logger.error("无可用AI，任务 %s 放弃", task_id)
                return
            ai_name = available[0]

        runner = self.runners[ai_name]
        print(f"🤖 使用 {ai_name} 执行任务 {task_id}")

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

            await self.process_result(task_id, task_type, result, ai_name)

        except Exception as e:
            logger.error("执行任务 %s 出错: %s", task_id, e)
            print(f"❌ 任务执行出错: {e}")

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
            await self.ws_client.send_auto_approved(task_id, result, score)

        elif action == "retry":
            next_ai = decision["next_ai"]
            print(f"🔄 重试: {task_id} 使用 {next_ai} (当前分数:{score})")
            await self.execute_task(
                task_id, task_type,
                {},  # params 已在首次调用时使用，retry 时由 runner 内部保留上下文
                use_ai=next_ai,
            )

        elif action == "need_review":
            print(f"📱 发送审核: {task_id} (分数:{score})")
            best = self.decision_engine.get_best_result(task_id)
            await self.ws_client.send_need_review(
                task_id, task_type,
                best if best is not None else result,
                score, decision["issues"], summary,
            )

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

    # ── 主循环 & 关闭 ────────────────────────────────────

    async def run(self):
        """启动并进入主循环。"""
        await self.setup()

        print("\n" + "=" * 50)
        print("  Browser-AI 就绪")
        print(f"  可用AI: {', '.join(self.controllers.keys()) or '无'}")
        print("=" * 50 + "\n")

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
