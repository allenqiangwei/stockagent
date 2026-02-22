"""实时数据服务 - 为仪表盘提供实时市场数据

支持 AkShare 和 TuShare 两种数据源，根据配置自动选择。
数据获取时自动绕过系统代理，直连国内数据源。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path
import os
import sys

# 调试日志文件
_DEBUG_LOG_PATH = Path(__file__).parent.parent.parent / "logs" / "data_source_debug.log"
_DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def _debug_log(msg: str):
    """写入调试日志"""
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%H:%M:%S')} | {msg}\n")
        print(msg, file=sys.stderr, flush=True)
    except:
        pass

# 在导入任何网络库之前，彻底禁用代理
_PROXY_VARS_TO_CLEAR = [
    'HTTP_PROXY', 'http_proxy',
    'HTTPS_PROXY', 'https_proxy',
    'ALL_PROXY', 'all_proxy',
]
_saved_proxies_at_import = {}
for _var in _PROXY_VARS_TO_CLEAR:
    if _var in os.environ:
        _saved_proxies_at_import[_var] = os.environ.pop(_var)

os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

import pandas as pd

# 在导入 akshare 前，先导入 requests 并禁用其代理功能
import requests
from requests.adapters import HTTPAdapter

# 浏览器风格的 User-Agent 头
_BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}

# 线程局部变量：控制是否允许代理
import threading
_proxy_thread_local = threading.local()

def _should_use_proxy() -> bool:
    """检查当前线程是否应该使用代理（由 with_proxy() 控制）"""
    return getattr(_proxy_thread_local, 'use_proxy', False)

def set_thread_proxy(enabled: bool):
    """设置当前线程是否使用代理（供 with_proxy() 调用）"""
    _proxy_thread_local.use_proxy = enabled

# 猴子补丁1：让 Session 初始化时默认禁用代理（不改 headers，留到请求时动态判断）
_original_session_init = requests.Session.__init__

def _patched_session_init(self, *args, **kwargs):
    _original_session_init(self, *args, **kwargs)
    if not _should_use_proxy():
        self.trust_env = False
        self.proxies = {}

requests.Session.__init__ = _patched_session_init

# 猴子补丁2：请求时动态判断代理和浏览器头
_original_request = requests.Session.request

def _patched_request(self, method, url, **kwargs):
    if _should_use_proxy():
        # AkShare 调用：加浏览器头伪装，避免被数据源屏蔽
        if 'headers' not in kwargs:
            kwargs['headers'] = {**self.headers, **_BROWSER_HEADERS}
        else:
            merged = {**_BROWSER_HEADERS, **kwargs['headers']}
            kwargs['headers'] = merged
    else:
        # TuShare 等直连调用：不改头，禁用代理
        if 'proxies' not in kwargs:
            kwargs['proxies'] = {}
    return _original_request(self, method, url, **kwargs)

requests.Session.request = _patched_request

_debug_log("[INFO] requests 代理补丁已应用 - trust_env=False, proxies={}, headers=Browser")

try:
    import akshare as ak
except ImportError:
    ak = None

try:
    import tushare as ts
except ImportError:
    ts = None

# 导入后恢复代理设置（给其他模块用），但 requests 已经被补丁
for _var, _val in _saved_proxies_at_import.items():
    os.environ[_var] = _val

from src.utils.logger import get_logger
from src.utils.network import no_proxy, with_proxy
from src.services.api_guard import get_api_guard

logger = get_logger(__name__)


def load_data_source_config() -> dict:
    """加载数据源配置

    Returns:
        配置字典，包含各分类数据源设置
    """
    default_config = {
        "realtime_quotes": "akshare",
        "historical_daily": "akshare",
        "index_data": "akshare",
        "sector_data": "akshare",
        "money_flow": "akshare",
        "stock_list": "akshare",
        "fallback_enabled": True,
        "tushare_token": ""
    }

    try:
        import yaml
        config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
                data_sources = config.get("data_sources", {})

                return {
                    "realtime_quotes": data_sources.get("realtime_quotes", "akshare"),
                    "historical_daily": data_sources.get("historical_daily", "akshare"),
                    "index_data": data_sources.get("index_data", "akshare"),
                    "sector_data": data_sources.get("sector_data", "akshare"),
                    "money_flow": data_sources.get("money_flow", "akshare"),
                    "stock_list": data_sources.get("stock_list", "akshare"),
                    "fallback_enabled": data_sources.get("fallback_enabled", True),
                    "tushare_token": data_sources.get("tushare", {}).get("token", "")
                }
    except Exception as e:
        logger.warning(f"加载数据源配置失败: {e}")

    return default_config


@dataclass
class IndexQuote:
    """指数实时行情"""
    name: str
    code: str
    current: float
    change: float
    change_pct: float
    open: float
    high: float
    low: float
    volume: float
    amount: float
    update_time: str


@dataclass
class MarketBreadth:
    """市场宽度数据"""
    advance_count: int  # 上涨家数
    decline_count: int  # 下跌家数
    unchanged_count: int  # 平盘家数
    total_count: int
    breadth_ratio: float  # 上涨比例


class LiveDataService:
    """实时数据服务

    根据配置为每个数据分类选择数据源。
    支持 AkShare（免费）和 TuShare Pro（需Token）。
    """

    def __init__(self):
        self.config = load_data_source_config()
        self.fallback_enabled = self.config.get("fallback_enabled", True)
        self._tushare_api = None

        # 初始化 TuShare（如果任何分类需要）
        needs_tushare = any(
            self.config.get(cat) == "tushare"
            for cat in ["realtime_quotes", "historical_daily", "index_data",
                       "sector_data", "money_flow", "stock_list"]
        )
        if needs_tushare or self.fallback_enabled:
            self._init_tushare()

        logger.info(f"数据源初始化完成，备用={'启用' if self.fallback_enabled else '禁用'}")

    def _init_tushare(self):
        """初始化TuShare API"""
        if ts is None:
            logger.warning("TuShare未安装")
            return

        token = self.config.get("tushare_token", "")
        if token and token != "YOUR_TUSHARE_TOKEN":
            try:
                with no_proxy():
                    self._tushare_api = ts.pro_api(token)
                logger.info("TuShare API初始化成功")
            except Exception as e:
                logger.error(f"TuShare API初始化失败: {e}")
        else:
            logger.warning("TuShare Token未配置")

    def get_source_for(self, category: str) -> str:
        """获取指定分类的数据源"""
        return self.config.get(category, "akshare")

    def get_current_source(self) -> str:
        """获取实时行情的数据源名称（用于显示）"""
        return self.config.get("realtime_quotes", "akshare")

    def get_all_sources(self) -> dict:
        """获取所有分类的数据源配置"""
        return {
            "realtime_quotes": self.config.get("realtime_quotes", "akshare"),
            "historical_daily": self.config.get("historical_daily", "akshare"),
            "index_data": self.config.get("index_data", "akshare"),
            "sector_data": self.config.get("sector_data", "akshare"),
            "money_flow": self.config.get("money_flow", "akshare"),
            "stock_list": self.config.get("stock_list", "akshare"),
        }

    def is_tushare_available(self) -> bool:
        """检查TuShare是否可用"""
        return self._tushare_api is not None

    def get_index_quote(self, index_code: str = "sh000001") -> Optional[IndexQuote]:
        """获取指数实时行情"""
        if ak is None:
            return None

        try:
            with with_proxy():
                df = ak.stock_zh_index_spot_sina()

            if df.empty:
                logger.warning("获取指数行情失败：返回空数据")
                return None

            row = df[df['代码'] == index_code]
            if row.empty:
                code_only = index_code[2:] if len(index_code) > 6 else index_code
                row = df[df['代码'].str.contains(code_only)]

            if row.empty:
                logger.warning(f"未找到指数: {index_code}")
                return None

            row = row.iloc[0]

            return IndexQuote(
                name=row.get('名称', '上证指数'),
                code=index_code,
                current=float(row.get('最新价', 0)),
                change=float(row.get('涨跌额', 0)),
                change_pct=float(row.get('涨跌幅', 0)),
                open=float(row.get('今开', 0)),
                high=float(row.get('最高', 0)),
                low=float(row.get('最低', 0)),
                volume=float(row.get('成交量', 0)),
                amount=float(row.get('成交额', 0)),
                update_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

        except Exception as e:
            logger.error(f"获取指数行情失败: {e}")
            return None

    def get_market_breadth(self) -> Optional[MarketBreadth]:
        """获取市场宽度（涨跌家数统计）"""
        if ak is None:
            _debug_log("[DEBUG] get_market_breadth: AkShare 未安装")
            return None

        errors = []
        guard = get_api_guard()

        # 方法1: 东方财富实时行情 (stock_zh_a_spot_em)
        if guard.is_blocked("eastmoney"):
            _debug_log("[INFO] get_market_breadth: 东方财富已熔断，跳过")
            errors.append("东方财富: 熔断中")
        else:
            try:
                _debug_log("[DEBUG] get_market_breadth: 尝试东方财富数据源...")
                with with_proxy():
                    df = ak.stock_zh_a_spot_em()

                if df is not None and not df.empty:
                    _debug_log(f"[DEBUG] get_market_breadth: 东方财富成功获取到 {len(df)} 行数据")
                    guard.record_success("eastmoney")
                    return self._calc_breadth_from_df(df, ['涨跌幅', '涨跌幅度', 'change_pct'])
            except Exception as e:
                errors.append(f"东方财富: {e}")
                guard.record_failure("eastmoney", str(e))
                _debug_log(f"[WARN] get_market_breadth: 东方财富失败 - {e}")

        # 方法2: 使用新浪指数数据估算市场宽度 (作为备选)
        try:
            _debug_log("[DEBUG] get_market_breadth: 尝试新浪指数数据...")
            with with_proxy():
                df = ak.stock_zh_index_spot_sina()

            if df is not None and not df.empty:
                _debug_log(f"[DEBUG] get_market_breadth: 新浪成功获取到 {len(df)} 行数据")
                pct_col = None
                for col in ['涨跌幅', 'change_pct']:
                    if col in df.columns:
                        pct_col = col
                        break

                if pct_col:
                    df[pct_col] = pd.to_numeric(df[pct_col], errors='coerce')
                    up = len(df[df[pct_col] > 0])
                    down = len(df[df[pct_col] < 0])
                    total = len(df)
                    _debug_log(f"[DEBUG] get_market_breadth: 新浪数据源成功 - 涨{up} 跌{down}")
                    return MarketBreadth(
                        advance_count=up * 100,
                        decline_count=down * 100,
                        unchanged_count=(total - up - down) * 100,
                        total_count=total * 100,
                        breadth_ratio=up / total if total > 0 else 0.5
                    )
        except Exception as e:
            errors.append(f"新浪指数: {e}")
            _debug_log(f"[WARN] get_market_breadth: 新浪指数失败 - {e}")

        _debug_log(f"[ERROR] get_market_breadth: 所有数据源失败 - {errors}")
        return None

    def _calc_breadth_from_df(self, df: pd.DataFrame, pct_col_names: list) -> Optional[MarketBreadth]:
        """从DataFrame计算市场宽度"""
        if df.empty:
            return None

        pct_col = None
        for col in pct_col_names:
            if col in df.columns:
                pct_col = col
                break

        if pct_col is None:
            _debug_log(f"[WARN] _calc_breadth_from_df: 未找到涨跌幅列，可用列: {df.columns.tolist()}")
            return None

        df = df.copy()
        df[pct_col] = pd.to_numeric(df[pct_col], errors='coerce')

        advance_count = len(df[df[pct_col] > 0])
        decline_count = len(df[df[pct_col] < 0])
        unchanged_count = len(df[df[pct_col] == 0])
        total_count = len(df)

        breadth_ratio = advance_count / total_count if total_count > 0 else 0.5

        return MarketBreadth(
            advance_count=advance_count,
            decline_count=decline_count,
            unchanged_count=unchanged_count,
            total_count=total_count,
            breadth_ratio=breadth_ratio
        )

    def get_index_history(self, index_code: str = "sh000001", days: int = 30) -> Optional[pd.DataFrame]:
        """获取指数历史数据"""
        if ak is None:
            return None

        try:
            with with_proxy():
                df = ak.stock_zh_index_daily(symbol=index_code)

            if df.empty:
                return None

            df = df.tail(days).copy()
            df['date'] = pd.to_datetime(df['date'])

            return df

        except Exception as e:
            logger.error(f"获取指数历史失败: {e}")
            return None

    def get_sector_performance(self) -> Optional[pd.DataFrame]:
        """获取行业板块涨跌幅"""
        errors = []

        # 方法1: AkShare 新浪行业板块 (更稳定)
        if ak is not None:
            try:
                _debug_log("[DEBUG] get_sector_performance: 尝试新浪行业板块...")
                with with_proxy():
                    df = ak.stock_sector_spot(indicator='行业')

                if df is not None and not df.empty:
                    _debug_log(f"[DEBUG] get_sector_performance: 新浪获取到 {len(df)} 行数据")
                    # 新浪返回: 板块, 涨跌幅, 股票名称(领涨股)
                    if '板块' in df.columns and '涨跌幅' in df.columns:
                        leader_col = '股票名称' if '股票名称' in df.columns else None
                        result = pd.DataFrame({
                            'name': df['板块'],
                            'change_pct': pd.to_numeric(df['涨跌幅'], errors='coerce'),
                            'leader': df[leader_col] if leader_col else '-'
                        })
                        _debug_log(f"[DEBUG] get_sector_performance: 新浪成功返回 {len(result)} 行")
                        return result.head(20)

            except Exception as e:
                errors.append(f"新浪: {e}")
                _debug_log(f"[WARN] get_sector_performance: 新浪失败 - {e}")

        # 方法2: AkShare 东方财富行业板块 (备选)
        guard = get_api_guard()
        if ak is not None and not guard.is_blocked("eastmoney"):
            try:
                _debug_log("[DEBUG] get_sector_performance: 尝试东方财富数据源...")
                with with_proxy():
                    df = ak.stock_board_industry_name_em()

                if df is not None and not df.empty:
                    _debug_log(f"[DEBUG] get_sector_performance: 东方财富获取到 {len(df)} 行数据")
                    required_cols = ['板块名称', '涨跌幅', '领涨股票']
                    if all(c in df.columns for c in required_cols):
                        result = df[required_cols].copy()
                        result.columns = ['name', 'change_pct', 'leader']
                        result['change_pct'] = pd.to_numeric(result['change_pct'], errors='coerce')
                        _debug_log(f"[DEBUG] get_sector_performance: 东方财富成功返回 {len(result)} 行")
                        guard.record_success("eastmoney")
                        return result.head(20)
                    else:
                        _debug_log(f"[WARN] get_sector_performance: 东方财富缺少必需列，可用列: {df.columns.tolist()}")

            except Exception as e:
                errors.append(f"东方财富: {e}")
                guard.record_failure("eastmoney", str(e))
                _debug_log(f"[WARN] get_sector_performance: 东方财富失败 - {e}")
        elif guard.is_blocked("eastmoney"):
            _debug_log("[INFO] get_sector_performance: 东方财富已熔断，跳过")

        # 方法2: TuShare 行业分类（如果可用）
        if self._tushare_api is not None:
            try:
                _debug_log("[DEBUG] get_sector_performance: 尝试TuShare数据源...")
                with no_proxy():
                    df = self._tushare_api.index_classify(level='L1', src='SW')

                if df is not None and not df.empty:
                    _debug_log(f"[DEBUG] get_sector_performance: TuShare获取到 {len(df)} 行数据")
                    result = pd.DataFrame({
                        'name': df['industry_name'] if 'industry_name' in df.columns else df.iloc[:, 0],
                        'change_pct': 0.0,
                        'leader': '-'
                    })
                    _debug_log(f"[DEBUG] get_sector_performance: TuShare成功返回 {len(result)} 行")
                    return result.head(20)

            except Exception as e:
                errors.append(f"TuShare: {e}")
                _debug_log(f"[WARN] get_sector_performance: TuShare失败 - {e}")

        # 方法3: AkShare 板块资金流排名
        if ak is not None:
            try:
                _debug_log("[DEBUG] get_sector_performance: 尝试AkShare板块资金流...")
                with with_proxy():
                    df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")

                if df is not None and not df.empty:
                    _debug_log(f"[DEBUG] get_sector_performance: 板块资金流获取到 {len(df)} 行，列名: {df.columns.tolist()}")
                    if '名称' in df.columns:
                        pct_col = None
                        for col in ['涨跌幅', '今日涨跌幅', 'change_pct']:
                            if col in df.columns:
                                pct_col = col
                                break

                        result = pd.DataFrame({
                            'name': df['名称'],
                            'change_pct': pd.to_numeric(df[pct_col], errors='coerce') if pct_col else 0.0,
                            'leader': '-'
                        })
                        _debug_log(f"[DEBUG] get_sector_performance: 板块资金流成功返回 {len(result)} 行")
                        return result.head(20)

            except Exception as e:
                errors.append(f"板块资金流: {e}")
                _debug_log(f"[WARN] get_sector_performance: 板块资金流失败 - {e}")

        _debug_log(f"[ERROR] get_sector_performance: 所有数据源失败 - {errors}")
        return None


# 全局单例
_live_data_service: Optional[LiveDataService] = None


def get_live_data_service(force_reload: bool = False) -> LiveDataService:
    """获取实时数据服务单例"""
    global _live_data_service
    if _live_data_service is None or force_reload:
        _live_data_service = LiveDataService()
    return _live_data_service


def reload_live_data_service() -> LiveDataService:
    """重新加载数据服务（配置变更后调用）"""
    return get_live_data_service(force_reload=True)
