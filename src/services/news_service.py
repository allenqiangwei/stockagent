"""新闻后台服务

每10分钟自动获取财经新闻并缓存到本地文件和数据库。
仪表盘从缓存文件读取，避免重复请求API。
数据库存储用于历史分析和去重。
"""

import json
import os
import threading
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from src.data_collector.news_crawler import NewsCrawler, NewsItem
from src.data_storage.database import Database
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 缓存目录
CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "news_cache"
CACHE_FILE = CACHE_DIR / "latest_news.json"

# 数据库路径
DB_PATH = Path(__file__).parent.parent.parent / "data" / "stockagent.db"


class NewsService:
    """新闻后台服务

    功能：
    - 定时获取财经新闻（默认每10分钟）
    - 缓存到本地JSON文件
    - 提供读取接口给仪表盘使用
    """

    def __init__(self, interval_minutes: int = 10, max_news_per_source: int = 0):
        """初始化

        Args:
            interval_minutes: 获取间隔（分钟）
            max_news_per_source: 每个数据源最大获取数量，0表示获取全部
        """
        self.interval = interval_minutes * 60  # 转换为秒
        self.max_news = max_news_per_source
        self.crawler = NewsCrawler()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._on_update: Optional[Callable] = None
        self._next_fetch_time: float = 0  # 下次获取的时间戳

        # 确保缓存目录存在
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # 初始化数据库
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.db = Database(str(DB_PATH))
        self.db.init_tables()

    def start(self):
        """启动后台服务"""
        if self._running:
            logger.warning("新闻服务已在运行")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"新闻后台服务已启动，每 {self.interval // 60} 分钟更新一次")

    def stop(self):
        """停止后台服务"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("新闻后台服务已停止")

    def _run_loop(self):
        """后台循环"""
        # 启动时立即获取一次
        self._fetch_and_cache()
        self._next_fetch_time = time.time() + self.interval

        while self._running:
            # 等待间隔时间
            for _ in range(self.interval):
                if not self._running:
                    break
                time.sleep(1)

            if self._running:
                self._fetch_and_cache()
                self._next_fetch_time = time.time() + self.interval

    def _fetch_and_cache(self):
        """获取新闻并缓存"""
        try:
            logger.info("开始获取财经新闻...")
            start_time = time.time()

            # 获取所有新闻
            all_news = self.crawler.fetch_all(max_count=self.max_news)

            # 计算统计信息
            by_source = {"cls": [], "eastmoney": [], "sina": []}
            for news in all_news:
                if news.source in by_source:
                    by_source[news.source].append(news)

            overall_sentiment = self.crawler.get_overall_sentiment(all_news)

            # 按情绪分组
            positive_news = [n for n in all_news if n.sentiment_score > 58]
            negative_news = [n for n in all_news if n.sentiment_score < 42]
            neutral_news = [n for n in all_news if 42 <= n.sentiment_score <= 58]

            # 提取关键词统计
            keyword_counts = {}
            for news in all_news:
                if news.keywords:
                    for kw in news.keywords.split(","):
                        kw = kw.strip()
                        if kw:
                            keyword_counts[kw] = keyword_counts.get(kw, 0) + 1

            sorted_keywords = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)[:20]

            # 构建缓存数据
            now = time.time()
            cache_data = {
                "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "fetch_timestamp": now,
                "next_fetch_timestamp": now + self.interval,
                "interval_seconds": self.interval,
                "total_count": len(all_news),
                "overall_sentiment": overall_sentiment,
                "positive_count": len(positive_news),
                "negative_count": len(negative_news),
                "neutral_count": len(neutral_news),
                "keyword_counts": sorted_keywords,
                "source_stats": {
                    "cls": {
                        "count": len(by_source["cls"]),
                        "avg_sentiment": sum(n.sentiment_score for n in by_source["cls"]) / len(by_source["cls"]) if by_source["cls"] else 50
                    },
                    "eastmoney": {
                        "count": len(by_source["eastmoney"]),
                        "avg_sentiment": sum(n.sentiment_score for n in by_source["eastmoney"]) / len(by_source["eastmoney"]) if by_source["eastmoney"] else 50
                    },
                    "sina": {
                        "count": len(by_source["sina"]),
                        "avg_sentiment": sum(n.sentiment_score for n in by_source["sina"]) / len(by_source["sina"]) if by_source["sina"] else 50
                    }
                },
                "news_list": [
                    {
                        "title": n.title,
                        "source": n.source,
                        "sentiment_score": n.sentiment_score,
                        "keywords": n.keywords,
                        "url": n.url,
                        "publish_time": n.publish_time,
                        "content": n.content
                    }
                    for n in all_news
                ]
            }

            # 写入缓存文件
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

            # 保存到数据库（自动去重）
            today = datetime.now().strftime("%Y-%m-%d")
            db_result = self.db.save_news_archive(cache_data["news_list"], fetch_date=today)

            elapsed = time.time() - start_time
            logger.info(
                f"新闻更新完成: {len(all_news)} 条新闻, 情绪 {overall_sentiment:.1f}, "
                f"入库 {db_result['inserted']} 条, 跳过 {db_result['skipped']} 条, 耗时 {elapsed:.1f}s"
            )

            # 触发回调
            if self._on_update:
                self._on_update(cache_data)

        except Exception as e:
            logger.error(f"获取新闻失败: {e}")

    def on_update(self, callback: Callable):
        """设置更新回调"""
        self._on_update = callback

    def fetch_now(self):
        """立即获取一次（同步）"""
        self._fetch_and_cache()
        self._next_fetch_time = time.time() + self.interval

    def get_next_fetch_time(self) -> float:
        """获取下次获取的时间戳

        Returns:
            下次获取的 Unix 时间戳，0 表示服务未运行
        """
        if not self._running or self._next_fetch_time == 0:
            return 0
        return self._next_fetch_time

    @staticmethod
    def get_cached_news() -> Optional[dict]:
        """读取缓存的新闻数据

        Returns:
            缓存的新闻数据，如果没有缓存返回None
        """
        if not CACHE_FILE.exists():
            return None

        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取新闻缓存失败: {e}")
            return None

    @staticmethod
    def is_cache_fresh(max_age_minutes: int = 15) -> bool:
        """检查缓存是否新鲜

        Args:
            max_age_minutes: 最大缓存时间（分钟）

        Returns:
            缓存是否在有效期内
        """
        cache = NewsService.get_cached_news()
        if not cache:
            return False

        fetch_time = cache.get("fetch_timestamp", 0)
        age = time.time() - fetch_time
        return age < max_age_minutes * 60

    def get_historical_news(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source: Optional[str] = None,
        min_sentiment: Optional[float] = None,
        max_sentiment: Optional[float] = None,
        limit: int = 100
    ) -> list:
        """查询历史新闻

        Args:
            start_date: 开始日期
            end_date: 结束日期
            source: 数据源
            min_sentiment: 最低情绪分数
            max_sentiment: 最高情绪分数
            limit: 最大返回数量

        Returns:
            新闻列表
        """
        return self.db.get_news_archive(
            start_date=start_date,
            end_date=end_date,
            source=source,
            min_sentiment=min_sentiment,
            max_sentiment=max_sentiment,
            limit=limit
        )

    def get_news_statistics(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> dict:
        """获取新闻统计信息

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            统计信息
        """
        return self.db.get_news_stats(start_date=start_date, end_date=end_date)

    def get_total_news_count(self) -> int:
        """获取数据库中新闻总数

        Returns:
            新闻总数
        """
        return self.db.get_news_count()


# 全局服务实例
_news_service: Optional[NewsService] = None


def get_news_service() -> NewsService:
    """获取全局新闻服务实例"""
    global _news_service
    if _news_service is None:
        _news_service = NewsService()
    return _news_service


def start_news_service():
    """启动新闻后台服务"""
    service = get_news_service()
    service.start()
    return service


def stop_news_service():
    """停止新闻后台服务"""
    global _news_service
    if _news_service:
        _news_service.stop()
        _news_service = None


if __name__ == "__main__":
    # 独立运行测试
    import signal

    print("启动新闻后台服务...")
    service = start_news_service()

    def signal_handler(sig, frame):
        print("\n正在停止服务...")
        stop_news_service()
        exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    print("服务已启动，按 Ctrl+C 停止")

    # 保持运行
    while True:
        time.sleep(1)
