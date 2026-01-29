# 并行执行模块

import asyncio
import logging
import time

from config.settings import AUTO_APPROVE_SCORE
from core.quality_checker import QualityChecker

logger = logging.getLogger(__name__)

# task_type → QualityChecker 使用的 checker 名称
TASK_TYPE_TO_CHECKER = {
    "search_contacts": "contact",
    "search_slaughterhouses": "slaughterhouse",
    "search_freight": "freight_forwarder",
    "generate_email": "email",
}

# task_type → 推荐执行模式
RECOMMENDED_MODES = {
    "search_contacts": "parallel",
    "search_slaughterhouses": "race",
    "search_freight": "parallel",
    "generate_email": "single",
}


class ParallelExecutor:
    """支持单AI、并行、竞速、最佳结果等多种执行策略。"""

    def __init__(self, controllers: dict, runners: dict, rate_limiter):
        self.controllers = controllers
        self.runners = runners
        self.rate_limiter = rate_limiter
        self.quality_checker = QualityChecker()
        self.mode = "single"
        self.max_parallel = 2

    # ── 配置 ─────────────────────────────────────────────

    def set_mode(self, mode: str):
        """设置执行模式: single | parallel | race | best"""
        if mode in ("single", "parallel", "race", "best"):
            self.mode = mode
            logger.info("执行模式已设为: %s", mode)
        else:
            logger.warning("未知执行模式: %s，保持 %s", mode, self.mode)

    def get_mode(self) -> str:
        return self.mode

    def reload_config(self, execution_mode: str | None = None, max_parallel: int | None = None):
        """从 ConfigManager 重新加载配置。"""
        if execution_mode is not None:
            self.set_mode(execution_mode)
        if max_parallel is not None:
            self.max_parallel = max_parallel
            logger.info("max_parallel 已更新为: %d", max_parallel)

    def select_execution_mode(self, task_type: str) -> str:
        """根据任务类型推荐执行模式。"""
        return RECOMMENDED_MODES.get(task_type, "single")

    # ── 单AI执行 ─────────────────────────────────────────

    async def execute_single(
        self, task_type: str, params: dict, ai_name: str,
    ) -> dict:
        """用单个 AI 执行任务，返回 {ai, result, score, time}。"""
        runner = self.runners.get(ai_name)
        if runner is None:
            return {"ai": ai_name, "result": None, "score": 0, "time": 0, "error": "AI不可用"}

        await self.rate_limiter.wait_if_needed(ai_name)
        start = time.time()

        try:
            result = await self._run_task(runner, task_type, params)
            self.rate_limiter.record_request(ai_name)
            elapsed = round(time.time() - start, 1)

            checker_type = TASK_TYPE_TO_CHECKER.get(task_type, task_type)
            report = self.quality_checker.check(checker_type, result)
            score = report["score"]

            logger.info("%s 完成 (%.1fs, %d分)", ai_name, elapsed, score)
            return {"ai": ai_name, "result": result, "score": score, "time": elapsed}

        except Exception as e:
            elapsed = round(time.time() - start, 1)
            logger.error("%s 执行失败 (%.1fs): %s", ai_name, elapsed, e)
            return {"ai": ai_name, "result": None, "score": 0, "time": elapsed, "error": str(e)}

    # ── 并行执行 ─────────────────────────────────────────

    async def execute_parallel(
        self, task_type: str, params: dict, ai_list: list[str],
    ) -> list[dict]:
        """并行启动多个 AI 执行相同任务，等待全部完成。"""
        ai_list = ai_list[:self.max_parallel]
        names = " + ".join(ai_list)
        print(f"🚀 并行执行: {names}")
        logger.info("并行执行: %s", names)

        tasks = [
            self.execute_single(task_type, params, ai)
            for ai in ai_list
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return list(results)

    # ── 竞速执行 ─────────────────────────────────────────

    async def execute_race(
        self, task_type: str, params: dict, ai_list: list[str],
    ) -> dict:
        """同时启动多个 AI，第一个达到合格分数的结果即返回。"""
        ai_list = ai_list[:self.max_parallel]
        names = " + ".join(ai_list)
        print(f"🏁 竞速执行: {names}")
        logger.info("竞速执行: %s", names)

        pending: set[asyncio.Task] = set()
        for ai in ai_list:
            t = asyncio.create_task(
                self.execute_single(task_type, params, ai),
                name=f"race-{ai}",
            )
            pending.add(t)

        best = {"ai": "", "result": None, "score": 0, "time": 0}

        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                entry = task.result()
                if entry["score"] > best["score"]:
                    best = entry
                # 达到合格分数 → 取消剩余任务
                if entry["score"] >= AUTO_APPROVE_SCORE:
                    print(f"🏆 {entry['ai']} 率先达标 ({entry['score']}分, {entry['time']}s)")
                    for p in pending:
                        p.cancel()
                    return best

        # 全部完成但无一达标，返回最佳
        if best["ai"]:
            print(f"🏁 竞速结束，最佳: {best['ai']} ({best['score']}分)")
        return best

    # ── 最佳结果执行 ──────────────────────────────────────

    async def execute_best(
        self, task_type: str, params: dict, ai_list: list[str],
    ) -> dict:
        """并行执行全部 AI，等待所有完成后返回最高分结果及对比报告。"""
        results = await self.execute_parallel(task_type, params, ai_list)

        # 构建对比报告
        report_lines = []
        best = {"ai": "", "result": None, "score": 0, "time": 0}
        for r in results:
            tag = ""
            if r["score"] > best["score"]:
                best = r
            report_lines.append(f"  {r['ai']}: {r['score']}分 ({r['time']}s)")

        # 给最高分加标记
        report = "对比结果:\n" + "\n".join(report_lines)
        print(f"🏆 最佳: {best['ai']} ({best['score']}分)")
        print(report)

        best["compare_report"] = report
        best["all_results"] = results
        return best

    # ── 结果合并 ─────────────────────────────────────────

    def merge_contact_results(self, results_list: list[dict]) -> dict:
        """合并多个 AI 的联系方式结果，去重并标注来源。"""
        seen_emails: dict[str, str] = {}
        seen_phones: dict[str, str] = {}
        seen_websites: dict[str, str] = {}
        raw_parts = []

        for entry in results_list:
            ai = entry.get("ai", "unknown")
            result = entry.get("result")
            if result is None:
                continue

            for email in result.get("emails", []):
                e = email.strip().lower()
                if e not in seen_emails:
                    seen_emails[e] = ai

            for phone in result.get("phones", []):
                p = phone.strip()
                if p not in seen_phones:
                    seen_phones[p] = ai

            for url in result.get("websites", []):
                u = url.strip().rstrip("/")
                if u not in seen_websites:
                    seen_websites[u] = ai

            raw_parts.append(f"=== {ai} ===\n{result.get('raw', '')}")

        return {
            "emails": [{"value": k, "source": v} for k, v in seen_emails.items()],
            "phones": [{"value": k, "source": v} for k, v in seen_phones.items()],
            "websites": [{"value": k, "source": v} for k, v in seen_websites.items()],
            "raw": "\n\n".join(raw_parts),
            "source_count": len(results_list),
        }

    # ── 内部 ─────────────────────────────────────────────

    async def _run_task(self, runner, task_type: str, params: dict):
        """根据 task_type 调用 runner 的对应方法。"""
        if task_type == "search_contacts":
            return await runner.search_contacts(
                params.get("company_name", ""),
                params.get("country", ""),
            )
        elif task_type == "search_slaughterhouses":
            return await runner.search_slaughterhouses(
                params.get("country", ""),
                params.get("region", ""),
            )
        elif task_type == "search_freight":
            return await runner.search_freight_forwarders(
                params.get("country", ""),
                params.get("cargo_type", "牛副产品"),
            )
        elif task_type == "generate_email":
            return await runner.generate_email(
                params.get("company_name", ""),
                params.get("language", "english"),
                params.get("product", "bovine gallstones"),
            )
        else:
            raise ValueError(f"未知任务类型: {task_type}")
