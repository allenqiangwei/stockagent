"""每日数据更新Pipeline"""
from typing import Dict, Any, Optional, List
from datetime import date, datetime, timedelta
import pandas as pd

from src.data_collector.collector_manager import CollectorManager
from src.data_storage.parquet_storage import ParquetStorage
from src.data_storage.database import Database
from src.data_collector.news_crawler import NewsCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)


# 主要指数代码
MAJOR_INDICES = [
    "000001.SH",  # 上证指数
    "399001.SZ",  # 深证成指
    "399006.SZ",  # 创业板指
    "000016.SH",  # 上证50
    "000300.SH",  # 沪深300
]


class DailyUpdater:
    """每日数据更新器

    负责协调数据采集、存储和日志记录。
    """

    def __init__(
        self,
        collector: CollectorManager,
        storage: ParquetStorage,
        database: Database,
        news_crawler: Optional[NewsCrawler] = None,
    ):
        """初始化更新器

        Args:
            collector: 数据采集管理器
            storage: Parquet存储管理器
            database: SQLite数据库
            news_crawler: 新闻爬虫（可选）
        """
        self.collector = collector
        self.storage = storage
        self.database = database
        self.news_crawler = news_crawler or NewsCrawler()

    def _is_already_updated(self, data_type: str, trade_date: str) -> bool:
        """检查数据是否已更新

        Args:
            data_type: 数据类型
            trade_date: 交易日期

        Returns:
            是否已更新
        """
        latest = self.database.get_latest_update(data_type)
        if latest and latest["trade_date"] >= trade_date and latest["status"] == "success":
            return True
        return False

    def update_daily(self, trade_date: str, force: bool = False) -> Dict[str, Any]:
        """更新日线数据

        Args:
            trade_date: 交易日期 (YYYYMMDD)
            force: 强制更新（忽略已更新检查）

        Returns:
            更新结果
        """
        if not force and self._is_already_updated("daily", trade_date):
            logger.info(f"日线数据 {trade_date} 已更新，跳过")
            return {"skipped": True, "trade_date": trade_date}

        logger.info(f"开始更新日线数据: {trade_date}")

        try:
            # 获取全市场日线数据
            df = self.collector.get_daily_all(trade_date)

            if df.empty:
                logger.warning(f"未获取到 {trade_date} 的日线数据")
                return {"success": False, "error": "No data", "trade_date": trade_date}

            # 保存到Parquet
            year = trade_date[:4]
            self.storage.append_daily(year, df)

            # 记录日志
            self.database.log_update(
                data_type="daily",
                trade_date=trade_date,
                record_count=len(df),
                status="success",
            )

            logger.info(f"日线数据更新完成: {len(df)} 条记录")
            return {
                "success": True,
                "trade_date": trade_date,
                "record_count": len(df),
            }

        except Exception as e:
            logger.error(f"日线数据更新失败: {e}")
            self.database.log_update(
                data_type="daily",
                trade_date=trade_date,
                record_count=0,
                status="failed",
                error_msg=str(e),
            )
            return {"success": False, "error": str(e), "trade_date": trade_date}

    def update_index(self, trade_date: str, force: bool = False) -> Dict[str, Any]:
        """更新指数数据

        Args:
            trade_date: 交易日期
            force: 强制更新

        Returns:
            更新结果
        """
        if not force and self._is_already_updated("index", trade_date):
            logger.info(f"指数数据 {trade_date} 已更新，跳过")
            return {"skipped": True, "trade_date": trade_date}

        logger.info(f"开始更新指数数据: {trade_date}")

        try:
            all_data = []

            for index_code in MAJOR_INDICES:
                df = self.collector.get_index_daily(
                    index_code,
                    start_date=trade_date,
                    end_date=trade_date
                )
                if not df.empty:
                    all_data.append(df)

            if not all_data:
                logger.warning(f"未获取到 {trade_date} 的指数数据")
                return {"success": False, "error": "No data", "trade_date": trade_date}

            combined = pd.concat(all_data, ignore_index=True)

            year = trade_date[:4]
            self.storage.append_index(year, combined)

            self.database.log_update(
                data_type="index",
                trade_date=trade_date,
                record_count=len(combined),
                status="success",
            )

            logger.info(f"指数数据更新完成: {len(combined)} 条记录")
            return {
                "success": True,
                "trade_date": trade_date,
                "record_count": len(combined),
            }

        except Exception as e:
            logger.error(f"指数数据更新失败: {e}")
            self.database.log_update(
                data_type="index",
                trade_date=trade_date,
                record_count=0,
                status="failed",
                error_msg=str(e),
            )
            return {"success": False, "error": str(e), "trade_date": trade_date}

    def update_money_flow(self, trade_date: str, force: bool = False) -> Dict[str, Any]:
        """更新资金流数据

        Args:
            trade_date: 交易日期
            force: 强制更新

        Returns:
            更新结果
        """
        if not force and self._is_already_updated("money_flow", trade_date):
            logger.info(f"资金流数据 {trade_date} 已更新，跳过")
            return {"skipped": True, "trade_date": trade_date}

        logger.info(f"开始更新资金流数据: {trade_date}")

        try:
            df = self.collector.get_money_flow(trade_date)

            if df.empty:
                logger.warning(f"未获取到 {trade_date} 的资金流数据")
                return {"success": False, "error": "No data", "trade_date": trade_date}

            year = trade_date[:4]
            self.storage.append_money_flow(year, df)

            self.database.log_update(
                data_type="money_flow",
                trade_date=trade_date,
                record_count=len(df),
                status="success",
            )

            logger.info(f"资金流数据更新完成: {len(df)} 条记录")
            return {
                "success": True,
                "trade_date": trade_date,
                "record_count": len(df),
            }

        except Exception as e:
            logger.error(f"资金流数据更新失败: {e}")
            self.database.log_update(
                data_type="money_flow",
                trade_date=trade_date,
                record_count=0,
                status="failed",
                error_msg=str(e),
            )
            return {"success": False, "error": str(e), "trade_date": trade_date}

    def update_news(self, trade_date: str) -> Dict[str, Any]:
        """更新新闻数据

        Args:
            trade_date: 交易日期

        Returns:
            更新结果
        """
        logger.info(f"开始爬取新闻: {trade_date}")

        try:
            news_list = self.news_crawler.crawl_all(max_count=20)

            if not news_list:
                logger.warning("未爬取到新闻")
                return {"success": False, "error": "No news", "trade_date": trade_date}

            # 保存到数据库
            news_data = [
                {
                    "trade_date": trade_date,
                    "title": n.title,
                    "source": n.source,
                    "sentiment_score": n.sentiment_score,
                    "keywords": n.keywords,
                }
                for n in news_list
            ]
            self.database.save_news_sentiment(news_data)

            # 计算整体情绪
            overall_sentiment = self.news_crawler.get_overall_sentiment(news_list)

            logger.info(f"新闻更新完成: {len(news_list)} 条, 整体情绪: {overall_sentiment:.1f}")
            return {
                "success": True,
                "trade_date": trade_date,
                "news_count": len(news_list),
                "overall_sentiment": overall_sentiment,
            }

        except Exception as e:
            logger.error(f"新闻更新失败: {e}")
            return {"success": False, "error": str(e), "trade_date": trade_date}

    def run_full_update(self, trade_date: str, force: bool = False) -> Dict[str, Any]:
        """运行完整的每日更新

        Args:
            trade_date: 交易日期
            force: 强制更新

        Returns:
            所有更新的结果
        """
        logger.info(f"========== 开始每日全量更新: {trade_date} ==========")

        results = {}

        # 1. 更新日线数据
        results["daily"] = self.update_daily(trade_date, force)

        # 2. 更新指数数据
        results["index"] = self.update_index(trade_date, force)

        # 3. 更新资金流数据
        results["money_flow"] = self.update_money_flow(trade_date, force)

        # 4. 更新新闻
        results["news"] = self.update_news(trade_date)

        # 统计结果
        success_count = sum(
            1 for r in results.values()
            if r.get("success") or r.get("skipped")
        )

        logger.info(f"========== 更新完成: {success_count}/4 成功 ==========")

        return results

    def update_stock_list(self) -> Dict[str, Any]:
        """更新股票列表

        Returns:
            更新结果
        """
        logger.info("开始更新股票列表...")

        try:
            df = self.collector.get_stock_list()

            if df.empty:
                return {"success": False, "error": "No data"}

            stocks = df.to_dict("records")
            self.database.upsert_stock_list(stocks)

            logger.info(f"股票列表更新完成: {len(stocks)} 只")
            return {"success": True, "stock_count": len(stocks)}

        except Exception as e:
            logger.error(f"股票列表更新失败: {e}")
            return {"success": False, "error": str(e)}
