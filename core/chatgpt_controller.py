# ChatGPT控制模块

import asyncio
import logging
import re

logger = logging.getLogger(__name__)


# ── 辅助函数 ──────────────────────────────────────────────

def extract_emails(text: str) -> list[str]:
    """从文本中提取邮箱地址。"""
    return re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)


def extract_phones(text: str) -> list[str]:
    """从文本中提取电话号码。"""
    return re.findall(r"\+?[\d\s\-().]{7,20}\d", text)


def extract_urls(text: str) -> list[str]:
    """从文本中提取网址。"""
    return re.findall(r"https?://[^\s<>\"')\]]+", text)


# ── ChatGPT 页面控制器 ───────────────────────────────────

class ChatGPTController:
    """通过 Playwright page 操控 ChatGPT 网页界面。"""

    def __init__(self, page):
        self.page = page

    async def send_message(self, text: str) -> str:
        """在输入框输入文本并发送，等待回复后返回内容。"""
        input_box = self.page.locator("#prompt-textarea")
        await input_box.click()
        await input_box.fill("")
        await input_box.fill(text)

        send_btn = self.page.locator('[data-testid="send-button"]')
        await send_btn.click()
        logger.info("消息已发送 (%d 字符)", len(text))

        return await self.wait_response()

    async def wait_response(self, timeout: int = 120) -> str:
        """等待 ChatGPT 回复完成（停止按钮消失），返回最新回复。"""
        # 先等回复开始生成
        await asyncio.sleep(2)

        stop_btn = self.page.locator('[data-testid="stop-button"]')
        elapsed = 0
        interval = 1

        while elapsed < timeout:
            try:
                visible = await stop_btn.is_visible()
                if not visible:
                    break
            except Exception:
                break
            await asyncio.sleep(interval)
            elapsed += interval

        if elapsed >= timeout:
            logger.warning("等待回复超时 (%ds)", timeout)

        # 回复结束后稍等渲染
        await asyncio.sleep(1)
        return await self.get_last_response()

    async def get_last_response(self) -> str:
        """获取页面上最后一条 assistant 消息的文本。"""
        messages = self.page.locator('[data-message-author-role="assistant"]')
        count = await messages.count()
        if count == 0:
            return ""
        last = messages.nth(count - 1)
        return (await last.inner_text()).strip()

    async def new_chat(self):
        """点击新建对话按钮，等待页面就绪。"""
        # ChatGPT 侧栏顶部的新对话按钮
        new_chat_btn = self.page.locator('a[href="/"]').first
        await new_chat_btn.click()
        await self.page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(1)
        logger.info("已新建对话")


# ── 业务任务运行器 ────────────────────────────────────────

class ChatGPTTaskRunner:
    """基于 ChatGPTController 封装具体的业务查询任务。"""

    def __init__(self, controller: ChatGPTController):
        self.controller = controller

    async def search_contacts(self, company_name: str, country: str) -> dict:
        """查找指定公司的联系方式。"""
        prompt = (
            f"请帮我查找{country}的{company_name}的联系方式，"
            f"包括邮箱、电话、官网"
        )
        raw = await self.controller.send_message(prompt)
        return {
            "emails": extract_emails(raw),
            "phones": extract_phones(raw),
            "websites": extract_urls(raw),
            "raw": raw,
        }

    async def search_slaughterhouses(self, country: str, region: str = "") -> dict:
        """查找屠宰场/肉类加工厂名单及联系方式。"""
        location = f"{country} {region}".strip()
        prompt = (
            f"请帮我查找{location}的主要牛屠宰场/肉类加工厂名单和联系方式"
        )
        raw = await self.controller.send_message(prompt)
        return {
            "emails": extract_emails(raw),
            "phones": extract_phones(raw),
            "websites": extract_urls(raw),
            "raw": raw,
        }

    async def search_freight_forwarders(
        self, country: str, cargo_type: str = "牛副产品"
    ) -> dict:
        """查找国际货代公司联系方式。"""
        prompt = (
            f"请帮我查找{country}专门做{cargo_type}国际运输的货代公司联系方式"
        )
        raw = await self.controller.send_message(prompt)
        return {
            "emails": extract_emails(raw),
            "phones": extract_phones(raw),
            "websites": extract_urls(raw),
            "raw": raw,
        }

    async def generate_email(
        self,
        company_name: str,
        language: str,
        product: str = "bovine gallstones",
    ) -> str:
        """生成 B2B 采购询价邮件。"""
        prompt = (
            f"请用{language}写一封专业的B2B采购询价邮件给{company_name}，"
            f"我们希望采购{product}，"
            f"请包含自我介绍、采购意向、规格要求、价格询问和联系方式占位符"
        )
        return await self.controller.send_message(prompt)

    async def optimize_content(self, content: str, issue: str) -> str:
        """根据指出的问题优化内容。"""
        prompt = f"请优化以下内容，问题是{issue}：\n{content}"
        return await self.controller.send_message(prompt)
