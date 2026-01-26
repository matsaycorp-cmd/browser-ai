# 质量检查模块

import logging
import re

logger = logging.getLogger(__name__)

# 各语言的常见关键词（用于语言检测）
LANGUAGE_KEYWORDS = {
    "english": ["dear", "regards", "thank", "sincerely", "please", "subject"],
    "portuguese": ["prezado", "atenciosamente", "obrigado", "senhor", "empresa"],
    "spanish": ["estimado", "atentamente", "gracias", "señor", "empresa"],
    "chinese": ["您好", "感谢", "此致", "敬启", "贵公司"],
}

# AI 幻觉 / 拒绝回答的常见标记
HALLUCINATION_MARKERS = [
    "I don't have access",
    "I cannot browse",
    "I'm not able to",
    "I can't access",
    "I don't have real-time",
    "as an AI",
    "我无法访问",
    "作为AI",
    "作为人工智能",
    "抱歉，我没有",
    "我无法浏览",
    "无法实时",
]

# 未填充占位符的模式
PLACEHOLDER_PATTERN = re.compile(
    r"\[(?:xxx|XXX|your|YOUR|填写|待填|company|name|email|phone)[^\]]*\]"
    r"|\{(?:xxx|XXX|your|YOUR|填写|待填|company|name|email|phone)[^}]*\}"
    r"|_{3,}"
    r"|\.\.\.",
    re.IGNORECASE,
)


class QualityChecker:
    """对 AI 返回结果进行多维度质量评分。"""

    def __init__(self):
        self.checkers = {
            "contact": self.check_contact_result,
            "email": self.check_email_content,
            "slaughterhouse": self.check_slaughterhouse_list,
            "freight_forwarder": self.check_freight_forwarder,
        }

    # ── 主入口 ────────────────────────────────────────────

    def check(self, task_type: str, result, **kwargs) -> dict:
        """根据 task_type 分派到对应检查方法，返回评分报告。"""
        checker = self.checkers.get(task_type)
        if checker is None:
            logger.warning("未知任务类型: %s，跳过质量检查", task_type)
            return {"score": 0, "passed": [], "failed": ["未知任务类型"], "issues": []}
        return checker(result, **kwargs)

    # ── 联系方式检查 ──────────────────────────────────────

    def check_contact_result(self, result: dict) -> dict:
        score = 0
        passed = []
        failed = []
        issues = []

        raw = result.get("raw", "")
        emails = result.get("emails", [])
        phones = result.get("phones", [])
        websites = result.get("websites", [])

        # 1. emails 非空 (+30)
        if emails:
            score += 30
            passed.append("emails非空")
        else:
            failed.append("emails为空")
            issues.append("未找到邮箱地址")

        # 2. email 格式有效 (+20)
        if emails and all(self._check_email_format(e) for e in emails):
            score += 20
            passed.append("email格式有效")
        elif emails:
            invalid = [e for e in emails if not self._check_email_format(e)]
            failed.append("email格式无效")
            issues.append(f"格式异常的邮箱: {invalid}")

        # 3. phones 格式合理 (+10)
        if phones and all(self._check_phone_format(p) for p in phones):
            score += 10
            passed.append("phones格式合理")
        elif phones:
            failed.append("phones格式不合理")
        else:
            failed.append("phones为空")

        # 4. websites 格式有效 (+10)
        if websites and all(self._check_url_format(u) for u in websites):
            score += 10
            passed.append("websites格式有效")
        elif websites:
            failed.append("websites格式无效")
        else:
            failed.append("websites为空")

        # 5. 无幻觉标记 (+30)
        if self._check_hallucination(raw):
            score += 30
            passed.append("无幻觉标记")
        else:
            failed.append("检测到幻觉标记")
            issues.append("回复中包含AI拒绝/幻觉标记")

        return {"score": score, "passed": passed, "failed": failed, "issues": issues}

    # ── 邮件内容检查 ──────────────────────────────────────

    def check_email_content(self, result, expected_language: str = "english") -> dict:
        score = 0
        passed = []
        failed = []
        issues = []

        text = result if isinstance(result, str) else result.get("raw", "")

        # 1. 非空且长度 > 100 字符 (+20)
        if text and len(text) > 100:
            score += 20
            passed.append("内容长度充足")
        else:
            failed.append("内容过短")
            issues.append(f"邮件长度不足 (当前{len(text)}字符，要求>100)")

        # 2. 有问候语 (+15)
        greetings = ["dear", "hello", "hi ", "good morning", "good afternoon",
                      "prezado", "estimado", "您好", "尊敬的"]
        text_lower = text.lower()
        if any(g in text_lower for g in greetings):
            score += 15
            passed.append("包含问候语")
        else:
            failed.append("缺少问候语")

        # 3. 有结束语 (+15)
        closings = ["regards", "sincerely", "best wishes", "thank you",
                     "atenciosamente", "atentamente", "此致", "敬上", "谢谢"]
        if any(c in text_lower for c in closings):
            score += 15
            passed.append("包含结束语")
        else:
            failed.append("缺少结束语")

        # 4. 语言正确 (+30)
        if self._check_language(text, expected_language):
            score += 30
            passed.append("语言匹配")
        else:
            failed.append("语言不匹配")
            issues.append(f"期望语言 {expected_language}，但未检测到对应关键词")

        # 5. 无未填充占位符 (+20)
        if self._check_placeholder(text):
            score += 20
            passed.append("无未填充占位符")
        else:
            failed.append("存在未填充占位符")
            issues.append("邮件中仍有 [xxx] / {xxx} / ___ 等占位符")

        return {"score": score, "passed": passed, "failed": failed, "issues": issues}

    # ── 屠宰场名单检查 ───────────────────────────────────

    def check_slaughterhouse_list(self, result: dict) -> dict:
        score = 0
        passed = []
        failed = []
        issues = []

        raw = result.get("raw", "")
        emails = result.get("emails", [])

        # 1. 名单非空 (+40)
        if raw and len(raw) > 50:
            score += 40
            passed.append("名单非空")
        else:
            failed.append("名单为空或过短")
            issues.append("未返回有效名单内容")

        # 2. 数量 >= 5（通过序号或列表项估算）
        items = re.findall(r"(?:^|\n)\s*(?:\d+[.、)]|\-|\*)\s*\S", raw)
        if len(items) >= 5:
            score += 20
            passed.append(f"列出{len(items)}家企业 (>=5)")
        else:
            failed.append(f"企业数量不足 ({len(items)}家)")
            issues.append("名单企业数量少于5家")

        # 3. 有公司名称（非纯数字行）(+20)
        name_lines = [
            l for l in raw.splitlines()
            if l.strip() and not l.strip().isdigit() and len(l.strip()) > 3
        ]
        if len(name_lines) >= 3:
            score += 20
            passed.append("包含公司名称")
        else:
            failed.append("缺少公司名称")

        # 4. 无幻觉标记 (+20)
        if self._check_hallucination(raw):
            score += 20
            passed.append("无幻觉标记")
        else:
            failed.append("检测到幻觉标记")
            issues.append("回复中包含AI拒绝/幻觉标记")

        return {"score": score, "passed": passed, "failed": failed, "issues": issues}

    # ── 货代检查 ─────────────────────────────────────────

    def check_freight_forwarder(self, result: dict) -> dict:
        score = 0
        passed = []
        failed = []
        issues = []

        raw = result.get("raw", "")
        emails = result.get("emails", [])
        phones = result.get("phones", [])
        websites = result.get("websites", [])

        # 1. emails 非空 (+30)
        if emails:
            score += 30
            passed.append("emails非空")
        else:
            failed.append("emails为空")
            issues.append("未找到邮箱地址")

        # 2. email 格式有效 (+20)
        if emails and all(self._check_email_format(e) for e in emails):
            score += 20
            passed.append("email格式有效")
        elif emails:
            failed.append("email格式无效")

        # 3. phones 格式合理 (+10)
        if phones and all(self._check_phone_format(p) for p in phones):
            score += 10
            passed.append("phones格式合理")
        elif phones:
            failed.append("phones格式不合理")
        else:
            failed.append("phones为空")

        # 4. websites 格式有效 (+10)
        if websites and all(self._check_url_format(u) for u in websites):
            score += 10
            passed.append("websites格式有效")
        elif websites:
            failed.append("websites格式无效")
        else:
            failed.append("websites为空")

        # 5. 无幻觉标记 (+30)
        if self._check_hallucination(raw):
            score += 30
            passed.append("无幻觉标记")
        else:
            failed.append("检测到幻觉标记")
            issues.append("回复中包含AI拒绝/幻觉标记")

        return {"score": score, "passed": passed, "failed": failed, "issues": issues}

    # ── 辅助方法 ─────────────────────────────────────────

    def _check_email_format(self, email: str) -> bool:
        """正则验证邮箱格式。"""
        return bool(re.match(
            r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
            email.strip(),
        ))

    def _check_phone_format(self, phone: str) -> bool:
        """检查至少有7位数字。"""
        digits = re.sub(r"\D", "", phone)
        return len(digits) >= 7

    def _check_url_format(self, url: str) -> bool:
        """检查是否以 http:// 或 https:// 开头。"""
        return url.strip().startswith(("http://", "https://"))

    def _check_language(self, text: str, expected: str) -> bool:
        """通过关键词检测文本语言是否匹配。"""
        keywords = LANGUAGE_KEYWORDS.get(expected.lower())
        if keywords is None:
            return True  # 未知语言，默认通过
        text_lower = text.lower()
        matches = sum(1 for kw in keywords if kw in text_lower)
        return matches >= 2  # 至少命中2个关键词

    def _check_hallucination(self, text: str) -> bool:
        """检测是否存在 AI 幻觉/拒绝标记。无标记返回 True。"""
        text_lower = text.lower()
        return not any(marker.lower() in text_lower for marker in HALLUCINATION_MARKERS)

    def _check_placeholder(self, text: str) -> bool:
        """检测是否存在未填充的占位符。无占位符返回 True。"""
        return not PLACEHOLDER_PATTERN.search(text)
