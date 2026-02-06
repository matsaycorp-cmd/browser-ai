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
        # Browser AI 命令
        self.application.add_handler(CommandHandler("ai_browse", self.cmd_ai_browse))
        self.application.add_handler(CommandHandler("ai_search", self.cmd_ai_search))
        self.application.add_handler(CommandHandler("ai_download", self.cmd_ai_download))
        self.application.add_handler(CommandHandler("ai_ask", self.cmd_ai_ask))
        self.application.add_handler(CommandHandler("ai_parallel", self.cmd_ai_parallel_search))
        # 回调按钮处理
        self.application.add_handler(
            CallbackQueryHandler(self.handle_callback, pattern="^registry_")
        )
        self.application.add_handler(
            CallbackQueryHandler(self.handle_callback, pattern="^approve_|^reject_")
        )
        self.application.add_handler(
            CallbackQueryHandler(self.handle_callback, pattern="^browse_|^download_")
        )

    # ══════════════════════════════════════════════════════════
    # Telegram 命令处理
    # ══════════════════════════════════════════════════════════

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令。"""
        await update.message.reply_text(
            "🤖 <b>Browser-AI 控制面板</b>\n\n"
            "<b>📋 业务命令</b>\n"
            "/status - 查看状态\n"
            "/search <公司> <国家> - 搜索联系方式\n"
            "/slaughter <国家> - 搜索屠宰场\n"
            "/registry <国家代码> <国家名> - 查询官方名录\n\n"
            "<b>🌐 浏览器命令</b>\n"
            "/ai_browse <URL> - 访问网页并提取内容\n"
            "/ai_search <关键词> - AI搜索并总结\n"
            "/ai_download <URL> - 下载文件\n"
            "/ai_ask <问题> - 直接询问AI\n"
            "/ai_parallel <查询1>|<查询2>... - 并行搜索多个关键词",
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

    # ══════════════════════════════════════════════════════════
    # Browser AI 命令
    # ══════════════════════════════════════════════════════════

    async def cmd_ai_browse(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /ai_browse 命令 - 让 Browser AI 访问网页。"""
        args = context.args
        if not args:
            await update.message.reply_text(
                "用法: /ai_browse <URL> [选项]\n\n"
                "选项:\n"
                "  --screenshot  截取页面截图\n"
                "  --wait <选择器>  等待元素加载\n\n"
                "示例:\n"
                "/ai_browse https://example.com\n"
                "/ai_browse https://example.com --screenshot"
            )
            return

        url = args[0]
        take_screenshot = "--screenshot" in args
        wait_selector = None

        # 解析 --wait 参数
        if "--wait" in args:
            try:
                wait_idx = args.index("--wait")
                if wait_idx + 1 < len(args):
                    wait_selector = args[wait_idx + 1]
            except (ValueError, IndexError):
                pass

        task_id = f"browse_{int(datetime.now().timestamp())}"

        success = await self._send_to_browser_ai("browser_task", {
            "task_id": task_id,
            "task_type": "browse",
            "params": {
                "url": url,
                "extract_content": True,
                "take_screenshot": take_screenshot,
                "wait_selector": wait_selector,
            },
        })

        if success:
            await update.message.reply_text(
                f"🌐 <b>正在访问网页</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"URL: {url}\n"
                f"截图: {'是' if take_screenshot else '否'}\n"
                f"任务ID: <code>{task_id}</code>",
                parse_mode="HTML",
            )
            self.pending_tasks[task_id] = {
                "type": "browse",
                "chat_id": update.effective_chat.id,
                "url": url,
                "created_at": datetime.now().isoformat(),
            }
        else:
            await update.message.reply_text("❌ 发送失败，Browser-AI 未连接")

    async def cmd_ai_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /ai_search 命令 - 让 Browser AI 搜索内容。"""
        args = context.args
        if not args:
            await update.message.reply_text(
                "用法: /ai_search <关键词> [选项]\n\n"
                "选项:\n"
                "  --ai <名称>  使用指定AI总结 (chatgpt/claude/gemini)\n"
                "  --max <数量>  最大结果数 (默认10)\n\n"
                "示例:\n"
                "/ai_search 阿根廷屠宰场名录\n"
                "/ai_search 牛黄价格 --ai chatgpt"
            )
            return

        # 解析参数
        use_ai = None
        max_results = 10
        query_parts = []

        i = 0
        while i < len(args):
            if args[i] == "--ai" and i + 1 < len(args):
                use_ai = args[i + 1]
                i += 2
            elif args[i] == "--max" and i + 1 < len(args):
                try:
                    max_results = int(args[i + 1])
                except ValueError:
                    pass
                i += 2
            else:
                query_parts.append(args[i])
                i += 1

        query = " ".join(query_parts)
        if not query:
            await update.message.reply_text("请提供搜索关键词")
            return

        task_id = f"search_{int(datetime.now().timestamp())}"

        success = await self._send_to_browser_ai("browser_task", {
            "task_id": task_id,
            "task_type": "search",
            "params": {
                "query": query,
                "search_engine": "google",
                "max_results": max_results,
                "use_ai": use_ai,
            },
        })

        if success:
            ai_text = f"AI总结: {use_ai}" if use_ai else "无AI总结"
            await update.message.reply_text(
                f"🔍 <b>正在搜索</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"关键词: {query}\n"
                f"最大结果: {max_results}\n"
                f"{ai_text}\n"
                f"任务ID: <code>{task_id}</code>",
                parse_mode="HTML",
            )
            self.pending_tasks[task_id] = {
                "type": "search",
                "chat_id": update.effective_chat.id,
                "query": query,
                "created_at": datetime.now().isoformat(),
            }
        else:
            await update.message.reply_text("❌ 发送失败，Browser-AI 未连接")

    async def cmd_ai_download(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /ai_download 命令 - 让 Browser AI 下载文件。"""
        args = context.args
        if not args:
            await update.message.reply_text(
                "用法: /ai_download <URL> [选项]\n\n"
                "选项:\n"
                "  --browser  使用浏览器下载（需要登录的页面）\n"
                "  --name <文件名>  指定保存文件名\n\n"
                "示例:\n"
                "/ai_download https://example.com/file.pdf\n"
                "/ai_download https://example.com/data.xlsx --browser"
            )
            return

        url = args[0]
        use_browser = "--browser" in args
        filename = None

        # 解析 --name 参数
        if "--name" in args:
            try:
                name_idx = args.index("--name")
                if name_idx + 1 < len(args):
                    filename = args[name_idx + 1]
            except (ValueError, IndexError):
                pass

        task_id = f"download_{int(datetime.now().timestamp())}"

        success = await self._send_to_browser_ai("browser_task", {
            "task_id": task_id,
            "task_type": "download",
            "params": {
                "url": url,
                "save_dir": "./data/registry_downloads",
                "filename": filename,
                "use_browser": use_browser,
            },
        })

        if success:
            await update.message.reply_text(
                f"📥 <b>正在下载文件</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"URL: {url}\n"
                f"浏览器模式: {'是' if use_browser else '否'}\n"
                f"任务ID: <code>{task_id}</code>",
                parse_mode="HTML",
            )
            self.pending_tasks[task_id] = {
                "type": "download",
                "chat_id": update.effective_chat.id,
                "url": url,
                "created_at": datetime.now().isoformat(),
            }
        else:
            await update.message.reply_text("❌ 发送失败，Browser-AI 未连接")

    async def cmd_ai_ask(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /ai_ask 命令 - 直接向 AI 提问。"""
        args = context.args
        if not args:
            await update.message.reply_text(
                "用法: /ai_ask <问题> [选项]\n\n"
                "选项:\n"
                "  --ai <名称>  使用指定AI (chatgpt/claude/gemini)\n\n"
                "示例:\n"
                "/ai_ask 南美洲主要的牛肉出口国有哪些\n"
                "/ai_ask 牛黄的市场价格是多少 --ai claude"
            )
            return

        # 解析参数
        use_ai = "chatgpt"  # 默认使用 ChatGPT
        prompt_parts = []

        i = 0
        while i < len(args):
            if args[i] == "--ai" and i + 1 < len(args):
                use_ai = args[i + 1]
                i += 2
            else:
                prompt_parts.append(args[i])
                i += 1

        prompt = " ".join(prompt_parts)
        if not prompt:
            await update.message.reply_text("请提供问题内容")
            return

        task_id = f"ask_{int(datetime.now().timestamp())}"

        success = await self._send_to_browser_ai("browser_task", {
            "task_id": task_id,
            "task_type": "ai_query",
            "params": {
                "prompt": prompt,
                "use_ai": use_ai,
                "new_chat": True,
            },
        })

        if success:
            await update.message.reply_text(
                f"🤖 <b>正在询问 {use_ai.upper()}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"问题: {prompt[:100]}{'...' if len(prompt) > 100 else ''}\n"
                f"任务ID: <code>{task_id}</code>",
                parse_mode="HTML",
            )
            self.pending_tasks[task_id] = {
                "type": "ai_query",
                "chat_id": update.effective_chat.id,
                "prompt": prompt,
                "ai": use_ai,
                "created_at": datetime.now().isoformat(),
            }
        else:
            await update.message.reply_text("❌ 发送失败，Browser-AI 未连接")

    async def cmd_ai_parallel_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /ai_parallel 命令 - 并行搜索多个关键词。"""
        args = context.args
        if not args:
            await update.message.reply_text(
                "用法: /ai_parallel <查询1> | <查询2> | ... [选项]\n\n"
                "使用 | 分隔多个搜索关键词\n\n"
                "选项:\n"
                "  --max <数量>  最大并发数 (默认3)\n"
                "  --timeout <秒>  单个查询超时 (默认30)\n"
                "  --engine <引擎>  搜索引擎 (google/bing/duckduckgo)\n\n"
                "示例:\n"
                "/ai_parallel 阿根廷屠宰场 | 巴西屠宰场 | 乌拉圭屠宰场\n"
                "/ai_parallel 公司A联系方式 | 公司B联系方式 --max 5"
            )
            return

        # 解析参数
        full_text = " ".join(args)
        max_concurrent = 3
        timeout_per_query = 30
        engine = "google"

        # 提取选项
        if "--max" in full_text:
            try:
                parts = full_text.split("--max")
                full_text = parts[0]
                max_val = parts[1].strip().split()[0]
                max_concurrent = int(max_val)
            except (IndexError, ValueError):
                pass

        if "--timeout" in full_text:
            try:
                parts = full_text.split("--timeout")
                full_text = parts[0]
                timeout_val = parts[1].strip().split()[0]
                timeout_per_query = int(timeout_val)
            except (IndexError, ValueError):
                pass

        if "--engine" in full_text:
            try:
                parts = full_text.split("--engine")
                full_text = parts[0]
                engine = parts[1].strip().split()[0]
            except (IndexError, ValueError):
                pass

        # 解析查询列表 (使用 | 分隔)
        queries_raw = [q.strip() for q in full_text.split("|") if q.strip()]

        if not queries_raw:
            await update.message.reply_text("请提供至少一个搜索关键词")
            return

        # 构建查询列表
        queries = []
        for i, query in enumerate(queries_raw):
            queries.append({
                "id": f"q{i+1}",
                "query": query,
                "engine": engine,
            })

        task_id = f"parallel_{int(datetime.now().timestamp())}"

        success = await self._send_to_browser_ai("parallel_search", {
            "task_id": task_id,
            "queries": queries,
            "max_concurrent": max_concurrent,
            "timeout_per_query": timeout_per_query,
        })

        if success:
            queries_preview = "\n".join(f"  {i+1}. {q['query']}" for i, q in enumerate(queries[:5]))
            if len(queries) > 5:
                queries_preview += f"\n  ... 还有 {len(queries) - 5} 个"

            await update.message.reply_text(
                f"🔍 <b>并行搜索已启动</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"查询数: {len(queries)}\n"
                f"最大并发: {max_concurrent}\n"
                f"超时: {timeout_per_query}秒\n"
                f"搜索引擎: {engine}\n\n"
                f"📋 查询列表:\n{queries_preview}\n\n"
                f"任务ID: <code>{task_id}</code>",
                parse_mode="HTML",
            )
            self.pending_tasks[task_id] = {
                "type": "parallel_search",
                "chat_id": update.effective_chat.id,
                "queries": queries,
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

                    # Browser 任务结果
                    elif msg_type in ("browse_result", "search_result", "download_result", "ai_query_result"):
                        await self._handle_browser_task_result(msg_data)

                    elif msg_type == "browser_task_error":
                        await self._handle_browser_task_error(msg_data)

                    elif msg_type == "browser_task_progress":
                        await self._handle_browser_task_progress(msg_data)

                    # 并行搜索结果
                    elif msg_type == "parallel_search_progress":
                        await self._handle_parallel_search_progress(msg_data)

                    elif msg_type == "parallel_search_complete":
                        await self._handle_parallel_search_complete(msg_data)

                    elif msg_type == "parallel_search_error":
                        await self._handle_parallel_search_error(msg_data)

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

    # ══════════════════════════════════════════════════════════
    # Browser 任务结果处理
    # ══════════════════════════════════════════════════════════

    async def _handle_browser_task_result(self, data: dict):
        """处理 Browser 任务结果。"""
        task_id = data.get("task_id", "")
        task_type = data.get("task_type", "")
        status = data.get("status", "")

        if not self.application:
            return

        # 根据任务类型格式化结果
        if task_type == "browse":
            message = self._format_browse_result(data)
        elif task_type == "search":
            message = self._format_search_result(data)
        elif task_type == "download":
            message = self._format_download_result(data)
        elif task_type == "ai_query":
            message = self._format_ai_query_result(data)
        else:
            message = f"📋 任务完成: {task_id}\n状态: {status}"

        for chat_id in TELEGRAM_ADMIN_IDS:
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception as e:
                logger.error(f"发送Browser任务结果失败: {e}")

        # 清理待处理任务
        if task_id in self.pending_tasks:
            del self.pending_tasks[task_id]

    def _format_browse_result(self, data: dict) -> str:
        """格式化浏览结果。"""
        url = data.get("url", "")
        title = data.get("title", "无标题")
        content = data.get("content", "")[:500]
        status = data.get("status", "")

        if status == "success":
            message = (
                f"🌐 <b>网页访问完成</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"标题: {title}\n"
                f"URL: {url}\n"
            )
            if content:
                message += f"\n📄 内容预览:\n<code>{content}</code>"

            if data.get("screenshot_path"):
                message += f"\n\n📷 截图已保存"
        else:
            error = data.get("error", "未知错误")
            message = f"❌ <b>网页访问失败</b>\nURL: {url}\n错误: {error}"

        return message

    def _format_search_result(self, data: dict) -> str:
        """格式化搜索结果。"""
        query = data.get("query", "")
        results = data.get("results", [])
        ai_summary = data.get("ai_summary", "")
        status = data.get("status", "")

        if status == "success":
            message = (
                f"🔍 <b>搜索完成</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"关键词: {query}\n"
                f"结果数: {len(results)}\n"
            )

            # 显示前5个结果
            if results:
                message += "\n📋 搜索结果:\n"
                for i, r in enumerate(results[:5], 1):
                    title = r.get("title", "")[:50]
                    url = r.get("url", "")
                    message += f"{i}. <a href=\"{url}\">{title}</a>\n"

            if ai_summary:
                message += f"\n🤖 AI总结:\n{ai_summary[:300]}"
        else:
            error = data.get("error", "未知错误")
            message = f"❌ <b>搜索失败</b>\n关键词: {query}\n错误: {error}"

        return message

    def _format_download_result(self, data: dict) -> str:
        """格式化下载结果。"""
        url = data.get("url", "")
        file_path = data.get("file_path", "")
        file_size = data.get("file_size", 0)
        status = data.get("status", "")

        if status == "success":
            # 格式化文件大小
            if file_size > 1024 * 1024:
                size_str = f"{file_size / 1024 / 1024:.1f} MB"
            elif file_size > 1024:
                size_str = f"{file_size / 1024:.1f} KB"
            else:
                size_str = f"{file_size} B"

            message = (
                f"📥 <b>下载完成</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"文件: {file_path.split('/')[-1] if file_path else '未知'}\n"
                f"大小: {size_str}\n"
                f"保存路径: <code>{file_path}</code>"
            )
        else:
            error = data.get("error", "未知错误")
            message = f"❌ <b>下载失败</b>\nURL: {url}\n错误: {error}"

        return message

    def _format_ai_query_result(self, data: dict) -> str:
        """格式化 AI 查询结果。"""
        ai = data.get("ai", "")
        response = data.get("response", "")[:1000]
        status = data.get("status", "")

        if status == "success":
            message = (
                f"🤖 <b>{ai.upper()} 回复</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{response}"
            )
        else:
            error = data.get("error", "未知错误")
            message = f"❌ <b>AI查询失败</b>\nAI: {ai}\n错误: {error}"

        return message

    async def _handle_browser_task_error(self, data: dict):
        """处理 Browser 任务错误。"""
        task_id = data.get("task_id", "")
        error = data.get("error", "未知错误")
        task_type = data.get("task_type", "")

        if not self.application:
            return

        message = (
            f"❌ <b>Browser任务失败</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"任务: {task_id}\n"
            f"类型: {task_type}\n"
            f"错误: {error}"
        )

        for chat_id in TELEGRAM_ADMIN_IDS:
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"发送Browser任务错误失败: {e}")

        # 清理待处理任务
        if task_id in self.pending_tasks:
            del self.pending_tasks[task_id]

    async def _handle_browser_task_progress(self, data: dict):
        """处理 Browser 任务进度更新。"""
        task_id = data.get("task_id", "")
        progress = data.get("progress", 0)
        message_text = data.get("message", "")

        # 进度更新可以选择性发送或只记录日志
        logger.info(f"任务 {task_id} 进度: {progress}% - {message_text}")

    # ══════════════════════════════════════════════════════════
    # 并行搜索结果处理
    # ══════════════════════════════════════════════════════════

    async def _handle_parallel_search_progress(self, data: dict):
        """处理并行搜索进度更新。"""
        task_id = data.get("task_id", "")
        status = data.get("status", "")
        total = data.get("total", 0)
        completed = data.get("completed", 0)
        current_query = data.get("current_query", "")
        message_text = data.get("message", "")

        logger.info(f"并行搜索 {task_id}: {completed}/{total} - {message_text}")

        # 只在开始和每5个完成时发送通知，避免刷屏
        if status == "started" and self.application:
            for chat_id in TELEGRAM_ADMIN_IDS:
                try:
                    await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=f"🚀 <b>并行搜索开始</b>\n任务: {task_id}\n总数: {total}",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.error(f"发送进度通知失败: {e}")

    async def _handle_parallel_search_complete(self, data: dict):
        """处理并行搜索完成。"""
        task_id = data.get("task_id", "")
        total = data.get("total", 0)
        success_count = data.get("success_count", 0)
        error_count = data.get("error_count", 0)
        results = data.get("results", [])

        if not self.application:
            return

        # 构建结果消息
        message = (
            f"✅ <b>并行搜索完成</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"任务: {task_id}\n"
            f"总数: {total}\n"
            f"成功: {success_count} ✅\n"
            f"失败: {error_count} ❌\n"
        )

        # 显示前5个结果摘要
        if results:
            message += "\n📋 结果摘要:\n"
            for i, r in enumerate(results[:5], 1):
                query = r.get("query", "")[:30]
                status = "✅" if r.get("status") == "success" else "❌"
                message += f"{i}. {status} {query}\n"

            if len(results) > 5:
                message += f"... 还有 {len(results) - 5} 个结果\n"

        for chat_id in TELEGRAM_ADMIN_IDS:
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"发送并行搜索结果失败: {e}")

        # 清理待处理任务
        if task_id in self.pending_tasks:
            del self.pending_tasks[task_id]

    async def _handle_parallel_search_error(self, data: dict):
        """处理并行搜索错误。"""
        task_id = data.get("task_id", "")
        error = data.get("error", "未知错误")

        if not self.application:
            return

        message = (
            f"❌ <b>并行搜索失败</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"任务: {task_id}\n"
            f"错误: {error}"
        )

        for chat_id in TELEGRAM_ADMIN_IDS:
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"发送并行搜索错误失败: {e}")

        # 清理待处理任务
        if task_id in self.pending_tasks:
            del self.pending_tasks[task_id]


async def main():
    server = BrowserAIServer()
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
