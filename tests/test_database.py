import pytest
import sqlite3
from src.data_storage.database import Database


class TestDatabase:
    def test_create_tables(self, tmp_path):
        """测试创建数据表"""
        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        db.init_tables()

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        assert "stock_list" in tables
        assert "data_update_log" in tables
        assert "news_sentiment" in tables

        conn.close()

    def test_insert_and_query_stock_list(self, tmp_path):
        """测试股票列表的增删改查"""
        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        db.init_tables()

        # 插入
        stocks = [
            {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行"},
            {"ts_code": "600000.SH", "name": "浦发银行", "industry": "银行"},
        ]
        db.upsert_stock_list(stocks)

        # 查询
        result = db.get_stock_list()
        assert len(result) == 2
        assert result[0]["ts_code"] == "000001.SZ"

    def test_log_data_update(self, tmp_path):
        """测试数据更新日志"""
        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        db.init_tables()

        db.log_update("daily", "2025-01-15", 3000, "success")

        log = db.get_latest_update("daily")
        assert log["trade_date"] == "2025-01-15"
        assert log["record_count"] == 3000
        assert log["status"] == "success"

    def test_get_latest_update_returns_none_if_empty(self, tmp_path):
        """测试空表返回None"""
        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        db.init_tables()

        result = db.get_latest_update("daily")
        assert result is None
