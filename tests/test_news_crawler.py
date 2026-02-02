import pytest
from unittest.mock import patch, Mock
from src.data_collector.news_crawler import NewsCrawler, NewsItem


class TestNewsCrawler:
    @patch("src.data_collector.news_crawler.requests")
    def test_crawl_eastmoney_news(self, mock_requests):
        """测试爬取东方财富新闻"""
        mock_response = Mock()
        mock_response.text = """
        <html>
        <body>
            <div class="news-item">
                <a href="/news/1.html">A股三大指数集体高开</a>
            </div>
            <div class="news-item">
                <a href="/news/2.html">北向资金净流入超50亿</a>
            </div>
        </body>
        </html>
        """
        mock_response.status_code = 200
        mock_requests.get.return_value = mock_response

        crawler = NewsCrawler()
        news_list = crawler.crawl_eastmoney(max_count=5)

        assert isinstance(news_list, list)

    def test_analyze_sentiment_positive(self):
        """测试正面新闻情绪分析"""
        crawler = NewsCrawler()

        score = crawler.analyze_sentiment("A股三大指数集体大涨 北向资金大举流入")

        assert score > 50  # 正面情绪分数应该大于50

    def test_analyze_sentiment_negative(self):
        """测试负面新闻情绪分析"""
        crawler = NewsCrawler()

        score = crawler.analyze_sentiment("A股暴跌 千股跌停 恐慌情绪蔓延")

        assert score < 50  # 负面情绪分数应该小于50

    def test_analyze_sentiment_neutral(self):
        """测试中性新闻情绪分析"""
        crawler = NewsCrawler()

        score = crawler.analyze_sentiment("央行公布最新货币政策报告")

        assert 40 <= score <= 60  # 中性情绪分数应该在40-60之间

    def test_news_item_dataclass(self):
        """测试NewsItem数据类"""
        item = NewsItem(
            title="测试新闻",
            source="eastmoney",
            sentiment_score=65.0,
            keywords="测试,新闻",
        )

        assert item.title == "测试新闻"
        assert item.sentiment_score == 65.0
