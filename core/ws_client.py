# WebSocket客户端模块

import asyncio
import json
import logging
import time

import websockets

logger = logging.getLogger(__name__)


class WSClient:
    """与 Telegram-bot 后端通过 WebSocket 双向通信。"""

    def __init__(self, server_url: str):
        self.server_url = server_url
        self.websocket = None
        self.connected = False
        self.callbacks: dict = {}

    # ── 连接管理 ──────────────────────────────────────────

    async def connect(self) -> bool:
        """连接 WebSocket 服务器并发送注册消息。"""
        try:
            self.websocket = await websockets.connect(self.server_url)
            await self.websocket.send(json.dumps({
                "type": "register",
                "client": "browser-ai",
                "status": "online",
            }))
            self.connected = True
            print(f"✅ 已连接服务器: {self.server_url}")
            logger.info("已连接 WebSocket 服务器: %s", self.server_url)
            return True
        except Exception as e:
            self.connected = False
            print(f"❌ 连接服务器失败: {e}")
            logger.error("WebSocket 连接失败: %s", e)
            return False

    async def disconnect(self):
        """关闭连接。"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        self.connected = False
        logger.info("WebSocket 连接已关闭")

    # ── 发送消息 ──────────────────────────────────────────

    async def send(self, message_type: str, data: dict):
        """发送通用消息。"""
        if not self.connected or not self.websocket:
            logger.warning("未连接，无法发送消息 (type=%s)", message_type)
            return
        message = {
            "type": message_type,
            "data": data,
            "timestamp": time.time(),
        }
        await self.websocket.send(json.dumps(message, ensure_ascii=False))
        logger.debug("已发送: %s", message_type)

    async def send_task_result(
        self,
        task_id: str,
        result,
        score: int,
        ai_used: str,
        attempt_summary: str,
    ):
        """发送任务完成结果。"""
        await self.send("task_result", {
            "task_id": task_id,
            "result": result,
            "score": score,
            "ai_used": ai_used,
            "attempt_summary": attempt_summary,
            "status": "completed",
        })

    async def send_need_review(
        self,
        task_id: str,
        task_type: str,
        result,
        score: int,
        issues: list,
        attempt_summary: str,
    ):
        """发送人工审核请求。"""
        await self.send("need_review", {
            "task_id": task_id,
            "task_type": task_type,
            "result": result,
            "score": score,
            "issues": issues,
            "attempt_summary": attempt_summary,
        })

    async def send_auto_approved(self, task_id: str, result, score: int):
        """发送自动通过通知。"""
        await self.send("auto_approved", {
            "task_id": task_id,
            "result": result,
            "score": score,
        })

    async def send_status(self, status_data: dict):
        """发送状态更新（当前任务、AI在线状态等）。"""
        await self.send("status_update", status_data)

    # ── 回调注册 & 监听 ──────────────────────────────────

    def on(self, message_type: str, callback):
        """注册消息处理回调。"""
        self.callbacks[message_type] = callback

    async def listen(self):
        """持续监听服务器消息，按 type 分派到回调。"""
        try:
            async for raw in self.websocket:
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("收到非JSON消息: %s", raw[:200])
                    continue

                msg_type = message.get("type", "")
                logger.debug("收到消息: %s", msg_type)

                # 心跳回复
                if msg_type == "ping":
                    await self.websocket.send(json.dumps({
                        "type": "pong",
                        "timestamp": time.time(),
                    }))
                    continue

                # 分派到注册的回调
                callback = self.callbacks.get(msg_type)
                if callback:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(message)
                        else:
                            callback(message)
                    except Exception as e:
                        logger.error("处理消息 %s 时出错: %s", msg_type, e)
                else:
                    logger.debug("未注册的消息类型: %s", msg_type)

        except websockets.ConnectionClosed:
            logger.warning("WebSocket 连接已断开")
            self.connected = False
        except Exception as e:
            logger.error("监听异常: %s", e)
            self.connected = False

    # ── 主循环 ────────────────────────────────────────────

    async def run(self):
        """主循环：自动重连，断开后每5秒重试。"""
        while True:
            if not self.connected:
                await self.connect()
            if self.connected:
                await self.listen()
            # 断线后等待再重连
            await asyncio.sleep(5)
