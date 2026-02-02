"""数据采集器管理器，处理多源切换和容灾"""
from typing import List, Optional
import pandas as pd

from src.data_collector.base_collector import BaseCollector, CollectorError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CollectorManager:
    """数据采集器管理器

    管理多个数据源，实现自动容灾切换。
    优先使用主数据源，失败时依次尝试备用源。
    """

    def __init__(
        self,
        primary: BaseCollector,
        fallbacks: Optional[List[BaseCollector]] = None
    ):
        """初始化管理器

        Args:
            primary: 主数据源
            fallbacks: 备用数据源列表
        """
        self.primary = primary
        self.fallbacks = fallbacks or []
        self._all_sources = [primary] + self.fallbacks

    def _try_sources(self, method_name: str, *args, **kwargs) -> pd.DataFrame:
        """尝试从多个数据源获取数据

        Args:
            method_name: 要调用的方法名
            *args, **kwargs: 方法参数

        Returns:
            获取到的数据

        Raises:
            CollectorError: 所有数据源都失败
        """
        errors = []

        for i, source in enumerate(self._all_sources):
            source_name = source.__class__.__name__
            try:
                method = getattr(source, method_name)
                result = method(*args, **kwargs)

                if i > 0:
                    logger.info(f"使用备用数据源 {source_name} 成功")

                return result

            except (CollectorError, Exception) as e:
                errors.append(f"{source_name}: {e}")
                logger.warning(f"数据源 {source_name} 失败: {e}")
                continue

        # 所有数据源都失败
        error_msg = "所有数据源都失败:\n" + "\n".join(errors)
        logger.error(error_msg)
        raise CollectorError(error_msg)

    def get_stock_list(self) -> pd.DataFrame:
        """获取A股股票列表"""
        return self._try_sources("get_stock_list")

    def get_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取单只股票日线数据"""
        return self._try_sources("get_daily", ts_code, start_date, end_date)

    def get_daily_all(self, trade_date: str) -> pd.DataFrame:
        """获取指定交易日全市场日线数据"""
        return self._try_sources("get_daily_all", trade_date)

    def get_index_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取指数日线数据"""
        return self._try_sources("get_index_daily", ts_code, start_date, end_date)

    def get_money_flow(self, trade_date: str) -> pd.DataFrame:
        """获取资金流数据"""
        return self._try_sources("get_money_flow", trade_date)


def create_collector_manager(config) -> CollectorManager:
    """根据配置创建采集器管理器

    Args:
        config: Config对象

    Returns:
        配置好的CollectorManager
    """
    from src.data_collector.tushare_collector import TuShareCollector
    from src.data_collector.akshare_collector import AkShareCollector

    # 创建主数据源
    primary_source = config.get("collector.primary_source", "tushare")

    if primary_source == "tushare":
        token = config.get("tushare.token")
        if not token:
            raise ValueError("TuShare token未配置")
        primary = TuShareCollector(
            token=token,
            request_interval=config.get("collector.request_interval", 0.3),
        )
    else:
        primary = AkShareCollector()

    # 创建备用数据源
    fallbacks = []
    fallback_sources = config.get("collector.fallback_sources", [])

    for source in fallback_sources:
        if source == "akshare" and primary_source != "akshare":
            fallbacks.append(AkShareCollector())
        # baostock暂不实现，可后续添加

    return CollectorManager(primary=primary, fallbacks=fallbacks)
