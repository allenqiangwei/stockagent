"""SQLite数据库管理模块"""
import sqlite3
from typing import Optional, List, Dict, Any
from contextlib import contextmanager


class Database:
    """SQLite数据库管理器

    管理股票列表、数据更新日志、新闻情绪等业务数据。
    """

    def __init__(self, db_path: str):
        """初始化数据库连接

        Args:
            db_path: SQLite数据库文件路径
        """
        self.db_path = db_path

    @contextmanager
    def _get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_tables(self) -> None:
        """初始化所有数据表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 股票列表表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_list (
                    ts_code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    industry TEXT,
                    market TEXT,
                    list_date TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 数据更新日志表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS data_update_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_type TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    record_count INTEGER,
                    status TEXT,
                    error_msg TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 新闻情绪表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news_sentiment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT,
                    sentiment_score REAL,
                    keywords TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 为常用查询创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_update_log_type_date
                ON data_update_log(data_type, trade_date DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_date
                ON news_sentiment(trade_date DESC)
            """)

    def upsert_stock_list(self, stocks: List[Dict[str, Any]]) -> None:
        """更新或插入股票列表

        Args:
            stocks: 股票信息列表，每个元素包含ts_code, name, industry等
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO stock_list
                (ts_code, name, industry, market, list_date, updated_at)
                VALUES (
                    :ts_code, :name, :industry,
                    :market, :list_date, CURRENT_TIMESTAMP
                )
            """, [
                {
                    "ts_code": s.get("ts_code"),
                    "name": s.get("name"),
                    "industry": s.get("industry"),
                    "market": s.get("market"),
                    "list_date": s.get("list_date"),
                }
                for s in stocks
            ])

    def get_stock_list(self) -> List[Dict[str, Any]]:
        """获取所有股票列表

        Returns:
            股票信息列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM stock_list ORDER BY ts_code")
            return [dict(row) for row in cursor.fetchall()]

    def log_update(
        self,
        data_type: str,
        trade_date: str,
        record_count: int,
        status: str,
        error_msg: Optional[str] = None
    ) -> None:
        """记录数据更新日志

        Args:
            data_type: 数据类型 (daily, index, money_flow, news)
            trade_date: 交易日期
            record_count: 记录数量
            status: 状态 (success, failed)
            error_msg: 错误信息
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO data_update_log
                (data_type, trade_date, record_count, status, error_msg)
                VALUES (?, ?, ?, ?, ?)
            """, (data_type, trade_date, record_count, status, error_msg))

    def get_latest_update(self, data_type: str) -> Optional[Dict[str, Any]]:
        """获取指定数据类型的最新更新记录

        Args:
            data_type: 数据类型

        Returns:
            最新更新记录或None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM data_update_log
                WHERE data_type = ?
                ORDER BY trade_date DESC, created_at DESC
                LIMIT 1
            """, (data_type,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def save_news_sentiment(self, news_list: List[Dict[str, Any]]) -> None:
        """保存新闻情绪数据

        Args:
            news_list: 新闻列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO news_sentiment
                (trade_date, title, source, sentiment_score, keywords)
                VALUES (:trade_date, :title, :source, :sentiment_score, :keywords)
            """, news_list)

    def get_news_by_date(self, trade_date: str) -> List[Dict[str, Any]]:
        """获取指定日期的新闻

        Args:
            trade_date: 交易日期

        Returns:
            新闻列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM news_sentiment
                WHERE trade_date = ?
                ORDER BY created_at DESC
            """, (trade_date,))
            return [dict(row) for row in cursor.fetchall()]
