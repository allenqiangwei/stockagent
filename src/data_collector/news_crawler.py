"""财经新闻获取和情绪分析

使用 AkShare 接口获取财经新闻，不使用爬虫。
支持数据源：财联社、东方财富、新浪财经
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

# 导入前清理代理
for _var in ['HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ.pop(_var, None)
os.environ['NO_PROXY'] = '*'

try:
    import akshare as ak
except ImportError:
    ak = None

from src.utils.logger import get_logger
from src.utils.network import no_proxy
from src.services.api_guard import get_api_guard

logger = get_logger(__name__)


@dataclass
class NewsItem:
    """新闻条目"""
    title: str
    source: str
    sentiment_score: float
    keywords: str = ""
    url: str = ""
    publish_time: str = ""
    content: str = ""


class NewsCrawler:
    """财经新闻获取器

    使用 AkShare 接口获取财经新闻，并进行简单的情绪分析。

    数据源:
    - 财联社 (stock_info_global_cls)
    - 东方财富 (stock_info_global_em)
    - 新浪财经 (stock_info_global_sina)
    """

    # 情绪关键词
    POSITIVE_KEYWORDS = [
        "大涨", "涨停", "突破", "新高", "利好", "上涨", "反弹",
        "流入", "增持", "买入", "牛市", "暴涨", "飙升", "走强",
        "提振", "政策支持", "刺激", "红盘", "翻红", "回暖",
        "增长", "盈利", "超预期", "景气", "复苏",
    ]

    NEGATIVE_KEYWORDS = [
        "暴跌", "跌停", "跳水", "崩盘", "恐慌", "下跌", "回落",
        "流出", "减持", "卖出", "熊市", "大跌", "走弱", "杀跌",
        "监管", "调查", "处罚", "绿盘", "翻绿", "破位",
        "亏损", "下滑", "低迷", "警示", "退市",
    ]

    def __init__(self, timeout: int = 10):
        """初始化

        Args:
            timeout: 请求超时时间(秒)
        """
        self.timeout = timeout
        if ak is None:
            logger.warning("AkShare 未安装，新闻功能不可用")

    def fetch_cls_news(self, max_count: int = 0) -> List[NewsItem]:
        """获取财联社新闻

        Args:
            max_count: 最大获取数量，0表示获取全部

        Returns:
            新闻列表
        """
        if ak is None:
            return []

        logger.info("正在获取财联社新闻...")

        try:
            with no_proxy():
                df = ak.stock_info_global_cls()

            if df is None or df.empty:
                logger.warning("财联社新闻返回空数据")
                return []

            news_list = []
            rows = df.head(max_count) if max_count > 0 else df
            for _, row in rows.iterrows():
                title = str(row.get('标题', ''))
                content = str(row.get('内容', ''))
                pub_date = str(row.get('发布日期', ''))
                pub_time = str(row.get('发布时间', ''))

                if not title or len(title) < 5:
                    continue

                # 合并标题和内容进行情绪分析
                text_for_analysis = title + " " + content
                score = self.analyze_sentiment(text_for_analysis)
                keywords = self._extract_keywords(text_for_analysis)

                news_list.append(NewsItem(
                    title=title,
                    source="cls",  # 财联社
                    sentiment_score=score,
                    keywords=keywords,
                    publish_time=f"{pub_date} {pub_time}".strip(),
                    content=content[:200] if content else "",  # 截取前200字
                ))

            logger.info(f"获取到 {len(news_list)} 条财联社新闻")
            return news_list

        except Exception as e:
            logger.error(f"获取财联社新闻失败: {e}")
            return []

    def fetch_eastmoney_news(self, max_count: int = 0) -> List[NewsItem]:
        """获取东方财富新闻

        Args:
            max_count: 最大获取数量，0表示获取全部

        Returns:
            新闻列表
        """
        if ak is None:
            return []

        # 熔断检查
        guard = get_api_guard()
        if guard.is_blocked("eastmoney"):
            logger.info("东方财富接口已熔断，跳过新闻获取")
            return []

        logger.info("正在获取东方财富新闻...")

        try:
            with no_proxy():
                df = ak.stock_info_global_em()

            if df is None or df.empty:
                logger.warning("东方财富新闻返回空数据")
                return []

            news_list = []
            rows = df.head(max_count) if max_count > 0 else df
            for _, row in rows.iterrows():
                title = str(row.get('标题', ''))
                summary = str(row.get('摘要', ''))
                pub_time = str(row.get('发布时间', ''))
                url = str(row.get('链接', ''))

                if not title or len(title) < 5:
                    continue

                text_for_analysis = title + " " + summary
                score = self.analyze_sentiment(text_for_analysis)
                keywords = self._extract_keywords(text_for_analysis)

                news_list.append(NewsItem(
                    title=title,
                    source="eastmoney",
                    sentiment_score=score,
                    keywords=keywords,
                    url=url,
                    publish_time=pub_time,
                    content=summary[:200] if summary else "",
                ))

            logger.info(f"获取到 {len(news_list)} 条东方财富新闻")
            guard.record_success("eastmoney")
            return news_list

        except Exception as e:
            logger.error(f"获取东方财富新闻失败: {e}")
            guard.record_failure("eastmoney", str(e))
            return []

    def fetch_sina_news(self, max_count: int = 0) -> List[NewsItem]:
        """获取新浪财经新闻

        Args:
            max_count: 最大获取数量，0表示获取全部

        Returns:
            新闻列表
        """
        if ak is None:
            return []

        logger.info("正在获取新浪财经新闻...")

        try:
            with no_proxy():
                df = ak.stock_info_global_sina()

            if df is None or df.empty:
                logger.warning("新浪财经新闻返回空数据")
                return []

            news_list = []
            rows = df.head(max_count) if max_count > 0 else df
            for _, row in rows.iterrows():
                content = str(row.get('内容', ''))
                pub_time = str(row.get('时间', ''))

                if not content or len(content) < 10:
                    continue

                # 新浪只有内容，取前50字作为标题
                title = content[:50] + "..." if len(content) > 50 else content

                score = self.analyze_sentiment(content)
                keywords = self._extract_keywords(content)

                news_list.append(NewsItem(
                    title=title,
                    source="sina",
                    sentiment_score=score,
                    keywords=keywords,
                    publish_time=pub_time,
                    content=content[:200],
                ))

            logger.info(f"获取到 {len(news_list)} 条新浪财经新闻")
            return news_list

        except Exception as e:
            logger.error(f"获取新浪财经新闻失败: {e}")
            return []

    def fetch_all(self, max_count: int = 0) -> List[NewsItem]:
        """获取所有数据源的新闻

        Args:
            max_count: 每个数据源的最大获取数量，0表示获取全部

        Returns:
            合并后的新闻列表
        """
        all_news = []

        # 财联社
        all_news.extend(self.fetch_cls_news(max_count))

        # 东方财富
        all_news.extend(self.fetch_eastmoney_news(max_count))

        # 新浪财经
        all_news.extend(self.fetch_sina_news(max_count))

        # 去重（基于标题前30字符）
        seen = set()
        unique_news = []
        for news in all_news:
            key = news.title[:30]
            if key not in seen:
                seen.add(key)
                unique_news.append(news)

        logger.info(f"共获取 {len(unique_news)} 条新闻（去重后）")
        return unique_news

    # 保留旧方法名以兼容
    def crawl_eastmoney(self, max_count: int = 0) -> List[NewsItem]:
        """兼容旧接口"""
        return self.fetch_eastmoney_news(max_count)

    def crawl_sina(self, max_count: int = 0) -> List[NewsItem]:
        """兼容旧接口"""
        return self.fetch_sina_news(max_count)

    def crawl_all(self, max_count: int = 0) -> List[NewsItem]:
        """兼容旧接口"""
        return self.fetch_all(max_count)

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
