"""Parquet文件存储管理模块"""
import os
from typing import Optional
import pandas as pd


class ParquetStorage:
    """Parquet文件存储管理器

    按年份分区存储历史K线数据，支持增量追加和日期范围查询。

    目录结构:
        {base_dir}/
        ├── daily/
        │   ├── 2023.parquet
        │   ├── 2024.parquet
        │   └── 2025.parquet
        ├── index/
        │   └── 2025.parquet
        └── money_flow/
            └── 2025.parquet
    """

    def __init__(self, base_dir: str):
        """初始化存储管理器

        Args:
            base_dir: 数据存储根目录
        """
        self.base_dir = base_dir
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """确保所需目录存在"""
        for subdir in ["daily", "index", "money_flow"]:
            os.makedirs(os.path.join(self.base_dir, subdir), exist_ok=True)

    def _get_file_path(self, data_type: str, year: str) -> str:
        """获取文件路径

        Args:
            data_type: 数据类型 (daily, index, money_flow)
            year: 年份

        Returns:
            完整文件路径
        """
        return os.path.join(self.base_dir, data_type, f"{year}.parquet")

    def _save(self, data_type: str, year: str, df: pd.DataFrame) -> None:
        """保存数据到Parquet文件

        Args:
            data_type: 数据类型
            year: 年份
            df: 数据DataFrame
        """
        file_path = self._get_file_path(data_type, year)
        df.to_parquet(file_path, index=False, compression="snappy")

    def _load(
        self,
        data_type: str,
        year: str,
        columns: Optional[list] = None,
    ) -> pd.DataFrame:
        """加载Parquet文件

        Args:
            data_type: 数据类型
            year: 年份
            columns: 要加载的列（可选）

        Returns:
            数据DataFrame，文件不存在返回空DataFrame
        """
        file_path = self._get_file_path(data_type, year)
        if not os.path.exists(file_path):
            return pd.DataFrame()

        return pd.read_parquet(file_path, columns=columns)

    def _append(self, data_type: str, year: str, df: pd.DataFrame) -> None:
        """追加数据到现有文件

        Args:
            data_type: 数据类型
            year: 年份
            df: 要追加的数据
        """
        existing = self._load(data_type, year)
        if len(existing) > 0:
            combined = pd.concat([existing, df], ignore_index=True)
            # 去重（基于ts_code和trade_date）
            if "ts_code" in combined.columns and "trade_date" in combined.columns:
                combined = combined.drop_duplicates(
                    subset=["ts_code", "trade_date"],
                    keep="last"
                )
        else:
            combined = df

        self._save(data_type, year, combined)

    # ===== Daily Data =====

    def save_daily(self, year: str, df: pd.DataFrame) -> None:
        """保存日线数据

        Args:
            year: 年份
            df: 日线数据
        """
        self._save("daily", year, df)

    def append_daily(self, year: str, df: pd.DataFrame) -> None:
        """追加日线数据

        Args:
            year: 年份
            df: 要追加的日线数据
        """
        self._append("daily", year, df)

    def load_daily(
        self,
        year: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        ts_codes: Optional[list] = None,
    ) -> pd.DataFrame:
        """加载日线数据

        Args:
            year: 年份
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            ts_codes: 股票代码列表

        Returns:
            日线数据DataFrame
        """
        df = self._load("daily", year)
        if len(df) == 0:
            return df

        if start_date:
            df = df[df["trade_date"] >= start_date]
        if end_date:
            df = df[df["trade_date"] <= end_date]
        if ts_codes:
            df = df[df["ts_code"].isin(ts_codes)]

        return df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    # ===== Index Data =====

    def save_index(self, year: str, df: pd.DataFrame) -> None:
        """保存指数数据"""
        self._save("index", year, df)

    def append_index(self, year: str, df: pd.DataFrame) -> None:
        """追加指数数据"""
        self._append("index", year, df)

    def load_index(
        self,
        year: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """加载指数数据"""
        df = self._load("index", year)
        if len(df) == 0:
            return df

        if start_date:
            df = df[df["trade_date"] >= start_date]
        if end_date:
            df = df[df["trade_date"] <= end_date]

        return df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    # ===== Money Flow Data =====

    def save_money_flow(self, year: str, df: pd.DataFrame) -> None:
        """保存资金流数据"""
        self._save("money_flow", year, df)

    def append_money_flow(self, year: str, df: pd.DataFrame) -> None:
        """追加资金流数据"""
        self._append("money_flow", year, df)

    def load_money_flow(
        self,
        year: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """加载资金流数据"""
        df = self._load("money_flow", year)
        if len(df) == 0:
            return df

        if start_date:
            df = df[df["trade_date"] >= start_date]
        if end_date:
            df = df[df["trade_date"] <= end_date]

        return df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    # ===== Utilities =====

    def get_latest_trade_date(self, data_type: str = "daily") -> Optional[str]:
        """获取指定数据类型的最新交易日期

        Args:
            data_type: 数据类型

        Returns:
            最新交易日期 (YYYYMMDD) 或 None
        """
        import datetime
        current_year = datetime.date.today().year

        # 从当前年份向前查找
        for year in range(current_year, current_year - 5, -1):
            df = self._load(data_type, str(year), columns=["trade_date"])
            if len(df) > 0:
                return df["trade_date"].max()

        return None

    def load_daily_multi_year(
        self,
        start_date: str,
        end_date: str,
        ts_codes: Optional[list] = None,
    ) -> pd.DataFrame:
        """加载跨年份的日线数据

        Args:
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            ts_codes: 股票代码列表

        Returns:
            合并的日线数据
        """
        start_year = int(start_date[:4])
        end_year = int(end_date[:4])

        dfs = []
        for year in range(start_year, end_year + 1):
            df = self.load_daily(
                str(year),
                start_date=start_date if year == start_year else None,
                end_date=end_date if year == end_year else None,
                ts_codes=ts_codes,
            )
            if len(df) > 0:
                dfs.append(df)

        if not dfs:
            return pd.DataFrame()

        return pd.concat(dfs, ignore_index=True).sort_values(
            ["ts_code", "trade_date"]
        ).reset_index(drop=True)
