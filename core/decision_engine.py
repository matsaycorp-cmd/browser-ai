# 决策引擎模块

import logging
import time

from config.settings import (
    AI_RETRY_ORDER,
    AUTO_APPROVE_SCORE,
    MAX_RETRY_ROUNDS,
    MIN_PASS_SCORE,
)
from core.quality_checker import QualityChecker

logger = logging.getLogger(__name__)


class DecisionEngine:
    """根据质量评分决定自动通过、重试（换AI）或人工审核。"""

    def __init__(self, quality_checker: QualityChecker):
        self.quality_checker = quality_checker
        self.auto_approve_score = AUTO_APPROVE_SCORE
        self.min_pass_score = MIN_PASS_SCORE
        self.max_retry_rounds = MAX_RETRY_ROUNDS
        self.ai_retry_order = list(AI_RETRY_ORDER)
        self.task_history: dict[str, dict] = {}

    def reload_config(
        self,
        auto_approve_score: int | None = None,
        min_pass_score: int | None = None,
        max_retry_rounds: int | None = None,
        ai_retry_order: list | None = None,
    ):
        """从 ConfigManager 重新加载配置。"""
        if auto_approve_score is not None:
            self.auto_approve_score = auto_approve_score
        if min_pass_score is not None:
            self.min_pass_score = min_pass_score
        if max_retry_rounds is not None:
            self.max_retry_rounds = max_retry_rounds
        if ai_retry_order is not None:
            self.ai_retry_order = list(ai_retry_order)
        logger.info(
            "决策引擎配置已更新: auto=%d, min=%d, max_retry=%d",
            self.auto_approve_score, self.min_pass_score, self.max_retry_rounds,
        )

    # ── 主入口 ────────────────────────────────────────────

    def evaluate(self, task_id: str, task_type: str, result, current_ai: str) -> dict:
        """评估结果质量并返回下一步决策。"""
        report = self.quality_checker.check(task_type, result)
        score = report["score"]

        self._record_attempt(task_id, current_ai, score, result)
        action = self._decide_action(task_id, score)

        decision = {
            "action": action,
            "score": score,
            "next_ai": None,
            "retry_round": self.get_retry_round(task_id),
            "issues": report.get("issues", []),
            "report": report,
        }

        if action == "retry":
            decision["next_ai"] = self._get_next_ai(task_id, current_ai)
            # 没有可用的下一个 AI 时转为人工审核
            if decision["next_ai"] is None:
                decision["action"] = "need_review"

        logger.info(
            "任务 %s: %s 得分 %d → %s (第%d轮)",
            task_id, current_ai, score, decision["action"], decision["retry_round"],
        )
        return decision

    # ── 内部决策 ──────────────────────────────────────────

    def _decide_action(self, task_id: str, score: int) -> str:
        """根据分数和重试轮数决定动作。"""
        if score >= self.auto_approve_score:
            return "auto_approve"
        if score >= self.min_pass_score:
            return "auto_approve"
        if self.get_retry_round(task_id) >= self.max_retry_rounds:
            return "need_review"
        return "retry"

    def _get_next_ai(self, task_id: str, current_ai: str) -> str | None:
        """按 AI_RETRY_ORDER 返回下一个尚未使用的 AI。"""
        history = self.task_history.get(task_id)
        used = set()
        if history:
            used = {a["ai"] for a in history["attempts"]}

        for ai in self.ai_retry_order:
            if ai not in used:
                return ai

        # 所有 AI 都用过，返回 None
        return None

    # ── 历史记录 ──────────────────────────────────────────

    def _record_attempt(self, task_id: str, ai_name: str, score: int, result):
        """记录一次尝试到 task_history。"""
        if task_id not in self.task_history:
            self.task_history[task_id] = {
                "attempts": [],
                "best_score": 0,
                "best_result": None,
            }

        entry = self.task_history[task_id]
        entry["attempts"].append({
            "ai": ai_name,
            "score": score,
            "timestamp": time.time(),
        })

        if score > entry["best_score"]:
            entry["best_score"] = score
            entry["best_result"] = result

    def get_retry_round(self, task_id: str) -> int:
        """返回该任务已经尝试了几轮。"""
        history = self.task_history.get(task_id)
        if history is None:
            return 0
        return len(history["attempts"])

    def get_best_result(self, task_id: str):
        """返回历史中得分最高的结果。"""
        history = self.task_history.get(task_id)
        if history is None:
            return None
        return history["best_result"]

    def get_attempt_summary(self, task_id: str) -> str:
        """生成尝试摘要，如 'ChatGPT(45分)→Claude(62分)→DeepSeek(58分)'。"""
        history = self.task_history.get(task_id)
        if not history or not history["attempts"]:
            return "无尝试记录"

        parts = []
        for attempt in history["attempts"]:
            name = attempt["ai"].capitalize()
            if attempt["ai"] == "chatgpt":
                name = "ChatGPT"
            elif attempt["ai"] == "deepseek":
                name = "DeepSeek"
            parts.append(f"{name}({attempt['score']}分)")

        return "→".join(parts)

    def reset_task(self, task_id: str):
        """清除某任务的全部历史记录。"""
        if task_id in self.task_history:
            del self.task_history[task_id]
            logger.info("已重置任务 %s 的历史记录", task_id)
