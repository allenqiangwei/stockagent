import pytest
import pandas as pd
from src.data_collector.base_collector import BaseCollector, CollectorError


class MockCollector(BaseCollector):
    """测试用的Mock采集器"""

    def __init__(self):
        super().__init__()
        self._stock_list = pd.DataFrame({
            "ts_code": ["000001.SZ", "600000.SH"],
            "name": ["平安银行", "浦发银行"],
        })
        self._daily_data = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "open": [10.0], "high": [10.5], "low": [9.8], "close": [10.2],
            "vol": [1000000], "amount": [10200000],
        })

    def _fetch_stock_list(self) -> pd.DataFrame:
        return self._stock_list

    def _fetch_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._daily_data[self._daily_data["ts_code"] == ts_code]

    def _fetch_index_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()

    def _fetch_money_flow(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame()


class TestBaseCollector:
    def test_get_stock_list(self):
        """测试获取股票列表"""
        collector = MockCollector()
        df = collector.get_stock_list()

        assert len(df) == 2
        assert "ts_code" in df.columns
        assert "name" in df.columns

    def test_get_daily_data(self):
        """测试获取日线数据"""
        collector = MockCollector()
        df = collector.get_daily("000001.SZ", "20250101", "20250114")

        assert len(df) == 1
        assert df.iloc[0]["ts_code"] == "000001.SZ"

    def test_retry_on_failure(self):
        """测试失败重试机制"""
        class FailingCollector(MockCollector):
            def __init__(self):
                super().__init__()
                self.attempts = 0

            def _fetch_stock_list(self) -> pd.DataFrame:
                self.attempts += 1
                if self.attempts < 3:
                    raise Exception("API Error")
                return self._stock_list

        collector = FailingCollector()
        df = collector.get_stock_list()

        assert collector.attempts == 3
        assert len(df) == 2

    def test_max_retries_exceeded_raises_error(self):
        """测试超过最大重试次数抛出异常"""
        class AlwaysFailCollector(MockCollector):
            def _fetch_stock_list(self) -> pd.DataFrame:
                raise Exception("API Error")

        collector = AlwaysFailCollector()
        collector.max_retries = 2

        with pytest.raises(CollectorError):
            collector.get_stock_list()
