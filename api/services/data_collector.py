"""Data collection service — TuShare (primary) + AkShare (fallback), configurable.

Provides stock lists and daily OHLCV data with automatic retry and
fallback between data sources. Primary/fallback order is controlled by
config.yaml per-category settings. Results are cached in the database.
"""

import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from api.config import get_settings
from api.models.stock import Stock, DailyPrice, DailyBasic, StockConcept, BoardSyncLog, TradingCalendar, IndexDaily, INDEX_CODES
from api.utils.network import no_proxy

logger = logging.getLogger(__name__)


class DataCollector:
    """Unified data collector with configurable primary/fallback data sources."""

    def __init__(self, db: Session):
        self.db = db
        self._settings = get_settings()
        self._tushare_api = None

    def _get_tushare_api(self):
        if self._tushare_api is None:
            token = self._settings.data_sources.tushare_token
            if token:
                import tushare as ts
                self._tushare_api = ts.pro_api(token)
        return self._tushare_api

    # ── Stock list ─────────────────────────────────────────

    def sync_stock_list(self) -> int:
        """Fetch A-share stock list and upsert to DB. Returns count."""
        preferred = self._settings.data_sources.stock_list
        if preferred == "tushare":
            primary_fn, fallback_fn = self._fetch_stock_list_tushare, self._fetch_stock_list_akshare
        else:
            primary_fn, fallback_fn = self._fetch_stock_list_akshare, self._fetch_stock_list_tushare

        df = primary_fn()
        if (df is None or df.empty) and self._settings.data_sources.fallback_enabled:
            df = fallback_fn()
        if df is None or df.empty:
            return 0

        count = 0
        for _, row in df.iterrows():
            code = str(row.get("code", "")).strip()
            if not code:
                continue
            existing = self.db.query(Stock).filter(Stock.code == code).first()
            if existing:
                existing.name = row.get("name", existing.name)
                existing.industry = row.get("industry", existing.industry) or ""
                existing.market = row.get("market", existing.market) or ""
            else:
                self.db.add(Stock(
                    code=code,
                    name=row.get("name", ""),
                    market=row.get("market", ""),
                    industry=row.get("industry", ""),
                    list_date=row.get("list_date", ""),
                ))
            count += 1
        self.db.commit()
        logger.info("Synced %d stocks", count)
        return count

    # ── Board sync (industry + concept) ──────────────────

    def _is_synced_today(self, board_type: str) -> bool:
        """Check if the given board_type was already synced today."""
        log = self.db.query(BoardSyncLog).filter(
            BoardSyncLog.board_type == board_type
        ).first()
        if not log:
            return False
        return log.last_synced.date() == date.today()

    def _update_sync_log(self, board_type: str, count: int):
        log = self.db.query(BoardSyncLog).filter(
            BoardSyncLog.board_type == board_type
        ).first()
        if log:
            log.last_synced = datetime.now()
            log.record_count = count
        else:
            self.db.add(BoardSyncLog(
                board_type=board_type,
                last_synced=datetime.now(),
                record_count=count,
            ))

    def sync_industries(self, force: bool = False) -> dict:
        """Fetch industry classification from AkShare and update stocks.

        Returns {"updated": N, "skipped": bool} — skipped=True if already synced today.
        """
        if not force and self._is_synced_today("industry"):
            logger.info("Industry already synced today, skipping")
            return {"updated": 0, "skipped": True}
        try:
            import akshare as ak
            with no_proxy():
                boards = ak.stock_board_industry_name_em()
            if boards is None or boards.empty:
                logger.warning("No industry boards returned")
                return {"updated": 0, "skipped": False}

            board_names = boards["板块名称"].tolist()
            logger.info("Fetching constituents for %d industry boards...", len(board_names))

            code_to_industry: dict[str, str] = {}
            for name in board_names:
                try:
                    time.sleep(0.3)
                    with no_proxy():
                        cons = ak.stock_board_industry_cons_em(symbol=name)
                    if cons is not None and not cons.empty:
                        for code in cons["代码"].tolist():
                            code_to_industry[str(code)] = name
                except Exception as e:
                    logger.debug("Board %s fetch failed: %s", name, e)

            updated = 0
            for code, industry in code_to_industry.items():
                stock = self.db.query(Stock).filter(Stock.code == code).first()
                if stock and stock.industry != industry:
                    stock.industry = industry
                    updated += 1

            self._update_sync_log("industry", len(code_to_industry))
            self.db.commit()
            logger.info("Updated industry for %d stocks (mapped %d total)",
                        updated, len(code_to_industry))
            return {"updated": updated, "skipped": False}
        except Exception as e:
            logger.error("sync_industries failed: %s", e)
            return {"updated": 0, "skipped": False}

    def sync_concepts(self, force: bool = False) -> dict:
        """Fetch concept boards from AkShare and store stock-concept mappings.

        Returns {"updated": N, "skipped": bool}.
        """
        if not force and self._is_synced_today("concept"):
            logger.info("Concepts already synced today, skipping")
            return {"updated": 0, "skipped": True}
        try:
            import akshare as ak
            with no_proxy():
                boards = ak.stock_board_concept_name_em()
            if boards is None or boards.empty:
                logger.warning("No concept boards returned")
                return {"updated": 0, "skipped": False}

            board_names = boards["板块名称"].tolist()
            logger.info("Fetching constituents for %d concept boards...", len(board_names))

            # Collect all (code, concept) pairs
            pairs: list[tuple[str, str]] = []
            for name in board_names:
                try:
                    time.sleep(0.3)
                    with no_proxy():
                        cons = ak.stock_board_concept_cons_em(symbol=name)
                    if cons is not None and not cons.empty:
                        for code in cons["代码"].tolist():
                            pairs.append((str(code), name))
                except Exception as e:
                    logger.debug("Concept board %s fetch failed: %s", name, e)

            # Replace all concept data (delete old, insert new)
            self.db.query(StockConcept).delete()
            inserted = 0
            seen: set[tuple[str, str]] = set()
            for code, concept in pairs:
                if (code, concept) not in seen:
                    seen.add((code, concept))
                    self.db.add(StockConcept(stock_code=code, concept_name=concept))
                    inserted += 1

            self._update_sync_log("concept", inserted)
            self.db.commit()
            logger.info("Synced %d stock-concept mappings from %d boards",
                        inserted, len(board_names))
            return {"updated": inserted, "skipped": False}
        except Exception as e:
            logger.error("sync_concepts failed: %s", e)
            return {"updated": 0, "skipped": False}

    def sync_boards(self, force: bool = False) -> dict:
        """Sync both industry and concept boards. Respects daily limit."""
        ind = self.sync_industries(force=force)
        con = self.sync_concepts(force=force)
        return {"industry": ind, "concepts": con}

    def get_stock_concepts(self, stock_code: str) -> list[str]:
        """Return concept names for a stock."""
        rows = self.db.query(StockConcept.concept_name).filter(
            StockConcept.stock_code == stock_code
        ).all()
        return [r[0] for r in rows]

    def get_stock_list(
        self, keyword: str = "", market: str = "", page: int = 1, size: int = 50
    ) -> tuple[list[Stock], int]:
        """Search stocks with pagination. Returns (items, total)."""
        q = self.db.query(Stock)
        if keyword:
            q = q.filter(
                (Stock.code.contains(keyword)) | (Stock.name.contains(keyword))
            )
        if market:
            q = q.filter(Stock.market == market)

        total = q.count()
        items = q.order_by(Stock.code).offset((page - 1) * size).limit(size).all()
        return items, total

    def get_all_stock_codes(self) -> list[str]:
        """Return all A-share stock codes (0xx/3xx/6xx only)."""
        rows = self.db.query(Stock.code).all()
        return [
            r.code for r in rows
            if r.code[:1] in ("0", "3", "6") and not r.code.startswith("9")
        ]

    def get_stocks_with_data(self, min_rows: int = 60) -> list[str]:
        """Return stock codes that have sufficient cached price data.

        Only returns codes with at least `min_rows` daily_prices rows,
        avoiding expensive API calls for stocks without local data.
        """
        from sqlalchemy import func as sa_func
        rows = (
            self.db.query(DailyPrice.stock_code)
            .group_by(DailyPrice.stock_code)
            .having(sa_func.count(DailyPrice.id) >= min_rows)
            .all()
        )
        return [r.stock_code for r in rows]

    def get_sample_stock_codes(self, count: int = 20) -> list[str]:
        """Return a sample of popular stock codes."""
        popular = [
            "000001", "600519", "000858", "601318", "000333",
            "600036", "000651", "601166", "600276", "002415",
            "300750", "601888", "600887", "000568", "002304",
            "601012", "600900", "002714", "300059", "601398",
        ]
        return popular[:count]

    # ── Daily price data ───────────────────────────────────

    def get_daily_df(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        local_only: bool = False,
    ) -> Optional[pd.DataFrame]:
        """Get daily OHLCV as DataFrame. Fetches from API if not cached.

        Args:
            stock_code: 6-digit code like "000001"
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            local_only: If True, skip network fetch and only return cached data

        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        # Auto-extend to 5 years for non-local requests
        if not local_only:
            five_years_ago = (date.today() - timedelta(days=5 * 365)).isoformat()
            if start_date > five_years_ago:
                start_date = five_years_ago

        req_start = date.fromisoformat(start_date)
        req_end = date.fromisoformat(end_date)

        # Check DB cache first
        rows = (
            self.db.query(DailyPrice)
            .filter(
                DailyPrice.stock_code == stock_code,
                DailyPrice.trade_date >= req_start,
                DailyPrice.trade_date <= req_end,
            )
            .order_by(DailyPrice.trade_date)
            .all()
        )

        # Check if cached data covers the requested range
        need_fetch = False
        if not rows or len(rows) < 5:
            need_fetch = True
        else:
            earliest_cached = rows[0].trade_date
            if isinstance(earliest_cached, str):
                earliest_cached = date.fromisoformat(earliest_cached)
            latest_cached = rows[-1].trade_date
            if isinstance(latest_cached, str):
                latest_cached = date.fromisoformat(latest_cached)
            # If the earliest cached date is >60 days after the requested start,
            # there's likely missing data — fetch from API to fill the gap
            if (earliest_cached - req_start).days > 60:
                need_fetch = True
            # If the latest cached date is >1 day before the requested end,
            # fetch fresh data to pick up any new trading days
            elif (req_end - latest_cached).days > 1:
                need_fetch = True
            # Internal gap detection: compare cached rows vs expected trading days
            elif not local_only:
                try:
                    trading_dates = self.get_trading_dates(start_date, end_date)
                    if trading_dates and len(rows) < len(trading_dates) * 0.9:
                        need_fetch = True
                        logger.info(
                            "Internal gap detected for %s: %d rows vs %d trading days",
                            stock_code, len(rows), len(trading_dates),
                        )
                except Exception:
                    pass  # Calendar not available, skip gap check

        if need_fetch and not local_only:
            df = self._fetch_daily_from_apis(stock_code, start_date, end_date)
            if df is not None and not df.empty:
                self._cache_daily(stock_code, df)
                return df
            # Fetch failed — fall through to use whatever local data we have

        # Return cached data
        if rows:
            df = pd.DataFrame([{
                "date": r.trade_date.isoformat() if isinstance(r.trade_date, date) else str(r.trade_date),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            } for r in rows])
            return df

        return None

    def _fetch_daily_from_apis(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """Try primary data source first, then fallback per config."""
        preferred = self._settings.data_sources.historical_daily
        if preferred == "tushare":
            primary_fn, fallback_fn = self._fetch_daily_tushare, self._fetch_daily_akshare
        else:
            primary_fn, fallback_fn = self._fetch_daily_akshare, self._fetch_daily_tushare

        df = primary_fn(stock_code, start_date, end_date)
        if df is not None and not df.empty:
            return df

        if self._settings.data_sources.fallback_enabled:
            df = fallback_fn(stock_code, start_date, end_date)
            if df is not None and not df.empty:
                return df

        return None

    def _cache_daily(self, stock_code: str, df: pd.DataFrame):
        """Upsert daily price data to DB."""
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        for _, row in df.iterrows():
            try:
                d = row.get("date", "")
                if isinstance(d, str):
                    trade_d = date.fromisoformat(d)
                else:
                    trade_d = d

                existing = (
                    self.db.query(DailyPrice)
                    .filter(
                        DailyPrice.stock_code == stock_code,
                        DailyPrice.trade_date == trade_d,
                    )
                    .first()
                )
                if existing:
                    existing.open = float(row["open"])
                    existing.high = float(row["high"])
                    existing.low = float(row["low"])
                    existing.close = float(row["close"])
                    existing.volume = float(row.get("volume", 0))
                else:
                    self.db.add(DailyPrice(
                        stock_code=stock_code,
                        trade_date=trade_d,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume", 0)),
                        amount=float(row.get("amount", 0)),
                    ))
            except Exception as e:
                logger.debug("Cache daily row error: %s", e)
                continue
        self.db.commit()

    # ── Daily basic (fundamental) data ─────────────────────

    def get_daily_basic_df(self, trade_date: str) -> Optional[pd.DataFrame]:
        """Get daily basic data (PE/PB/MV) for a trade date. DB cache → TuShare fetch.

        Args:
            trade_date: YYYY-MM-DD format

        Returns:
            DataFrame indexed by stock_code with columns: pe, pb, total_mv, circ_mv, turnover_rate
        """
        trade_d = date.fromisoformat(trade_date)

        # Check DB cache
        rows = (
            self.db.query(DailyBasic)
            .filter(DailyBasic.trade_date == trade_d)
            .all()
        )
        if rows:
            df = pd.DataFrame([{
                "stock_code": r.stock_code,
                "pe": r.pe,
                "pb": r.pb,
                "total_mv": r.total_mv,
                "circ_mv": r.circ_mv,
                "turnover_rate": r.turnover_rate,
            } for r in rows])
            return df.set_index("stock_code")

        # Fetch from TuShare
        api = self._get_tushare_api()
        if api is None:
            logger.warning("TuShare API not configured, cannot fetch daily_basic")
            return None

        try:
            ts_date = trade_date.replace("-", "")
            time.sleep(0.3)
            with no_proxy():
                df = api.daily_basic(
                    trade_date=ts_date,
                    fields="ts_code,pe,pb,total_mv,circ_mv,turnover_rate",
                )
            if df is None or df.empty:
                return None

            df["stock_code"] = df["ts_code"].str.split(".").str[0]
            df = df.drop(columns=["ts_code"])

            # Cache to DB
            for _, row in df.iterrows():
                code = row["stock_code"]
                self.db.add(DailyBasic(
                    stock_code=code,
                    trade_date=trade_d,
                    pe=row.get("pe") if pd.notna(row.get("pe")) else None,
                    pb=row.get("pb") if pd.notna(row.get("pb")) else None,
                    total_mv=row.get("total_mv") if pd.notna(row.get("total_mv")) else None,
                    circ_mv=row.get("circ_mv") if pd.notna(row.get("circ_mv")) else None,
                    turnover_rate=row.get("turnover_rate") if pd.notna(row.get("turnover_rate")) else None,
                ))
            self.db.commit()
            logger.info("Cached daily_basic for %s: %d stocks", trade_date, len(df))

            return df.set_index("stock_code")[["pe", "pb", "total_mv", "circ_mv", "turnover_rate"]]
        except Exception as e:
            logger.warning("TuShare daily_basic fetch failed for %s: %s", trade_date, e)
            return None

    def prefetch_daily_basic(self, dates: list[str]) -> dict[str, pd.DataFrame]:
        """Bulk-load daily basic data for multiple dates, skipping cached ones.

        Args:
            dates: List of YYYY-MM-DD date strings

        Returns:
            Dict mapping date string → DataFrame indexed by stock_code
        """
        result: dict[str, pd.DataFrame] = {}
        for d in dates:
            df = self.get_daily_basic_df(d)
            if df is not None and not df.empty:
                result[d] = df
        return result

    # ── AkShare implementations ────────────────────────────

    def _fetch_stock_list_akshare(self) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak
            with no_proxy():
                df = ak.stock_info_a_code_name()
            if df is None or df.empty:
                return None
            df = df.rename(columns={"code": "code", "name": "name"})
            df["industry"] = ""
            df["market"] = df["code"].apply(
                lambda c: "SH" if str(c).startswith("6") else "SZ"
            )
            df["list_date"] = ""
            return df[["code", "name", "market", "industry", "list_date"]]
        except Exception as e:
            logger.warning("AkShare stock list failed: %s", e)
            return None

    def _fetch_daily_akshare(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak
            time.sleep(0.5)
            with no_proxy():
                df = ak.stock_zh_a_hist(
                    symbol=stock_code,
                    period="daily",
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                    adjust="qfq",
                )
            if df is None or df.empty:
                return None

            df = df.rename(columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
            })
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            return df[["date", "open", "high", "low", "close", "volume"]].copy()
        except Exception as e:
            logger.warning("AkShare daily %s failed: %s", stock_code, e)
            return None

    # ── TuShare implementations ────────────────────────────

    def _fetch_stock_list_tushare(self) -> Optional[pd.DataFrame]:
        api = self._get_tushare_api()
        if api is None:
            return None
        try:
            with no_proxy():
                df = api.stock_basic(
                    exchange="", list_status="L",
                    fields="ts_code,name,industry,market,list_date",
                )
            if df is None or df.empty:
                return None
            df["code"] = df["ts_code"].str.split(".").str[0]
            df["market"] = df["ts_code"].str.split(".").str[1]
            return df[["code", "name", "market", "industry", "list_date"]]
        except Exception as e:
            logger.warning("TuShare stock list failed: %s", e)
            return None

    def _fetch_daily_tushare(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        api = self._get_tushare_api()
        if api is None:
            return None
        try:
            ts_code = (
                f"{stock_code}.SH" if stock_code.startswith("6")
                else f"{stock_code}.SZ"
            )
            time.sleep(0.3)
            with no_proxy():
                df = api.daily(
                    ts_code=ts_code,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                )
            if df is None or df.empty:
                return None

            df = df.rename(columns={
                "trade_date": "date",
                "vol": "volume",
            })
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df.sort_values("date").reset_index(drop=True)
            return df[["date", "open", "high", "low", "close", "volume"]].copy()
        except Exception as e:
            logger.warning("TuShare daily %s failed: %s", stock_code, e)
            return None

    # ── Trading calendar ──────────────────────────────────

    # Class-level cache: {(exchange, start, end): [date_str, ...]}
    _trading_dates_cache: dict[tuple, list[str]] = {}

    def get_trading_dates(
        self, start_date: str, end_date: str, exchange: str = "SSE"
    ) -> list[str]:
        """Get trading dates (is_open=1) for a date range. DB-cached, then memory-cached.

        Returns list of YYYY-MM-DD strings sorted ascending.
        """
        cache_key = (exchange, start_date, end_date)
        if cache_key in self._trading_dates_cache:
            return self._trading_dates_cache[cache_key]

        start_d = date.fromisoformat(start_date)
        end_d = date.fromisoformat(end_date)

        # Check DB
        db_rows = (
            self.db.query(TradingCalendar.trade_date)
            .filter(
                TradingCalendar.exchange == exchange,
                TradingCalendar.trade_date >= start_d,
                TradingCalendar.trade_date <= end_d,
                TradingCalendar.is_open == 1,
            )
            .order_by(TradingCalendar.trade_date)
            .all()
        )

        # Check if DB has any calendar data for this range
        db_total = (
            self.db.query(TradingCalendar)
            .filter(
                TradingCalendar.exchange == exchange,
                TradingCalendar.trade_date >= start_d,
                TradingCalendar.trade_date <= end_d,
            )
            .count()
        )

        expected_days = (end_d - start_d).days + 1
        if db_total >= expected_days * 0.9:
            # DB has sufficient data
            result = [r.trade_date.isoformat() for r in db_rows]
            self._trading_dates_cache[cache_key] = result
            return result

        # Fetch from TuShare and cache
        result = self._fetch_and_cache_calendar(start_date, end_date, exchange)
        self._trading_dates_cache[cache_key] = result
        return result

    def _fetch_and_cache_calendar(
        self, start_date: str, end_date: str, exchange: str = "SSE"
    ) -> list[str]:
        """Fetch trading calendar from TuShare and cache to DB."""
        api = self._get_tushare_api()
        if api is None:
            logger.warning("TuShare API not configured, cannot fetch trading calendar")
            return []

        try:
            ts_start = start_date.replace("-", "")
            ts_end = end_date.replace("-", "")
            time.sleep(0.3)
            with no_proxy():
                df = api.trade_cal(
                    exchange=exchange,
                    start_date=ts_start,
                    end_date=ts_end,
                )
            if df is None or df.empty:
                return []

            open_dates: list[str] = []
            for _, row in df.iterrows():
                cal_date_str = str(row["cal_date"])
                is_open = int(row["is_open"])
                cal_date = date.fromisoformat(
                    f"{cal_date_str[:4]}-{cal_date_str[4:6]}-{cal_date_str[6:8]}"
                )

                # Upsert to DB
                existing = (
                    self.db.query(TradingCalendar)
                    .filter(
                        TradingCalendar.exchange == exchange,
                        TradingCalendar.trade_date == cal_date,
                    )
                    .first()
                )
                if existing:
                    existing.is_open = is_open
                else:
                    self.db.add(TradingCalendar(
                        exchange=exchange,
                        trade_date=cal_date,
                        is_open=is_open,
                    ))

                if is_open == 1:
                    open_dates.append(cal_date.isoformat())

            self.db.commit()
            logger.info(
                "Cached trading calendar %s~%s: %d trading days",
                start_date, end_date, len(open_dates),
            )
            return sorted(open_dates)
        except Exception as e:
            logger.warning("TuShare trade_cal failed: %s", e)
            return []

    # ── Batch daily data by date ──────────────────────────

    def _fetch_daily_batch_by_date(self, trade_date: str) -> int:
        """Fetch ALL stocks' daily data for one date via TuShare. Returns record count."""
        api = self._get_tushare_api()
        if api is None:
            return 0

        try:
            ts_date = trade_date.replace("-", "")
            time.sleep(0.5)
            with no_proxy():
                df = api.daily(trade_date=ts_date)
            if df is None or df.empty:
                return 0

            # Convert ts_code (e.g. "000001.SZ") to 6-digit code
            df["stock_code"] = df["ts_code"].str.split(".").str[0]
            trade_d = date.fromisoformat(trade_date)
            count = self._cache_daily_batch(trade_d, df)
            logger.info("Batch fetched %s: %d records", trade_date, count)
            return count
        except Exception as e:
            logger.warning("Batch daily fetch for %s failed: %s", trade_date, e)
            return 0

    def _cache_daily_batch(self, trade_d: date, df: pd.DataFrame) -> int:
        """Bulk upsert daily prices for a single date. More efficient than row-by-row."""
        # Get existing codes for this date
        existing_codes = set(
            r.stock_code for r in
            self.db.query(DailyPrice.stock_code)
            .filter(DailyPrice.trade_date == trade_d)
            .all()
        )

        inserted = 0
        for _, row in df.iterrows():
            code = str(row.get("stock_code", ""))
            if not code or code[:1] not in ("0", "3", "6"):
                continue  # Skip non A-share

            try:
                if code in existing_codes:
                    # Update existing
                    self.db.query(DailyPrice).filter(
                        DailyPrice.stock_code == code,
                        DailyPrice.trade_date == trade_d,
                    ).update({
                        DailyPrice.open: float(row["open"]),
                        DailyPrice.high: float(row["high"]),
                        DailyPrice.low: float(row["low"]),
                        DailyPrice.close: float(row["close"]),
                        DailyPrice.volume: float(row.get("vol", 0)),
                        DailyPrice.amount: float(row.get("amount", 0)),
                    })
                else:
                    self.db.add(DailyPrice(
                        stock_code=code,
                        trade_date=trade_d,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("vol", 0)),
                        amount=float(row.get("amount", 0)),
                    ))
                    inserted += 1
            except Exception as e:
                self.db.rollback()
                logger.debug("Batch cache row error for %s: %s", code, e)
                continue

        try:
            self.db.commit()
        except Exception:
            # Handle concurrent inserts (UNIQUE constraint) — rollback and skip
            self.db.rollback()
            logger.debug("Batch cache commit conflict for %s, skipping", trade_d)
            return 0
        return inserted + len(existing_codes)

    # ── Gap detection and repair ──────────────────────────

    def repair_daily_gaps(
        self,
        start_date: str,
        end_date: str,
        progress_callback=None,
    ) -> dict:
        """Detect and repair missing daily data for all stocks in date range.

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            progress_callback: (current, total, message) -> None

        Returns:
            {"repaired_dates": N, "records_added": N, "total_trading_days": N}
        """
        trading_dates = self.get_trading_dates(start_date, end_date)
        if not trading_dates:
            logger.info("No trading dates in range %s~%s", start_date, end_date)
            return {"repaired_dates": 0, "records_added": 0, "total_trading_days": 0}

        # Count records per trading date
        from sqlalchemy import func as sa_func
        start_d = date.fromisoformat(start_date)
        end_d = date.fromisoformat(end_date)

        date_counts = dict(
            self.db.query(
                DailyPrice.trade_date,
                sa_func.count(DailyPrice.id),
            )
            .filter(
                DailyPrice.trade_date >= start_d,
                DailyPrice.trade_date <= end_d,
            )
            .group_by(DailyPrice.trade_date)
            .all()
        )

        # Threshold: 80% of the max daily count (or 3000 if no data yet)
        max_count = max(date_counts.values()) if date_counts else 0
        threshold = max(int(max_count * 0.8), 3000)

        # Find gap dates
        gap_dates = []
        for td_str in trading_dates:
            td = date.fromisoformat(td_str)
            count = date_counts.get(td, 0)
            if count < threshold:
                gap_dates.append(td_str)

        if not gap_dates:
            logger.info(
                "No data gaps detected in %s~%s (%d trading days, threshold=%d)",
                start_date, end_date, len(trading_dates), threshold,
            )
            return {
                "repaired_dates": 0,
                "records_added": 0,
                "total_trading_days": len(trading_dates),
            }

        logger.info(
            "Detected %d gap dates in %s~%s (threshold=%d), repairing...",
            len(gap_dates), start_date, end_date, threshold,
        )

        total_added = 0
        for i, gap_date in enumerate(gap_dates, 1):
            if progress_callback:
                progress_callback(
                    i, len(gap_dates),
                    f"修复数据缺口: {gap_date} ({i}/{len(gap_dates)})",
                )
            added = self._fetch_daily_batch_by_date(gap_date)
            total_added += added

        logger.info(
            "Gap repair done: %d dates repaired, %d records added",
            len(gap_dates), total_added,
        )
        return {
            "repaired_dates": len(gap_dates),
            "records_added": total_added,
            "total_trading_days": len(trading_dates),
        }

    # ── Index daily data (上证/深成指/创业板) ─────────────

    def get_index_daily_df(
        self,
        index_code: str,
        start_date: str,
        end_date: str,
        force_refresh: bool = False,
    ) -> Optional[pd.DataFrame]:
        """Get index daily OHLCV as DataFrame. DB-cached with API fallback.

        Args:
            index_code: e.g. "000001.SH"
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            force_refresh: bypass cache and re-fetch from API

        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        req_start = date.fromisoformat(start_date)
        req_end = date.fromisoformat(end_date)

        # Check DB cache
        rows = (
            self.db.query(IndexDaily)
            .filter(
                IndexDaily.index_code == index_code,
                IndexDaily.trade_date >= req_start,
                IndexDaily.trade_date <= req_end,
            )
            .order_by(IndexDaily.trade_date)
            .all()
        )

        # Determine if we need to fetch from API
        need_fetch = force_refresh
        if not need_fetch:
            if not rows or len(rows) < 5:
                need_fetch = True
            else:
                earliest = rows[0].trade_date
                latest = rows[-1].trade_date
                if (earliest - req_start).days > 60:
                    need_fetch = True
                elif (req_end - latest).days > 1:
                    need_fetch = True

        if need_fetch:
            df = self._fetch_index_from_api(index_code, start_date, end_date)
            if df is not None and not df.empty:
                self._cache_index_daily(index_code, df)
                return df

        # Return cached data
        if rows:
            return pd.DataFrame([{
                "date": r.trade_date.isoformat() if isinstance(r.trade_date, date) else str(r.trade_date),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            } for r in rows])

        return None

    def _fetch_index_from_api(
        self, index_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """Fetch index daily data. Respects index_data config for primary source."""
        info = INDEX_CODES.get(index_code)
        if not info:
            logger.warning("Unknown index code: %s", index_code)
            return None

        preferred = self._settings.data_sources.index_data
        if preferred == "tushare":
            primary_fn = lambda: self._fetch_index_tushare(index_code, start_date, end_date)
            fallback_fn = lambda: self._fetch_index_akshare(index_code, info, start_date, end_date)
        else:
            primary_fn = lambda: self._fetch_index_akshare(index_code, info, start_date, end_date)
            fallback_fn = lambda: self._fetch_index_tushare(index_code, start_date, end_date)

        df = primary_fn()
        if df is not None and not df.empty:
            return df

        if self._settings.data_sources.fallback_enabled:
            df = fallback_fn()
            if df is not None and not df.empty:
                return df

        return None

    def _fetch_index_akshare(
        self, index_code: str, info: dict, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """Fetch index daily data from AkShare."""
        try:
            import akshare as ak
            time.sleep(0.5)
            with no_proxy():
                df = ak.stock_zh_index_daily_em(
                    symbol=info["ak_symbol"],
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                )
            if df is None or df.empty:
                logger.warning("AkShare returned empty data for %s", index_code)
                return None

            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df.sort_values("date").reset_index(drop=True)
            logger.info(
                "Fetched %s (%s) from AkShare: %d rows (%s ~ %s)",
                info["name"], index_code, len(df),
                df["date"].iloc[0], df["date"].iloc[-1],
            )
            return df[["date", "open", "high", "low", "close", "volume"]].copy()
        except Exception as e:
            logger.warning("AkShare index fetch for %s failed: %s", index_code, e)
            return None

    def _fetch_index_tushare(
        self, index_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """Fetch index daily data from TuShare index_daily API."""
        api = self._get_tushare_api()
        if api is None:
            return None
        try:
            # index_code is already in TuShare ts_code format: "000001.SH"
            time.sleep(0.3)
            with no_proxy():
                df = api.index_daily(
                    ts_code=index_code,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                )
            if df is None or df.empty:
                logger.warning("TuShare returned empty index data for %s", index_code)
                return None

            df = df.rename(columns={
                "trade_date": "date",
                "vol": "volume",
            })
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df.sort_values("date").reset_index(drop=True)
            info = INDEX_CODES.get(index_code, {})
            logger.info(
                "Fetched %s (%s) from TuShare: %d rows (%s ~ %s)",
                info.get("name", index_code), index_code, len(df),
                df["date"].iloc[0], df["date"].iloc[-1],
            )
            return df[["date", "open", "high", "low", "close", "volume"]].copy()
        except Exception as e:
            logger.warning("TuShare index fetch for %s failed: %s", index_code, e)
            return None

    def _cache_index_daily(self, index_code: str, df: pd.DataFrame):
        """Upsert index daily data to DB."""
        for _, row in df.iterrows():
            try:
                d = row.get("date", "")
                trade_d = date.fromisoformat(d) if isinstance(d, str) else d

                existing = (
                    self.db.query(IndexDaily)
                    .filter(
                        IndexDaily.index_code == index_code,
                        IndexDaily.trade_date == trade_d,
                    )
                    .first()
                )
                if existing:
                    existing.open = float(row["open"])
                    existing.high = float(row["high"])
                    existing.low = float(row["low"])
                    existing.close = float(row["close"])
                    existing.volume = float(row.get("volume", 0))
                else:
                    self.db.add(IndexDaily(
                        index_code=index_code,
                        trade_date=trade_d,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume", 0)),
                    ))
            except Exception as e:
                logger.debug("Cache index row error: %s", e)
                continue
        self.db.commit()

    def sync_all_indices(self, start_date: str, end_date: str):
        """Sync all major indices to DB. Idempotent — skips if data exists."""
        for code, info in INDEX_CODES.items():
            try:
                self.get_index_daily_df(code, start_date, end_date)
                logger.info("Index %s (%s) synced", info["name"], code)
            except Exception as e:
                logger.warning("Index sync failed for %s: %s", code, e)
