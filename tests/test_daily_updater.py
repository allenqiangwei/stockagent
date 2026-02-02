import pytest
import pandas as pd
from unittest.mock import Mock, patch
from datetime import date
from src.data_pipeline.daily_updater import DailyUpdater


class TestDailyUpdater:
    def test_update_daily_data(self, tmp_path):
        """测试更新日线数据"""
        # Mock依赖
        mock_collector = Mock()
        mock_storage = Mock()
        mock_db = Mock()

        mock_collector.get_daily_all.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ", "600000.SH"],
            "trade_date": ["20250114", "20250114"],
            "open": [10.0, 8.0],
            "high": [10.5, 8.5],
            "low": [9.8, 7.9],
            "close": [10.2, 8.2],
            "vol": [1000000, 800000],
            "amount": [10200000, 6560000],
        })

        mock_db.get_latest_update.return_value = {
            "trade_date": "20250113",
        }

        updater = DailyUpdater(
            collector=mock_collector,
            storage=mock_storage,
            database=mock_db,
        )

        result = updater.update_daily("20250114")

        assert result["success"] is True
        assert result["record_count"] == 2
        mock_storage.append_daily.assert_called_once()
        mock_db.log_update.assert_called_once()

    def test_skip_if_already_updated(self, tmp_path):
        """测试跳过已更新的日期"""
        mock_collector = Mock()
        mock_storage = Mock()
        mock_db = Mock()

        mock_db.get_latest_update.return_value = {
            "trade_date": "20250114",
            "status": "success",
        }

        updater = DailyUpdater(
            collector=mock_collector,
            storage=mock_storage,
            database=mock_db,
        )

        result = updater.update_daily("20250114")

        assert result["skipped"] is True
        mock_collector.get_daily_all.assert_not_called()

    def test_update_index_data(self):
        """测试更新指数数据"""
        mock_collector = Mock()
        mock_storage = Mock()
        mock_db = Mock()

        mock_collector.get_index_daily.return_value = pd.DataFrame({
            "ts_code": ["000001.SH"],
            "trade_date": ["20250114"],
            "close": [3200.0],
        })

        mock_db.get_latest_update.return_value = None

        updater = DailyUpdater(
            collector=mock_collector,
            storage=mock_storage,
            database=mock_db,
        )

        result = updater.update_index("20250114")

        assert result["success"] is True

    def test_full_daily_update(self):
        """测试完整的每日更新流程"""
        mock_collector = Mock()
        mock_storage = Mock()
        mock_db = Mock()
        mock_news_crawler = Mock()

        mock_collector.get_daily_all.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "close": [10.2],
        })
        mock_collector.get_index_daily.return_value = pd.DataFrame({
            "ts_code": ["000001.SH"],
            "trade_date": ["20250114"],
            "close": [3200.0],
        })
        mock_collector.get_money_flow.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "net_mf_vol": [20000.0],
        })

        mock_news_crawler.crawl_all.return_value = []

        mock_db.get_latest_update.return_value = None

        updater = DailyUpdater(
            collector=mock_collector,
            storage=mock_storage,
            database=mock_db,
            news_crawler=mock_news_crawler,
        )

        results = updater.run_full_update("20250114")

        assert "daily" in results
        assert "index" in results
        assert "money_flow" in results
