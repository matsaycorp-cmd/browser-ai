# Gemini (Google AI) 控制模块

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


# ── Gemini 页面控制器 ────────────────────────────────────

class GeminiController:
    """通过 Playwright page 操控 Google Gemini 网页界面。"""

    def __init__(self, page):
        self.page = page
        self.base_url = "https://gemini.google.com/app"

    async def send_message(self, text: str) -> str:
        """在输入框输入文本并发送，等待回复后返回内容。"""
        # Gemini 输入框选择器
        input_selectors = [
            'rich-textarea',
            'textarea[aria-label*="prompt"]',
            'textarea[placeholder*="Enter"]',
            'div[contenteditable="true"]',
            'textarea',
        ]

        input_box = None
        for selector in input_selectors:
            try:
                elem = self.page.locator(selector).first
                if await elem.is_visible():
                    input_box = elem
                    break
            except Exception:
                continue

        if input_box is None:
            logger.error("找不到 Gemini 输入框")
            raise RuntimeError("找不到 Gemini 输入框")

        # 清空并输入
        await input_box.click()
        await asyncio.sleep(0.3)

        # 尝试多种方式清空
        try:
            await input_box.fill("")
        except Exception:
            await self.page.keyboard.press("Control+a")
            await self.page.keyboard.press("Delete")

        # 输入文本
        await input_box.fill(text)
        await asyncio.sleep(0.5)

        # 发送按钮选择器
        send_selectors = [
            'button[aria-label*="Send"]',
            'button[aria-label*="submit"]',
            'button[data-test-id="send-button"]',
            'button.send-button',
            'mat-icon[data-mat-icon-name="send"]',
        ]

        sent = False
        for selector in send_selectors:
            try:
                btn = self.page.locator(selector).first
                if await btn.is_visible():
                    await btn.click()
                    sent = True
                    break
            except Exception:
                continue

        # 如果找不到发送按钮，尝试回车发送
        if not sent:
            await self.page.keyboard.press("Enter")

        logger.info("消息已发送 (%d 字符)", len(text))
        return await self.wait_response()

    async def wait_response(self, timeout: int = 120) -> str:
        """等待 Gemini 回复完成（响应稳定或加载指示器消失）。"""
        await asyncio.sleep(3)

        # 加载指示器选择器
        loading_selectors = [
            '.loading-indicator',
            '.response-loading',
            '[class*="loading"]',
            '[class*="spinner"]',
            '.thinking-indicator',
        ]

        elapsed = 0
        interval = 2
        stable_count = 0
        last_text = ""

        while elapsed < timeout:
            # 检查加载指示器
            is_loading = False
            for selector in loading_selectors:
                try:
                    indicator = self.page.locator(selector).first
                    if await indicator.is_visible():
                        is_loading = True
                        break
                except Exception:
                    continue

            # 内容稳定检测（连续3次相同且有内容）
            current_text = await self.get_last_response()
            if current_text:
                if current_text == last_text and not is_loading:
                    stable_count += 1
                    if stable_count >= 3:
                        break
                else:
                    stable_count = 0
            last_text = current_text

            # 如果没有加载指示器且有内容，可能已完成
            if not is_loading and current_text and len(current_text) > 50:
                stable_count += 1
                if stable_count >= 2:
                    break

            await asyncio.sleep(interval)
            elapsed += interval

        if elapsed >= timeout:
            logger.warning("等待回复超时 (%ds)", timeout)

        await asyncio.sleep(1)
        return await self.get_last_response()

    async def get_last_response(self) -> str:
        """获取页面上最后一条模型回复的文本。"""
        # Gemini 响应选择器
        response_selectors = [
            '.response-content',
            '.model-response-text',
            '[class*="response-container"] .markdown',
            '[class*="model-response"]',
            'message-content[class*="model"]',
            '.message-content',
        ]

        for selector in response_selectors:
            try:
                messages = self.page.locator(selector)
                count = await messages.count()
                if count > 0:
                    last = messages.nth(count - 1)
                    text = await last.inner_text()
                    if text.strip():
                        return self._clean_response(text.strip())
            except Exception:
                continue

        # 备选方案：查找所有可能的响应区域
        try:
            all_text = await self.page.locator('main').inner_text()
            # 尝试提取最后一段有意义的文本
            paragraphs = [p.strip() for p in all_text.split('\n\n') if len(p.strip()) > 20]
            if paragraphs:
                return self._clean_response(paragraphs[-1])
        except Exception:
            pass

        return ""

    def _clean_response(self, text: str) -> str:
        """清理响应文本，移除多余的UI元素文本。"""
        # 移除常见的UI文本
        ui_patterns = [
            r'^Copy$',
            r'^Share$',
            r'^Edit$',
            r'^Report$',
            r'^\d+ characters$',
        ]

        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            is_ui = False
            for pattern in ui_patterns:
                if re.match(pattern, line.strip(), re.IGNORECASE):
                    is_ui = True
                    break
            if not is_ui:
                cleaned_lines.append(line)

        return '\n'.join(cleaned_lines).strip()

    async def new_chat(self) -> bool:
        """开始新对话。"""
        # 新对话按钮选择器
        new_chat_selectors = [
            'a[href*="/app"]',
            'button[aria-label*="New chat"]',
            'button[aria-label*="new conversation"]',
            '[class*="new-chat"]',
        ]

        for selector in new_chat_selectors:
            try:
                btn = self.page.locator(selector).first
                if await btn.is_visible():
                    await btn.click()
                    await self.page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(1)
                    logger.info("已新建对话")
                    return True
            except Exception:
                continue

        # 如果找不到按钮，直接导航
        try:
            await self.page.goto(self.base_url)
            await self.page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(1)
            logger.info("已新建对话（通过导航）")
            return True
        except Exception as e:
            logger.error("新建对话失败: %s", e)
            return False

    async def check_login(self) -> bool:
        """检查是否已登录 Google 账号。"""
        try:
            # 检查是否有输入框（登录后才有）
            input_selectors = [
                'rich-textarea',
                'textarea[aria-label*="prompt"]',
                'div[contenteditable="true"]',
            ]

            for selector in input_selectors:
                try:
                    elem = self.page.locator(selector).first
                    if await elem.is_visible():
                        return True
                except Exception:
                    continue

            # 检查是否有登录按钮（未登录）
            login_indicators = [
                'a[href*="accounts.google.com"]',
                'button:has-text("Sign in")',
                '[class*="sign-in"]',
            ]

            for selector in login_indicators:
                try:
                    elem = self.page.locator(selector).first
                    if await elem.is_visible():
                        return False
                except Exception:
                    continue

            return False
        except Exception:
            return False

    async def check_usage_limit(self) -> dict:
        """检查是否有使用限制提示。"""
        limit_indicators = [
            'Usage limit',
            'rate limit',
            'too many requests',
            'try again later',
            'quota exceeded',
        ]

        try:
            page_text = await self.page.locator('body').inner_text()
            page_text_lower = page_text.lower()

            for indicator in limit_indicators:
                if indicator.lower() in page_text_lower:
                    return {
                        "limited": True,
                        "message": f"检测到使用限制: {indicator}",
                    }

            return {"limited": False, "message": None}
        except Exception:
            return {"limited": False, "message": None}


# ── 业务任务运行器 ────────────────────────────────────────

class GeminiTaskRunner:
    """基于 GeminiController 封装业务查询任务。

    Gemini 特点：
    - 擅长最新信息搜索（与 Google 搜索整合）
    - 支持多模态（图片分析）
    - 多语言能力强
    """

    def __init__(self, controller: GeminiController):
        self.controller = controller

    async def search_contacts(self, company_name: str, country: str) -> dict:
        """查找公司联系方式（利用 Gemini 的 Google 搜索能力）。"""
        prompt = f"""Please search for contact information of {company_name} in {country}.

I need:
1. Official company email addresses (especially export/sales/business development)
2. Phone numbers with international dialing code
3. Official website URL
4. Social media links (LinkedIn, etc.)
5. If available, names of key contacts (export manager, sales director)

Please provide verified, accurate information. Format your response clearly with sections for each type of contact info."""

        raw = await self.controller.send_message(prompt)
        return {
            "emails": extract_emails(raw),
            "phones": extract_phones(raw),
            "websites": extract_urls(raw),
            "raw": raw,
        }

    async def search_slaughterhouses(self, country: str, region: str = None) -> dict:
        """搜索屠宰场信息。"""
        location = f"{region}, {country}" if region else country
        prompt = f"""Search for beef slaughterhouses and meat processing plants in {location}.

I need:
1. Company names (local language and English if available)
2. Contact information (email, phone, website)
3. Export certifications (SIF, HALAL, EU approved, etc.)
4. Products they process (beef, by-products, etc.)
5. Company size/capacity if available

Focus on companies that:
- Have export licenses
- Process cattle/beef products
- May have bovine by-products available

List at least 5-10 companies if possible."""

        raw = await self.controller.send_message(prompt)
        return {
            "emails": extract_emails(raw),
            "phones": extract_phones(raw),
            "websites": extract_urls(raw),
            "raw": raw,
        }

    async def search_freight_forwarders(self, origin: str, destination: str = "China") -> dict:
        """搜索冷链物流商。"""
        prompt = f"""Search for freight forwarders specializing in cold chain logistics from {origin} to {destination}.

Requirements:
1. Experience with animal products/meat transport
2. Cold chain/refrigerated container capability
3. Experience with biological products if possible

For each company, provide:
- Company name
- Contact email and phone
- Website
- Services offered
- Coverage areas

List at least 5 companies with their contact details."""

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
        language: str = "english",
        product: str = "bovine gallstones",
    ) -> str:
        """生成 B2B 采购询价邮件。"""
        prompt = f"""Write a professional B2B procurement inquiry email to {company_name} in {language}.

Our company wants to establish a long-term partnership to purchase {product}.

The email should include:
1. Brief company introduction (we are a Chinese import company)
2. Specific purchase intention and estimated quantity
3. Product quality specifications inquiry
4. Questions about pricing, payment terms, and delivery conditions
5. Use placeholders like [YOUR NAME], [YOUR COMPANY], [YOUR EMAIL] for personalization

Tone: Professional, sincere, business-appropriate
Length: Medium (not too long, not too short)

Please write the complete email."""

        return await self.controller.send_message(prompt)

    async def analyze_registry_source(self, url: str, context: str) -> dict:
        """分析数据源可靠性。"""
        prompt = f"""Please analyze this data source for reliability:

URL: {url}
Context: {context}

Please evaluate:
1. Is this an official government/authority source?
2. Is the data likely to be accurate and up-to-date?
3. What is the credibility score (0-100)?
4. Are there any red flags or concerns?
5. What alternative sources might have similar data?

Return your analysis in a structured format."""

        raw = await self.controller.send_message(prompt)
        return {
            "url": url,
            "analysis": raw,
            "urls_found": extract_urls(raw),
        }

    async def verify_company_info(self, company_info: dict) -> dict:
        """验证公司信息的真实性。"""
        prompt = f"""Please verify the following company information:

Company Name: {company_info.get('name', 'N/A')}
Country: {company_info.get('country', 'N/A')}
Website: {company_info.get('website', 'N/A')}
Industry: {company_info.get('industry', 'meat processing')}

Please check:
1. Does this company actually exist?
2. Is the website legitimate?
3. Is the company registered/licensed?
4. Are there any news or reviews about them?
5. Any red flags or concerns?

Provide a confidence score (0-100) and detailed findings."""

        raw = await self.controller.send_message(prompt)
        return {
            "company_info": company_info,
            "verification_result": raw,
            "urls_found": extract_urls(raw),
        }

    async def translate_content(
        self,
        content: str,
        source_lang: str,
        target_lang: str,
    ) -> str:
        """翻译内容（利用 Gemini 的多语言能力）。"""
        prompt = f"""Translate the following text from {source_lang} to {target_lang}.

Maintain:
- Professional tone
- Business terminology
- Original formatting where possible

Text to translate:
{content}

Provide only the translation, no explanations."""

        return await self.controller.send_message(prompt)

    async def optimize_content(self, content: str, issue: str) -> str:
        """根据问题优化内容。"""
        prompt = f"""Please optimize the following content.

Issue to address: {issue}

Requirements:
- Maintain professional tone
- Improve accuracy
- Keep the same format
- Output only the optimized content

Original content:
{content}"""

        return await self.controller.send_message(prompt)
