# Claude控制模块

import asyncio
import json
import logging
import re

from core.chatgpt_controller import extract_emails, extract_phones, extract_urls

logger = logging.getLogger(__name__)


# ── Claude.ai 页面控制器 ─────────────────────────────────

class ClaudeController:
    """通过 Playwright page 操控 Claude.ai 网页界面。"""

    def __init__(self, page):
        self.page = page

    async def send_message(self, text: str) -> str:
        """在输入框输入文本并发送，等待回复后返回内容。"""
        input_box = self.page.locator('[contenteditable="true"]').first
        await input_box.click()

        # 全选并清空已有内容
        await self.page.keyboard.press("Control+A")
        await self.page.keyboard.press("Backspace")

        await input_box.fill(text)
        await self.page.keyboard.press("Enter")
        logger.info("消息已发送 (%d 字符)", len(text))

        return await self.wait_response()

    async def wait_response(self, timeout: int = 180) -> str:
        """等待 Claude 回复完成，通过停止按钮消失或内容稳定来判断。"""
        # 等待回复开始生成
        await asyncio.sleep(3)

        stop_btn = self.page.locator('button[aria-label="Stop Response"]')
        elapsed = 0
        interval = 2
        stable_count = 0
        last_text = ""

        while elapsed < timeout:
            # 检查停止按钮是否还在
            try:
                stop_visible = await stop_btn.is_visible()
            except Exception:
                stop_visible = False

            if not stop_visible:
                # 按钮已消失，回复完成
                break

            # 检查内容是否已稳定（连续3次相同）
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

        # 回复结束后稍等渲染
        await asyncio.sleep(1)
        return await self.get_last_response()

    async def get_last_response(self) -> str:
        """获取页面上最后一条助手消息的文本。"""
        # Claude.ai 的助手消息容器
        messages = self.page.locator('[data-is-streaming]')
        count = await messages.count()

        # 回退：尝试通用的消息容器选择器
        if count == 0:
            messages = self.page.locator(".font-claude-message")
            count = await messages.count()

        if count == 0:
            return ""

        last = messages.nth(count - 1)
        return (await last.inner_text()).strip()

    async def new_chat(self):
        """点击新建对话按钮，等待页面就绪。"""
        new_chat_btn = self.page.locator('a[href="/new"]').first
        try:
            await new_chat_btn.click()
        except Exception:
            # 备选：直接导航
            await self.page.goto("https://claude.ai/new")
        await self.page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(1)
        logger.info("已新建对话")


# ── 业务任务运行器 ────────────────────────────────────────

class ClaudeTaskRunner:
    """基于 ClaudeController 封装具体的业务查询任务。"""

    def __init__(self, controller: ClaudeController):
        self.controller = controller

    async def search_contacts(self, company_name: str, country: str) -> dict:
        """查找指定公司的联系方式（利用 Claude 的复杂指令理解能力）。"""
        prompt = (
            f"请帮我查找{country}的{company_name}的联系方式。\n"
            f"请分别列出以下信息：\n"
            f"1. 电子邮箱地址\n"
            f"2. 电话号码（含国际区号）\n"
            f"3. 官方网站URL\n"
            f"如果某项信息无法确认，请明确标注'未找到'。"
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
            f"请帮我查找{location}的主要牛屠宰场/肉类加工厂。\n"
            f"请以列表形式给出每家企业的：\n"
            f"1. 公司名称\n"
            f"2. 联系邮箱\n"
            f"3. 电话号码\n"
            f"4. 官网地址\n"
            f"请尽量提供真实可查证的信息。"
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
            f"请帮我查找{country}专门做{cargo_type}国际运输的货代公司。\n"
            f"要求：\n"
            f"1. 具备冷链/特殊货物运输资质\n"
            f"2. 提供公司名称、联系邮箱、电话、官网\n"
            f"请列出至少5家公司。"
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
            f"我们希望长期采购{product}。\n"
            f"邮件要求：\n"
            f"1. 简洁专业的自我介绍\n"
            f"2. 明确的采购意向和预估数量\n"
            f"3. 产品规格要求\n"
            f"4. 价格与付款条件询问\n"
            f"5. 用 [YOUR NAME] 等占位符标注需替换的信息\n"
            f"语气正式但友好，篇幅适中。"
        )
        return await self.controller.send_message(prompt)

    async def optimize_content(self, content: str, issue: str) -> str:
        """利用 Claude 的优化能力改进内容。"""
        prompt = (
            f"请改进以下内容，保持专业性。\n"
            f"需要改进的问题：{issue}\n"
            f"要求：只输出改进后的内容，不要加额外说明。\n\n"
            f"原始内容：\n{content}"
        )
        return await self.controller.send_message(prompt)

    async def verify_result(self, original_result: str, task_type: str) -> dict:
        """让 Claude 验证另一个 AI 的输出结果是否可靠。"""
        prompt = (
            f"请验证以下{task_type}结果是否可靠。\n"
            f"请用JSON格式返回验证结论，包含三个字段：\n"
            f'- "valid": true 或 false\n'
            f'- "confidence": 0-100 的置信度分数\n'
            f'- "issues": 问题列表（字符串数组），没有问题则为空数组\n\n'
            f"待验证内容：\n{original_result}"
        )
        raw = await self.controller.send_message(prompt)

        # 尝试从回复中提取 JSON
        try:
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                result = json.loads(match.group())
                return {
                    "valid": bool(result.get("valid", False)),
                    "confidence": int(result.get("confidence", 0)),
                    "issues": list(result.get("issues", [])),
                }
        except (json.JSONDecodeError, ValueError):
            logger.warning("无法解析验证结果JSON，使用启发式判断")

        # JSON 解析失败时的启发式回退
        text_lower = raw.lower()
        has_issues = any(
            kw in text_lower for kw in ["不可靠", "不准确", "错误", "问题", "unreliable", "incorrect"]
        )
        return {
            "valid": not has_issues,
            "confidence": 30,
            "issues": [raw[:200]] if has_issues else [],
        }
