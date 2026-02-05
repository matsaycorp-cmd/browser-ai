"""
Telegram Bot 通知处理模块

将此代码添加到 telegram-bot/server.py 中。
"""

# ============================================================
# 添加到 server.py 的顶部 imports 区域
# ============================================================

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ============================================================
# 添加到 BrowserAIServer 类中
# ============================================================

class NotificationHandler:
    """处理来自 browser-ai 的 Telegram 通知。"""

    def __init__(self, application):
        """
        初始化通知处理器。

        Args:
            application: telegram.ext.Application 实例
        """
        self.application = application
        self.admin_chat_ids = []  # 从 config 加载

    def set_admin_ids(self, admin_ids: list):
        """设置管理员聊天ID列表。"""
        self.admin_chat_ids = admin_ids

    async def handle_notification(self, data: dict):
        """
        处理通知消息。

        Args:
            data: 通知数据，包含 notification_type 和具体内容
        """
        notification_type = data.get("notification_type")
        message = data.get("message", "")

        if not message:
            return

        # 构建内联键盘（如果有）
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

        # 发送消息给所有管理员
        for chat_id in self.admin_chat_ids:
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                )
            except Exception as e:
                print(f"发送通知失败 (chat_id={chat_id}): {e}")


# ============================================================
# 在 handle_websocket 方法中添加处理逻辑
# ============================================================

# 在 handle_websocket 的消息类型判断中添加：
"""
elif msg_type == "telegram_notification":
    # 处理 Telegram 通知
    await self.notification_handler.handle_notification(data)
"""


# ============================================================
# 添加回调查询处理器
# ============================================================

async def handle_registry_callback(update, context):
    """处理名录相关的回调按钮。"""
    query = update.callback_query
    await query.answer()

    callback_data = query.data

    if callback_data.startswith("registry_skip:"):
        registry_id = callback_data.split(":")[1]
        await query.edit_message_text(
            text=f"⏭️ 已跳过名录: {registry_id}\n\n原消息已处理。",
            parse_mode="HTML"
        )
        # TODO: 通知 browser-ai 跳过该名录

    elif callback_data.startswith("registry_retry:"):
        registry_id = callback_data.split(":")[1]
        await query.edit_message_text(
            text=f"🔄 正在重试下载: {registry_id}...",
            parse_mode="HTML"
        )
        # TODO: 通知 browser-ai 重试下载


# ============================================================
# 完整的 server.py 示例
# ============================================================

COMPLETE_SERVER_EXAMPLE = '''
"""
Telegram Bot + WebSocket 服务器
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
        self.application.add_handler(
            CallbackQueryHandler(self.handle_callback, pattern="^registry_")
        )

    # ── Telegram 命令 ────────────────────────────────────

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令。"""
        await update.message.reply_text(
            "🤖 <b>Browser-AI 控制面板</b>\\n\\n"
            "/status - 查看状态\\n"
            "/search <公司> <国家> - 搜索联系方式\\n"
            "/slaughter <国家> - 搜索屠宰场\\n"
            "/registry <国家代码> <国家名> - 查询官方名录",
            parse_mode="HTML",
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /status 命令。"""
        if self.clients:
            status = "🟢 Browser-AI 已连接"
        else:
            status = "🔴 Browser-AI 未连接"
        await update.message.reply_text(status)

    async def cmd_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /search 命令。"""
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("用法: /search <公司> <国家>")
            return

        company = args[0]
        country = " ".join(args[1:])
        task_id = f"search_{int(datetime.now().timestamp())}"

        await self._send_to_browser_ai("new_task", {
            "task_id": task_id,
            "task_type": "search_contacts",
            "params": {"company_name": company, "country": country},
        })
        await update.message.reply_text(f"✅ 已发送: {task_id}")

    async def cmd_slaughter(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /slaughter 命令。"""
        args = context.args
        if not args:
            await update.message.reply_text("用法: /slaughter <国家> [地区]")
            return

        country = args[0]
        region = " ".join(args[1:]) if len(args) > 1 else ""
        task_id = f"slaughter_{int(datetime.now().timestamp())}"

        await self._send_to_browser_ai("new_task", {
            "task_id": task_id,
            "task_type": "search_slaughterhouses",
            "params": {"country": country, "region": region},
        })
        await update.message.reply_text(f"✅ 已发送: {task_id}")

    async def cmd_registry(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /registry 命令 - 官方名录查询。"""
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("用法: /registry <国家代码> <国家名>\\n例如: /registry AR 阿根廷")
            return

        country_code = args[0].upper()
        country_name = " ".join(args[1:])
        inquiry_id = f"registry_{int(datetime.now().timestamp())}"

        await self._send_to_browser_ai("registry_inquiry", {
            "inquiry_id": inquiry_id,
            "country_code": country_code,
            "country_name": country_name,
            "use_debate": True,
        })
        await update.message.reply_text(f"✅ 已发送名录查询: {inquiry_id}")

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

        elif callback_data.startswith("registry_retry:"):
            registry_id = callback_data.split(":")[1]
            await query.edit_message_text(
                text=f"🔄 正在重试: {registry_id}...",
                parse_mode="HTML"
            )

    # ── WebSocket 处理 ────────────────────────────────────

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
                    logger.info(f"收到消息: {msg_type}")

                    if msg_type == "register":
                        await self._send_config(websocket)

                    elif msg_type == "request_config":
                        await self._send_config(websocket)

                    elif msg_type == "telegram_notification":
                        await self._handle_telegram_notification(data.get("data", {}))

                    elif msg_type == "task_result":
                        await self._handle_task_result(data.get("data", {}))

                    elif msg_type == "need_review":
                        await self._handle_need_review(data.get("data", {}))

                except json.JSONDecodeError:
                    logger.warning(f"无效JSON: {message[:100]}")

        except websockets.ConnectionClosed:
            logger.info(f"客户端断开: {client_id}")
        finally:
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

    async def _send_to_browser_ai(self, msg_type: str, data: dict):
        """发送消息到 Browser-AI。"""
        if not self.clients:
            logger.warning("没有连接的客户端")
            return

        message = json.dumps({
            "type": msg_type,
            "data": data,
        })

        for websocket in self.clients.values():
            try:
                await websocket.send(message)
            except Exception as e:
                logger.error(f"发送失败: {e}")

    async def _handle_telegram_notification(self, data: dict):
        """处理 Telegram 通知。"""
        if not self.application:
            return

        message = data.get("message", "")
        if not message:
            return

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
            except Exception as e:
                logger.error(f"发送通知失败: {e}")

    async def _handle_task_result(self, data: dict):
        """处理任务结果。"""
        task_id = data.get("task_id", "")
        result = data.get("result", {})
        score = data.get("score", 0)

        if self.application:
            message = f"📋 <b>任务完成</b>: {task_id}\\n评分: {score}"
            for chat_id in TELEGRAM_ADMIN_IDS:
                try:
                    await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

    async def _handle_need_review(self, data: dict):
        """处理需要审核的任务。"""
        task_id = data.get("task_id", "")
        score = data.get("score", 0)
        issues = data.get("issues", [])

        if self.application:
            issues_text = "\\n".join(f"  • {i}" for i in issues[:5])
            message = f"⚠️ <b>需要审核</b>: {task_id}\\n评分: {score}\\n问题:\\n{issues_text}"
            for chat_id in TELEGRAM_ADMIN_IDS:
                try:
                    await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="HTML",
                    )
                except Exception:
                    pass


async def main():
    server = BrowserAIServer()
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
'''

print("此文件包含 Telegram 通知处理代码。")
print("请将相关代码添加到 telegram-bot/server.py 中。")
print()
print("或者直接使用 COMPLETE_SERVER_EXAMPLE 替换整个 server.py")
