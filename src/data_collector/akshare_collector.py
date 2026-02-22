"""AkShare数据采集器（备用数据源）

数据获取时自动绕过系统代理，直连国内数据源。
"""
import time
import pandas as pd
import akshare as ak

from src.data_collector.base_collector import BaseCollector
from src.utils.logger import get_logger
from src.utils.network import no_proxy

logger = get_logger(__name__)


class AkShareCollector(BaseCollector):
    """AkShare数据采集器

    作为TuShare的备用数据源。AkShare是免费的，但数据更新可能稍慢。

    API文档: https://akshare.akfamily.xyz/
    """

    def __init__(
        self,
        request_interval: float = 0.5,
        max_retries: int = 3,
    ):
        """初始化AkShare采集器

        Args:
            request_interval: 请求间隔(秒)
            max_retries: 最大重试次数
        """
        super().__init__(max_retries=max_retries)
        self.request_interval = request_interval

    def _rate_limit(self):
        """请求频率限制"""
        time.sleep(self.request_interval)

    def _convert_code_to_ts(self, code: str) -> str:
        """将纯数字代码转换为ts_code格式

        Args:
            code: 纯数字代码 (如 000001)

        Returns:
            ts_code格式 (如 000001.SZ)
        """
        if code.startswith("6"):
            return f"{code}.SH"
        else:
            return f"{code}.SZ"

    def _convert_ts_to_code(self, ts_code: str) -> str:
        """将ts_code格式转换为纯数字代码

        Args:
            ts_code: ts_code格式 (如 000001.SZ)

        Returns:
            纯数字代码 (如 000001)
        """
        return ts_code.split(".")[0]

    def _fetch_stock_list(self) -> pd.DataFrame:
        """获取A股股票列表

        Returns:
            DataFrame with columns: ts_code, name
        """
        logger.info("正在通过AkShare获取A股股票列表...")
        self._rate_limit()

        with no_proxy():
            df = ak.stock_info_a_code_name()

        # 转换为统一格式
        df["ts_code"] = df["code"].apply(self._convert_code_to_ts)
        df = df.rename(columns={"name": "name"})
        df = df[["ts_code", "name"]]

        # AkShare不提供industry字段，设为空
        df["industry"] = ""
        df["market"] = ""
        df["list_date"] = ""

        logger.info(f"获取到 {len(df)} 只股票")
        return df

    def _fetch_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取单只股票日线数据

        Args:
            ts_code: 股票代码 (如 000001.SZ)
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)

        Returns:
            日线数据（统一字段格式）
        """
        self._rate_limit()

        code = self._convert_ts_to_code(ts_code)

        # AkShare使用 YYYY-MM-DD 格式
        start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"

        with no_proxy():
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start,
                end_date=end,
                adjust="qfq",  # 前复权
            )

        if df.empty:
            return pd.DataFrame()

        # 转换为统一格式
        df = df.rename(columns={
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "vol",
            "成交额": "amount",
        })

        # 转换日期格式
        df["trade_date"] = df["trade_date"].str.replace("-", "")
        df["ts_code"] = ts_code

        return df[["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]]

    def _fetch_index_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取指数日线数据

        Args:
            ts_code: 指数代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            指数日线数据
        """
        self._rate_limit()

        # AkShare指数代码映射
        index_map = {
            "000001.SH": "sh000001",  # 上证指数
            "399001.SZ": "sz399001",  # 深证成指
            "399006.SZ": "sz399006",  # 创业板指
        }

        ak_code = index_map.get(ts_code)
        if not ak_code:
            logger.warning(f"未知指数代码: {ts_code}")
            return pd.DataFrame()

        with no_proxy():
            df = ak.stock_zh_index_daily(symbol=ak_code)

        if df.empty:
            return pd.DataFrame()

        # 过滤日期范围
        df["trade_date"] = df["date"].astype(str).str.replace("-", "")
        df = df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)]

        df["ts_code"] = ts_code

        return df[["ts_code", "trade_date", "open", "high", "low", "close", "volume"]]

    def _fetch_money_flow(self, trade_date: str) -> pd.DataFrame:
        """获取资金流数据

        注意: AkShare的资金流接口与TuShare不同，此处返回空DataFrame
        """
        logger.warning("AkShare资金流数据接口不兼容，请使用TuShare")
        return pd.DataFrame()
