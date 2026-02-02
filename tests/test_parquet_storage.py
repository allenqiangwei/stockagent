import pytest
import pandas as pd
from datetime import date
from src.data_storage.parquet_storage import ParquetStorage


class TestParquetStorage:
    def test_save_and_load_daily_data(self, tmp_path):
        """测试保存和加载日线数据"""
        storage = ParquetStorage(str(tmp_path))

        df = pd.DataFrame({
            "ts_code": ["000001.SZ", "000001.SZ", "600000.SH"],
            "trade_date": ["20250113", "20250114", "20250114"],
            "open": [10.0, 10.5, 8.0],
            "high": [10.5, 11.0, 8.5],
            "low": [9.8, 10.2, 7.9],
            "close": [10.2, 10.8, 8.2],
            "vol": [1000000, 1200000, 800000],
            "amount": [10200000, 12960000, 6560000],
        })

        storage.save_daily("2025", df)

        loaded = storage.load_daily("2025")
        assert len(loaded) == 3
        assert loaded["ts_code"].tolist() == ["000001.SZ", "000001.SZ", "600000.SH"]

    def test_append_daily_data(self, tmp_path):
        """测试追加日线数据"""
        storage = ParquetStorage(str(tmp_path))

        # 先保存一批数据
        df1 = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250113"],
            "open": [10.0], "high": [10.5], "low": [9.8],
            "close": [10.2], "vol": [1000000], "amount": [10200000],
        })
        storage.save_daily("2025", df1)

        # 追加新数据
        df2 = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "open": [10.5], "high": [11.0], "low": [10.2],
            "close": [10.8], "vol": [1200000], "amount": [12960000],
        })
        storage.append_daily("2025", df2)

        loaded = storage.load_daily("2025")
        assert len(loaded) == 2

    def test_load_nonexistent_file_returns_empty(self, tmp_path):
        """测试加载不存在的文件返回空DataFrame"""
        storage = ParquetStorage(str(tmp_path))

        loaded = storage.load_daily("2020")
        assert len(loaded) == 0
        assert isinstance(loaded, pd.DataFrame)

    def test_load_daily_with_date_range(self, tmp_path):
        """测试按日期范围加载数据"""
        storage = ParquetStorage(str(tmp_path))

        df = pd.DataFrame({
            "ts_code": ["000001.SZ"] * 5,
            "trade_date": ["20250110", "20250113", "20250114", "20250115", "20250116"],
            "open": [10.0, 10.5, 10.8, 11.0, 10.5],
            "high": [10.5, 11.0, 11.2, 11.5, 11.0],
            "low": [9.8, 10.2, 10.5, 10.8, 10.2],
            "close": [10.2, 10.8, 11.0, 11.2, 10.6],
            "vol": [1000000] * 5,
            "amount": [10000000] * 5,
        })
        storage.save_daily("2025", df)

        loaded = storage.load_daily("2025", start_date="20250113", end_date="20250115")
        assert len(loaded) == 3
        assert loaded["trade_date"].min() == "20250113"
        assert loaded["trade_date"].max() == "20250115"

    def test_get_latest_trade_date(self, tmp_path):
        """测试获取最新交易日期"""
        storage = ParquetStorage(str(tmp_path))

        df = pd.DataFrame({
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": ["20250113", "20250114"],
            "open": [10.0, 10.5], "high": [10.5, 11.0], "low": [9.8, 10.2],
            "close": [10.2, 10.8], "vol": [1000000, 1200000], "amount": [10200000, 12960000],
        })
        storage.save_daily("2025", df)

        latest = storage.get_latest_trade_date("daily")
        assert latest == "20250114"

    def test_save_and_load_index_data(self, tmp_path):
        """测试保存和加载指数数据"""
        storage = ParquetStorage(str(tmp_path))

        df = pd.DataFrame({
            "ts_code": ["000001.SH", "399001.SZ"],
            "trade_date": ["20250114", "20250114"],
            "close": [3200.0, 10500.0],
            "pct_chg": [0.5, 0.8],
        })

        storage.save_index("2025", df)
        loaded = storage.load_index("2025")

        assert len(loaded) == 2
