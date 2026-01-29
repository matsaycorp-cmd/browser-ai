# 主程序入口

import asyncio
import logging

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
from core.decision_engine import DecisionEngine
from core.deepseek_controller import DeepSeekController, DeepSeekTaskRunner
from core.parallel_executor import ParallelExecutor
from core.personnel_searcher import PersonnelEvaluator, PersonnelSearcher
from core.quality_checker import QualityChecker
from core.rate_limiter import RateLimiter
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
        self.rate_limiter = RateLimiter()
        self.parallel_executor: ParallelExecutor | None = None  # 在 setup 后初始化
        self.task_store = TaskPersistence()
        self.ws_client = WSClient(WS_SERVER_URL)
        self.personnel_searcher: PersonnelSearcher | None = None
        self.personnel_evaluator: PersonnelEvaluator | None = None

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

        # 5. 连接 WebSocket
        await self.ws_client.connect()

        # 6. 注册消息处理器
        self.ws_client.on("new_task", self.handle_new_task)
        self.ws_client.on("retry_task", self.handle_retry_task)
        self.ws_client.on("review_result", self.handle_review_result)
        self.ws_client.on("config_update", self.handle_config_update)
        self.ws_client.on("personnel_search", self.handle_personnel_search)

        # 7. 请求服务器配置
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
