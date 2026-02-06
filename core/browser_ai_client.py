"""
Browser AI WebSocket 客户端

用于从其他项目（如 slaughter-house-auto-search）触发 Browser AI 任务。
支持网页浏览、搜索、文件下载等功能。

使用示例：
    from browser_ai_client import BrowserAIClient

    async def main():
        client = BrowserAIClient("ws://localhost:8765")
        await client.connect()

        # 浏览网页
        result = await client.browse_url("https://example.com")

        # 搜索内容
        result = await client.search("屠宰场名录")

        # 下载文件
        result = await client.download_file("https://example.com/file.pdf", "./downloads/")

        await client.disconnect()
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional, Callable, Any
from urllib.parse import urlparse

import websockets

logger = logging.getLogger(__name__)


class BrowserAIClient:
    """Browser AI WebSocket 客户端。"""

    def __init__(
        self,
        server_url: str = "ws://localhost:8765",
        timeout: int = 300,
        download_dir: str = "./data/registry_downloads"
    ):
        """
        初始化客户端。

        Args:
            server_url: WebSocket 服务器地址
            timeout: 任务超时时间（秒）
            download_dir: 下载文件保存目录
        """
        self.server_url = server_url
        self.timeout = timeout
        self.download_dir = download_dir
        self.websocket = None
        self.connected = False
        self.pending_tasks = {}  # task_id -> asyncio.Future
        self.callbacks = {}
        self._listen_task = None

        # 确保下载目录存在
        os.makedirs(download_dir, exist_ok=True)

    async def connect(self) -> bool:
        """连接到 Browser AI 服务器。"""
        try:
            # 清除代理环境变量以避免本地连接被拦截
            parsed = urlparse(self.server_url)
            host = parsed.hostname or ""

            if host in ("localhost", "127.0.0.1", "::1"):
                import os as _os
                proxy_vars = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                              "ALL_PROXY", "all_proxy"]
                original_env = {}
                for var in proxy_vars:
                    if var in _os.environ:
                        original_env[var] = _os.environ.pop(var)

            self.websocket = await websockets.connect(self.server_url)

            # 注册客户端
            await self.websocket.send(json.dumps({
                "type": "register",
                "client": "browser-ai-client",
                "capabilities": ["browse", "search", "download"],
            }))

            self.connected = True
            logger.info(f"已连接到 Browser AI: {self.server_url}")

            # 启动消息监听
            self._listen_task = asyncio.create_task(self._listen())

            return True

        except Exception as e:
            logger.error(f"连接失败: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        """断开连接。"""
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        if self.websocket:
            await self.websocket.close()
            self.websocket = None

        self.connected = False
        logger.info("已断开连接")

    async def _listen(self):
        """监听服务器消息。"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type", "")

                    # 处理任务结果
                    if msg_type in ("task_result", "browse_result", "search_result", "download_result"):
                        task_id = data.get("data", {}).get("task_id")
                        if task_id and task_id in self.pending_tasks:
                            future = self.pending_tasks.pop(task_id)
                            if not future.done():
                                future.set_result(data.get("data", {}))

                    # 处理错误
                    elif msg_type == "task_error":
                        task_id = data.get("data", {}).get("task_id")
                        if task_id and task_id in self.pending_tasks:
                            future = self.pending_tasks.pop(task_id)
                            if not future.done():
                                future.set_exception(
                                    Exception(data.get("data", {}).get("error", "未知错误"))
                                )

                    # 处理进度更新
                    elif msg_type == "task_progress":
                        task_id = data.get("data", {}).get("task_id")
                        callback = self.callbacks.get(task_id)
                        if callback:
                            await callback(data.get("data", {}))

                except json.JSONDecodeError:
                    logger.warning(f"无效JSON: {message[:100]}")

        except websockets.ConnectionClosed:
            logger.warning("连接已断开")
            self.connected = False

    async def _send_task(
        self,
        task_type: str,
        params: dict,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """
        发送任务并等待结果。

        Args:
            task_type: 任务类型
            params: 任务参数
            progress_callback: 进度回调函数

        Returns:
            任务结果
        """
        if not self.connected or not self.websocket:
            raise ConnectionError("未连接到 Browser AI 服务器")

        task_id = f"{task_type}_{uuid.uuid4().hex[:8]}"

        # 创建结果 Future
        future = asyncio.get_event_loop().create_future()
        self.pending_tasks[task_id] = future

        if progress_callback:
            self.callbacks[task_id] = progress_callback

        # 发送任务
        message = {
            "type": "browser_task",
            "data": {
                "task_id": task_id,
                "task_type": task_type,
                "params": params,
            }
        }
        await self.websocket.send(json.dumps(message, ensure_ascii=False))
        logger.info(f"已发送任务: {task_id} ({task_type})")

        # 等待结果
        try:
            result = await asyncio.wait_for(future, timeout=self.timeout)
            return result
        except asyncio.TimeoutError:
            self.pending_tasks.pop(task_id, None)
            self.callbacks.pop(task_id, None)
            raise TimeoutError(f"任务超时: {task_id}")

    # ══════════════════════════════════════════════════════════
    # 公开 API
    # ══════════════════════════════════════════════════════════

    async def browse_url(
        self,
        url: str,
        extract_content: bool = True,
        take_screenshot: bool = False,
        wait_selector: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """
        使用 Browser AI 访问指定网页。

        Args:
            url: 要访问的 URL
            extract_content: 是否提取页面内容
            take_screenshot: 是否截图
            wait_selector: 等待的元素选择器
            progress_callback: 进度回调

        Returns:
            {
                "task_id": "任务ID",
                "url": "访问的URL",
                "title": "页面标题",
                "content": "页面内容（如果 extract_content=True）",
                "screenshot_path": "截图路径（如果 take_screenshot=True）",
                "status": "success/failed",
                "error": "错误信息（如果失败）"
            }
        """
        params = {
            "url": url,
            "extract_content": extract_content,
            "take_screenshot": take_screenshot,
            "wait_selector": wait_selector,
        }
        return await self._send_task("browse", params, progress_callback)

    async def search(
        self,
        query: str,
        search_engine: str = "google",
        max_results: int = 10,
        use_ai: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """
        使用 Browser AI 搜索指定内容。

        Args:
            query: 搜索关键词
            search_engine: 搜索引擎 (google/bing/duckduckgo)
            max_results: 最大结果数
            use_ai: 指定使用的 AI (chatgpt/claude/gemini)
            progress_callback: 进度回调

        Returns:
            {
                "task_id": "任务ID",
                "query": "搜索关键词",
                "results": [
                    {"title": "", "url": "", "snippet": ""},
                    ...
                ],
                "ai_summary": "AI 摘要（如果 use_ai 指定）",
                "status": "success/failed"
            }
        """
        params = {
            "query": query,
            "search_engine": search_engine,
            "max_results": max_results,
            "use_ai": use_ai,
        }
        return await self._send_task("search", params, progress_callback)

    async def download_file(
        self,
        url: str,
        save_dir: Optional[str] = None,
        filename: Optional[str] = None,
        use_browser: bool = False,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """
        使用 Browser AI 下载文件。

        当普通 HTTP 下载失败时，可以使用浏览器自动化下载。

        Args:
            url: 文件 URL
            save_dir: 保存目录（默认使用 self.download_dir）
            filename: 文件名（默认从 URL 提取）
            use_browser: 是否使用浏览器下载（用于需要登录或 JS 渲染的页面）
            progress_callback: 进度回调

        Returns:
            {
                "task_id": "任务ID",
                "url": "下载URL",
                "file_path": "保存路径",
                "file_size": 文件大小,
                "status": "success/failed",
                "error": "错误信息（如果失败）"
            }
        """
        params = {
            "url": url,
            "save_dir": save_dir or self.download_dir,
            "filename": filename,
            "use_browser": use_browser,
        }
        return await self._send_task("download", params, progress_callback)

    async def ai_query(
        self,
        prompt: str,
        use_ai: str = "chatgpt",
        new_chat: bool = True,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """
        直接向 AI 发送查询。

        Args:
            prompt: 提示词
            use_ai: 使用的 AI (chatgpt/claude/gemini)
            new_chat: 是否新建对话
            progress_callback: 进度回调

        Returns:
            {
                "task_id": "任务ID",
                "ai": "使用的AI",
                "response": "AI响应",
                "status": "success/failed"
            }
        """
        params = {
            "prompt": prompt,
            "use_ai": use_ai,
            "new_chat": new_chat,
        }
        return await self._send_task("ai_query", params, progress_callback)

    async def extract_table(
        self,
        url: str,
        table_selector: Optional[str] = None,
        output_format: str = "json",
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """
        从网页提取表格数据。

        Args:
            url: 网页 URL
            table_selector: 表格选择器（默认自动检测）
            output_format: 输出格式 (json/csv/excel)
            progress_callback: 进度回调

        Returns:
            {
                "task_id": "任务ID",
                "url": "网页URL",
                "tables": [{"headers": [...], "rows": [[...], ...]}, ...],
                "file_path": "保存的文件路径（如果 output_format 非 json）",
                "status": "success/failed"
            }
        """
        params = {
            "url": url,
            "table_selector": table_selector,
            "output_format": output_format,
        }
        return await self._send_task("extract_table", params, progress_callback)


# ══════════════════════════════════════════════════════════════
# 便捷函数
# ══════════════════════════════════════════════════════════════

_default_client: Optional[BrowserAIClient] = None


async def get_client(server_url: str = "ws://localhost:8765") -> BrowserAIClient:
    """获取或创建默认客户端。"""
    global _default_client
    if _default_client is None or not _default_client.connected:
        _default_client = BrowserAIClient(server_url)
        await _default_client.connect()
    return _default_client


async def browse(url: str, **kwargs) -> dict:
    """便捷函数：浏览网页。"""
    client = await get_client()
    return await client.browse_url(url, **kwargs)


async def search(query: str, **kwargs) -> dict:
    """便捷函数：搜索内容。"""
    client = await get_client()
    return await client.search(query, **kwargs)


async def download(url: str, **kwargs) -> dict:
    """便捷函数：下载文件。"""
    client = await get_client()
    return await client.download_file(url, **kwargs)


async def ask_ai(prompt: str, ai: str = "chatgpt", **kwargs) -> dict:
    """便捷函数：询问 AI。"""
    client = await get_client()
    return await client.ai_query(prompt, use_ai=ai, **kwargs)


# ══════════════════════════════════════════════════════════════
# 命令行接口
# ══════════════════════════════════════════════════════════════

async def cli_main():
    """命令行入口。"""
    import argparse

    parser = argparse.ArgumentParser(description="Browser AI 客户端")
    parser.add_argument("--server", default="ws://localhost:8765", help="服务器地址")

    subparsers = parser.add_subparsers(dest="command", help="命令")

    # browse 命令
    browse_parser = subparsers.add_parser("browse", help="浏览网页")
    browse_parser.add_argument("url", help="网页 URL")
    browse_parser.add_argument("--screenshot", action="store_true", help="截图")

    # search 命令
    search_parser = subparsers.add_parser("search", help="搜索内容")
    search_parser.add_argument("query", help="搜索关键词")
    search_parser.add_argument("--engine", default="google", help="搜索引擎")
    search_parser.add_argument("--ai", help="使用 AI 总结")

    # download 命令
    download_parser = subparsers.add_parser("download", help="下载文件")
    download_parser.add_argument("url", help="文件 URL")
    download_parser.add_argument("--dir", help="保存目录")
    download_parser.add_argument("--browser", action="store_true", help="使用浏览器下载")

    # ask 命令
    ask_parser = subparsers.add_parser("ask", help="询问 AI")
    ask_parser.add_argument("prompt", help="提示词")
    ask_parser.add_argument("--ai", default="chatgpt", help="使用的 AI")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    client = BrowserAIClient(args.server)
    if not await client.connect():
        print("连接失败")
        return

    try:
        if args.command == "browse":
            result = await client.browse_url(args.url, take_screenshot=args.screenshot)
        elif args.command == "search":
            result = await client.search(args.query, search_engine=args.engine, use_ai=args.ai)
        elif args.command == "download":
            result = await client.download_file(args.url, save_dir=args.dir, use_browser=args.browser)
        elif args.command == "ask":
            result = await client.ai_query(args.prompt, use_ai=args.ai)

        print(json.dumps(result, ensure_ascii=False, indent=2))

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(cli_main())
