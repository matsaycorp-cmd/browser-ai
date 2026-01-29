# 人员搜索模块 - 搜索货代、验货公司、自由职业者

import asyncio
import json
import logging
import re

logger = logging.getLogger(__name__)

# 搜索平台配置
SEARCH_PLATFORMS = {
    "google": {
        "url": "https://www.google.com",
        "type": ["freight_forwarder", "inspection_company", "freelancer"],
    },
    "fiverr": {
        "url": "https://www.fiverr.com",
        "type": ["freelancer"],
    },
    "upwork": {
        "url": "https://www.upwork.com",
        "type": ["freelancer"],
    },
    "linkedin": {
        "url": "https://www.linkedin.com",
        "type": ["fulltime", "freelancer"],
    },
    "freight_directories": {
        "urls": [
            "https://www.freightos.com",
            "https://www.flexport.com",
        ],
        "type": ["freight_forwarder"],
    },
}


class PersonnelSearcher:
    """搜索货代、验货公司、自由职业者。"""

    def __init__(self, controllers: dict, browser_manager=None):
        """
        初始化搜索器。

        Args:
            controllers: AI控制器字典 {"chatgpt": controller, ...}
            browser_manager: 浏览器管理器（用于直接页面操作）
        """
        self.controllers = controllers
        self.browser_manager = browser_manager
        self.platforms = SEARCH_PLATFORMS

    # ── 货代搜索 ──────────────────────────────────────────

    async def search_freight_forwarders(
        self,
        country: str,
        city: str | None = None,
        keywords: list[str] | None = None,
    ) -> list[dict]:
        """
        搜索货代公司。

        Args:
            country: 国家
            city: 城市（可选）
            keywords: 额外关键词（可选）

        Returns:
            货代公司列表
        """
        location = f"{country} {city}" if city else country
        extra_kw = " ".join(keywords) if keywords else ""
        query = f"{location} freight forwarder animal products cold chain {extra_kw}".strip()

        logger.info("搜索货代: %s", query)

        results = []

        # Google 搜索
        try:
            google_results = await self._google_search(query)
            for item in google_results:
                item["source"] = "google"
                item["type"] = "freight_forwarder"
                results.append(item)
        except Exception as e:
            logger.error("Google搜索货代失败: %s", e)

        # 货代目录搜索
        try:
            directory_results = await self._search_freight_directories(location)
            results.extend(directory_results)
        except Exception as e:
            logger.error("货代目录搜索失败: %s", e)

        logger.info("找到 %d 个货代结果", len(results))
        return results

    # ── 验货公司搜索 ──────────────────────────────────────

    async def search_inspection_companies(
        self,
        country: str,
        city: str | None = None,
    ) -> list[dict]:
        """
        搜索验货公司。

        Args:
            country: 国家
            city: 城市（可选）

        Returns:
            验货公司列表
        """
        location = f"{country} {city}" if city else country
        query = f"{location} inspection company product inspection services"

        logger.info("搜索验货公司: %s", query)

        results = []

        try:
            google_results = await self._google_search(query)
            for item in google_results:
                item["source"] = "google"
                item["type"] = "inspection_company"
                results.append(item)
        except Exception as e:
            logger.error("搜索验货公司失败: %s", e)

        logger.info("找到 %d 个验货公司结果", len(results))
        return results

    # ── 自由职业者搜索 ────────────────────────────────────

    async def search_freelancers(
        self,
        country: str,
        city: str,
        platform: str = "fiverr",
    ) -> list[dict]:
        """
        在指定平台搜索自由职业者。

        Args:
            country: 国家
            city: 城市
            platform: 平台 (fiverr/upwork)

        Returns:
            自由职业者列表
        """
        logger.info("在 %s 搜索自由职业者: %s, %s", platform, country, city)

        results = []

        if platform == "fiverr":
            query = f"product inspection {city}"
            results = await self._search_fiverr(query)
        elif platform == "upwork":
            query = f"warehouse inspection {country}"
            results = await self._search_upwork(query)
        else:
            logger.warning("未知平台: %s", platform)

        for item in results:
            item["source"] = platform
            item["type"] = "freelancer"

        logger.info("找到 %d 个自由职业者", len(results))
        return results

    # ── 综合搜索 ──────────────────────────────────────────

    async def search_all(
        self,
        country: str,
        city: str | None = None,
        types: list[str] | None = None,
    ) -> dict[str, list]:
        """
        综合搜索所有类型。

        Args:
            country: 国家
            city: 城市（可选）
            types: 搜索类型列表，可选值：
                   ["freight_forwarder", "inspection_company", "freelancer"]
                   默认搜索全部类型

        Returns:
            分类后的结果字典
        """
        if types is None:
            types = ["freight_forwarder", "inspection_company", "freelancer"]

        logger.info("综合搜索: %s %s, 类型: %s", country, city or "", types)

        results = {
            "freight_forwarder": [],
            "inspection_company": [],
            "freelancer": [],
        }

        tasks = []

        if "freight_forwarder" in types:
            tasks.append(("freight_forwarder", self.search_freight_forwarders(country, city)))

        if "inspection_company" in types:
            tasks.append(("inspection_company", self.search_inspection_companies(country, city)))

        if "freelancer" in types and city:
            # 同时搜索 Fiverr 和 Upwork
            tasks.append(("freelancer_fiverr", self.search_freelancers(country, city, "fiverr")))
            tasks.append(("freelancer_upwork", self.search_freelancers(country, city, "upwork")))

        # 并行执行搜索
        for task_type, coro in tasks:
            try:
                task_results = await coro
                if task_type.startswith("freelancer"):
                    results["freelancer"].extend(task_results)
                else:
                    results[task_type] = task_results
            except Exception as e:
                logger.error("搜索 %s 失败: %s", task_type, e)

        total = sum(len(v) for v in results.values())
        logger.info("综合搜索完成，共找到 %d 个结果", total)

        return results

    # ── 平台搜索实现 ──────────────────────────────────────

    async def _google_search(self, query: str) -> list[dict]:
        """执行Google搜索并提取结果。"""
        if not self.browser_manager:
            logger.warning("无浏览器管理器，跳过Google搜索")
            return []

        page = await self.browser_manager.new_page()

        try:
            # 访问Google
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # 提取结果
            results = await self._extract_google_results(page)
            return results

        finally:
            await page.close()

    async def _search_fiverr(self, query: str) -> list[dict]:
        """在Fiverr搜索。"""
        if not self.browser_manager:
            logger.warning("无浏览器管理器，跳过Fiverr搜索")
            return []

        page = await self.browser_manager.new_page()

        try:
            url = f"https://www.fiverr.com/search/gigs?query={query.replace(' ', '%20')}"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            results = await self._extract_fiverr_results(page)
            return results

        finally:
            await page.close()

    async def _search_upwork(self, query: str) -> list[dict]:
        """在Upwork搜索。"""
        if not self.browser_manager:
            logger.warning("无浏览器管理器，跳过Upwork搜索")
            return []

        page = await self.browser_manager.new_page()

        try:
            url = f"https://www.upwork.com/search/profiles/?q={query.replace(' ', '%20')}"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            results = await self._extract_upwork_results(page)
            return results

        finally:
            await page.close()

    async def _search_freight_directories(self, location: str) -> list[dict]:
        """在货代目录网站搜索。"""
        results = []
        urls = self.platforms["freight_directories"]["urls"]

        for base_url in urls:
            try:
                if not self.browser_manager:
                    continue

                page = await self.browser_manager.new_page()
                try:
                    await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2)

                    # 尝试找搜索框并搜索
                    search_input = await page.query_selector('input[type="search"], input[name="q"], input[placeholder*="search" i]')
                    if search_input:
                        await search_input.fill(location)
                        await search_input.press("Enter")
                        await asyncio.sleep(3)

                        # 提取结果（简化版）
                        items = await page.query_selector_all('article, .result, .listing, [class*="card"]')
                        for item in items[:10]:
                            text = await item.inner_text()
                            results.append({
                                "title": text[:100] if text else "Unknown",
                                "url": base_url,
                                "source": "freight_directory",
                                "type": "freight_forwarder",
                            })

                finally:
                    await page.close()

            except Exception as e:
                logger.error("搜索 %s 失败: %s", base_url, e)

        return results

    # ── 结果提取 ──────────────────────────────────────────

    async def _extract_google_results(self, page) -> list[dict]:
        """从Google搜索结果页提取信息。"""
        results = []

        try:
            # Google搜索结果选择器
            items = await page.query_selector_all("div.g, div[data-hveid]")

            for item in items[:15]:  # 最多取15条
                try:
                    # 标题和链接
                    title_el = await item.query_selector("h3")
                    link_el = await item.query_selector("a[href^='http']")
                    snippet_el = await item.query_selector("div[data-sncf], div.VwiC3b, span.aCOpRe")

                    title = await title_el.inner_text() if title_el else ""
                    link = await link_el.get_attribute("href") if link_el else ""
                    snippet = await snippet_el.inner_text() if snippet_el else ""

                    if title and link:
                        # 尝试从摘要中提取联系信息
                        phone = self._extract_phone(snippet)
                        address = self._extract_address(snippet)

                        results.append({
                            "title": title.strip(),
                            "url": link,
                            "snippet": snippet.strip()[:300] if snippet else "",
                            "phone": phone,
                            "address": address,
                        })

                except Exception as e:
                    logger.debug("提取单条Google结果失败: %s", e)
                    continue

        except Exception as e:
            logger.error("提取Google结果失败: %s", e)

        return results

    async def _extract_fiverr_results(self, page) -> list[dict]:
        """从Fiverr搜索结果提取。"""
        results = []

        try:
            # Fiverr gig卡片选择器
            items = await page.query_selector_all('[class*="gig-card"], [class*="GigCard"], article')

            for item in items[:15]:
                try:
                    # 卖家名
                    seller_el = await item.query_selector('[class*="seller-name"], [class*="username"], a[href*="/"]')
                    seller = await seller_el.inner_text() if seller_el else "Unknown"

                    # 评分
                    rating_el = await item.query_selector('[class*="rating"], [class*="star"]')
                    rating_text = await rating_el.inner_text() if rating_el else ""
                    rating = self._parse_rating(rating_text)

                    # 评价数
                    reviews_el = await item.query_selector('[class*="reviews"], [class*="rating-count"]')
                    reviews_text = await reviews_el.inner_text() if reviews_el else "0"
                    reviews = self._parse_number(reviews_text)

                    # 价格
                    price_el = await item.query_selector('[class*="price"], span:has-text("$")')
                    price_text = await price_el.inner_text() if price_el else ""
                    price = self._parse_price(price_text)

                    # 服务描述
                    desc_el = await item.query_selector('h3, [class*="title"], [class*="description"]')
                    description = await desc_el.inner_text() if desc_el else ""

                    # 链接
                    link_el = await item.query_selector('a[href*="/"]')
                    link = await link_el.get_attribute("href") if link_el else ""
                    if link and not link.startswith("http"):
                        link = f"https://www.fiverr.com{link}"

                    results.append({
                        "seller_name": seller.strip(),
                        "rating": rating,
                        "reviews_count": reviews,
                        "price": price,
                        "description": description.strip()[:200] if description else "",
                        "url": link,
                        "platform": "fiverr",
                    })

                except Exception as e:
                    logger.debug("提取单条Fiverr结果失败: %s", e)
                    continue

        except Exception as e:
            logger.error("提取Fiverr结果失败: %s", e)

        return results

    async def _extract_upwork_results(self, page) -> list[dict]:
        """从Upwork搜索结果提取。"""
        results = []

        try:
            # Upwork个人资料卡片选择器
            items = await page.query_selector_all('[data-test="freelancer-tile"], [class*="profile-tile"], article')

            for item in items[:15]:
                try:
                    # 自由职业者名
                    name_el = await item.query_selector('[class*="name"], h4, [data-test="freelancer-name"]')
                    name = await name_el.inner_text() if name_el else "Unknown"

                    # 评分
                    rating_el = await item.query_selector('[class*="rating"], [data-test="job-success"]')
                    rating_text = await rating_el.inner_text() if rating_el else ""
                    rating = self._parse_rating(rating_text)

                    # 时薪
                    rate_el = await item.query_selector('[data-test="rate"], [class*="rate"], span:has-text("/hr")')
                    rate_text = await rate_el.inner_text() if rate_el else ""
                    hourly_rate = self._parse_price(rate_text)

                    # 技能
                    skills = []
                    skill_els = await item.query_selector_all('[class*="skill"], [data-test="skill"]')
                    for skill_el in skill_els[:5]:
                        skill_text = await skill_el.inner_text()
                        if skill_text:
                            skills.append(skill_text.strip())

                    # 简介
                    bio_el = await item.query_selector('[class*="description"], [class*="overview"], p')
                    bio = await bio_el.inner_text() if bio_el else ""

                    # 链接
                    link_el = await item.query_selector('a[href*="/freelancers/"]')
                    link = await link_el.get_attribute("href") if link_el else ""
                    if link and not link.startswith("http"):
                        link = f"https://www.upwork.com{link}"

                    results.append({
                        "freelancer_name": name.strip(),
                        "rating": rating,
                        "hourly_rate": hourly_rate,
                        "skills": skills,
                        "bio": bio.strip()[:200] if bio else "",
                        "url": link,
                        "platform": "upwork",
                    })

                except Exception as e:
                    logger.debug("提取单条Upwork结果失败: %s", e)
                    continue

        except Exception as e:
            logger.error("提取Upwork结果失败: %s", e)

        return results

    # ── 辅助方法 ──────────────────────────────────────────

    def _extract_phone(self, text: str) -> str | None:
        """从文本中提取电话号码。"""
        if not text:
            return None
        patterns = [
            r'\+?[\d\s\-\(\)]{10,20}',
            r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group().strip()
        return None

    def _extract_address(self, text: str) -> str | None:
        """从文本中提取地址。"""
        if not text:
            return None
        # 简单的地址模式匹配
        patterns = [
            r'\d+\s+[\w\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr)[\w\s,]*',
            r'[\w\s]+,\s*[\w\s]+,\s*\d{5}',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group().strip()
        return None

    def _parse_rating(self, text: str) -> float:
        """解析评分。"""
        if not text:
            return 0.0
        match = re.search(r'(\d+\.?\d*)', text)
        if match:
            return float(match.group(1))
        return 0.0

    def _parse_number(self, text: str) -> int:
        """解析数字。"""
        if not text:
            return 0
        # 处理 "1.2k", "500+" 等格式
        text = text.lower().replace("+", "").replace(",", "")
        match = re.search(r'(\d+\.?\d*)(k)?', text)
        if match:
            num = float(match.group(1))
            if match.group(2) == "k":
                num *= 1000
            return int(num)
        return 0

    def _parse_price(self, text: str) -> float:
        """解析价格。"""
        if not text:
            return 0.0
        match = re.search(r'\$?\s*(\d+\.?\d*)', text.replace(",", ""))
        if match:
            return float(match.group(1))
        return 0.0


class PersonnelEvaluator:
    """使用AI评估搜索到的人员/公司。"""

    def __init__(self, ai_controller):
        """
        初始化评估器。

        Args:
            ai_controller: AI控制器（用于信用评估）
        """
        self.ai_controller = ai_controller

    async def evaluate_single(self, personnel_info: dict, personnel_type: str) -> dict:
        """
        评估单个搜索结果。

        Args:
            personnel_info: 人员/公司信息
            personnel_type: 类型 (freight_forwarder/inspection_company/freelancer)

        Returns:
            评估结果
        """
        type_names = {
            "freight_forwarder": "货代公司",
            "inspection_company": "验货公司",
            "freelancer": "自由职业者",
        }
        type_name = type_names.get(personnel_type, personnel_type)

        # 格式化信息
        info_text = json.dumps(personnel_info, ensure_ascii=False, indent=2)

        prompt = f"""请评估以下{type_name}的可信度，用于外包验货工作。

信息：
{info_text}

请从以下维度评分（总分100）：

1. 背景可信度（20分）：
   - 有官网/平台认证 +10
   - 成立时间/从业时间长 +5
   - 有实体地址 +5

2. 行业相关性（25分）：
   - 有动物产品/农产品经验 +15
   - 有食品/医药物流经验 +10
   - 有冷链经验 +5

3. 评价口碑（25分）：
   - 平台评分4分以上 +10
   - 好评数量多 +10
   - 无明显差评 +5

4. 风险指标（30分，扣分项）：
   - 信息不完整 -10
   - 价格异常低 -10
   - 无法验证身份 -15
   - 有负面信息 -20

请返回JSON格式：
{{
  "score": 总分,
  "breakdown": {{
    "background": 分数,
    "relevance": 分数,
    "reputation": 分数,
    "risk_deduction": 扣分
  }},
  "strengths": ["优点1", "优点2"],
  "risks": ["风险1", "风险2"],
  "recommendation": "推荐/谨慎/不推荐",
  "suggested_max_value": 建议最高货值美元,
  "notes": "其他备注"
}}

只返回JSON，不要其他内容。"""

        try:
            # 发送消息给AI
            await self.ai_controller.send_message(prompt)
            await self.ai_controller.wait_response()
            response = await self.ai_controller.get_last_response()

            # 解析JSON
            evaluation = self._parse_evaluation_response(response)

            # 合并原始信息和评估结果
            result = dict(personnel_info)
            result["ai_evaluation"] = evaluation
            result["ai_score"] = evaluation.get("score", 0)

            logger.info(
                "评估完成: %s, 得分: %d",
                personnel_info.get("title") or personnel_info.get("seller_name") or personnel_info.get("freelancer_name", "Unknown"),
                result["ai_score"],
            )

            return result

        except Exception as e:
            logger.error("评估失败: %s", e)
            result = dict(personnel_info)
            result["ai_evaluation"] = {"error": str(e)}
            result["ai_score"] = 0
            return result

    async def evaluate_batch(self, personnel_list: list[dict], personnel_type: str) -> list[dict]:
        """
        批量评估。

        Args:
            personnel_list: 人员/公司列表
            personnel_type: 类型

        Returns:
            带评分的完整列表
        """
        logger.info("开始批量评估 %d 个 %s", len(personnel_list), personnel_type)

        results = []
        for i, info in enumerate(personnel_list):
            logger.info("评估进度: %d/%d", i + 1, len(personnel_list))
            try:
                evaluated = await self.evaluate_single(info, personnel_type)
                results.append(evaluated)
                # 避免请求过快
                await asyncio.sleep(2)
            except Exception as e:
                logger.error("批量评估中断: %s", e)
                info["ai_evaluation"] = {"error": str(e)}
                info["ai_score"] = 0
                results.append(info)

        # 按评分排序
        results.sort(key=lambda x: x.get("ai_score", 0), reverse=True)

        logger.info("批量评估完成，共 %d 个结果", len(results))
        return results

    async def deep_research(self, personnel_info: dict) -> dict:
        """
        深度调研单个候选人。

        Args:
            personnel_info: 人员/公司信息

        Returns:
            详细调研报告
        """
        name = (
            personnel_info.get("title")
            or personnel_info.get("seller_name")
            or personnel_info.get("freelancer_name")
            or "Unknown"
        )

        prompt = f"""请对以下公司/个人进行深度调研：

基本信息：
{json.dumps(personnel_info, ensure_ascii=False, indent=2)}

请尝试了解以下信息（如果能找到的话）：

1. 公司注册信息
   - 注册时间
   - 注册资本
   - 法人代表
   - 经营范围

2. 公开新闻报道
   - 正面报道
   - 负面报道
   - 行业动态

3. 社交媒体
   - 官方账号
   - 活跃度
   - 粉丝互动

4. 风险信息
   - 法律诉讼记录
   - 行政处罚
   - 信用评级

5. 行业评价
   - 同行评价
   - 客户反馈
   - 行业排名

请返回JSON格式的详细报告：
{{
  "company_name": "{name}",
  "registration": {{
    "found": true/false,
    "details": "..."
  }},
  "news": {{
    "positive": ["..."],
    "negative": ["..."]
  }},
  "social_media": {{
    "accounts": ["..."],
    "activity_level": "活跃/一般/不活跃"
  }},
  "risks": {{
    "lawsuits": ["..."],
    "penalties": ["..."],
    "credit_rating": "..."
  }},
  "industry_reputation": {{
    "peer_review": "...",
    "customer_feedback": "...",
    "ranking": "..."
  }},
  "overall_assessment": "综合评估",
  "trust_level": "高/中/低",
  "recommended_action": "建议采取的行动"
}}

只返回JSON，不要其他内容。"""

        try:
            await self.ai_controller.send_message(prompt)
            await self.ai_controller.wait_response()
            response = await self.ai_controller.get_last_response()

            report = self._parse_evaluation_response(response)
            report["original_info"] = personnel_info

            logger.info("深度调研完成: %s", name)
            return report

        except Exception as e:
            logger.error("深度调研失败: %s", e)
            return {
                "original_info": personnel_info,
                "error": str(e),
                "trust_level": "unknown",
            }

    def _parse_evaluation_response(self, response: str) -> dict:
        """解析AI返回的评估JSON。"""
        if not response:
            return {"error": "Empty response", "score": 0}

        try:
            # 尝试直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # 尝试提取JSON块
        json_patterns = [
            r'```json\s*([\s\S]*?)\s*```',
            r'```\s*([\s\S]*?)\s*```',
            r'\{[\s\S]*\}',
        ]

        for pattern in json_patterns:
            match = re.search(pattern, response)
            if match:
                try:
                    json_str = match.group(1) if '```' in pattern else match.group(0)
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    continue

        # 解析失败，返回原始响应
        logger.warning("无法解析AI返回的JSON")
        return {
            "raw_response": response[:500],
            "score": 50,  # 给一个默认分数
            "recommendation": "需人工审核",
        }
