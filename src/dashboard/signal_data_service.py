"""信号数据服务 - 连接信号生成系统与仪表盘

提供实时历史数据适配器和信号获取服务。
"""

import json
import os
import sys
import threading
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

# 调试日志
_DEBUG_LOG_PATH = Path(__file__).parent.parent.parent / "logs" / "signal_debug.log"
_DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def _debug_log(msg: str):
    """写入调试日志"""
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%H:%M:%S')} | {msg}\n")
        print(msg, file=sys.stderr, flush=True)
    except:
        pass

# 导入前清理代理
_PROXY_VARS = ['HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY', 'https_proxy', 'ALL_PROXY', 'all_proxy']
for _var in _PROXY_VARS:
    os.environ.pop(_var, None)
os.environ['NO_PROXY'] = '*'

import pandas as pd

try:
    import akshare as ak
except ImportError:
    ak = None
    _debug_log("[WARN] akshare not available")

try:
    import tushare as ts
except ImportError:
    ts = None
    _debug_log("[WARN] tushare not available")

from src.utils.network import no_proxy, with_proxy
from src.utils.config import Config
from src.services.news_service import NewsService
from src.services.api_guard import get_api_guard


class LiveHistoricalDataAdapter:
    """实时历史数据适配器 - 默认使用 TuShare 获取历史K线数据

    实现 StorageProtocol 接口，供 DailySignalGenerator 使用。
    优先使用 TuShare，失败时回退到 AkShare。

    Usage:
        adapter = LiveHistoricalDataAdapter()
        df = adapter.load_daily("000001", "20240101", "20240410")
    """

    # 缓存已获取的数据，避免重复请求
    _cache: dict = {}
    _cache_lock = threading.Lock()
    _tushare_api = None

    _tushare_call_times: list = []  # 记录每次调用的时间戳
    _rate_lock = threading.Lock()

    def __init__(self):
        """初始化适配器，加载 TuShare Token 和限速配置"""
        self._tushare_call_times = []
        self._init_tushare()
        # 从 config 读取 TuShare 限速值
        try:
            from pathlib import Path
            config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"
            config = Config(str(config_path))
            self._tushare_max_per_min = config.get("data_sources.tushare.rate_limit", 450)
        except Exception:
            self._tushare_max_per_min = 450
        # 初始化数据库连接（用于日线数据缓存）
        self._db = self._init_db()

    def _init_db(self):
        """初始化数据库"""
        try:
            from pathlib import Path
            from src.data_storage.database import Database
            db_path = Path(__file__).parent.parent.parent / "data" / "stockagent.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db = Database(str(db_path))
            db.init_tables()
            return db
        except Exception as e:
            _debug_log(f"[WARN] 数据库初始化失败，将不使用本地缓存: {e}")
            return None

    def _init_tushare(self):
        """初始化 TuShare API"""
        if ts is None:
            _debug_log("[WARN] TuShare 未安装")
            return

        try:
            from pathlib import Path
            config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"
            config = Config(str(config_path))
            token = config.get("data_sources.tushare.token", "")

            if token and token != "YOUR_TUSHARE_TOKEN":
                self._tushare_api = ts.pro_api(token)
                _debug_log("[INFO] TuShare API 初始化成功")
            else:
                _debug_log("[WARN] TuShare Token 未配置")
        except Exception as e:
            _debug_log(f"[ERROR] TuShare 初始化失败: {e}")

    def _convert_code_for_tushare(self, stock_code: str) -> str:
        """转换股票代码为 TuShare 格式 (000001 -> 000001.SZ)"""
        clean_code = stock_code.split('.')[0]
        if clean_code.startswith('6'):
            return f"{clean_code}.SH"
        else:
            return f"{clean_code}.SZ"

    def _format_date_dash(self, date_str: str) -> str:
        """统一日期格式为 YYYY-MM-DD"""
        d = date_str.replace('-', '')
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    def _df_to_rows(self, df: pd.DataFrame) -> list:
        """将 DataFrame 转为数据库行 [(date_str, o, h, l, c, v, a), ...]"""
        rows = []
        for _, row in df.iterrows():
            date_val = row['date']
            if hasattr(date_val, 'strftime'):
                date_str = date_val.strftime('%Y-%m-%d')
            else:
                date_str = str(date_val)[:10]
            rows.append((
                date_str,
                float(row.get('open', 0)),
                float(row.get('high', 0)),
                float(row.get('low', 0)),
                float(row.get('close', 0)),
                float(row.get('volume', 0)),
                float(row.get('amount', 0)) if 'amount' in row.index else 0.0,
            ))
        return rows

    def _rows_to_df(self, rows: list) -> pd.DataFrame:
        """将数据库行转为 DataFrame（与 API 输出格式一致）"""
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
        df['date'] = pd.to_datetime(df['date'])
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')
        return df.sort_values('date').reset_index(drop=True)

    def load_daily(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """加载股票日线数据（数据库优先，只补缺失数据）

        流程: 内存缓存 → 数据库 → API（仅补缺失日期）→ 存回数据库

        Args:
            stock_code: 股票代码 (如 "000001" 或 "000001.SZ")
            start_date: 开始日期 (YYYYMMDD 或 YYYY-MM-DD)
            end_date: 结束日期

        Returns:
            包含 date, open, high, low, close, volume 列的 DataFrame
        """
        clean_code = stock_code.split('.')[0]

        # 1. 检查内存缓存
        cache_key = f"{clean_code}_{start_date}_{end_date}"
        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        # 格式化日期
        start_fmt = self._format_date_yyyymmdd(start_date) if start_date else "20200101"
        end_fmt = self._format_date_yyyymmdd(end_date) if end_date else datetime.now().strftime("%Y%m%d")
        start_dash = self._format_date_dash(start_fmt)
        end_dash = self._format_date_dash(end_fmt)

        # 2. 从数据库查询
        db_df = pd.DataFrame()
        if self._db is not None:
            try:
                rows = self._db.load_daily_data(clean_code, start_dash, end_dash)
                if rows:
                    db_df = self._rows_to_df(rows)
            except Exception as e:
                _debug_log(f"[WARN] load_daily({clean_code}): 数据库读取失败 - {e}")

        # 3. 判断数据库数据是否完整
        if not db_df.empty:
            db_latest = db_df['date'].max()
            db_earliest = db_df['date'].min()
            end_dt = pd.to_datetime(end_dash)
            start_dt = pd.to_datetime(start_dash)

            # 检查1: 最新日期是否接近 end_date
            missing_days = (end_dt - db_latest).days

            # 检查2: 历史数据是否覆盖到 start_date（允许7天误差）
            history_ok = (db_earliest - start_dt).days <= 7

            if missing_days <= 1 and history_ok:
                # 数据完整且最新 → 直接返回
                with self._cache_lock:
                    self._cache[cache_key] = db_df
                return db_df

            if missing_days <= 10 and history_ok:
                # 历史够但缺最近几天 → 只补缺失日期
                fetch_start = (db_latest + pd.Timedelta(days=1)).strftime("%Y%m%d")
                new_df = self._load_from_tushare(clean_code, fetch_start, end_fmt)
                if new_df is None or new_df.empty:
                    new_df = self._load_from_akshare(clean_code, fetch_start, end_fmt)

                if new_df is not None and not new_df.empty:
                    self._save_to_db(clean_code, new_df)
                    db_df = pd.concat([db_df, new_df], ignore_index=True)
                    db_df = db_df.drop_duplicates(subset='date').sort_values('date').reset_index(drop=True)

                with self._cache_lock:
                    self._cache[cache_key] = db_df
                return db_df

            # 数据不完整（最新日期太旧 或 历史不足3年）→ 进入步骤4获取全量
            _debug_log(
                f"[DEBUG] load_daily({clean_code}): 数据库不完整"
                f"（最新={db_latest.strftime('%Y-%m-%d')}, "
                f"最早={db_earliest.strftime('%Y-%m-%d')}, "
                f"缺{missing_days}天, 历史{'够' if history_ok else '不足'}），重新获取全量"
            )

        # 4. 数据库无数据或严重不足 → 从 API 获取全量（失败则等 60s 重试）
        import time
        max_retries = 5
        for retry in range(max_retries):
            # 尝试 TuShare
            ts_result = self._load_from_tushare(clean_code, start_fmt, end_fmt)

            # TuShare 成功连接但该股票无数据（如 B 股）→ 直接跳过，不重试
            if isinstance(ts_result, str) and ts_result == self._TUSHARE_NO_DATA:
                df = self._load_from_akshare(clean_code, start_fmt, end_fmt)
                if df is None or df.empty:
                    _debug_log(f"[INFO] load_daily({clean_code}): 该股票无日线数据，跳过")
                    return pd.DataFrame()
                break

            df = ts_result if isinstance(ts_result, pd.DataFrame) and not ts_result.empty else None

            # TuShare 连接失败 → 尝试 AkShare
            if df is None:
                df = self._load_from_akshare(clean_code, start_fmt, end_fmt)

            # 成功获取数据
            if df is not None and not df.empty:
                break

            # 全部失败 → 等 60s 后重试
            if retry < max_retries - 1:
                _debug_log(
                    f"[WARN] load_daily({clean_code}): 所有数据源失败"
                    f"（第{retry+1}次），等待60s后重试..."
                )
                time.sleep(60)
            else:
                _debug_log(
                    f"[ERROR] load_daily({clean_code}): 重试{max_retries}次仍失败，跳过该股票"
                )
                return pd.DataFrame()

        # 5. 存入数据库
        self._save_to_db(clean_code, df)

        # 6. 缓存到内存
        with self._cache_lock:
            self._cache[cache_key] = df
        return df

    def _save_to_db(self, stock_code: str, df: pd.DataFrame):
        """将 DataFrame 保存到数据库"""
        if self._db is None or df is None or df.empty:
            return
        try:
            rows = self._df_to_rows(df)
            saved = self._db.save_daily_data(stock_code, rows)
            if saved > 0:
                _debug_log(f"[DEBUG] load_daily({stock_code}): 存入数据库 {saved} 行")
        except Exception as e:
            _debug_log(f"[WARN] load_daily({stock_code}): 数据库写入失败 - {e}")

    def _tushare_rate_wait(self):
        """TuShare 限速等待

        滑动窗口限速：记录最近 60 秒内的调用次数，
        达到阈值时 sleep 直到窗口内调用数降到安全值。
        """
        import time
        with self._rate_lock:
            now = time.time()
            # 清除超过 60 秒的旧记录
            self._tushare_call_times = [t for t in self._tushare_call_times if now - t < 60]

            if len(self._tushare_call_times) >= self._tushare_max_per_min:
                # 需要等待：计算最早一条记录还有多久过期
                oldest = self._tushare_call_times[0]
                wait_time = 60 - (now - oldest) + 0.5  # 多等 0.5s 安全余量
                if wait_time > 0:
                    _debug_log(f"[INFO] TuShare限速: 已达 {len(self._tushare_call_times)}/min，等待 {wait_time:.1f}s")
                    time.sleep(wait_time)
                    # 清理过期记录
                    now = time.time()
                    self._tushare_call_times = [t for t in self._tushare_call_times if now - t < 60]

            self._tushare_call_times.append(time.time())

    # 特殊返回值：TuShare 成功连接但该股票无数据（如 B 股）
    _TUSHARE_NO_DATA = "NO_DATA"

    def _load_from_tushare(self, stock_code: str, start_date: str, end_date: str):
        """从 TuShare 加载数据（直连，不走代理）

        Returns:
            DataFrame: 成功获取数据
            "NO_DATA": TuShare 成功连接但该股票无数据（不应重试）
            None: 连接失败（可重试）
        """
        if self._tushare_api is None:
            return None

        import time

        for attempt in range(2):
            try:
                ts_code = self._convert_code_for_tushare(stock_code)
                if attempt == 0:
                    _debug_log(f"[DEBUG] load_daily({stock_code}): TuShare({ts_code})...")

                self._tushare_rate_wait()

                with no_proxy():
                    df = self._tushare_api.daily(
                        ts_code=ts_code,
                        start_date=start_date,
                        end_date=end_date
                    )

                if df is None or df.empty:
                    # 成功连接但无数据 → 该股票在 TuShare 中没有日线数据
                    _debug_log(f"[DEBUG] load_daily({stock_code}): TuShare无数据")
                    return self._TUSHARE_NO_DATA

                column_mapping = {
                    'trade_date': 'date',
                    'ts_code': 'code',
                    'open': 'open',
                    'high': 'high',
                    'low': 'low',
                    'close': 'close',
                    'vol': 'volume',
                    'amount': 'amount'
                }
                df = df.rename(columns=column_mapping)
                df = df.sort_values('date').reset_index(drop=True)
                df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

                numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount']
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')

                _debug_log(f"[DEBUG] load_daily({stock_code}): TuShare成功 {len(df)} 行")
                return df

            except Exception as e:
                err_msg = str(e)
                if "每分钟最多访问" in err_msg and attempt == 0:
                    _debug_log(f"[WARN] load_daily({stock_code}): TuShare频率限制，等待60s...")
                    time.sleep(60)
                    with self._rate_lock:
                        self._tushare_call_times.clear()
                    continue
                _debug_log(f"[WARN] load_daily({stock_code}): TuShare失败 - {e}")
                return None

        return None

    def _load_from_akshare(self, stock_code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """从 AkShare 加载数据（先代理后直连）"""
        if ak is None:
            return None

        for proxy_mode, mode_name in [(with_proxy, "代理"), (no_proxy, "直连")]:
            try:
                _debug_log(f"[DEBUG] load_daily({stock_code}): AkShare({mode_name})...")

                with proxy_mode():
                    df = ak.stock_zh_a_hist(
                        symbol=stock_code,
                        period="daily",
                        start_date=start_date,
                        end_date=end_date,
                        adjust="qfq"
                    )

                if df is None or df.empty:
                    continue

                # AkShare 列名映射
                column_mapping = {
                    '日期': 'date',
                    '开盘': 'open',
                    '最高': 'high',
                    '最低': 'low',
                    '收盘': 'close',
                    '成交量': 'volume',
                    '成交额': 'amount'
                }
                df = df.rename(columns=column_mapping)

                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'])

                numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount']
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')

                _debug_log(f"[DEBUG] load_daily({stock_code}): AkShare({mode_name})成功 {len(df)} 行")
                return df

            except Exception as e:
                _debug_log(f"[WARN] load_daily({stock_code}): AkShare({mode_name})失败 - {e}")

        return None

    def _format_date_yyyymmdd(self, date_str: str) -> str:
        """统一日期格式为 YYYYMMDD"""
        if '-' in date_str:
            return date_str.replace('-', '')
        return date_str

    def clear_cache(self):
        """清除数据缓存"""
        self._cache.clear()


class SignalDataService:
    """信号数据服务 - 获取和缓存交易信号

    缓存策略：
    - 日线数据每天只更新一次，同一交易日的信号结果持久化到文件
    - 只有日期变化或用户主动刷新时才重新计算
    - 缓存文件存储在 data/signal_cache/ 目录

    Usage:
        service = SignalDataService()
        buy_signals = service.get_buy_signals(top_n=10)
        sell_signals = service.get_sell_signals(top_n=10)
    """

    # 内存缓存
    _signal_cache: dict = {}
    _stock_list_cache: list = []

    # 缓存文件目录
    _CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "signal_cache"

    def __init__(self):
        self._adapter = LiveHistoricalDataAdapter()
        self._generator = None  # SignalCombiner, 延迟初始化
        self._indicator_calculator = None  # IndicatorCalculator, 延迟初始化
        self._stock_name_map: dict[str, str] = {}  # code → name 映射
        # 确保缓存目录存在
        self._CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _get_combiner(self):
        """获取信号合成器（延迟导入避免 XGBoost 依赖）"""
        if self._generator is None:
            try:
                # 直接导入 SignalCombiner，避免触发 XGBoost 依赖
                from src.signals.signal_combiner import SignalCombiner
                from src.indicators import IndicatorCalculator
                self._generator = SignalCombiner()
                self._indicator_calculator = IndicatorCalculator(
                    config=self._generator.get_indicator_config()
                )
                _debug_log("[INFO] SignalCombiner 初始化成功")
            except Exception as e:
                _debug_log(f"[ERROR] SignalCombiner 初始化失败: {e}")
                raise
        return self._generator

    def get_all_stock_codes(self) -> list[str]:
        """获取所有A股股票代码，并构建 code→name 映射

        数据源优先级: TuShare → AkShare → EastMoney → 数据库缓存
        每个 API 源会尝试两种代理模式（直连/代理），提高成功率。
        成功获取后自动缓存到数据库，下次 API 全部失败时可用。

        Returns:
            股票代码列表 (6位纯数字格式)
        """
        # 检查内存缓存
        cache_key = "all_stock_codes"
        if cache_key in self._signal_cache:
            _debug_log(f"[DEBUG] get_all_stock_codes: 使用缓存 ({len(self._signal_cache[cache_key])} 只)")
            return self._signal_cache[cache_key]

        stock_codes = []

        # --- 数据源1: TuShare stock_basic（永远直连，不走代理） ---
        if self._adapter._tushare_api is not None and not stock_codes:
            try:
                _debug_log("[DEBUG] get_all_stock_codes: TuShare(直连)...")
                with no_proxy():
                    df = self._adapter._tushare_api.stock_basic(
                        exchange='',
                        list_status='L',
                        fields='ts_code,symbol,name,list_status'
                    )
                if df is not None and not df.empty:
                    stock_codes = df['symbol'].tolist()
                    if 'name' in df.columns:
                        self._stock_name_map = dict(zip(df['symbol'].astype(str), df['name']))
                    _debug_log(f"[INFO] get_all_stock_codes: TuShare成功 {len(stock_codes)} 只")
            except Exception as e:
                _debug_log(f"[WARN] get_all_stock_codes: TuShare失败 - {e}")

        # --- 数据源2: AkShare stock_info_a_code_name ---
        if not stock_codes and ak is not None:
            for proxy_mode, mode_name in [(with_proxy, "代理"), (no_proxy, "直连")]:
                try:
                    _debug_log(f"[DEBUG] get_all_stock_codes: AkShare stock_info({mode_name})...")
                    with proxy_mode():
                        df = ak.stock_info_a_code_name()
                    if df is not None and not df.empty:
                        code_col = 'code' if 'code' in df.columns else '代码'
                        name_col = 'name' if 'name' in df.columns else '名称'
                        if code_col in df.columns:
                            stock_codes = df[code_col].astype(str).tolist()
                            if name_col in df.columns:
                                self._stock_name_map = dict(zip(
                                    df[code_col].astype(str), df[name_col]
                                ))
                            _debug_log(f"[INFO] get_all_stock_codes: AkShare({mode_name})成功 {len(stock_codes)} 只")
                            break
                except Exception as e:
                    _debug_log(f"[WARN] get_all_stock_codes: AkShare stock_info({mode_name})失败 - {e}")

        # --- 数据源3: EastMoney stock_zh_a_spot_em ---
        guard = get_api_guard()
        if not stock_codes and ak is not None:
            if guard.is_blocked("eastmoney"):
                _debug_log("[INFO] get_all_stock_codes: 东方财富已熔断，跳过")
            else:
                for proxy_mode, mode_name in [(with_proxy, "代理"), (no_proxy, "直连")]:
                    try:
                        _debug_log(f"[DEBUG] get_all_stock_codes: EastMoney({mode_name})...")
                        with proxy_mode():
                            df = ak.stock_zh_a_spot_em()
                        if df is not None and not df.empty:
                            code_col = '代码' if '代码' in df.columns else 'code'
                            name_col = '名称' if '名称' in df.columns else 'name'
                            if code_col in df.columns:
                                stock_codes = df[code_col].astype(str).tolist()
                                if name_col in df.columns:
                                    self._stock_name_map = dict(zip(
                                        df[code_col].astype(str), df[name_col]
                                    ))
                                _debug_log(f"[INFO] get_all_stock_codes: EastMoney({mode_name})成功 {len(stock_codes)} 只")
                                guard.record_success("eastmoney")
                                break
                    except Exception as e:
                        _debug_log(f"[WARN] get_all_stock_codes: EastMoney({mode_name})失败 - {e}")
                else:
                    # 两种模式都失败才触发熔断
                    guard.record_failure("eastmoney", "所有代理模式均失败")

        # --- 数据源4: 数据库缓存（最后兜底） ---
        if not stock_codes and self._adapter._db is not None:
            try:
                _debug_log("[DEBUG] get_all_stock_codes: 从数据库缓存加载...")
                db_stocks = self._adapter._db.get_stock_list()
                if db_stocks:
                    for s in db_stocks:
                        ts_code = s.get("ts_code", "")
                        code = ts_code.split(".")[0] if "." in ts_code else ts_code
                        stock_codes.append(code)
                        name = s.get("name", "")
                        if name:
                            self._stock_name_map[code] = name
                    _debug_log(f"[INFO] get_all_stock_codes: 数据库缓存加载 {len(stock_codes)} 只股票")
            except Exception as e:
                _debug_log(f"[WARN] get_all_stock_codes: 数据库缓存加载失败 - {e}")

        # API 成功时保存到数据库（为未来兜底）
        if stock_codes and self._stock_name_map and self._adapter._db is not None:
            try:
                db_records = [
                    {"ts_code": code, "name": self._stock_name_map.get(code, ""),
                     "industry": None, "market": None, "list_date": None}
                    for code in stock_codes
                ]
                self._adapter._db.upsert_stock_list(db_records)
                _debug_log(f"[INFO] get_all_stock_codes: 已缓存 {len(db_records)} 只股票到数据库")
            except Exception as e:
                _debug_log(f"[WARN] get_all_stock_codes: 保存数据库缓存失败 - {e}")

        # 内存缓存
        if stock_codes:
            self._signal_cache[cache_key] = stock_codes

        return stock_codes

    def get_stock_name(self, code: str) -> str:
        """获取股票名称"""
        return self._stock_name_map.get(code, "")

    def get_sample_stock_codes(self, n: int = 20) -> list[str]:
        """获取样本股票代码列表 (用于快速测试)

        Args:
            n: 返回的股票数量

        Returns:
            股票代码列表
        """
        # 沪深300部分成分股 (热门大盘股)
        default_codes = [
            "600519",  # 贵州茅台
            "000858",  # 五粮液
            "601318",  # 中国平安
            "600036",  # 招商银行
            "000333",  # 美的集团
            "600276",  # 恒瑞医药
            "000001",  # 平安银行
            "600030",  # 中信证券
            "601166",  # 兴业银行
            "000651",  # 格力电器
            "600887",  # 伊利股份
            "002415",  # 海康威视
            "601398",  # 工商银行
            "600900",  # 长江电力
            "000002",  # 万科A
            "002594",  # 比亚迪
            "601888",  # 中国中免
            "600809",  # 山西汾酒
            "002304",  # 洋河股份
            "600690",  # 海尔智家
        ]

        return default_codes[:n]

    def _get_cache_file(self, trade_date: str) -> Path:
        """获取缓存文件路径"""
        return self._CACHE_DIR / f"signals_{trade_date.replace('-', '')}.json"

    def _is_cache_valid(self, trade_date: str) -> bool:
        """检查缓存是否有效（内存 → 文件 → 数据库）"""
        # 内存缓存
        if trade_date in self._signal_cache:
            return True
        # 文件缓存
        cache_file = self._get_cache_file(trade_date)
        if cache_file.exists():
            return True
        # 数据库
        try:
            from src.data_storage.database import Database
            db_path = Path(__file__).parent.parent.parent / "data" / "stockagent.db"
            if db_path.exists():
                db = Database(str(db_path))
                rows = db.get_signals_by_date(trade_date, limit=1)
                if rows:
                    return True
        except Exception:
            pass
        return False

    def _signal_to_dict(self, signal) -> dict:
        """将 CombinedSignal 转换为字典"""
        return {
            'stock_code': signal.stock_code,
            'stock_name': signal.stock_name,
            'trade_date': signal.trade_date,
            'final_score': signal.final_score,
            'signal_level': signal.signal_level.value,
            'swing_score': signal.swing_score,
            'trend_score': signal.trend_score,
            'ml_score': signal.ml_score,
            'sentiment_score': signal.sentiment_score,
            'reasons': signal.reasons
        }

    def _dict_to_signal(self, d: dict):
        """将字典转换回 CombinedSignal"""
        from src.signals.signal_combiner import CombinedSignal
        from src.signals.base_signal import SignalLevel
        return CombinedSignal(
            stock_code=d['stock_code'],
            trade_date=d['trade_date'],
            final_score=d['final_score'],
            signal_level=SignalLevel(d['signal_level']),
            swing_score=d['swing_score'],
            trend_score=d['trend_score'],
            ml_score=d['ml_score'],
            stock_name=d.get('stock_name', ''),
            sentiment_score=d.get('sentiment_score'),
            reasons=d['reasons']
        )

    def _action_signal_to_dict(self, sig) -> dict:
        """将 ActionSignal 转换为字典（用于文件缓存序列化）"""
        return {
            'stock_code': sig.stock_code,
            'trade_date': sig.trade_date,
            'action': sig.action.value,
            'strategy_name': sig.strategy_name,
            'confidence_score': sig.confidence_score,
            'sell_reason': sig.sell_reason.value if sig.sell_reason else None,
            'exit_config': {
                'stop_loss_pct': sig.exit_config.stop_loss_pct,
                'take_profit_pct': sig.exit_config.take_profit_pct,
                'max_hold_days': sig.exit_config.max_hold_days,
            } if sig.exit_config else None,
            'trigger_rules': sig.trigger_rules,
            'reasons': sig.reasons,
            'stock_name': sig.stock_name,
        }

    def _dict_to_action_signal(self, d: dict):
        """将字典转换回 ActionSignal"""
        from src.signals.action_signal import (
            ActionSignal, SignalAction, SellReason, ExitConfig
        )
        exit_cfg_raw = d.get('exit_config')
        exit_config = ExitConfig(
            stop_loss_pct=exit_cfg_raw.get('stop_loss_pct'),
            take_profit_pct=exit_cfg_raw.get('take_profit_pct'),
            max_hold_days=exit_cfg_raw.get('max_hold_days'),
        ) if exit_cfg_raw else None

        sell_reason = SellReason(d['sell_reason']) if d.get('sell_reason') else None

        return ActionSignal(
            stock_code=d['stock_code'],
            trade_date=d['trade_date'],
            action=SignalAction(d['action']),
            strategy_name=d['strategy_name'],
            confidence_score=d.get('confidence_score', 50.0),
            sell_reason=sell_reason,
            exit_config=exit_config,
            trigger_rules=d.get('trigger_rules', []),
            reasons=d.get('reasons', []),
            stock_name=d.get('stock_name', ''),
        )

    def _get_market_sentiment(self) -> Optional[float]:
        """获取当前市场情绪分数

        从新闻缓存中获取整体市场情绪。

        Returns:
            情绪分数 (0-100, 50为中性)，获取失败返回None
        """
        try:
            cached = NewsService.get_cached_news()
            if cached and NewsService.is_cache_fresh(max_age_minutes=60):
                sentiment = cached.get("overall_sentiment", 50.0)
                _debug_log(f"[INFO] 市场情绪分数: {sentiment:.1f}")
                return sentiment
            else:
                _debug_log("[WARN] 新闻缓存过期或不存在，不使用情绪因子")
                return None
        except Exception as e:
            _debug_log(f"[WARN] 获取市场情绪失败: {e}")
            return None

    def _detect_market_regime(self):
        """检测当前市场状态，用于自适应权重

        Returns:
            MarketRegime 对象，失败返回 None
        """
        try:
            from src.signals.market_regime import MarketRegimeDetector
            from src.dashboard.live_data_service import get_live_data_service

            detector = MarketRegimeDetector()
            live_service = get_live_data_service()

            # 获取指数历史数据
            index_df = live_service.get_index_history(index_code="sh000001", days=30)

            # 获取市场宽度
            breadth = live_service.get_market_breadth()
            breadth_ratio = breadth.breadth_ratio if breadth else None

            regime = detector.detect(index_df=index_df, breadth_ratio=breadth_ratio)
            return regime

        except Exception as e:
            _debug_log(f"[WARN] 市场状态检测失败: {e}")
            return None

    def _save_signals_to_db(self, trade_date: str, result: dict, market_regime=None):
        """将信号保存到数据库（永久存储）"""
        try:
            from src.data_storage.database import Database
            db_path = Path(__file__).parent.parent.parent / "data" / "stockagent.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db = Database(str(db_path))
            db.init_tables()

            regime_name = market_regime.regime if market_regime else None
            swing_w = market_regime.swing_weight if market_regime else None
            trend_w = market_regime.trend_weight if market_regime else None

            all_signals = (
                result.get('buy_signals', []) +
                result.get('sell_signals', []) +
                result.get('hold_signals', [])
            )

            sig_dicts = []
            for s in all_signals:
                sig_dicts.append({
                    'stock_code': s.stock_code,
                    'final_score': s.final_score,
                    'signal_level': s.signal_level.value,
                    'signal_level_name': s.signal_level.name,
                    'swing_score': s.swing_score,
                    'trend_score': s.trend_score,
                    'ml_score': s.ml_score,
                    'sentiment_score': s.sentiment_score,
                    'market_regime': regime_name,
                    'swing_weight': swing_w,
                    'trend_weight': trend_w,
                    'reasons': s.reasons,
                })

            db_result = db.save_signals(sig_dicts, trade_date)
            _debug_log(f"[INFO] 信号入库: {db_result['saved']} 条 ({trade_date})")

        except Exception as e:
            _debug_log(f"[WARN] 信号入库失败: {e}")

    def _save_action_signals_to_db(self, trade_date: str, action_signals: list):
        """将动作信号保存到数据库"""
        if not action_signals:
            return
        try:
            from src.data_storage.database import Database
            db_path = Path(__file__).parent.parent.parent / "data" / "stockagent.db"
            db = Database(str(db_path))
            db.init_tables()

            sig_dicts = []
            for a in action_signals:
                exit_cfg = a.exit_config
                sig_dicts.append({
                    'stock_code': a.stock_code,
                    'action': a.action.value,
                    'strategy_name': a.strategy_name,
                    'confidence_score': a.confidence_score,
                    'sell_reason': a.sell_reason.value if a.sell_reason else None,
                    'trigger_rules': a.trigger_rules,
                    'stop_loss_pct': exit_cfg.stop_loss_pct if exit_cfg else None,
                    'take_profit_pct': exit_cfg.take_profit_pct if exit_cfg else None,
                    'max_hold_days': exit_cfg.max_hold_days if exit_cfg else None,
                    'reasons': a.reasons,
                })

            db_result = db.save_action_signals(sig_dicts, trade_date)
            _debug_log(f"[INFO] 动作信号入库: {db_result['saved']} 条 ({trade_date})")

        except Exception as e:
            _debug_log(f"[WARN] 动作信号入库失败: {e}")

    def _load_cache(self, trade_date: str) -> Optional[dict]:
        """从缓存加载信号数据（内存 → 文件 → 数据库）"""
        # 1. 内存缓存
        if trade_date in self._signal_cache:
            _debug_log(f"[DEBUG] _load_cache({trade_date}): 使用内存缓存")
            return self._signal_cache[trade_date]

        # 2. 文件缓存
        cache_file = self._get_cache_file(trade_date)
        if cache_file.exists():
            try:
                import json
                with open(cache_file, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)

                data = {
                    'buy_signals': [self._dict_to_signal(d) for d in raw_data['buy_signals']],
                    'sell_signals': [self._dict_to_signal(d) for d in raw_data['sell_signals']],
                    'hold_signals': [self._dict_to_signal(d) for d in raw_data['hold_signals']],
                    'total': raw_data['total'],
                    'trade_date': raw_data['trade_date'],
                    'market_sentiment': raw_data.get('market_sentiment'),
                    'market_regime': raw_data.get('market_regime'),
                    'last_refresh_time': raw_data.get('last_refresh_time'),
                    'action_buy_signals': [self._dict_to_action_signal(d) for d in raw_data.get('action_buy_signals', [])],
                    'action_sell_signals': [self._dict_to_action_signal(d) for d in raw_data.get('action_sell_signals', [])],
                }

                self._signal_cache[trade_date] = data
                _debug_log(f"[DEBUG] _load_cache({trade_date}): 从文件加载缓存 ({data['total']} 只股票)")
                return data
            except Exception as e:
                _debug_log(f"[WARN] _load_cache({trade_date}): 文件加载失败 - {e}")

        # 3. 数据库回退
        db_result = self.load_signals_from_db(trade_date)
        if db_result:
            _debug_log(f"[DEBUG] _load_cache({trade_date}): 从数据库回退加载")
            return db_result

        return None

    def _save_cache(self, trade_date: str, data: dict):
        """保存缓存到文件"""
        try:
            import json
            # 序列化信号对象
            from datetime import datetime as _dt
            refresh_time = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            data['last_refresh_time'] = refresh_time

            raw_data = {
                'buy_signals': [self._signal_to_dict(s) for s in data['buy_signals']],
                'sell_signals': [self._signal_to_dict(s) for s in data['sell_signals']],
                'hold_signals': [self._signal_to_dict(s) for s in data['hold_signals']],
                'total': data['total'],
                'trade_date': data['trade_date'],
                'market_sentiment': data.get('market_sentiment'),
                'market_regime': data.get('market_regime'),
                'last_refresh_time': refresh_time,
                'action_buy_signals': [self._action_signal_to_dict(a) for a in data.get('action_buy_signals', [])],
                'action_sell_signals': [self._action_signal_to_dict(a) for a in data.get('action_sell_signals', [])],
            }

            cache_file = self._get_cache_file(trade_date)
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(raw_data, f, ensure_ascii=False, indent=2)

            # 同时保存到内存
            self._signal_cache[trade_date] = data
            _debug_log(f"[INFO] _save_cache({trade_date}): 缓存已保存到 {cache_file.name}")
        except Exception as e:
            _debug_log(f"[ERROR] _save_cache({trade_date}): 保存失败 - {e}")

    def _process_stock(self, stock_code: str, trade_date: str, sentiment_score: Optional[float] = None, market_regime=None):
        """处理单只股票生成信号（打分 + 动作信号）

        Args:
            stock_code: 股票代码
            trade_date: 交易日期
            sentiment_score: 市场情绪分数（可选）
            market_regime: 市场状态（可选）

        Returns:
            (CombinedSignal, list[ActionSignal]) 或 None
        """
        # 计算回看日期
        end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=3*365)  # 获取不少于3年的数据
        start_date = start_dt.strftime("%Y%m%d")
        end_date = end_dt.strftime("%Y%m%d")

        df = self._adapter.load_daily(stock_code, start_date, end_date)

        if df is None or df.empty or len(df) < 60:
            return None

        try:
            # 计算技术指标（使用策略规则所需的参数配置）
            from src.indicators import IndicatorCalculator
            from src.signals.signal_combiner import SignalCombiner
            combiner = SignalCombiner()
            calc = IndicatorCalculator(config=combiner.get_indicator_config())
            indicators = calc.calculate_all(df)
            df_with_indicators = pd.concat([df, indicators], axis=1)
            signal = combiner.combine(
                df=df_with_indicators,
                stock_code=stock_code,
                trade_date=trade_date,
                ml_score=None,
                sentiment_score=sentiment_score,
                market_regime=market_regime
            )
            signal.stock_name = self.get_stock_name(stock_code)

            # 生成动作信号（买入/卖出触发）
            action_signals = combiner.generate_action_signals(
                df=df_with_indicators,
                stock_code=stock_code,
                trade_date=trade_date,
                combined_signal=signal,
            )
            for a in action_signals:
                a.stock_name = signal.stock_name

            return signal, action_signals

        except Exception as e:
            _debug_log(f"[ERROR] _process_stock({stock_code}): {e}")
            return None

    def get_signals(self, trade_date: Optional[str] = None, stock_codes: Optional[list[str]] = None, progress_callback=None):
        """获取指定日期的所有信号（顺序处理）

        Args:
            trade_date: 交易日期 (默认为今天)
            stock_codes: 股票代码列表 (默认分析全部A股)
            progress_callback: 进度回调函数 (current, total, stock_code) -> None

        Returns:
            包含 buy_signals 和 sell_signals 的字典
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        # 检查缓存（内存或文件）
        if self._is_cache_valid(trade_date):
            cached = self._load_cache(trade_date)
            if cached:
                return cached

        if stock_codes is None:
            _debug_log("[DEBUG] get_signals: 正在获取全部股票列表...")
            stock_codes = self.get_all_stock_codes()
            _debug_log(f"[DEBUG] get_signals: get_all_stock_codes 返回 {len(stock_codes)} 只股票")
            if not stock_codes:
                _debug_log("[ERROR] get_signals: 无法获取股票列表（TuShare 和 AkShare 均失败），终止分析")
                return {
                    'buy_signals': [], 'sell_signals': [], 'hold_signals': [],
                    'total': 0, 'trade_date': trade_date,
                    'market_sentiment': None, 'market_regime': None,
                    'error': '无法获取股票列表，请检查 TuShare Token 配置和网络连接',
                }

        total = len(stock_codes)
        _debug_log(f"[INFO] get_signals: 生成信号 ({trade_date}, {total} 只股票, 顺序处理)")

        try:
            # 获取市场情绪（所有股票共用）
            market_sentiment = self._get_market_sentiment()

            # 检测市场状态（自适应权重）
            market_regime = self._detect_market_regime()
            if market_regime:
                _debug_log(
                    f"[INFO] 市场状态: {market_regime.regime_label} "
                    f"(趋势强度={market_regime.trend_strength:.2f}, "
                    f"波动率={market_regime.volatility:.2f}, "
                    f"波段={market_regime.swing_weight:.0%}, "
                    f"趋势={market_regime.trend_weight:.0%})"
                )

            # 顺序处理所有股票
            signals = []
            all_action_signals = []

            for i, code in enumerate(stock_codes, 1):
                if progress_callback:
                    progress_callback(i, total, code)
                try:
                    proc_result = self._process_stock(code, trade_date,
                                                      market_sentiment, market_regime)
                    if proc_result:
                        combined_sig, action_sigs = proc_result
                        signals.append(combined_sig)
                        all_action_signals.extend(action_sigs)
                except Exception as e:
                    _debug_log(f"[ERROR] 处理 {code} 异常: {e}")

            # 分类信号
            buy_signals = [s for s in signals if s.signal_level.is_bullish()]
            sell_signals = [s for s in signals if s.signal_level.is_bearish()]
            hold_signals = [s for s in signals if not s.signal_level.is_bullish() and not s.signal_level.is_bearish()]

            regime_info = None
            if market_regime:
                regime_info = {
                    'regime': market_regime.regime,
                    'regime_label': market_regime.regime_label,
                    'trend_strength': market_regime.trend_strength,
                    'volatility': market_regime.volatility,
                    'breadth': market_regime.breadth,
                    'swing_weight': market_regime.swing_weight,
                    'trend_weight': market_regime.trend_weight,
                }

            # 分类动作信号
            action_buy = [a for a in all_action_signals if a.action.value == "BUY"]
            action_sell = [a for a in all_action_signals if a.action.value == "SELL"]

            result = {
                'buy_signals': sorted(buy_signals, key=lambda s: s.final_score, reverse=True),
                'sell_signals': sorted(sell_signals, key=lambda s: s.final_score),
                'hold_signals': hold_signals,
                'total': len(signals),
                'trade_date': trade_date,
                'market_sentiment': market_sentiment,
                'market_regime': regime_info,
                'action_buy_signals': sorted(action_buy, key=lambda a: a.confidence_score, reverse=True),
                'action_sell_signals': sorted(action_sell, key=lambda a: a.confidence_score),
            }

            # 保存缓存到文件
            self._save_cache(trade_date, result)

            # 保存到数据库（永久存储）
            self._save_signals_to_db(trade_date, result, market_regime)

            # 保存动作信号到数据库
            self._save_action_signals_to_db(trade_date, all_action_signals)

            _debug_log(
                f"[INFO] get_signals: 完成 - "
                f"买入{len(buy_signals)} 卖出{len(sell_signals)} 持有{len(hold_signals)} | "
                f"动作信号: BUY {len(action_buy)} SELL {len(action_sell)}"
            )
            return result

        except Exception as e:
            _debug_log(f"[ERROR] get_signals: {e}")
            import traceback
            _debug_log(traceback.format_exc())
            return {
                'buy_signals': [],
                'sell_signals': [],
                'hold_signals': [],
                'total': 0,
                'trade_date': trade_date,
                'error': str(e)
            }

    def get_latest_available_date(self) -> Optional[str]:
        """获取最新可用的信号日期（文件缓存 → 数据库）

        用于仪表盘默认显示最新信号，避免跨日后信号消失。

        Returns:
            最新日期字符串 (YYYY-MM-DD)，无数据时返回 None
        """
        latest_file_date = None
        latest_db_date = None

        # 1. 扫描文件缓存目录
        try:
            cache_files = sorted(self._CACHE_DIR.glob("signals_*.json"), reverse=True)
            if cache_files:
                # 文件名格式: signals_YYYYMMDD.json
                fname = cache_files[0].stem  # signals_20260207
                date_part = fname.replace("signals_", "")
                if len(date_part) == 8:
                    latest_file_date = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
        except Exception as e:
            _debug_log(f"[WARN] get_latest_available_date: 扫描缓存文件失败 - {e}")

        # 2. 查询数据库
        try:
            from src.data_storage.database import Database
            db_path = Path(__file__).parent.parent.parent / "data" / "stockagent.db"
            if db_path.exists():
                db = Database(str(db_path))
                latest_db_date = db.get_latest_signal_date()
        except Exception as e:
            _debug_log(f"[WARN] get_latest_available_date: 查询数据库失败 - {e}")

        # 3. 返回两者中更新的日期
        candidates = [d for d in [latest_file_date, latest_db_date] if d]
        if not candidates:
            return None
        return max(candidates)

    def load_signals_from_db(self, trade_date: str) -> Optional[dict]:
        """从数据库加载信号数据，重建与 _load_cache 相同格式的结果

        Args:
            trade_date: 交易日期 (YYYY-MM-DD)

        Returns:
            与 get_signals() 返回格式相同的字典，无数据时返回 None
        """
        try:
            from src.data_storage.database import Database
            from src.signals.signal_combiner import CombinedSignal
            from src.signals.base_signal import SignalLevel

            db_path = Path(__file__).parent.parent.parent / "data" / "stockagent.db"
            if not db_path.exists():
                return None

            db = Database(str(db_path))
            rows = db.get_signals_by_date(trade_date, limit=10000)

            if not rows:
                return None

            buy_signals = []
            sell_signals = []
            hold_signals = []

            for row in rows:
                # 解析 reasons (数据库中以 JSON 字符串存储)
                reasons_raw = row.get("reasons", "[]")
                if isinstance(reasons_raw, str):
                    try:
                        reasons = json.loads(reasons_raw)
                    except (json.JSONDecodeError, TypeError):
                        reasons = []
                else:
                    reasons = reasons_raw if reasons_raw else []

                signal_level_val = row.get("signal_level", 3)
                try:
                    signal_level = SignalLevel(signal_level_val)
                except ValueError:
                    signal_level = SignalLevel.HOLD

                signal = CombinedSignal(
                    stock_code=row.get("stock_code", ""),
                    trade_date=trade_date,
                    final_score=row.get("final_score", 50.0),
                    signal_level=signal_level,
                    swing_score=row.get("swing_score", 50.0) or 50.0,
                    trend_score=row.get("trend_score", 50.0) or 50.0,
                    ml_score=row.get("ml_score"),
                    stock_name=self.get_stock_name(row.get("stock_code", "")),
                    sentiment_score=row.get("sentiment_score"),
                    reasons=reasons,
                )

                if signal_level.is_bullish():
                    buy_signals.append(signal)
                elif signal_level.is_bearish():
                    sell_signals.append(signal)
                else:
                    hold_signals.append(signal)

            # 获取 market_regime 信息（从第一条记录）
            regime_name = rows[0].get("market_regime") if rows else None
            regime_info = None
            if regime_name:
                sw = rows[0].get("swing_weight")
                tw = rows[0].get("trend_weight")
                regime_info = {
                    'regime': regime_name,
                    'regime_label': regime_name,
                    'swing_weight': sw,
                    'trend_weight': tw,
                }

            result = {
                'buy_signals': sorted(buy_signals, key=lambda s: s.final_score, reverse=True),
                'sell_signals': sorted(sell_signals, key=lambda s: s.final_score),
                'hold_signals': hold_signals,
                'total': len(rows),
                'trade_date': trade_date,
                'market_sentiment': None,
                'market_regime': regime_info,
                'last_refresh_time': None,
            }

            # 缓存到内存（下次直接使用）
            self._signal_cache[trade_date] = result
            _debug_log(
                f"[INFO] load_signals_from_db({trade_date}): "
                f"加载 {len(rows)} 条信号 (买{len(buy_signals)} 卖{len(sell_signals)} 持有{len(hold_signals)})"
            )
            return result

        except Exception as e:
            _debug_log(f"[WARN] load_signals_from_db({trade_date}): 加载失败 - {e}")
            return None

    def get_buy_signals(self, top_n: int = 10, trade_date: Optional[str] = None) -> list:
        """获取买入信号"""
        result = self.get_signals(trade_date)
        return result['buy_signals'][:top_n]

    def get_sell_signals(self, top_n: int = 10, trade_date: Optional[str] = None) -> list:
        """获取卖出信号"""
        result = self.get_signals(trade_date)
        return result['sell_signals'][:top_n]

    def clear_cache(self, trade_date: Optional[str] = None):
        """清除信号缓存

        Args:
            trade_date: 指定日期清除，None 则清除所有缓存
        """
        if trade_date:
            # 清除指定日期的缓存
            self._signal_cache.pop(trade_date, None)
            cache_file = self._get_cache_file(trade_date)
            if cache_file.exists():
                cache_file.unlink()
                _debug_log(f"[INFO] clear_cache: 已删除 {cache_file.name}")
        else:
            # 清除所有缓存
            self._signal_cache.clear()
            for cache_file in self._CACHE_DIR.glob("signals_*.json"):
                cache_file.unlink()
                _debug_log(f"[INFO] clear_cache: 已删除 {cache_file.name}")

        self._adapter.clear_cache()


# 单例模式
_signal_service: Optional[SignalDataService] = None


def get_signal_service() -> SignalDataService:
    """获取信号数据服务单例"""
    global _signal_service
    if _signal_service is None:
        _signal_service = SignalDataService()
    return _signal_service
