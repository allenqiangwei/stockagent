"""财经新闻爬虫和情绪分析"""
import re
from dataclasses import dataclass
from typing import List, Optional
import requests
from bs4 import BeautifulSoup

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class NewsItem:
    """新闻条目"""
    title: str
    source: str
    sentiment_score: float
    keywords: str = ""
    url: str = ""


class NewsCrawler:
    """财经新闻爬虫

    爬取主流财经网站的新闻标题，并进行简单的情绪分析。
    """

    # 情绪关键词
    POSITIVE_KEYWORDS = [
        "大涨", "涨停", "突破", "新高", "利好", "上涨", "反弹",
        "流入", "增持", "买入", "牛市", "暴涨", "飙升", "走强",
        "提振", "政策支持", "刺激", "红盘", "翻红",
    ]

    NEGATIVE_KEYWORDS = [
        "暴跌", "跌停", "跳水", "崩盘", "恐慌", "下跌", "回落",
        "流出", "减持", "卖出", "熊市", "大跌", "走弱", "杀跌",
        "监管", "调查", "处罚", "绿盘", "翻绿", "破位",
    ]

    def __init__(self, timeout: int = 10):
        """初始化爬虫

        Args:
            timeout: 请求超时时间(秒)
        """
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }

    def crawl_eastmoney(self, max_count: int = 20) -> List[NewsItem]:
        """爬取东方财富财经新闻

        Args:
            max_count: 最大爬取数量

        Returns:
            新闻列表
        """
        logger.info("正在爬取东方财富新闻...")

        url = "https://finance.eastmoney.com/a/cywjh.html"

        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout
            )
            response.encoding = "utf-8"

            soup = BeautifulSoup(response.text, "lxml")

            news_list = []
            # 东方财富新闻列表的选择器（可能需要根据实际页面调整）
            for item in soup.select("div.text a, li.title a")[:max_count]:
                title = item.get_text(strip=True)
                if not title or len(title) < 5:
                    continue

                href = item.get("href", "")
                score = self.analyze_sentiment(title)
                keywords = self._extract_keywords(title)

                news_list.append(NewsItem(
                    title=title,
                    source="eastmoney",
                    sentiment_score=score,
                    keywords=keywords,
                    url=href,
                ))

            logger.info(f"爬取到 {len(news_list)} 条新闻")
            return news_list

        except Exception as e:
            logger.error(f"爬取东方财富新闻失败: {e}")
            return []

    def crawl_sina(self, max_count: int = 20) -> List[NewsItem]:
        """爬取新浪财经新闻

        Args:
            max_count: 最大爬取数量

        Returns:
            新闻列表
        """
        logger.info("正在爬取新浪财经新闻...")

        url = "https://finance.sina.com.cn/stock/"

        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout
            )
            response.encoding = "utf-8"

            soup = BeautifulSoup(response.text, "lxml")

            news_list = []
            for item in soup.select("a[href*='/stock/']")[:max_count]:
                title = item.get_text(strip=True)
                if not title or len(title) < 5:
                    continue

                href = item.get("href", "")
                score = self.analyze_sentiment(title)
                keywords = self._extract_keywords(title)

                news_list.append(NewsItem(
                    title=title,
                    source="sina",
                    sentiment_score=score,
                    keywords=keywords,
                    url=href,
                ))

            logger.info(f"爬取到 {len(news_list)} 条新闻")
            return news_list

        except Exception as e:
            logger.error(f"爬取新浪财经新闻失败: {e}")
            return []

    def crawl_all(self, max_count: int = 20) -> List[NewsItem]:
        """爬取所有数据源的新闻

        Args:
            max_count: 每个数据源的最大爬取数量

        Returns:
            合并后的新闻列表
        """
        all_news = []

        # 东方财富
        all_news.extend(self.crawl_eastmoney(max_count))

        # 新浪财经
        all_news.extend(self.crawl_sina(max_count))

        # 去重（基于标题）
        seen = set()
        unique_news = []
        for news in all_news:
            if news.title not in seen:
                seen.add(news.title)
                unique_news.append(news)

        return unique_news

    def analyze_sentiment(self, text: str) -> float:
        """分析文本情绪

        使用简单的关键词匹配方法。

        Args:
            text: 新闻标题或内容

        Returns:
            情绪分数 (0-100, 50为中性)
        """
        positive_count = sum(1 for kw in self.POSITIVE_KEYWORDS if kw in text)
        negative_count = sum(1 for kw in self.NEGATIVE_KEYWORDS if kw in text)

        # 基准分50
        score = 50.0

        # 正面关键词加分，负面减分
        score += positive_count * 8
        score -= negative_count * 10

        # 限制在0-100范围
        return max(0, min(100, score))

    def _extract_keywords(self, text: str) -> str:
        """提取关键词

        Args:
            text: 文本

        Returns:
            逗号分隔的关键词
        """
        keywords = []

        for kw in self.POSITIVE_KEYWORDS + self.NEGATIVE_KEYWORDS:
            if kw in text:
                keywords.append(kw)

        return ",".join(keywords[:5])  # 最多5个关键词

    def get_overall_sentiment(self, news_list: List[NewsItem]) -> float:
        """计算整体市场情绪

        Args:
            news_list: 新闻列表

        Returns:
            整体情绪分数 (0-100)
        """
        if not news_list:
            return 50.0

        total_score = sum(n.sentiment_score for n in news_list)
        return total_score / len(news_list)
