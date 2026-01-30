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

# 对抗验证配置（默认值，可被DebateOrchestrator覆盖）
DEBATE_CONFIG = {
    "enabled": True,
    "min_value_threshold": 500,
    "confidence_threshold": 80,
}


class DecisionEngine:
    """根据质量评分决定自动通过、重试（换AI）或人工审核。"""

    def __init__(self, quality_checker: QualityChecker):
        self.quality_checker = quality_checker
        self.auto_approve_score = AUTO_APPROVE_SCORE
        self.min_pass_score = MIN_PASS_SCORE
        self.max_retry_rounds = MAX_RETRY_ROUNDS
        self.ai_retry_order = list(AI_RETRY_ORDER)
        self.task_history: dict[str, dict] = {}
        self.debate_orchestrator = None  # 由外部设置
        self.debate_config = dict(DEBATE_CONFIG)

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

    # ── 对抗验证集成 ────────────────────────────────────────

    def set_debate_orchestrator(self, orchestrator):
        """设置对抗验证编排器。"""
        self.debate_orchestrator = orchestrator
        logger.info("对抗验证编排器已设置")

    def update_debate_config(self, **kwargs):
        """更新对抗验证配置。"""
        self.debate_config.update(kwargs)
        if self.debate_orchestrator:
            self.debate_orchestrator.update_config(**kwargs)
        logger.info("对抗验证配置已更新: %s", kwargs)

    async def evaluate_with_debate(
        self,
        task_id: str,
        task_type: str,
        result,
        current_ai: str,
        use_debate: bool = True,
        cargo_value: float = 0,
    ) -> dict:
        """
        带对抗验证的评估。

        Args:
            task_id: 任务ID
            task_type: 任务类型
            result: 任务结果
            current_ai: 当前使用的AI
            use_debate: 是否使用对抗验证
            cargo_value: 货值（用于判断是否启用对抗验证）

        Returns:
            评估结果，包含对抗验证结果（如启用）
        """
        # 1. 先做基础质量检查
        basic_report = self.quality_checker.check(task_type, result)
        basic_score = basic_report["score"]

        self._record_attempt(task_id, current_ai, basic_score, result)

        # 2. 判断是否需要对抗验证
        should_debate = (
            use_debate
            and self.debate_config.get("enabled", True)
            and self.debate_orchestrator is not None
            and self._should_run_debate(task_type, cargo_value)
        )

        if should_debate:
            logger.info("任务 %s 启用对抗验证", task_id)

            try:
                # 准备对抗验证参数
                debate_params = self._prepare_debate_params(task_type, result)

                # 运行对抗验证
                debate_result = await self.debate_orchestrator.run_debate(
                    task_type, debate_params,
                )

                # 合并分数
                debate_confidence = debate_result.get("overall_confidence", 50)
                final_score = self._combine_scores(basic_score, debate_confidence)

                # 决定下一步行动
                action = self._decide_action_with_debate(
                    task_id, final_score, debate_result,
                )

                return {
                    "action": action,
                    "score": final_score,
                    "basic_score": basic_score,
                    "debate_confidence": debate_confidence,
                    "basic_report": basic_report,
                    "debate_result": debate_result,
                    "retry_round": self.get_retry_round(task_id),
                    "issues": basic_report.get("issues", []),
                    "next_ai": self._get_next_ai(task_id, current_ai) if action == "retry" else None,
                    "debate_summary": debate_result.get("summary", ""),
                    "needs_human_review": debate_result.get("needs_human_review", False),
                }

            except Exception as e:
                logger.error("对抗验证失败: %s，回退到基础评估", e)
                # 对抗验证失败时回退到基础评估

        # 3. 不启用对抗验证时，使用原有逻辑
        action = self._decide_action(task_id, basic_score)

        decision = {
            "action": action,
            "score": basic_score,
            "basic_score": basic_score,
            "debate_confidence": None,
            "basic_report": basic_report,
            "debate_result": None,
            "retry_round": self.get_retry_round(task_id),
            "issues": basic_report.get("issues", []),
            "next_ai": None,
        }

        if action == "retry":
            decision["next_ai"] = self._get_next_ai(task_id, current_ai)
            if decision["next_ai"] is None:
                decision["action"] = "need_review"

        logger.info(
            "任务 %s: %s 得分 %d → %s (第%d轮, 无对抗验证)",
            task_id, current_ai, basic_score, decision["action"], decision["retry_round"],
        )

        return decision

    def _should_run_debate(self, task_type: str, cargo_value: float) -> bool:
        """判断是否应该运行对抗验证。"""
        # 检查任务类型
        debate_task_types = [
            "contact_discovery",
            "search_contacts",
            "personnel_search",
            "contact",
            "personnel",
        ]
        if task_type not in debate_task_types:
            return False

        # 检查货值阈值
        min_value = self.debate_config.get("min_value_threshold", 500)
        if cargo_value > 0 and cargo_value < min_value:
            return False

        return True

    def _prepare_debate_params(self, task_type: str, result) -> dict:
        """准备对抗验证参数。"""
        if task_type in ("contact_discovery", "search_contacts", "contact"):
            # 联系方式任务
            if isinstance(result, dict):
                return {
                    "company_name": result.get("company_name", ""),
                    "country": result.get("country", ""),
                    "existing_result": result,
                }
            return {"existing_result": result}

        elif task_type in ("personnel_search", "personnel"):
            # 人员搜索任务
            if isinstance(result, dict):
                return {"personnel_info": result}
            return {"personnel_info": {"data": result}}

        return {"result": result}

    def _combine_scores(self, basic_score: int, debate_confidence: int) -> int:
        """
        合并基础评分和对抗验证置信度。

        权重：基础评分40%，对抗验证60%
        """
        combined = int(basic_score * 0.4 + debate_confidence * 0.6)
        return max(0, min(100, combined))

    def _decide_action_with_debate(
        self,
        task_id: str,
        final_score: int,
        debate_result: dict,
    ) -> str:
        """根据对抗验证结果决定动作。"""
        needs_review = debate_result.get("needs_human_review", False)
        risk_level = debate_result.get("risk_level", "medium")
        confidence_threshold = self.debate_config.get("confidence_threshold", 80)

        # 高风险或需要人工复核
        if needs_review or risk_level == "high":
            return "need_review"

        # 分数高且低风险
        if final_score >= self.auto_approve_score and risk_level == "low":
            return "auto_approve"

        # 分数达到最低通过线
        if final_score >= self.min_pass_score:
            # 如果置信度低于阈值，仍需人工复核
            debate_confidence = debate_result.get("overall_confidence", 0)
            if debate_confidence < confidence_threshold:
                return "need_review"
            return "auto_approve"

        # 分数不够，检查是否还能重试
        if self.get_retry_round(task_id) >= self.max_retry_rounds:
            return "need_review"

        return "retry"
