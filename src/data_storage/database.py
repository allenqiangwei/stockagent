"""SQLite数据库管理模块"""
import hashlib
import json
import sqlite3
from datetime import datetime
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

            # 新闻情绪表（旧表，保留兼容）
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

            # 新闻存档表（完整字段，支持去重）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news_archive (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title_hash TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    sentiment_score REAL,
                    keywords TEXT,
                    url TEXT,
                    publish_time TEXT,
                    content TEXT,
                    fetch_date TEXT NOT NULL,
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
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_archive_date
                ON news_archive(fetch_date DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_archive_source
                ON news_archive(source, fetch_date DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_archive_sentiment
                ON news_archive(sentiment_score)
            """)

            # Add sentiment_analyzed column if missing (migration)
            try:
                cursor.execute("""
                    ALTER TABLE news_archive ADD COLUMN sentiment_analyzed INTEGER DEFAULT 0
                """)
            except Exception:
                pass  # Column already exists

            # 交易信号表（永久存储，支持历史回测）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trading_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    final_score REAL NOT NULL,
                    signal_level INTEGER NOT NULL,
                    signal_level_name TEXT NOT NULL,
                    swing_score REAL,
                    trend_score REAL,
                    ml_score REAL,
                    sentiment_score REAL,
                    market_regime TEXT,
                    swing_weight REAL,
                    trend_weight REAL,
                    reasons TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, trade_date)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_date
                ON trading_signals(trade_date DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_stock
                ON trading_signals(stock_code, trade_date DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_level
                ON trading_signals(signal_level, trade_date DESC)
            """)

            # 股票日线数据表（缓存历史行情，避免重复 API 调用）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_daily (
                    stock_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    amount REAL,
                    PRIMARY KEY (stock_code, trade_date)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_daily_code_date
                ON stock_daily(stock_code, trade_date DESC)
            """)

            # 指标配置表（管理所有可用的技术指标实例）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS indicator_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    indicator_type TEXT NOT NULL,
                    name TEXT NOT NULL UNIQUE,
                    params TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 信号策略表（规则驱动的策略）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signal_strategy (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT DEFAULT '',
                    rules TEXT NOT NULL DEFAULT '[]',
                    weight REAL NOT NULL DEFAULT 0.5,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    buy_conditions TEXT NOT NULL DEFAULT '[]',
                    sell_conditions TEXT NOT NULL DEFAULT '[]',
                    exit_config TEXT NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 迁移：如果旧表有 indicators 列但无 rules 列，重建表
            cursor.execute("PRAGMA table_info(signal_strategy)")
            columns = {row[1] for row in cursor.fetchall()}
            if "indicators" in columns and "rules" not in columns:
                cursor.execute("DROP TABLE signal_strategy")
                cursor.execute("""
                    CREATE TABLE signal_strategy (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        description TEXT DEFAULT '',
                        rules TEXT NOT NULL DEFAULT '[]',
                        weight REAL NOT NULL DEFAULT 0.5,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        buy_conditions TEXT NOT NULL DEFAULT '[]',
                        sell_conditions TEXT NOT NULL DEFAULT '[]',
                        exit_config TEXT NOT NULL DEFAULT '{}',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # 刷新列信息（重建后列集合已变）
                cursor.execute("PRAGMA table_info(signal_strategy)")
                columns = {row[1] for row in cursor.fetchall()}

            # 迁移：给 signal_strategy 增加 buy/sell/exit 列
            if "buy_conditions" not in columns and "rules" in columns:
                for col, default in [
                    ("buy_conditions", "'[]'"),
                    ("sell_conditions", "'[]'"),
                    ("exit_config", "'{}'"),
                ]:
                    try:
                        cursor.execute(
                            f"ALTER TABLE signal_strategy ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}"
                        )
                    except sqlite3.OperationalError:
                        pass  # 列已存在

            # 动作信号表（回测系统的精确买卖指令）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS action_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    action TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    confidence_score REAL,
                    sell_reason TEXT,
                    trigger_rules TEXT,
                    stop_loss_pct REAL,
                    take_profit_pct REAL,
                    max_hold_days INTEGER,
                    reasons TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, trade_date, action, strategy_name)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_action_signals_date
                ON action_signals(trade_date DESC, action)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_action_signals_stock
                ON action_signals(stock_code, trade_date DESC)
            """)

            # 回测运行记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id INTEGER NOT NULL,
                    strategy_name TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    capital_per_trade REAL DEFAULT 10000,
                    total_trades INTEGER,
                    win_rate REAL,
                    total_return_pct REAL,
                    max_drawdown_pct REAL,
                    avg_hold_days REAL,
                    result_json TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (strategy_id) REFERENCES signal_strategy(id)
                )
            """)

            # 回测交易明细表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS backtest_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    stock_code TEXT NOT NULL,
                    strategy_name TEXT,
                    buy_date TEXT,
                    buy_price REAL,
                    sell_date TEXT,
                    sell_price REAL,
                    sell_reason TEXT,
                    pnl_pct REAL,
                    hold_days INTEGER,
                    FOREIGN KEY (run_id) REFERENCES backtest_runs(id)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_backtest_trades_run
                ON backtest_trades(run_id)
            """)

    def save_daily_data(self, stock_code: str, rows: list) -> int:
        """批量保存日线数据

        Args:
            stock_code: 股票代码 (6位)
            rows: [(trade_date, open, high, low, close, volume, amount), ...]
                  trade_date 为 YYYY-MM-DD 字符串

        Returns:
            保存的行数
        """
        if not rows:
            return 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO stock_daily
                (stock_code, trade_date, open, high, low, close, volume, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [(stock_code, *row) for row in rows])
            return len(rows)

    def load_daily_data(self, stock_code: str, start_date: str, end_date: str):
        """从数据库加载日线数据

        Args:
            stock_code: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)

        Returns:
            list of tuples: [(trade_date, open, high, low, close, volume, amount), ...]
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT trade_date, open, high, low, close, volume, amount
                FROM stock_daily
                WHERE stock_code = ? AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date ASC
            """, (stock_code, start_date, end_date))
            return cursor.fetchall()

    def get_latest_trade_date(self, stock_code: str) -> Optional[str]:
        """获取某只股票在数据库中最新的交易日期

        Returns:
            YYYY-MM-DD 字符串，或 None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT MAX(trade_date) FROM stock_daily WHERE stock_code = ?
            """, (stock_code,))
            row = cursor.fetchone()
            return row[0] if row and row[0] else None

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

    @staticmethod
    def _compute_title_hash(title: str) -> str:
        """计算标题哈希用于去重

        Args:
            title: 新闻标题

        Returns:
            标题的MD5哈希值
        """
        # 移除空格和标点，统一小写，再计算哈希
        normalized = title.strip().lower()
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()

    def save_news_archive(
        self,
        news_list: List[Dict[str, Any]],
        fetch_date: Optional[str] = None
    ) -> Dict[str, int]:
        """保存新闻到存档表（自动去重）

        Args:
            news_list: 新闻列表，每个元素包含 title, source, sentiment_score 等
            fetch_date: 获取日期，默认为今天

        Returns:
            包含 inserted（新增）和 skipped（跳过/重复）数量的字典
        """
        if fetch_date is None:
            fetch_date = datetime.now().strftime("%Y-%m-%d")

        inserted = 0
        skipped = 0

        with self._get_connection() as conn:
            cursor = conn.cursor()

            for news in news_list:
                title = news.get("title", "")
                if not title:
                    skipped += 1
                    continue

                title_hash = self._compute_title_hash(title)

                try:
                    cursor.execute("""
                        INSERT INTO news_archive
                        (title_hash, title, source, sentiment_score, keywords,
                         url, publish_time, content, fetch_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        title_hash,
                        title,
                        news.get("source", ""),
                        news.get("sentiment_score", 50.0),
                        news.get("keywords", ""),
                        news.get("url", ""),
                        news.get("publish_time", ""),
                        news.get("content", ""),
                        fetch_date
                    ))
                    inserted += 1
                except sqlite3.IntegrityError:
                    # 标题哈希重复，跳过
                    skipped += 1

        return {"inserted": inserted, "skipped": skipped}

    def get_news_archive(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source: Optional[str] = None,
        min_sentiment: Optional[float] = None,
        max_sentiment: Optional[float] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """查询新闻存档

        Args:
            start_date: 开始日期（含）
            end_date: 结束日期（含）
            source: 数据源过滤
            min_sentiment: 最低情绪分数
            max_sentiment: 最高情绪分数
            limit: 最大返回数量

        Returns:
            新闻列表
        """
        conditions = []
        params = []

        if start_date:
            conditions.append("fetch_date >= ?")
            params.append(start_date)

        if end_date:
            conditions.append("fetch_date <= ?")
            params.append(end_date)

        if source:
            conditions.append("source = ?")
            params.append(source)

        if min_sentiment is not None:
            conditions.append("sentiment_score >= ?")
            params.append(min_sentiment)

        if max_sentiment is not None:
            conditions.append("sentiment_score <= ?")
            params.append(max_sentiment)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT * FROM news_archive
                WHERE {where_clause}
                ORDER BY fetch_date DESC, created_at DESC
                LIMIT ?
            """, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_news_stats(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取新闻统计信息

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            统计信息字典
        """
        conditions = []
        params = []

        if start_date:
            conditions.append("fetch_date >= ?")
            params.append(start_date)

        if end_date:
            conditions.append("fetch_date <= ?")
            params.append(end_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 总数和平均情绪
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total,
                    AVG(sentiment_score) as avg_sentiment,
                    MIN(sentiment_score) as min_sentiment,
                    MAX(sentiment_score) as max_sentiment
                FROM news_archive
                WHERE {where_clause}
            """, params)
            row = cursor.fetchone()
            stats = dict(row) if row else {}

            # 按来源统计
            cursor.execute(f"""
                SELECT source, COUNT(*) as count, AVG(sentiment_score) as avg_sentiment
                FROM news_archive
                WHERE {where_clause}
                GROUP BY source
            """, params)
            stats["by_source"] = [dict(r) for r in cursor.fetchall()]

            # 按日期统计
            cursor.execute(f"""
                SELECT fetch_date, COUNT(*) as count, AVG(sentiment_score) as avg_sentiment
                FROM news_archive
                WHERE {where_clause}
                GROUP BY fetch_date
                ORDER BY fetch_date DESC
                LIMIT 30
            """, params)
            stats["by_date"] = [dict(r) for r in cursor.fetchall()]

            # 情绪分布
            cursor.execute(f"""
                SELECT
                    SUM(CASE WHEN sentiment_score > 58 THEN 1 ELSE 0 END) as positive,
                    SUM(CASE WHEN sentiment_score < 42 THEN 1 ELSE 0 END) as negative,
                    SUM(CASE WHEN sentiment_score BETWEEN 42 AND 58 THEN 1 ELSE 0 END) as neutral
                FROM news_archive
                WHERE {where_clause}
            """, params)
            sentiment_row = cursor.fetchone()
            if sentiment_row:
                stats["sentiment_distribution"] = dict(sentiment_row)

            return stats

    def get_news_count(self) -> int:
        """获取新闻存档总数

        Returns:
            新闻总数
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM news_archive")
            return cursor.fetchone()[0]

    # ── 交易信号 CRUD ──────────────────────────────────────────

    def save_signals(
        self,
        signals: List[Dict[str, Any]],
        trade_date: str
    ) -> Dict[str, int]:
        """批量保存交易信号（INSERT OR REPLACE 去重）

        Args:
            signals: 信号列表，每个元素包含 stock_code, final_score 等
            trade_date: 交易日期

        Returns:
            包含 saved 数量的字典
        """
        saved = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for sig in signals:
                try:
                    reasons = sig.get("reasons", [])
                    if isinstance(reasons, list):
                        import json
                        reasons = json.dumps(reasons, ensure_ascii=False)

                    cursor.execute("""
                        INSERT OR REPLACE INTO trading_signals
                        (stock_code, trade_date, final_score, signal_level,
                         signal_level_name, swing_score, trend_score,
                         ml_score, sentiment_score, market_regime,
                         swing_weight, trend_weight, reasons)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        sig["stock_code"],
                        trade_date,
                        sig["final_score"],
                        sig["signal_level"],
                        sig.get("signal_level_name", ""),
                        sig.get("swing_score"),
                        sig.get("trend_score"),
                        sig.get("ml_score"),
                        sig.get("sentiment_score"),
                        sig.get("market_regime"),
                        sig.get("swing_weight"),
                        sig.get("trend_weight"),
                        reasons
                    ))
                    saved += 1
                except Exception:
                    pass
        return {"saved": saved}

    def get_signals_by_date(
        self,
        trade_date: str,
        signal_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """查询某天的信号

        Args:
            trade_date: 交易日期
            signal_type: 信号类型过滤 ("buy"=level>=4, "sell"=level<=2)
            limit: 最大返回数量

        Returns:
            信号列表
        """
        conditions = ["trade_date = ?"]
        params: list = [trade_date]

        if signal_type == "buy":
            conditions.append("signal_level >= 4")
        elif signal_type == "sell":
            conditions.append("signal_level <= 2")

        where_clause = " AND ".join(conditions)
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT * FROM trading_signals
                WHERE {where_clause}
                ORDER BY final_score DESC
                LIMIT ?
            """, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_latest_signal_date(self) -> Optional[str]:
        """获取数据库中最新的信号日期

        Returns:
            最新的 trade_date 字符串（如 "2025-02-07"），无信号时返回 None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT MAX(trade_date) FROM trading_signals"
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else None

    def get_signal_history(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """查询某只股票的信号历史

        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            信号历史列表
        """
        conditions = ["stock_code = ?"]
        params: list = [stock_code]

        if start_date:
            conditions.append("trade_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("trade_date <= ?")
            params.append(end_date)

        where_clause = " AND ".join(conditions)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT * FROM trading_signals
                WHERE {where_clause}
                ORDER BY trade_date DESC
            """, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_signal_stats(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取信号统计信息

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            统计信息：总数、每日买卖数量、平均分等
        """
        conditions = []
        params: list = []

        if start_date:
            conditions.append("trade_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("trade_date <= ?")
            params.append(end_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 总体统计
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total,
                    AVG(final_score) as avg_score,
                    SUM(CASE WHEN signal_level >= 4 THEN 1 ELSE 0 END) as buy_count,
                    SUM(CASE WHEN signal_level <= 2 THEN 1 ELSE 0 END) as sell_count,
                    SUM(CASE WHEN signal_level = 3 THEN 1 ELSE 0 END) as hold_count
                FROM trading_signals
                WHERE {where_clause}
            """, params)
            stats = dict(cursor.fetchone())

            # 按日期统计
            cursor.execute(f"""
                SELECT
                    trade_date,
                    COUNT(*) as total,
                    SUM(CASE WHEN signal_level >= 4 THEN 1 ELSE 0 END) as buy_count,
                    SUM(CASE WHEN signal_level <= 2 THEN 1 ELSE 0 END) as sell_count,
                    AVG(final_score) as avg_score
                FROM trading_signals
                WHERE {where_clause}
                GROUP BY trade_date
                ORDER BY trade_date DESC
                LIMIT 30
            """, params)
            stats["by_date"] = [dict(r) for r in cursor.fetchall()]

            return stats

    def get_signal_count(self) -> int:
        """获取信号总数

        Returns:
            信号总数
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM trading_signals")
            return cursor.fetchone()[0]

    # ── 动作信号 CRUD ──────────────────────────────────────────

    def save_action_signals(
        self,
        signals: List[Dict[str, Any]],
        trade_date: str
    ) -> Dict[str, int]:
        """批量保存动作信号（INSERT OR REPLACE）

        Args:
            signals: 动作信号列表，每个元素包含:
                stock_code, action, strategy_name, confidence_score,
                sell_reason, trigger_rules, stop_loss_pct, take_profit_pct,
                max_hold_days, reasons
            trade_date: 交易日期

        Returns:
            包含 saved 数量的字典
        """
        saved = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for sig in signals:
                try:
                    trigger_rules = sig.get("trigger_rules", [])
                    if isinstance(trigger_rules, list):
                        trigger_rules = json.dumps(trigger_rules, ensure_ascii=False)

                    reasons = sig.get("reasons", [])
                    if isinstance(reasons, list):
                        reasons = json.dumps(reasons, ensure_ascii=False)

                    cursor.execute("""
                        INSERT OR REPLACE INTO action_signals
                        (stock_code, trade_date, action, strategy_name,
                         confidence_score, sell_reason, trigger_rules,
                         stop_loss_pct, take_profit_pct, max_hold_days, reasons)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        sig["stock_code"],
                        trade_date,
                        sig["action"],
                        sig["strategy_name"],
                        sig.get("confidence_score"),
                        sig.get("sell_reason"),
                        trigger_rules,
                        sig.get("stop_loss_pct"),
                        sig.get("take_profit_pct"),
                        sig.get("max_hold_days"),
                        reasons,
                    ))
                    saved += 1
                except Exception:
                    pass
        return {"saved": saved}

    def get_action_signals(
        self,
        trade_date: Optional[str] = None,
        stock_code: Optional[str] = None,
        action: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """查询动作信号

        Args:
            trade_date: 精确日期（优先于 start/end_date）
            stock_code: 股票代码过滤
            action: "BUY" 或 "SELL"
            start_date: 日期范围起始
            end_date: 日期范围结束
            limit: 最大返回数量

        Returns:
            动作信号列表
        """
        conditions = []
        params: list = []

        if trade_date:
            conditions.append("trade_date = ?")
            params.append(trade_date)
        else:
            if start_date:
                conditions.append("trade_date >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("trade_date <= ?")
                params.append(end_date)

        if stock_code:
            conditions.append("stock_code = ?")
            params.append(stock_code)

        if action:
            conditions.append("action = ?")
            params.append(action)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT * FROM action_signals
                WHERE {where_clause}
                ORDER BY trade_date DESC, confidence_score DESC
                LIMIT ?
            """, params)
            return [dict(row) for row in cursor.fetchall()]

    # ── 指标配置 CRUD ──────────────────────────────────────────

    def get_all_indicators(self) -> List[Dict[str, Any]]:
        """获取所有指标配置"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM indicator_config ORDER BY id")
            rows = [dict(row) for row in cursor.fetchall()]
            for row in rows:
                row["params"] = json.loads(row["params"])
            return rows

    def get_indicator(self, indicator_id: int) -> Optional[Dict[str, Any]]:
        """获取单个指标配置"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM indicator_config WHERE id = ?", (indicator_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d["params"] = json.loads(d["params"])
                return d
            return None

    def save_indicator(self, indicator_type: str, name: str,
                       params: Dict[str, Any], enabled: bool = True) -> int:
        """新增指标配置，返回新 ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO indicator_config (indicator_type, name, params, enabled)
                VALUES (?, ?, ?, ?)
            """, (indicator_type, name, json.dumps(params, ensure_ascii=False),
                  1 if enabled else 0))
            return cursor.lastrowid

    def update_indicator(self, indicator_id: int, **kwargs) -> None:
        """更新指标配置（支持 name, params, enabled）"""
        allowed = {"name", "params", "enabled"}
        sets = []
        values = []
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            if k == "params":
                v = json.dumps(v, ensure_ascii=False)
            if k == "enabled":
                v = 1 if v else 0
            sets.append(f"{k} = ?")
            values.append(v)
        if not sets:
            return
        values.append(indicator_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE indicator_config SET {', '.join(sets)} WHERE id = ?",
                values
            )

    def delete_indicator(self, indicator_id: int) -> None:
        """删除指标配置"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM indicator_config WHERE id = ?", (indicator_id,))

    def get_indicator_count(self) -> int:
        """获取指标配置总数"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM indicator_config")
            return cursor.fetchone()[0]

    # ── 信号策略 CRUD ──────────────────────────────────────────

    def _parse_strategy_row(self, row: dict) -> dict:
        """解析策略行，将 JSON 字段反序列化"""
        row["rules"] = json.loads(row.get("rules", "[]"))
        row["buy_conditions"] = json.loads(row.get("buy_conditions", "[]"))
        row["sell_conditions"] = json.loads(row.get("sell_conditions", "[]"))
        row["exit_config"] = json.loads(row.get("exit_config", "{}"))
        return row

    def get_all_strategies(self) -> List[Dict[str, Any]]:
        """获取所有信号策略"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM signal_strategy ORDER BY id")
            rows = [dict(row) for row in cursor.fetchall()]
            return [self._parse_strategy_row(r) for r in rows]

    def get_strategy(self, strategy_id: int) -> Optional[Dict[str, Any]]:
        """获取单个信号策略"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM signal_strategy WHERE id = ?", (strategy_id,))
            row = cursor.fetchone()
            if row:
                return self._parse_strategy_row(dict(row))
            return None

    def save_strategy(self, name: str, description: str,
                      rules: List[Dict[str, Any]],
                      weight: float = 0.5,
                      enabled: bool = True,
                      buy_conditions: Optional[List] = None,
                      sell_conditions: Optional[List] = None,
                      exit_config: Optional[Dict] = None) -> int:
        """新增信号策略，返回新 ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO signal_strategy
                (name, description, rules, weight, enabled,
                 buy_conditions, sell_conditions, exit_config)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, description,
                  json.dumps(rules, ensure_ascii=False),
                  weight,
                  1 if enabled else 0,
                  json.dumps(buy_conditions or [], ensure_ascii=False),
                  json.dumps(sell_conditions or [], ensure_ascii=False),
                  json.dumps(exit_config or {}, ensure_ascii=False)))
            return cursor.lastrowid

    def update_strategy(self, strategy_id: int, **kwargs) -> None:
        """更新信号策略"""
        allowed = {"name", "description", "rules", "weight", "enabled",
                   "buy_conditions", "sell_conditions", "exit_config"}
        json_fields = {"rules", "buy_conditions", "sell_conditions", "exit_config"}
        sets = []
        values = []
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            if k in json_fields:
                v = json.dumps(v, ensure_ascii=False)
            if k == "enabled":
                v = 1 if v else 0
            sets.append(f"{k} = ?")
            values.append(v)
        if not sets:
            return
        values.append(strategy_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE signal_strategy SET {', '.join(sets)} WHERE id = ?",
                values
            )

    def delete_strategy(self, strategy_id: int) -> None:
        """删除信号策略"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM signal_strategy WHERE id = ?", (strategy_id,))

    def _get_strategy_count(self) -> int:
        """获取策略配置总数"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM signal_strategy")
            return cursor.fetchone()[0]

    def _migrate_strategy_buy_sell_conditions(self) -> int:
        """迁移：给已有策略补充 buy/sell/exit 默认值

        仅当策略的 buy_conditions 仍为空 [] 时才补充，
        避免覆盖用户已自定义的条件。

        Returns:
            更新的策略数
        """
        # 默认条件定义（与 seed 一致）
        defaults = {
            "波段策略": {
                "buy_conditions": [
                    {"field": "RSI", "operator": "<", "compare_type": "value",
                     "compare_value": 30, "label": "RSI超卖(<30)"},
                    {"field": "KDJ_K", "operator": ">", "compare_type": "field",
                     "compare_field": "KDJ_D", "label": "KDJ金叉(K>D)"},
                    {"field": "MACD_hist", "operator": ">", "compare_type": "value",
                     "compare_value": 0, "label": "MACD多头动量(柱>0)"},
                ],
                "sell_conditions": [
                    {"field": "RSI", "operator": ">", "compare_type": "value",
                     "compare_value": 75, "label": "RSI超买(>75)"},
                    {"field": "KDJ_K", "operator": "<", "compare_type": "field",
                     "compare_field": "KDJ_D", "label": "KDJ死叉(K<D)"},
                ],
                "exit_config": {
                    "stop_loss_pct": -8.0,
                    "take_profit_pct": 20.0,
                    "max_hold_days": 30,
                },
            },
            "趋势策略": {
                "buy_conditions": [
                    {"field": "MA", "params": {"period": 5}, "operator": ">",
                     "compare_type": "field", "compare_field": "MA",
                     "compare_params": {"period": 20}, "label": "MA(5)上穿MA(20)"},
                    {"field": "ADX_plus_di", "operator": ">", "compare_type": "field",
                     "compare_field": "ADX_minus_di", "label": "+DI强于-DI"},
                    {"field": "close", "operator": ">", "compare_type": "field",
                     "compare_field": "EMA", "compare_params": {"period": 12},
                     "label": "价格在EMA(12)之上"},
                ],
                "sell_conditions": [
                    {"field": "MA", "params": {"period": 5}, "operator": "<",
                     "compare_type": "field", "compare_field": "MA",
                     "compare_params": {"period": 20}, "label": "MA(5)下穿MA(20)"},
                    {"field": "close", "operator": "<", "compare_type": "field",
                     "compare_field": "EMA", "compare_params": {"period": 12},
                     "label": "价格跌破EMA(12)"},
                ],
                "exit_config": {
                    "stop_loss_pct": -10.0,
                    "take_profit_pct": 30.0,
                    "max_hold_days": 60,
                },
            },
        }

        updated = 0
        strategies = self.get_all_strategies()
        for strategy in strategies:
            name = strategy.get("name", "")
            # 仅当 buy_conditions 为空时才补充（说明是迁移前创建的旧策略）
            if name in defaults and not strategy.get("buy_conditions"):
                d = defaults[name]
                self.update_strategy(
                    strategy["id"],
                    buy_conditions=d["buy_conditions"],
                    sell_conditions=d["sell_conditions"],
                    exit_config=d["exit_config"],
                )
                updated += 1
        return updated

    def seed_default_indicators_and_strategies(self) -> Dict[str, int]:
        """预填充默认指标和策略（分别检查，仅在各自表为空时填充）

        Returns:
            {"indicators": 新增指标数, "strategies": 新增策略数}
        """
        result = {"indicators": 0, "strategies": 0}

        # 指标和策略独立检查，避免迁移后某一方无法重新填充
        has_indicators = self.get_indicator_count() > 0
        has_strategies = self._get_strategy_count() > 0

        # 8个默认指标
        if not has_indicators:
            default_indicators = [
                ("MA", "MA(5,10,20,60)", {"periods": [5, 10, 20, 60]}),
                ("EMA", "EMA(12,26)", {"periods": [12, 26]}),
                ("RSI", "RSI(14)", {"period": 14, "overbought": 70, "oversold": 30}),
                ("MACD", "MACD(12,26,9)", {"fast_period": 12, "slow_period": 26, "signal_period": 9}),
                ("KDJ", "KDJ(9,3,3)", {"fastk_period": 9, "slowk_period": 3, "slowd_period": 3}),
                ("ADX", "ADX(14)", {"period": 14, "threshold": 25}),
                ("OBV", "OBV", {}),
                ("ATR", "ATR(14)", {"period": 14}),
            ]
            for ind_type, name, params in default_indicators:
                self.save_indicator(ind_type, name, params)
                result["indicators"] += 1

        # 策略独立检查，表迁移后可单独重新填充
        if not has_strategies:
            swing_rules = [
                {"field": "RSI", "operator": "<", "compare_type": "value",
                 "compare_value": 30, "score": 25, "label": "RSI超卖看涨"},
                {"field": "RSI", "operator": ">", "compare_type": "value",
                 "compare_value": 70, "score": -25, "label": "RSI超买看跌"},
                {"field": "KDJ_K", "operator": ">", "compare_type": "field",
                 "compare_field": "KDJ_D", "score": 15, "label": "KDJ金叉"},
                {"field": "KDJ_K", "operator": "<", "compare_type": "field",
                 "compare_field": "KDJ_D", "score": -15, "label": "KDJ死叉"},
                {"field": "MACD_hist", "operator": ">", "compare_type": "value",
                 "compare_value": 0, "score": 10, "label": "MACD多头动量"},
                {"field": "MACD_hist", "operator": "<", "compare_type": "value",
                 "compare_value": 0, "score": -10, "label": "MACD空头动量"},
            ]

            trend_rules = [
                {"field": "MA", "params": {"period": 5}, "operator": ">",
                 "compare_type": "field", "compare_field": "MA",
                 "compare_params": {"period": 20}, "score": 20,
                 "label": "MA(5)在MA(20)之上"},
                {"field": "MA", "params": {"period": 5}, "operator": "<",
                 "compare_type": "field", "compare_field": "MA",
                 "compare_params": {"period": 20}, "score": -20,
                 "label": "MA(5)在MA(20)之下"},
                {"field": "ADX_plus_di", "operator": ">", "compare_type": "field",
                 "compare_field": "ADX_minus_di", "score": 15,
                 "label": "+DI强于-DI（上涨趋势）"},
                {"field": "ADX_plus_di", "operator": "<", "compare_type": "field",
                 "compare_field": "ADX_minus_di", "score": -15,
                 "label": "-DI强于+DI（下跌趋势）"},
                {"field": "close", "operator": ">", "compare_type": "field",
                 "compare_field": "EMA", "compare_params": {"period": 12},
                 "score": 10, "label": "价格在EMA(12)之上"},
                {"field": "close", "operator": "<", "compare_type": "field",
                 "compare_field": "EMA", "compare_params": {"period": 12},
                 "score": -10, "label": "价格在EMA(12)之下"},
            ]

            # 波段策略：买入条件 = RSI超卖 AND KDJ金叉 AND MACD多头
            swing_buy = [
                {"field": "RSI", "operator": "<", "compare_type": "value",
                 "compare_value": 30, "label": "RSI超卖(<30)"},
                {"field": "KDJ_K", "operator": ">", "compare_type": "field",
                 "compare_field": "KDJ_D", "label": "KDJ金叉(K>D)"},
                {"field": "MACD_hist", "operator": ">", "compare_type": "value",
                 "compare_value": 0, "label": "MACD多头动量(柱>0)"},
            ]
            # 波段策略：卖出条件 = RSI超买 OR KDJ死叉（任一触发）
            swing_sell = [
                {"field": "RSI", "operator": ">", "compare_type": "value",
                 "compare_value": 75, "label": "RSI超买(>75)"},
                {"field": "KDJ_K", "operator": "<", "compare_type": "field",
                 "compare_field": "KDJ_D", "label": "KDJ死叉(K<D)"},
            ]
            swing_exit = {
                "stop_loss_pct": -8.0,
                "take_profit_pct": 20.0,
                "max_hold_days": 30,
            }

            # 趋势策略：买入条件 = MA金叉 AND +DI强 AND 价格在EMA上
            trend_buy = [
                {"field": "MA", "params": {"period": 5}, "operator": ">",
                 "compare_type": "field", "compare_field": "MA",
                 "compare_params": {"period": 20}, "label": "MA(5)上穿MA(20)"},
                {"field": "ADX_plus_di", "operator": ">", "compare_type": "field",
                 "compare_field": "ADX_minus_di", "label": "+DI强于-DI"},
                {"field": "close", "operator": ">", "compare_type": "field",
                 "compare_field": "EMA", "compare_params": {"period": 12},
                 "label": "价格在EMA(12)之上"},
            ]
            # 趋势策略：卖出条件 = MA死叉 OR 价格跌破EMA
            trend_sell = [
                {"field": "MA", "params": {"period": 5}, "operator": "<",
                 "compare_type": "field", "compare_field": "MA",
                 "compare_params": {"period": 20}, "label": "MA(5)下穿MA(20)"},
                {"field": "close", "operator": "<", "compare_type": "field",
                 "compare_field": "EMA", "compare_params": {"period": 12},
                 "label": "价格跌破EMA(12)"},
            ]
            trend_exit = {
                "stop_loss_pct": -10.0,
                "take_profit_pct": 30.0,
                "max_hold_days": 60,
            }

            self.save_strategy(
                "波段策略", "基于RSI超买超卖、KDJ交叉、MACD动量，适合震荡市",
                swing_rules, weight=0.5,
                buy_conditions=swing_buy,
                sell_conditions=swing_sell,
                exit_config=swing_exit,
            )
            self.save_strategy(
                "趋势策略", "基于MA交叉、DI方向、EMA位置，适合趋势市",
                trend_rules, weight=0.5,
                buy_conditions=trend_buy,
                sell_conditions=trend_sell,
                exit_config=trend_exit,
            )
            result["strategies"] += 2

        # 数据迁移：给旧策略补充 buy/sell/exit 默认值
        if has_strategies:
            migrated = self._migrate_strategy_buy_sell_conditions()
            result["migrated"] = migrated

        return result

    # ── 回测 CRUD ──────────────────────────────────────────

    def save_backtest_run(
        self,
        strategy_id: int,
        result_obj,
    ) -> int:
        """保存回测运行记录

        Args:
            strategy_id: 策略 ID
            result_obj: BacktestResult dataclass 实例

        Returns:
            run_id（新插入行的 ID）
        """
        # 序列化完整结果（equity_curve + trades 等）
        result_dict = {
            "strategy_name": result_obj.strategy_name,
            "start_date": result_obj.start_date,
            "end_date": result_obj.end_date,
            "initial_capital": result_obj.initial_capital,
            "total_trades": result_obj.total_trades,
            "win_trades": result_obj.win_trades,
            "lose_trades": result_obj.lose_trades,
            "win_rate": result_obj.win_rate,
            "total_return_pct": result_obj.total_return_pct,
            "max_drawdown_pct": result_obj.max_drawdown_pct,
            "avg_hold_days": result_obj.avg_hold_days,
            "avg_pnl_pct": result_obj.avg_pnl_pct,
            "equity_curve": result_obj.equity_curve,
            "sell_reason_stats": result_obj.sell_reason_stats,
        }
        result_json = json.dumps(result_dict, ensure_ascii=False)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO backtest_runs
                (strategy_id, strategy_name, start_date, end_date,
                 capital_per_trade, total_trades, win_rate,
                 total_return_pct, max_drawdown_pct, avg_hold_days,
                 result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                strategy_id,
                result_obj.strategy_name,
                result_obj.start_date,
                result_obj.end_date,
                result_obj.initial_capital,
                result_obj.total_trades,
                result_obj.win_rate,
                result_obj.total_return_pct,
                result_obj.max_drawdown_pct,
                result_obj.avg_hold_days,
                result_json,
            ))
            return cursor.lastrowid

    def save_backtest_trades(self, run_id: int, trades: list) -> int:
        """批量保存回测交易明细

        Args:
            run_id: 回测运行 ID
            trades: Trade dataclass 实例列表

        Returns:
            保存的记录数
        """
        if not trades:
            return 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO backtest_trades
                (run_id, stock_code, strategy_name, buy_date, buy_price,
                 sell_date, sell_price, sell_reason, pnl_pct, hold_days)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    run_id,
                    t.stock_code,
                    t.strategy_name,
                    t.buy_date,
                    t.buy_price,
                    t.sell_date,
                    t.sell_price,
                    t.sell_reason,
                    t.pnl_pct,
                    t.hold_days,
                )
                for t in trades
            ])
            return len(trades)

    def get_backtest_runs(
        self,
        strategy_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """查询回测历史

        Args:
            strategy_id: 按策略过滤（可选）
            limit: 最大返回数

        Returns:
            回测运行记录列表
        """
        conditions = []
        params: list = []
        if strategy_id is not None:
            conditions.append("strategy_id = ?")
            params.append(strategy_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT * FROM backtest_runs
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
            """, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_backtest_trades(self, run_id: int) -> List[Dict[str, Any]]:
        """查询单次回测的交易明细

        Args:
            run_id: 回测运行 ID

        Returns:
            交易记录列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM backtest_trades
                WHERE run_id = ?
                ORDER BY buy_date ASC
            """, (run_id,))
            return [dict(row) for row in cursor.fetchall()]
