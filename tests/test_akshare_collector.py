import pytest
import pandas as pd
from unittest.mock import patch
from src.data_collector.akshare_collector import AkShareCollector


class TestAkShareCollector:
    @patch("src.data_collector.akshare_collector.ak")
    def test_fetch_stock_list(self, mock_ak):
        """测试获取股票列表"""
        mock_ak.stock_info_a_code_name.return_value = pd.DataFrame({
            "code": ["000001", "600000"],
            "name": ["平安银行", "浦发银行"],
        })

        collector = AkShareCollector()
        df = collector.get_stock_list()

        assert len(df) == 2
        assert "ts_code" in df.columns  # 统一转换为ts_code格式

    @patch("src.data_collector.akshare_collector.ak")
    def test_fetch_daily(self, mock_ak):
        """测试获取日线数据"""
        mock_ak.stock_zh_a_hist.return_value = pd.DataFrame({
            "日期": ["2025-01-14"],
            "开盘": [10.0],
            "收盘": [10.2],
            "最高": [10.5],
            "最低": [9.8],
            "成交量": [1000000],
            "成交额": [10200000.0],
        })

        collector = AkShareCollector()
        df = collector.get_daily("000001.SZ", "20250101", "20250114")

        assert len(df) == 1
        # 验证字段名已转换为统一格式
        assert "close" in df.columns
        assert "trade_date" in df.columns

    @patch("src.data_collector.akshare_collector.ak")
    def test_fetch_index_daily(self, mock_ak):
        """测试获取指数日线数据"""
        mock_ak.stock_zh_index_daily.return_value = pd.DataFrame({
            "date": ["2025-01-14"],
            "open": [3180.0],
            "high": [3220.0],
            "low": [3170.0],
            "close": [3200.0],
            "volume": [300000000000.0],
        })

        collector = AkShareCollector()
        df = collector.get_index_daily("000001.SH", "20250101", "20250114")

        assert len(df) == 1
        assert df.iloc[0]["close"] == 3200.0
