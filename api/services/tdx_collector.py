"""TDX (pytdx) data collector for A-share market data.

Provides stock lists, daily OHLCV with forward adjustment (前复权),
index data, and industry/concept board data via TDX protocol.

Reference: chanlun-pro/src/chanlun/exchange/exchange_tdx.py
"""

import copy
import datetime
import logging
import time
import warnings
from contextlib import contextmanager
from math import ceil
from typing import Optional

import pandas as pd
from pytdx.errors import TdxConnectionError
from pytdx.hq import TdxHq_API

logger = logging.getLogger(__name__)


# ── TDX server IPs (from CHANLUN-PRO tdx_best_ip.py) ──────────────

TDX_STOCK_IPS = [
    {"ip": "180.153.18.170", "port": 7709},
    {"ip": "218.75.126.9", "port": 7709},
    {"ip": "60.12.136.250", "port": 7709},
    {"ip": "60.191.117.167", "port": 7709},
    {"ip": "shtdx.gtjas.com", "port": 7709},
    {"ip": "sztdx.gtjas.com", "port": 7709},
    {"ip": "110.41.147.114", "port": 7709, "name": "深圳双线1"},
    {"ip": "110.41.2.72", "port": 7709, "name": "深圳双线2"},
    {"ip": "110.41.4.4", "port": 7709, "name": "深圳双线3"},
    {"ip": "175.178.112.197", "port": 7709, "name": "深圳双线4"},
    {"ip": "175.178.128.227", "port": 7709, "name": "深圳双线5"},
    {"ip": "110.41.154.219", "port": 7709, "name": "深圳双线6"},
    {"ip": "124.70.176.52", "port": 7709, "name": "上海双线1"},
    {"ip": "122.51.120.217", "port": 7709, "name": "上海双线2"},
    {"ip": "123.60.186.45", "port": 7709, "name": "上海双线3"},
    {"ip": "123.60.164.122", "port": 7709, "name": "上海双线4"},
    {"ip": "111.229.247.189", "port": 7709, "name": "上海双线5"},
    {"ip": "124.70.199.56", "port": 7709, "name": "上海双线6"},
    {"ip": "121.36.54.217", "port": 7709, "name": "北京双线1"},
    {"ip": "121.36.81.195", "port": 7709, "name": "北京双线2"},
    {"ip": "123.249.15.60", "port": 7709, "name": "北京双线3"},
    {"ip": "124.71.85.110", "port": 7709, "name": "广州双线1"},
    {"ip": "139.9.51.18", "port": 7709, "name": "广州双线2"},
    {"ip": "139.159.239.163", "port": 7709, "name": "广州双线3"},
    {"ip": "122.51.232.182", "port": 7709, "name": "上海双线7"},
    {"ip": "118.25.98.114", "port": 7709, "name": "上海双线8"},
    {"ip": "121.36.225.169", "port": 7709, "name": "上海双线9"},
    {"ip": "123.60.70.228", "port": 7709, "name": "上海双线10"},
    {"ip": "123.60.73.44", "port": 7709, "name": "上海双线11"},
    {"ip": "124.70.133.119", "port": 7709, "name": "上海双线12"},
    {"ip": "124.71.187.72", "port": 7709, "name": "上海双线13"},
    {"ip": "124.71.187.122", "port": 7709, "name": "上海双线14"},
    {"ip": "129.204.230.128", "port": 7709, "name": "深圳双线7"},
    {"ip": "124.70.75.113", "port": 7709, "name": "北京双线4"},
    {"ip": "124.71.9.153", "port": 7709, "name": "广州双线4"},
    {"ip": "123.60.84.66", "port": 7709, "name": "上海双线15"},
    {"ip": "111.230.186.52", "port": 7709, "name": "深圳双线8"},
    {"ip": "120.46.186.223", "port": 7709, "name": "北京双线5"},
    {"ip": "124.70.22.210", "port": 7709, "name": "北京双线6"},
    {"ip": "139.9.133.247", "port": 7709, "name": "北京双线7"},
    {"ip": "116.205.163.254", "port": 7709, "name": "广州双线5"},
    {"ip": "116.205.171.132", "port": 7709, "name": "广州双线6"},
    {"ip": "116.205.183.150", "port": 7709, "name": "广州双线7"},
]

# TDX index code mapping: our code → (market, tdx_code)
_INDEX_MAP = {
    "000001.SH": (1, "999999"),  # 上证指数 uses 999999 in TDX
    "399001.SZ": (0, "399001"),  # 深证成指
    "399006.SZ": (0, "399006"),  # 创业板指
    "000300.SH": (1, "000300"),  # 沪深300
    "000016.SH": (1, "000016"),  # 上证50
    "000905.SH": (1, "000905"),  # 中证500
}

# TDX frequency map
_FREQ_MAP = {
    "1m": 8, "5m": 0, "15m": 1, "30m": 2, "60m": 3,
    "d": 9, "w": 5, "m": 6, "y": 11,
}


class TdxCollector:
    """TDX data collector using pytdx TCP protocol."""

    def __init__(self):
        self._best_ip: Optional[dict] = None
        self._ip_cache_time: float = 0.0
        self._xdxr_cache: dict[str, pd.DataFrame] = {}  # key: "market_code"

    # ── Connection management ──────────────────────────

    def _get_best_ip(self) -> dict:
        """Get the best TDX server IP. Cached for 24 hours."""
        from api.utils.network import no_proxy

        now = time.time()
        if self._best_ip and (now - self._ip_cache_time) < 86400:
            return self._best_ip

        logger.info("Selecting best TDX server IP...")
        best = None
        best_time = datetime.timedelta(9, 9, 0)

        with no_proxy():
            for ip_info in TDX_STOCK_IPS:
                try:
                    api = TdxHq_API()
                    t1 = datetime.datetime.now()
                    with api.connect(ip_info["ip"], ip_info["port"], time_out=0.7):
                        res = api.get_security_list(0, 1)
                        if res is not None and len(res) > 0:
                            elapsed = datetime.datetime.now() - t1
                            if elapsed < best_time:
                                best_time = elapsed
                                best = ip_info
                                # Good enough — under 100ms
                                if elapsed.total_seconds() < 0.1:
                                    break
                except Exception:
                    continue

        if best is None:
            # Fallback to first IP
            best = TDX_STOCK_IPS[0]
            logger.warning("No TDX server responded to ping, using fallback: %s", best["ip"])
        else:
            logger.info("Best TDX server: %s (%.0fms)", best["ip"], best_time.total_seconds() * 1000)

        self._best_ip = best
        self._ip_cache_time = now
        return best

    @contextmanager
    def _connect(self):
        """Get a connected TDX client. Resets IP on connection error.

        Clears proxy env vars since pytdx uses raw TCP sockets.
        """
        from api.utils.network import no_proxy

        ip_info = self._get_best_ip()
        client = TdxHq_API(raise_exception=True, auto_retry=True)
        try:
            with no_proxy(), client.connect(ip_info["ip"], ip_info["port"], time_out=10):
                yield client
        except TdxConnectionError:
            logger.warning("TDX connection failed, resetting IP cache")
            self._best_ip = None
            self._ip_cache_time = 0.0
            raise

    # ── Market code helpers ────────────────────────────

    @staticmethod
    def _code_to_market(code: str) -> int:
        """Map 6-digit stock code to TDX market code."""
        if code.startswith("6"):
            return 1  # SH
        return 0  # SZ (0xx, 3xx)

    @staticmethod
    def _for_sz(code: str) -> str:
        """Classify Shenzhen stock type (from CHANLUN-PRO)."""
        prefix2 = code[:2]
        if prefix2 in ("00", "30", "02"):
            return "stock_cn"
        if prefix2 == "39":
            return "index_cn"
        if prefix2 in ("15", "16"):
            return "etf_cn"
        prefix3 = code[:3]
        bond_prefixes = {
            "101", "104", "105", "106", "107", "108", "109",
            "111", "112", "114", "115", "116", "117", "118",
            "119", "123", "127", "128", "131", "139",
        }
        if prefix3 in bond_prefixes:
            return "bond_cn"
        if prefix2 == "20":
            return "stockB_cn"
        return "undefined"

    @staticmethod
    def _for_sh(code: str) -> str:
        """Classify Shanghai stock type (from CHANLUN-PRO)."""
        if code[0] == "6":
            return "stock_cn"
        prefix3 = code[:3]
        if prefix3 in ("000", "880", "999"):
            return "index_cn"
        prefix2 = code[:2]
        if prefix2 in ("51", "58"):
            return "etf_cn"
        bond_prefixes = {
            "102", "110", "113", "120", "122", "124", "130",
            "132", "133", "134", "135", "136", "140", "141",
            "143", "144", "147", "148",
        }
        if prefix3 in bond_prefixes:
            return "bond_cn"
        return "undefined"

    # ── Stock list ─────────────────────────────────────

    def fetch_stock_list(self) -> pd.DataFrame:
        """Fetch all A-share stocks from TDX.

        Returns DataFrame with columns: code, name, market, industry, list_date
        """
        all_stocks = []
        seen_codes = set()

        with self._connect() as client:
            for market in (0, 1):  # 0=SZ, 1=SH
                count = client.get_security_count(market)
                for i in range(int(count / 1000) + 1):
                    try:
                        batch = client.to_df(client.get_security_list(market, i * 1000))
                    except Exception as e:
                        logger.debug("Skipping page %d market %d: %s", i, market, e)
                        continue
                    for _, row in batch.iterrows():
                        code = str(row["code"])
                        name = str(row["name"])

                        # Classify stock type
                        stype = self._for_sz(code) if market == 0 else self._for_sh(code)
                        if stype != "stock_cn":
                            continue
                        if code in seen_codes:
                            continue
                        seen_codes.add(code)

                        mkt = "SZ" if market == 0 else "SH"
                        all_stocks.append({
                            "code": code,
                            "name": name,
                            "market": mkt,
                            "industry": "",
                            "list_date": "",
                        })

        logger.info("TDX stock list: %d stocks", len(all_stocks))
        return pd.DataFrame(all_stocks)

    # ── Daily K-lines with forward adjustment ──────────

    def fetch_daily(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """Fetch daily OHLCV with forward adjustment (前复权).

        Args:
            stock_code: 6-digit code like "000001"
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD

        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        market = self._code_to_market(stock_code)

        # Calculate how many pages we need (700 bars per page)
        try:
            d_start = datetime.date.fromisoformat(start_date)
            d_end = datetime.date.fromisoformat(end_date)
            days = (d_end - d_start).days
            pages = max(2, ceil(days / 500))  # ~500 trading days per 700 calendar days
            pages = min(pages, 12)  # Cap at 12 pages (8400 bars)
        except Exception:
            pages = 4

        try:
            with self._connect() as client:
                # Fetch raw K-line data (paginated)
                frames = []
                for i in range(1, pages + 1):
                    data = client.to_df(
                        client.get_security_bars(9, market, stock_code, (i - 1) * 700, 700)
                    )
                    if data is None or len(data) == 0:
                        break
                    frames.append(data)

                if not frames:
                    return None

                ks = pd.concat(frames, axis=0, sort=False)
                if len(ks) == 0:
                    return None

                ks["date"] = pd.to_datetime(ks["datetime"])
                ks = ks.drop_duplicates(["date"], keep="last").sort_values("date")

                # Fetch xdxr info for forward adjustment
                xdxr = client.to_df(client.get_xdxr_info(market, stock_code))
                if len(xdxr) > 0:
                    xdxr["date"] = pd.to_datetime(
                        xdxr["year"].astype(str) + "-"
                        + xdxr["month"].astype(str) + "-"
                        + xdxr["day"].astype(str)
                    )

                # Apply forward adjustment
                ks = self._apply_qfq(ks, xdxr)

                # Rename and filter columns
                ks["volume"] = ks["vol"]
                ks["date_str"] = ks["date"].dt.strftime("%Y-%m-%d")

                # Filter to requested date range
                mask = (ks["date_str"] >= start_date) & (ks["date_str"] <= end_date)
                result = ks.loc[mask, ["date_str", "open", "high", "low", "close", "volume"]].copy()
                result = result.rename(columns={"date_str": "date"})
                result = result.reset_index(drop=True)

                if len(result) == 0:
                    return None
                return result

        except TdxConnectionError:
            logger.warning("TDX connection error fetching daily for %s", stock_code)
            self._best_ip = None
            self._ip_cache_time = 0.0
            return None
        except Exception as e:
            logger.warning("TDX daily fetch failed for %s: %s", stock_code, e)
            return None

    @staticmethod
    def _apply_qfq(ks: pd.DataFrame, xdxr: pd.DataFrame) -> pd.DataFrame:
        """Apply forward adjustment (前复权) to K-line data.

        Ported from CHANLUN-PRO klines_fq() (lines 614-697).
        """
        if len(xdxr) == 0:
            return ks

        info = copy.deepcopy(xdxr.query("category==1"))
        if len(info) == 0:
            return ks

        # Set date as index for alignment
        info = info.set_index("date")
        ks = ks.assign(if_trade=1)
        ks = ks.set_index("date")

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning)

            # Merge xdxr category markers into K-line data
            data = pd.concat(
                [ks, info.loc[ks.index[0]:ks.index[-1], ["category"]]],
                axis=1,
            )
            data["if_trade"] = data["if_trade"].fillna(0)
            data = data.ffill()

            # Merge dividend fields
            data = pd.concat(
                [data, info.loc[ks.index[0]:ks.index[-1],
                 ["fenhong", "peigu", "peigujia", "songzhuangu"]]],
                axis=1,
            )

        data = data.fillna(0)

        # Calculate pre-close
        data["preclose"] = (
            data["close"].shift(1) * 10
            - data["fenhong"]
            + data["peigu"] * data["peigujia"]
        ) / (10 + data["peigu"] + data["songzhuangu"])

        # Forward adjustment factor
        data["adj"] = (
            (data["preclose"].shift(-1) / data["close"]).fillna(1)[::-1].cumprod()
        )

        # Apply adjustment to OHLC
        for col in ["open", "high", "low", "close"]:
            data[col] = round(data[col] * data["adj"], 2)

        # Restore date column and filter to trading days
        data = data[data["if_trade"] == 1]
        data = data.reset_index()
        return data

    # ── Daily K-lines with raw prices + adj_factor ─────

    def fetch_daily_raw(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """Fetch daily raw OHLCV + adj_factor (NOT forward-adjusted).

        Args:
            stock_code: 6-digit code like "000001"
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, adj_factor
        """
        market = self._code_to_market(stock_code)

        # Calculate how many pages we need (700 bars per page)
        try:
            d_start = datetime.date.fromisoformat(start_date)
            d_end = datetime.date.fromisoformat(end_date)
            days = (d_end - d_start).days
            pages = max(2, ceil(days / 500))  # ~500 trading days per 700 calendar days
            pages = min(pages, 12)  # Cap at 12 pages (8400 bars)
        except Exception:
            pages = 4

        try:
            with self._connect() as client:
                # Fetch raw K-line data (paginated)
                frames = []
                for i in range(1, pages + 1):
                    data = client.to_df(
                        client.get_security_bars(9, market, stock_code, (i - 1) * 700, 700)
                    )
                    if data is None or len(data) == 0:
                        break
                    frames.append(data)

                if not frames:
                    return None

                ks = pd.concat(frames, axis=0, sort=False)
                if len(ks) == 0:
                    return None

                ks["date"] = pd.to_datetime(ks["datetime"])
                ks = ks.drop_duplicates(["date"], keep="last").sort_values("date")

                # Fetch xdxr info for adjustment factor computation
                xdxr = client.to_df(client.get_xdxr_info(market, stock_code))
                if len(xdxr) > 0:
                    xdxr["date"] = pd.to_datetime(
                        xdxr["year"].astype(str) + "-"
                        + xdxr["month"].astype(str) + "-"
                        + xdxr["day"].astype(str)
                    )

                # Compute adjustment factor (without modifying OHLC)
                adj_series = self._compute_adj_factor(ks, xdxr)

                # Build result with raw prices + adj_factor
                ks["volume"] = ks["vol"]
                ks["adj_factor"] = adj_series.values
                ks["date_str"] = ks["date"].dt.strftime("%Y-%m-%d")

                # Filter to requested date range
                mask = (ks["date_str"] >= start_date) & (ks["date_str"] <= end_date)
                result = ks.loc[mask, ["date_str", "open", "high", "low", "close", "volume", "adj_factor"]].copy()
                result = result.rename(columns={"date_str": "date"})
                result = result.reset_index(drop=True)

                if len(result) == 0:
                    return None
                return result

        except TdxConnectionError:
            logger.warning("TDX connection error fetching daily_raw for %s", stock_code)
            self._best_ip = None
            self._ip_cache_time = 0.0
            return None
        except Exception as e:
            logger.warning("TDX daily_raw fetch failed for %s: %s", stock_code, e)
            return None

    @staticmethod
    def _compute_adj_factor(ks: pd.DataFrame, xdxr: pd.DataFrame) -> pd.Series:
        """Compute forward-adjustment factor without modifying K-line prices.

        Returns a Series of cumulative adjustment factors aligned to ks rows.
        Multiply raw OHLC by adj_factor to get forward-adjusted (前复权) prices.
        """
        ones = pd.Series(1.0, index=ks.index)

        if len(xdxr) == 0:
            return ones

        info = copy.deepcopy(xdxr.query("category==1"))
        if len(info) == 0:
            return ones

        # Set date as index for alignment
        info = info.set_index("date")
        ks_tmp = ks.assign(if_trade=1).set_index("date")

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning)

            # Merge xdxr category markers into K-line data
            data = pd.concat(
                [ks_tmp, info.loc[ks_tmp.index[0]:ks_tmp.index[-1], ["category"]]],
                axis=1,
            )
            data["if_trade"] = data["if_trade"].fillna(0)
            data = data.ffill()

            # Merge dividend fields
            data = pd.concat(
                [data, info.loc[ks_tmp.index[0]:ks_tmp.index[-1],
                 ["fenhong", "peigu", "peigujia", "songzhuangu"]]],
                axis=1,
            )

        data = data.fillna(0)

        # Calculate pre-close (same formula as _apply_qfq)
        data["preclose"] = (
            data["close"].shift(1) * 10
            - data["fenhong"]
            + data["peigu"] * data["peigujia"]
        ) / (10 + data["peigu"] + data["songzhuangu"])

        # Forward adjustment factor
        data["adj"] = (
            (data["preclose"].shift(-1) / data["close"]).fillna(1)[::-1].cumprod()
        )

        # Filter back to trading days and return adj series
        data = data[data["if_trade"] == 1]
        data = data.reset_index()
        return data["adj"].reset_index(drop=True)

    # ── Index K-lines ──────────────────────────────────

    def fetch_index_daily(
        self, index_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """Fetch index daily OHLCV. No forward adjustment needed.

        Args:
            index_code: e.g. "000001.SH"
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD

        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        mapping = _INDEX_MAP.get(index_code)
        if not mapping:
            logger.warning("Unknown index code for TDX: %s", index_code)
            return None

        market, tdx_code = mapping

        try:
            d_start = datetime.date.fromisoformat(start_date)
            d_end = datetime.date.fromisoformat(end_date)
            days = (d_end - d_start).days
            pages = max(2, ceil(days / 500))
            pages = min(pages, 12)
        except Exception:
            pages = 4

        try:
            with self._connect() as client:
                frames = []
                for i in range(1, pages + 1):
                    data = client.to_df(
                        client.get_index_bars(9, market, tdx_code, (i - 1) * 700, 700)
                    )
                    if data is None or len(data) == 0:
                        break
                    frames.append(data)

                if not frames:
                    return None

                ks = pd.concat(frames, axis=0, sort=False)
                ks["date"] = pd.to_datetime(ks["datetime"]).dt.strftime("%Y-%m-%d")
                ks = ks.drop_duplicates(["date"], keep="last").sort_values("date")

                # Filter date range
                mask = (ks["date"] >= start_date) & (ks["date"] <= end_date)
                result = ks.loc[mask, ["date", "open", "high", "low", "close", "vol"]].copy()
                result = result.rename(columns={"vol": "volume"})
                result = result.reset_index(drop=True)

                if len(result) == 0:
                    return None

                logger.info("TDX index %s: %d rows (%s ~ %s)",
                            index_code, len(result), result["date"].iloc[0], result["date"].iloc[-1])
                return result

        except TdxConnectionError:
            logger.warning("TDX connection error fetching index %s", index_code)
            self._best_ip = None
            self._ip_cache_time = 0.0
            return None
        except Exception as e:
            logger.warning("TDX index fetch failed for %s: %s", index_code, e)
            return None

    # ── Industry / Concept boards ──────────────────────

    def fetch_industry_boards(self) -> dict[str, list[str]]:
        """Fetch industry classification from TDX.

        Returns {industry_name: [stock_code_1, stock_code_2, ...]}
        """
        return self._fetch_block_info("block.dat")

    def fetch_concept_boards(self) -> dict[str, list[str]]:
        """Fetch concept boards from TDX.

        Returns {concept_name: [stock_code_1, stock_code_2, ...]}
        """
        return self._fetch_block_info("block_gn.dat")

    def _fetch_block_info(self, block_file: str) -> dict[str, list[str]]:
        """Parse TDX block info file into {board_name: [codes]}."""
        try:
            with self._connect() as client:
                data = client.get_and_parse_block_info(block_file)

            if not data:
                return {}

            boards: dict[str, list[str]] = {}
            for item in data:
                name = item.get("blockname", "").strip()
                code = item.get("code", "").strip()
                if not name or not code:
                    continue
                # Only include A-share stock codes (0xx, 3xx, 6xx)
                if code[:1] not in ("0", "3", "6"):
                    continue
                if name not in boards:
                    boards[name] = []
                boards[name].append(code)

            logger.info("TDX %s: %d boards, %d total mappings",
                        block_file, len(boards), sum(len(v) for v in boards.values()))
            return boards

        except TdxConnectionError:
            logger.warning("TDX connection error fetching %s", block_file)
            self._best_ip = None
            self._ip_cache_time = 0.0
            return {}
        except Exception as e:
            logger.warning("TDX block info fetch failed for %s: %s", block_file, e)
            return {}
