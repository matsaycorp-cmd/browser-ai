"""
Telegram Bot + WebSocket 服务器

将此文件复制到 telegram-bot/server.py
"""

import asyncio
import json
import logging
from datetime import datetime

import websockets
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import TELEGRAM_ADMIN_IDS, TELEGRAM_BOT_TOKEN, WS_HOST, WS_PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


class BrowserAIServer:
    """Browser-AI WebSocket 服务器 + Telegram Bot。"""

    def __init__(self):
        self.clients = {}
        self.pending_tasks = {}
        self.application = None

    async def start(self):
        """启动服务器。"""
        print("=" * 50)
        print("  Telegram Bot + WebSocket 服务器")
        print("=" * 50)

        # 启动 WebSocket 服务器
        ws_server = await websockets.serve(
            self.handle_websocket,
            WS_HOST,
            WS_PORT,
        )
        print(f"✅ WebSocket 服务器: ws://{WS_HOST}:{WS_PORT}")

        # 启动 Telegram Bot
        if TELEGRAM_BOT_TOKEN:
            self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
            self._register_handlers()
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            print("✅ Telegram Bot 已启动")
        else:
            print("⚠️  未配置 Telegram，仅运行 WebSocket")

        print("=" * 50)
        print("等待 browser-ai 连接...")
        print("=" * 50)

        # 保持运行
        await asyncio.Future()

    def _register_handlers(self):
        """注册 Telegram 命令处理器。"""
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("status", self.cmd_status))
        self.application.add_handler(CommandHandler("search", self.cmd_search))
        self.application.add_handler(CommandHandler("slaughter", self.cmd_slaughter))
        self.application.add_handler(CommandHandler("registry", self.cmd_registry))
        # 回调按钮处理
        self.application.add_handler(
            CallbackQueryHandler(self.handle_callback, pattern="^registry_")
        )
        self.application.add_handler(
            CallbackQueryHandler(self.handle_callback, pattern="^approve_|^reject_")
        )

    # ══════════════════════════════════════════════════════════
    # Telegram 命令处理
    # ══════════════════════════════════════════════════════════

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令。"""
        await update.message.reply_text(
            "🤖 <b>Browser-AI 控制面板</b>\n\n"
            "/status - 查看状态\n"
            "/search <公司> <国家> - 搜索联系方式\n"
            "/slaughter <国家> - 搜索屠宰场\n"
            "/registry <国家代码> <国家名> - 查询官方名录",
            parse_mode="HTML",
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /status 命令。"""
        if self.clients:
            client_count = len(self.clients)
            status = f"🟢 Browser-AI 已连接 ({client_count} 个客户端)"
        else:
            status = "🔴 Browser-AI 未连接"

        pending_count = len(self.pending_tasks)
        if pending_count > 0:
            status += f"\n📋 待处理任务: {pending_count}"

        await update.message.reply_text(status)

    async def cmd_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /search 命令 - 搜索联系方式。"""
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("用法: /search <公司> <国家>")
            return

        company = args[0]
        country = " ".join(args[1:])
        task_id = f"search_{int(datetime.now().timestamp())}"

        success = await self._send_to_browser_ai("new_task", {
            "task_id": task_id,
            "task_type": "search_contacts",
            "params": {"company_name": company, "country": country},
        })

        if success:
            await update.message.reply_text(f"✅ 已发送: {task_id}")
            self.pending_tasks[task_id] = {
                "type": "search_contacts",
                "chat_id": update.effective_chat.id,
                "created_at": datetime.now().isoformat(),
            }
        else:
            await update.message.reply_text("❌ 发送失败，Browser-AI 未连接")

    async def cmd_slaughter(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /slaughter 命令 - 搜索屠宰场。"""
        args = context.args
        if not args:
            await update.message.reply_text("用法: /slaughter <国家> [地区]")
            return

        country = args[0]
        region = " ".join(args[1:]) if len(args) > 1 else ""
        task_id = f"slaughter_{int(datetime.now().timestamp())}"

        success = await self._send_to_browser_ai("new_task", {
            "task_id": task_id,
            "task_type": "search_slaughterhouses",
            "params": {"country": country, "region": region},
        })

        if success:
            await update.message.reply_text(f"✅ 已发送: {task_id}")
            self.pending_tasks[task_id] = {
                "type": "search_slaughterhouses",
                "chat_id": update.effective_chat.id,
                "created_at": datetime.now().isoformat(),
            }
        else:
            await update.message.reply_text("❌ 发送失败，Browser-AI 未连接")

    async def cmd_registry(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /registry 命令 - 官方名录查询。"""
        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "用法: /registry <国家代码> <国家名>\n"
                "例如: /registry AR 阿根廷"
            )
            return

        country_code = args[0].upper()
        country_name = " ".join(args[1:])
        inquiry_id = f"registry_{int(datetime.now().timestamp())}"

        success = await self._send_to_browser_ai("registry_inquiry", {
            "inquiry_id": inquiry_id,
            "country_code": country_code,
            "country_name": country_name,
            "use_debate": True,
        })

        if success:
            await update.message.reply_text(f"✅ 已发送名录查询: {inquiry_id}")
            self.pending_tasks[inquiry_id] = {
                "type": "registry_inquiry",
                "chat_id": update.effective_chat.id,
                "country_code": country_code,
                "country_name": country_name,
                "created_at": datetime.now().isoformat(),
            }
        else:
            await update.message.reply_text("❌ 发送失败，Browser-AI 未连接")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理回调按钮。"""
        query = update.callback_query
        await query.answer()

        callback_data = query.data

        if callback_data.startswith("registry_skip:"):
            registry_id = callback_data.split(":")[1]
            await query.edit_message_text(
                text=f"⏭️ 已跳过名录: {registry_id}",
                parse_mode="HTML"
            )
            # 通知 browser-ai 跳过
            await self._send_to_browser_ai("registry_action", {
                "action": "skip",
                "registry_id": registry_id,
            })

        elif callback_data.startswith("registry_retry:"):
            registry_id = callback_data.split(":")[1]
            await query.edit_message_text(
                text=f"🔄 正在重试: {registry_id}...",
                parse_mode="HTML"
            )
            # 通知 browser-ai 重试
            await self._send_to_browser_ai("registry_action", {
                "action": "retry",
                "registry_id": registry_id,
            })

        elif callback_data.startswith("approve_"):
            task_id = callback_data.replace("approve_", "")
            await query.edit_message_text(
                text=f"✅ 已批准: {task_id}",
                parse_mode="HTML"
            )
            await self._send_to_browser_ai("review_result", {
                "task_id": task_id,
                "approved": True,
            })

        elif callback_data.startswith("reject_"):
            task_id = callback_data.replace("reject_", "")
            await query.edit_message_text(
                text=f"❌ 已拒绝: {task_id}",
                parse_mode="HTML"
            )
            await self._send_to_browser_ai("review_result", {
                "task_id": task_id,
                "approved": False,
                "reason": "手动拒绝",
            })

    # ══════════════════════════════════════════════════════════
    # WebSocket 处理
    # ══════════════════════════════════════════════════════════

    async def handle_websocket(self, websocket, path=None):
        """处理 WebSocket 连接。"""
        client_id = id(websocket)
        self.clients[client_id] = websocket
        logger.info(f"Browser-AI 客户端已连接: {client_id}")

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type", "")
                    msg_data = data.get("data", {})
                    logger.info(f"收到消息: {msg_type}")

                    if msg_type == "register":
                        await self._send_config(websocket)

                    elif msg_type == "request_config":
                        await self._send_config(websocket)

                    elif msg_type == "telegram_notification":
                        await self._handle_telegram_notification(msg_data)

                    elif msg_type == "task_result":
                        await self._handle_task_result(msg_data)

                    elif msg_type == "need_review":
                        await self._handle_need_review(msg_data)

                    elif msg_type == "auto_approved":
                        await self._handle_auto_approved(msg_data)

                    elif msg_type == "status_update":
                        await self._handle_status_update(msg_data)

                    elif msg_type == "registry_inquiry_complete":
                        await self._handle_registry_complete(msg_data)

                    elif msg_type == "registry_inquiry_error":
                        await self._handle_registry_error(msg_data)

                except json.JSONDecodeError:
                    logger.warning(f"无效JSON: {message[:100]}")

        except websockets.ConnectionClosed:
            logger.info(f"客户端断开: {client_id}")
        finally:
            if client_id in self.clients:
                del self.clients[client_id]

    async def _send_config(self, websocket):
        """发送配置到客户端。"""
        config = {
            "type": "config_update",
            "data": {
                "execution_mode": "single",
                "max_parallel": 2,
                "auto_approve_score": 85,
                "min_pass_score": 70,
            },
        }
        await websocket.send(json.dumps(config))

    async def _send_to_browser_ai(self, msg_type: str, data: dict) -> bool:
        """发送消息到 Browser-AI。"""
        if not self.clients:
            logger.warning("没有连接的客户端")
            return False

        message = json.dumps({
            "type": msg_type,
            "data": data,
        }, ensure_ascii=False)

        success = False
        for websocket in self.clients.values():
            try:
                await websocket.send(message)
                success = True
            except Exception as e:
                logger.error(f"发送失败: {e}")

        return success

    # ══════════════════════════════════════════════════════════
    # Telegram 通知处理
    # ══════════════════════════════════════════════════════════

    async def _handle_telegram_notification(self, data: dict):
        """处理 Telegram 通知。"""
        if not self.application:
            logger.warning("Telegram 未配置，跳过通知")
            return

        message = data.get("message", "")
        if not message:
            return

        notification_type = data.get("notification_type", "")
        logger.info(f"处理 Telegram 通知: {notification_type}")

        # 构建内联键盘
        reply_markup = None
        if "inline_keyboard" in data:
            keyboard = []
            for row in data["inline_keyboard"]:
                keyboard_row = []
                for btn in row:
                    if "url" in btn:
                        keyboard_row.append(
                            InlineKeyboardButton(btn["text"], url=btn["url"])
                        )
                    elif "callback_data" in btn:
                        keyboard_row.append(
                            InlineKeyboardButton(btn["text"], callback_data=btn["callback_data"])
                        )
                keyboard.append(keyboard_row)
            reply_markup = InlineKeyboardMarkup(keyboard)

        # 发送给所有管理员
        for chat_id in TELEGRAM_ADMIN_IDS:
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                )
                logger.info(f"通知已发送到 chat_id={chat_id}")
            except Exception as e:
                logger.error(f"发送通知失败 (chat_id={chat_id}): {e}")

    async def _handle_task_result(self, data: dict):
        """处理任务结果。"""
        task_id = data.get("task_id", "")
        result = data.get("result", {})
        score = data.get("score", 0)
        ai_used = data.get("ai_used", "")

        if not self.application:
            return

        # 格式化结果
        raw_text = result.get("raw", "")[:500] if isinstance(result, dict) else str(result)[:500]

        message = (
            f"📋 <b>任务完成</b>: {task_id}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"AI: {ai_used}\n"
            f"评分: {score}\n"
            f"\n📄 结果预览:\n<code>{raw_text}</code>"
        )

        for chat_id in TELEGRAM_ADMIN_IDS:
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"发送结果失败: {e}")

        # 清理待处理任务
        if task_id in self.pending_tasks:
            del self.pending_tasks[task_id]

    async def _handle_need_review(self, data: dict):
        """处理需要审核的任务。"""
        task_id = data.get("task_id", "")
        task_type = data.get("task_type", "")
        score = data.get("score", 0)
        issues = data.get("issues", [])
        result = data.get("result", {})

        if not self.application:
            return

        issues_text = "\n".join(f"  • {i}" for i in issues[:5]) if issues else "无"
        raw_preview = result.get("raw", "")[:300] if isinstance(result, dict) else ""

        message = (
            f"⚠️ <b>需要审核</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"任务: {task_id}\n"
            f"类型: {task_type}\n"
            f"评分: {score}\n"
            f"\n❗ 问题:\n{issues_text}"
        )

        if raw_preview:
            message += f"\n\n📄 预览:\n<code>{raw_preview}</code>"

        # 审核按钮
        keyboard = [
            [
                InlineKeyboardButton("✅ 批准", callback_data=f"approve_{task_id}"),
                InlineKeyboardButton("❌ 拒绝", callback_data=f"reject_{task_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        for chat_id in TELEGRAM_ADMIN_IDS:
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            except Exception as e:
                logger.error(f"发送审核请求失败: {e}")

    async def _handle_auto_approved(self, data: dict):
        """处理自动通过的任务。"""
        task_id = data.get("task_id", "")
        score = data.get("score", 0)

        if not self.application:
            return

        message = f"✅ <b>自动通过</b>: {task_id}\n评分: {score}"

        for chat_id in TELEGRAM_ADMIN_IDS:
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"发送自动通过通知失败: {e}")

        # 清理待处理任务
        if task_id in self.pending_tasks:
            del self.pending_tasks[task_id]

    async def _handle_status_update(self, data: dict):
        """处理状态更新。"""
        event = data.get("event", "")
        if event == "rate_limited":
            task_id = data.get("task_id", "")
            wait_seconds = data.get("wait_seconds", 0)
            logger.info(f"任务 {task_id} 因速率限制等待 {wait_seconds}s")

    async def _handle_registry_complete(self, data: dict):
        """处理名录查询完成。"""
        inquiry_id = data.get("inquiry_id", "")
        result = data.get("result", {})

        logger.info(f"名录查询完成: {inquiry_id}")

        # 清理待处理任务
        if inquiry_id in self.pending_tasks:
            del self.pending_tasks[inquiry_id]

    async def _handle_registry_error(self, data: dict):
        """处理名录查询错误。"""
        inquiry_id = data.get("inquiry_id", "")
        error = data.get("error", "")

        if not self.application:
            return

        message = f"❌ <b>名录查询失败</b>\n任务: {inquiry_id}\n错误: {error}"

        for chat_id in TELEGRAM_ADMIN_IDS:
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"发送错误通知失败: {e}")

        # 清理待处理任务
        if inquiry_id in self.pending_tasks:
            del self.pending_tasks[inquiry_id]


async def main():
    server = BrowserAIServer()
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
