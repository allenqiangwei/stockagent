import pytest
import pandas as pd
from unittest.mock import Mock, patch
from src.data_collector.collector_manager import CollectorManager
from src.data_collector.base_collector import CollectorError


class TestCollectorManager:
    def test_use_primary_source_when_available(self):
        """测试优先使用主数据源"""
        mock_primary = Mock()
        mock_fallback = Mock()

        mock_primary.get_stock_list.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "name": ["平安银行"],
        })

        manager = CollectorManager(
            primary=mock_primary,
            fallbacks=[mock_fallback],
        )

        df = manager.get_stock_list()

        assert len(df) == 1
        mock_primary.get_stock_list.assert_called_once()
        mock_fallback.get_stock_list.assert_not_called()

    def test_fallback_when_primary_fails(self):
        """测试主数据源失败时切换到备用源"""
        mock_primary = Mock()
        mock_fallback = Mock()

        mock_primary.get_stock_list.side_effect = CollectorError("API Error")
        mock_fallback.get_stock_list.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "name": ["平安银行"],
        })

        manager = CollectorManager(
            primary=mock_primary,
            fallbacks=[mock_fallback],
        )

        df = manager.get_stock_list()

        assert len(df) == 1
        mock_primary.get_stock_list.assert_called_once()
        mock_fallback.get_stock_list.assert_called_once()

    def test_all_sources_fail_raises_error(self):
        """测试所有数据源都失败时抛出异常"""
        mock_primary = Mock()
        mock_fallback = Mock()

        mock_primary.get_stock_list.side_effect = CollectorError("Primary Error")
        mock_fallback.get_stock_list.side_effect = CollectorError("Fallback Error")

        manager = CollectorManager(
            primary=mock_primary,
            fallbacks=[mock_fallback],
        )

        with pytest.raises(CollectorError):
            manager.get_stock_list()

    def test_get_daily_with_fallback(self):
        """测试获取日线数据的容灾切换"""
        mock_primary = Mock()
        mock_fallback = Mock()

        mock_primary.get_daily_all.side_effect = CollectorError("Rate limit")
        mock_fallback.get_daily_all.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "close": [10.2],
        })

        manager = CollectorManager(
            primary=mock_primary,
            fallbacks=[mock_fallback],
        )

        df = manager.get_daily_all("20250114")

        assert len(df) == 1
