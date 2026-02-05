# DeepSeek控制模块

import asyncio
import logging

from core.chatgpt_controller import extract_emails, extract_phones, extract_urls

logger = logging.getLogger(__name__)


# ── DeepSeek 页面控制器 ──────────────────────────────────

class DeepSeekController:
    """通过 Playwright page 操控 DeepSeek 网页界面。"""

    def __init__(self, page):
        self.page = page

    async def send_message(self, text: str) -> str:
        """在输入框输入文本并发送，等待回复后返回内容。"""
        input_box = self.page.locator("textarea").first
        await input_box.click()
        await input_box.fill("")
        await input_box.fill(text)

        # 优先点击发送按钮，回退为回车
        send_btn = self.page.locator('div[class*="send"]', has_text="").first
        try:
            if await send_btn.is_visible():
                await send_btn.click()
            else:
                await self.page.keyboard.press("Enter")
        except Exception:
            await self.page.keyboard.press("Enter")

        logger.info("消息已发送 (%d 字符)", len(text))
        return await self.wait_response()

    async def wait_response(self, timeout: int = 120) -> str:
        """等待 DeepSeek 回复完成（停止按钮消失或内容稳定）。"""
        await asyncio.sleep(2)

        stop_btn = self.page.locator('div[class*="stop"]').first
        elapsed = 0
        interval = 2
        stable_count = 0
        last_text = ""

        while elapsed < timeout:
            # 检查停止按钮
            try:
                stop_visible = await stop_btn.is_visible()
            except Exception:
                stop_visible = False

            if not stop_visible:
                break

            # 内容稳定检测（连续3次相同）
            current_text = await self.get_last_response()
            if current_text and current_text == last_text:
                stable_count += 1
                if stable_count >= 3:
                    break
            else:
                stable_count = 0
            last_text = current_text

            await asyncio.sleep(interval)
            elapsed += interval

        if elapsed >= timeout:
            logger.warning("等待回复超时 (%ds)", timeout)

        await asyncio.sleep(1)
        return await self.get_last_response()

    async def get_last_response(self) -> str:
        """获取页面上最后一条助手消息的文本。"""
        # DeepSeek 的 markdown 渲染容器
        messages = self.page.locator('div.markdown')
        count = await messages.count()

        if count == 0:
            messages = self.page.locator('div[class*="message"] div[class*="assistant"]')
            count = await messages.count()

        if count == 0:
            return ""

        last = messages.nth(count - 1)
        return (await last.inner_text()).strip()

    async def new_chat(self):
        """点击新建对话按钮，等待页面就绪。"""
        new_chat_btn = self.page.locator('div[class*="new"]', has_text="新对话").first
        try:
            await new_chat_btn.click()
        except Exception:
            await self.page.goto("https://chat.deepseek.com/")
        await self.page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(1)
        logger.info("已新建对话")


# ── 业务任务运行器 ────────────────────────────────────────

class DeepSeekTaskRunner:
    """基于 DeepSeekController 封装业务查询任务（侧重中文搜索能力）。"""

    def __init__(self, controller: DeepSeekController):
        self.controller = controller

    async def search_contacts(self, company_name: str, country: str) -> dict:
        """查找指定公司的联系方式（利用 DeepSeek 中文搜索优势）。"""
        prompt = (
            f"请详细查找{country}的{company_name}的联系方式。\n"
            f"需要包括：\n"
            f"- 公司官方邮箱或业务联系邮箱\n"
            f"- 电话号码（含国际区号）\n"
            f"- 官方网站地址\n"
            f"- 如有中国办事处或代理商信息也请一并列出"
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
            f"请查找{location}的主要牛屠宰场和肉类加工厂，要求：\n"
            f"1. 列出企业名称（中英文）\n"
            f"2. 联系邮箱和电话\n"
            f"3. 官网地址\n"
            f"4. 如有出口资质或认证信息请标注\n"
            f"请尽量提供完整准确的信息列表。"
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
            f"请查找{country}专门从事{cargo_type}国际运输的货代公司，要求：\n"
            f"1. 具备冷链运输或特殊生物制品运输能力\n"
            f"2. 列出公司名称、联系邮箱、电话、官网\n"
            f"3. 如有中国分公司或合作代理也请列出\n"
            f"请至少提供5家相关企业信息。"
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
            f"请用{language}撰写一封专业的B2B采购询价邮件给{company_name}，"
            f"我方希望长期稳定采购{product}。\n"
            f"邮件须包含：\n"
            f"1. 公司简介与采购背景\n"
            f"2. 具体采购意向与预估数量\n"
            f"3. 产品质量规格要求\n"
            f"4. 价格、付款方式及交货条件询问\n"
            f"5. 需替换的信息用 [YOUR NAME] 等占位符标注\n"
            f"语气专业诚恳，篇幅适中。"
        )
        return await self.controller.send_message(prompt)

    async def optimize_content(self, content: str, issue: str) -> str:
        """根据指出的问题优化内容。"""
        prompt = (
            f"请优化以下内容，保持专业性和准确性。\n"
            f"存在的问题：{issue}\n"
            f"要求：直接输出优化后的完整内容，不需要额外解释。\n\n"
            f"原始内容：\n{content}"
        )
        return await self.controller.send_message(prompt)
