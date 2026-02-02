"""数据采集器基类"""
import time
from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


class CollectorError(Exception):
    """数据采集相关错误"""
    pass


class BaseCollector(ABC):
    """数据采集器抽象基类

    定义统一的数据采集接口，所有具体采集器（TuShare、AkShare等）需实现此接口。
    包含自动重试机制。
    """

    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0):
        """初始化采集器

        Args:
            max_retries: 最大重试次数
            retry_delay: 重试间隔(秒)
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _retry(self, func, *args, **kwargs):
        """带重试的函数调用

        Args:
            func: 要执行的函数
            *args, **kwargs: 函数参数

        Returns:
            函数返回值

        Raises:
            CollectorError: 超过最大重试次数
        """
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(
                    f"采集失败 (尝试 {attempt}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        raise CollectorError(f"采集失败，已重试{self.max_retries}次: {last_error}")

    # ===== Public Interface =====

    def get_stock_list(self) -> pd.DataFrame:
        """获取A股股票列表

        Returns:
            包含ts_code, name, industry等字段的DataFrame
        """
        return self._retry(self._fetch_stock_list)

    def get_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取单只股票的日线数据

        Args:
            ts_code: 股票代码 (如 000001.SZ)
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)

        Returns:
            日线数据DataFrame
        """
        return self._retry(self._fetch_daily, ts_code, start_date, end_date)

    def get_daily_all(
        self,
        trade_date: str
    ) -> pd.DataFrame:
        """获取指定交易日的所有股票日线数据

        Args:
            trade_date: 交易日期 (YYYYMMDD)

        Returns:
            全市场日线数据
        """
        return self._retry(self._fetch_daily_all, trade_date)

    def get_index_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取指数日线数据

        Args:
            ts_code: 指数代码 (如 000001.SH)
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            指数日线数据
        """
        return self._retry(self._fetch_index_daily, ts_code, start_date, end_date)

    def get_money_flow(self, trade_date: str) -> pd.DataFrame:
        """获取资金流数据

        Args:
            trade_date: 交易日期

        Returns:
            资金流数据
        """
        return self._retry(self._fetch_money_flow, trade_date)

    # ===== Abstract Methods (子类必须实现) =====

    @abstractmethod
    def _fetch_stock_list(self) -> pd.DataFrame:
        """获取股票列表的具体实现"""
        pass

    @abstractmethod
    def _fetch_daily(
        self, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """获取单只股票日线数据的具体实现"""
        pass

    def _fetch_daily_all(self, trade_date: str) -> pd.DataFrame:
        """获取指定日期全市场数据的具体实现

        默认实现为空，因为不是所有数据源都支持此功能
        """
        raise NotImplementedError("此数据源不支持获取全市场日线数据")

    @abstractmethod
    def _fetch_index_daily(
        self, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """获取指数日线数据的具体实现"""
        pass

    @abstractmethod
    def _fetch_money_flow(self, trade_date: str) -> pd.DataFrame:
        """获取资金流数据的具体实现"""
        pass
