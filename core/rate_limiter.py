# 请求频率限制模块

import asyncio
import logging
import random
import time

logger = logging.getLogger(__name__)

# 各AI平台的速率限制配置
DEFAULT_LIMITS = {
    "chatgpt": {"per_hour": 50, "min_interval": 8},
    "claude": {"per_hour": 40, "min_interval": 10},
    "deepseek": {"per_hour": 60, "min_interval": 5},
    "gemini": {"per_hour": 40, "min_interval": 8},
}


class RateLimiter:
    """控制各 AI 平台的请求频率，防止触发限流。"""

    def __init__(self, limits: dict | None = None):
        self.limits = limits or dict(DEFAULT_LIMITS)
        self.request_history: dict[str, list[float]] = {}
        self.last_request: dict[str, float] = {}

    # ── 等待 & 检查 ──────────────────────────────────────

    async def wait_if_needed(self, ai_name: str):
        """如果距上次请求间隔不足，则 sleep 等待，并加入随机延迟。"""
        cfg = self.limits.get(ai_name)
        if cfg is None:
            return

        min_interval = cfg["min_interval"]
        last = self.last_request.get(ai_name, 0)
        elapsed = time.time() - last
        wait = 0.0

        if elapsed < min_interval:
            wait = min_interval - elapsed

        # 随机延迟 1-3 秒
        jitter = random.uniform(1, 3)
        wait += jitter

        if wait > jitter:
            # 有真实等待（不只是 jitter）才提示
            print(f"⏳ 等待 {wait:.1f} 秒后请求 {ai_name}...")
        logger.debug("%s: 等待 %.1f 秒 (间隔 %.1f + 随机 %.1f)", ai_name, wait, wait - jitter, jitter)

        await asyncio.sleep(wait)

    def can_request(self, ai_name: str) -> bool:
        """检查该 AI 最近 1 小时的请求次数是否未超限。"""
        cfg = self.limits.get(ai_name)
        if cfg is None:
            return True

        self._cleanup_history(ai_name)
        history = self.request_history.get(ai_name, [])
        return len(history) < cfg["per_hour"]

    def record_request(self, ai_name: str):
        """记录一次请求。"""
        now = time.time()
        self.request_history.setdefault(ai_name, []).append(now)
        self.last_request[ai_name] = now
        logger.debug("%s: 已记录请求 (本小时第 %d 次)", ai_name, len(self.request_history[ai_name]))

    # ── 查询 ─────────────────────────────────────────────

    def get_available_ai(self, preferred_order: list[str]) -> str | None:
        """按优先顺序返回第一个未达到限制的 AI。"""
        for ai_name in preferred_order:
            if self.can_request(ai_name):
                return ai_name
        return None

    def get_status(self) -> dict:
        """返回各 AI 的用量状态。"""
        status = {}
        for ai_name, cfg in self.limits.items():
            self._cleanup_history(ai_name)
            used = len(self.request_history.get(ai_name, []))
            status[ai_name] = {
                "used": used,
                "limit": cfg["per_hour"],
                "available": used < cfg["per_hour"],
            }
        return status

    def get_wait_time(self, ai_name: str) -> float:
        """返回该 AI 还需等待多少秒才能发起下一次请求。"""
        cfg = self.limits.get(ai_name)
        if cfg is None:
            return 0.0

        # 最小间隔等待
        last = self.last_request.get(ai_name, 0)
        elapsed = time.time() - last
        interval_wait = max(0.0, cfg["min_interval"] - elapsed)

        # 如果已达每小时上限，计算最早过期的请求还要多久
        self._cleanup_history(ai_name)
        history = self.request_history.get(ai_name, [])
        if len(history) >= cfg["per_hour"] and history:
            oldest = history[0]
            quota_wait = oldest + 3600 - time.time()
            return max(interval_wait, quota_wait)

        return interval_wait

    # ── 内部 ─────────────────────────────────────────────

    def _cleanup_history(self, ai_name: str):
        """清理超过 1 小时的请求记录。"""
        cutoff = time.time() - 3600
        history = self.request_history.get(ai_name)
        if history:
            self.request_history[ai_name] = [t for t in history if t > cutoff]
