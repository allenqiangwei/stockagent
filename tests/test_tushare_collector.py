import pytest
import pandas as pd
from unittest.mock import Mock, patch
from src.data_collector.tushare_collector import TuShareCollector


class TestTuShareCollector:
    @patch("src.data_collector.tushare_collector.ts")
    def test_fetch_stock_list(self, mock_ts):
        """测试获取股票列表"""
        mock_api = Mock()
        mock_ts.pro_api.return_value = mock_api
        mock_api.stock_basic.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ", "600000.SH"],
            "name": ["平安银行", "浦发银行"],
            "industry": ["银行", "银行"],
            "market": ["主板", "主板"],
            "list_date": ["19910403", "19991110"],
        })

        collector = TuShareCollector("test_token")
        df = collector.get_stock_list()

        assert len(df) == 2
        mock_api.stock_basic.assert_called_once()

    @patch("src.data_collector.tushare_collector.ts")
    def test_fetch_daily(self, mock_ts):
        """测试获取日线数据"""
        mock_api = Mock()
        mock_ts.pro_api.return_value = mock_api
        mock_api.daily.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "vol": [1000000.0],
            "amount": [10200000.0],
        })

        collector = TuShareCollector("test_token")
        df = collector.get_daily("000001.SZ", "20250101", "20250114")

        assert len(df) == 1
        assert df.iloc[0]["close"] == 10.2

    @patch("src.data_collector.tushare_collector.ts")
    def test_fetch_daily_all(self, mock_ts):
        """测试获取全市场日线数据"""
        mock_api = Mock()
        mock_ts.pro_api.return_value = mock_api
        mock_api.daily.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ", "600000.SH"],
            "trade_date": ["20250114", "20250114"],
            "open": [10.0, 8.0],
            "high": [10.5, 8.5],
            "low": [9.8, 7.9],
            "close": [10.2, 8.2],
            "vol": [1000000.0, 800000.0],
            "amount": [10200000.0, 6560000.0],
        })

        collector = TuShareCollector("test_token")
        df = collector.get_daily_all("20250114")

        assert len(df) == 2

    @patch("src.data_collector.tushare_collector.ts")
    def test_fetch_index_daily(self, mock_ts):
        """测试获取指数日线数据"""
        mock_api = Mock()
        mock_ts.pro_api.return_value = mock_api
        mock_api.index_daily.return_value = pd.DataFrame({
            "ts_code": ["000001.SH"],
            "trade_date": ["20250114"],
            "close": [3200.0],
            "pct_chg": [0.5],
        })

        collector = TuShareCollector("test_token")
        df = collector.get_index_daily("000001.SH", "20250101", "20250114")

        assert len(df) == 1
        assert df.iloc[0]["close"] == 3200.0

    @patch("src.data_collector.tushare_collector.ts")
    def test_fetch_money_flow(self, mock_ts):
        """测试获取资金流数据"""
        mock_api = Mock()
        mock_ts.pro_api.return_value = mock_api
        mock_api.moneyflow.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "buy_sm_vol": [100000.0],
            "sell_sm_vol": [80000.0],
            "net_mf_vol": [20000.0],
        })

        collector = TuShareCollector("test_token")
        df = collector.get_money_flow("20250114")

        assert len(df) == 1
