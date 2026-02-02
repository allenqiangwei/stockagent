"""TuShare数据采集器"""
import time
import pandas as pd
import tushare as ts

from src.data_collector.base_collector import BaseCollector
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TuShareCollector(BaseCollector):
    """TuShare数据采集器

    使用TuShare Pro API获取A股行情数据。
    需要TuShare Pro账号和足够的积分。

    API文档: https://tushare.pro/document/2
    """

    def __init__(
        self,
        token: str,
        request_interval: float = 0.3,
        max_retries: int = 3,
    ):
        """初始化TuShare采集器

        Args:
            token: TuShare Pro API token
            request_interval: 请求间隔(秒)，避免频率限制
            max_retries: 最大重试次数
        """
        super().__init__(max_retries=max_retries)
        self.request_interval = request_interval
        self._api = ts.pro_api(token)

    def _rate_limit(self):
        """请求频率限制"""
        time.sleep(self.request_interval)

    def _fetch_stock_list(self) -> pd.DataFrame:
        """获取A股股票列表

        Returns:
            DataFrame with columns: ts_code, name, industry, market, list_date
        """
        logger.info("正在获取A股股票列表...")
        self._rate_limit()

        df = self._api.stock_basic(
            exchange="",
            list_status="L",  # 上市状态
            fields="ts_code,name,industry,market,list_date"
        )

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
            ts_code: 股票代码
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)

        Returns:
            日线数据
        """
        self._rate_limit()

        df = self._api.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

        return df

    def _fetch_daily_all(self, trade_date: str) -> pd.DataFrame:
        """获取指定交易日全市场日线数据

        Args:
            trade_date: 交易日期 (YYYYMMDD)

        Returns:
            全市场日线数据
        """
        logger.info(f"正在获取 {trade_date} 全市场日线数据...")
        self._rate_limit()

        df = self._api.daily(trade_date=trade_date)

        logger.info(f"获取到 {len(df)} 条记录")
        return df

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

        df = self._api.index_daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

        return df

    def _fetch_money_flow(self, trade_date: str) -> pd.DataFrame:
        """获取资金流数据

        Args:
            trade_date: 交易日期

        Returns:
            资金流数据
        """
        logger.info(f"正在获取 {trade_date} 资金流数据...")
        self._rate_limit()

        df = self._api.moneyflow(trade_date=trade_date)

        logger.info(f"获取到 {len(df)} 条资金流记录")
        return df

    def get_trade_calendar(
        self,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取交易日历

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            交易日历 (is_open=1表示交易日)
        """
        self._rate_limit()

        df = self._api.trade_cal(
            exchange="SSE",
            start_date=start_date,
            end_date=end_date,
        )

        return df

    def get_daily_basic(self, trade_date: str) -> pd.DataFrame:
        """获取每日基本面指标

        包含PE、PB、市值等数据

        Args:
            trade_date: 交易日期

        Returns:
            基本面数据
        """
        logger.info(f"正在获取 {trade_date} 基本面数据...")
        self._rate_limit()

        df = self._api.daily_basic(
            trade_date=trade_date,
            fields="ts_code,trade_date,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,total_mv,circ_mv"
        )

        logger.info(f"获取到 {len(df)} 条基本面记录")
        return df
