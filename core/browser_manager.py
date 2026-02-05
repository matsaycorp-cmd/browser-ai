# 浏览器管理模块

import asyncio
import logging

from playwright.async_api import async_playwright

from config.settings import AI_URLS, PROXY_CONFIG

logger = logging.getLogger(__name__)

# 各AI平台的登录状态检测选择器
LOGIN_SELECTORS = {
    "chatgpt": "#prompt-textarea",
    "claude": '[contenteditable="true"]',
    "gemini": "textarea",
}


class BrowserManager:
    """管理 Playwright 浏览器实例及各AI平台的页面会话。"""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.playwright = None
        self.browser = None  # persistent context (BrowserContext)
        self.sessions: dict = {}

    async def start(self, headless: bool = False):
        """启动 Playwright 并用持久化上下文打开 Chromium。"""
        self.playwright = await async_playwright().start()

        # 构建启动参数
        launch_options = {
            "user_data_dir": self.data_dir,
            "headless": headless,
            "viewport": {"width": 1280, "height": 800},
            "args": ["--disable-blink-features=AutomationControlled"],
        }

        # 添加代理配置（如果启用）
        if PROXY_CONFIG.get("enabled"):
            proxy_server = PROXY_CONFIG.get("server")
            if proxy_server:
                launch_options["proxy"] = {"server": proxy_server}
                logger.info("已配置代理: %s", proxy_server)

        self.browser = await self.playwright.chromium.launch_persistent_context(
            **launch_options
        )
        logger.info("浏览器已启动 (headless=%s)", headless)

    async def open_session(self, ai_name: str) -> dict:
        """为指定AI平台新建页面并导航，返回 {page, logged_in}。"""
        url = AI_URLS.get(ai_name)
        if url is None:
            raise ValueError(f"未知的AI平台: {ai_name}")

        page = await self.browser.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        logger.info("已打开 %s (%s)", ai_name, url)

        logged_in = await self.check_login(ai_name, page)
        self.sessions[ai_name] = {"page": page, "logged_in": logged_in}
        return self.sessions[ai_name]

    async def check_login(self, ai_name: str, page=None) -> bool:
        """检查指定AI平台的登录状态（5秒超时）。"""
        if page is None:
            session = self.sessions.get(ai_name)
            if session is None:
                return False
            page = session["page"]

        selector = LOGIN_SELECTORS.get(ai_name)
        if selector is None:
            logger.warning("无 %s 的登录检测选择器", ai_name)
            return False

        try:
            await page.wait_for_selector(selector, timeout=5000)
            return True
        except Exception:
            return False

    async def wait_for_login(self, ai_name: str, timeout: int = 180) -> bool:
        """等待用户在浏览器中手动登录，每2秒检查一次。"""
        print(f"请在浏览器中登录 {ai_name}...")
        elapsed = 0
        while elapsed < timeout:
            if await self.check_login(ai_name):
                session = self.sessions.get(ai_name)
                if session:
                    session["logged_in"] = True
                logger.info("%s 登录成功", ai_name)
                return True
            await asyncio.sleep(2)
            elapsed += 2
        logger.warning("%s 登录超时 (%ds)", ai_name, timeout)
        return False

    async def close(self):
        """关闭浏览器和 Playwright。"""
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
        logger.info("浏览器已关闭")
