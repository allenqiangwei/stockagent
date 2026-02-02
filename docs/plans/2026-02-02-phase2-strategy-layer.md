# 第二阶段：策略层实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 构建完整的策略信号生成系统，包括技术指标计算、波段交易策略、趋势跟踪策略、XGBoost模型和信号组合。

**Architecture:** 基于TA-Lib的技术指标 → 波段/趋势双策略信号 → XGBoost多分类模型 → 加权信号组合（35%+35%+30%）

**Tech Stack:** Python 3.9+, TA-Lib, pandas, numpy, xgboost, scikit-learn, pytest

---

## 前置准备

### Task 0: 安装TA-Lib依赖

**Step 1: 安装TA-Lib C库（macOS）**

```bash
brew install ta-lib
```

**Step 2: 安装Python包装器**

```bash
pip install TA-Lib
```

**Step 3: 更新requirements.txt**

在requirements.txt中添加：
```txt
# Technical Analysis
TA-Lib>=0.4.28

# Machine Learning
xgboost>=2.0.0
scikit-learn>=1.3.0
joblib>=1.3.0
```

**Step 4: 安装新依赖**

```bash
pip install -r requirements.txt
```

**Step 5: 验证安装**

```bash
python -c "import talib; print(talib.__version__)"
python -c "import xgboost; print(xgboost.__version__)"
```

**Step 6: 创建目录结构**

```bash
mkdir -p src/indicators src/signals src/ml_models/models
touch src/indicators/__init__.py src/signals/__init__.py src/ml_models/__init__.py
```

**Step 7: Commit**

```bash
git add -A
git commit -m "chore: add TA-Lib and XGBoost dependencies for phase 2"
```

---

## 模块1: 技术指标

### Task 1: 指标基类

**Files:**
- Create: `src/indicators/base_indicator.py`
- Create: `tests/test_indicators.py`

**Step 1: 写失败测试**

`tests/test_indicators.py`:
```python
import pytest
import pandas as pd
import numpy as np
from src.indicators.base_indicator import BaseIndicator


class MockIndicator(BaseIndicator):
    """测试用的Mock指标"""

    @property
    def name(self) -> str:
        return "mock"

    @property
    def columns(self) -> list:
        return ["mock_value"]

    def _calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["mock_value"] = df["close"] * 2
        return df


class TestBaseIndicator:
    @pytest.fixture
    def sample_df(self):
        """创建测试用的OHLCV数据"""
        return pd.DataFrame({
            "ts_code": ["000001.SZ"] * 10,
            "trade_date": pd.date_range("2025-01-01", periods=10).strftime("%Y%m%d"),
            "open": [10.0, 10.5, 10.3, 10.8, 11.0, 10.9, 11.2, 11.5, 11.3, 11.8],
            "high": [10.5, 10.8, 10.6, 11.0, 11.3, 11.2, 11.5, 11.8, 11.6, 12.0],
            "low": [9.8, 10.2, 10.0, 10.5, 10.8, 10.6, 11.0, 11.2, 11.0, 11.5],
            "close": [10.2, 10.6, 10.4, 10.9, 11.1, 11.0, 11.3, 11.6, 11.4, 11.9],
            "vol": [1000000] * 10,
            "amount": [10000000] * 10,
        })

    def test_calculate_adds_columns(self, sample_df):
        """测试计算后添加了新列"""
        indicator = MockIndicator()
        result = indicator.calculate(sample_df)

        assert "mock_value" in result.columns
        assert len(result) == len(sample_df)

    def test_calculate_preserves_original_columns(self, sample_df):
        """测试保留原始列"""
        indicator = MockIndicator()
        result = indicator.calculate(sample_df)

        for col in ["ts_code", "trade_date", "open", "high", "low", "close"]:
            assert col in result.columns

    def test_indicator_name_property(self):
        """测试指标名称属性"""
        indicator = MockIndicator()
        assert indicator.name == "mock"

    def test_indicator_columns_property(self):
        """测试输出列属性"""
        indicator = MockIndicator()
        assert indicator.columns == ["mock_value"]
```

**Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_indicators.py -v
```
Expected: FAIL (ModuleNotFoundError)

**Step 3: 实现基类**

`src/indicators/base_indicator.py`:
```python
"""技术指标基类"""
from abc import ABC, abstractmethod
from typing import List
import pandas as pd


class BaseIndicator(ABC):
    """技术指标抽象基类

    所有技术指标都应继承此类，并实现_calculate方法。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """指标名称"""
        pass

    @property
    @abstractmethod
    def columns(self) -> List[str]:
        """该指标生成的列名列表"""
        pass

    @abstractmethod
    def _calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算指标的具体实现

        Args:
            df: 包含OHLCV数据的DataFrame

        Returns:
            添加了指标列的DataFrame
        """
        pass

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算指标（公共接口）

        Args:
            df: 包含OHLCV数据的DataFrame，需包含以下列：
                - open, high, low, close: 价格数据
                - vol: 成交量（可选）

        Returns:
            添加了指标列的DataFrame
        """
        if df.empty:
            return df

        return self._calculate(df)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name})"
```

**Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_indicators.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/indicators/base_indicator.py tests/test_indicators.py
git commit -m "feat: add BaseIndicator abstract class"
```

---

### Task 2: 趋势指标（MA/EMA/MACD/ADX）

**Files:**
- Create: `src/indicators/trend_indicators.py`
- Update: `tests/test_indicators.py`

**Step 1: 写失败测试**

在 `tests/test_indicators.py` 添加：
```python
from src.indicators.trend_indicators import (
    MAIndicator, EMAIndicator, MACDIndicator, ADXIndicator
)


class TestMAIndicator:
    @pytest.fixture
    def sample_df(self):
        """创建足够长的测试数据（60天以上）"""
        np.random.seed(42)
        n = 100
        close = 10 + np.cumsum(np.random.randn(n) * 0.1)
        return pd.DataFrame({
            "ts_code": ["000001.SZ"] * n,
            "trade_date": pd.date_range("2025-01-01", periods=n).strftime("%Y%m%d"),
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "vol": [1000000] * n,
        })

    def test_ma_calculation(self, sample_df):
        """测试MA计算"""
        indicator = MAIndicator(periods=[5, 10, 20])
        result = indicator.calculate(sample_df)

        assert "ma5" in result.columns
        assert "ma10" in result.columns
        assert "ma20" in result.columns

        # 前N-1个值应该是NaN
        assert pd.isna(result["ma5"].iloc[3])
        assert pd.notna(result["ma5"].iloc[5])

    def test_ma_values_correct(self, sample_df):
        """测试MA计算值正确"""
        indicator = MAIndicator(periods=[5])
        result = indicator.calculate(sample_df)

        # 手动计算第5个MA5
        expected = sample_df["close"].iloc[:5].mean()
        assert abs(result["ma5"].iloc[4] - expected) < 0.0001


class TestEMAIndicator:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        n = 100
        close = 10 + np.cumsum(np.random.randn(n) * 0.1)
        return pd.DataFrame({
            "close": close,
        })

    def test_ema_calculation(self, sample_df):
        """测试EMA计算"""
        indicator = EMAIndicator(periods=[12, 26])
        result = indicator.calculate(sample_df)

        assert "ema12" in result.columns
        assert "ema26" in result.columns


class TestMACDIndicator:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        n = 100
        close = 10 + np.cumsum(np.random.randn(n) * 0.1)
        return pd.DataFrame({
            "close": close,
        })

    def test_macd_calculation(self, sample_df):
        """测试MACD计算"""
        indicator = MACDIndicator()
        result = indicator.calculate(sample_df)

        assert "macd" in result.columns
        assert "macd_signal" in result.columns
        assert "macd_hist" in result.columns

    def test_macd_golden_cross(self, sample_df):
        """测试MACD金叉判断"""
        indicator = MACDIndicator()
        result = indicator.calculate(sample_df)

        # macd_hist > 0 且前一天 < 0 即为金叉
        result["golden_cross"] = (result["macd_hist"] > 0) & (result["macd_hist"].shift(1) < 0)
        assert "golden_cross" in result.columns


class TestADXIndicator:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        n = 100
        close = 10 + np.cumsum(np.random.randn(n) * 0.1)
        return pd.DataFrame({
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
        })

    def test_adx_calculation(self, sample_df):
        """测试ADX计算"""
        indicator = ADXIndicator()
        result = indicator.calculate(sample_df)

        assert "adx" in result.columns
        assert "plus_di" in result.columns
        assert "minus_di" in result.columns

    def test_adx_range(self, sample_df):
        """测试ADX值在0-100范围内"""
        indicator = ADXIndicator()
        result = indicator.calculate(sample_df)

        valid_adx = result["adx"].dropna()
        assert (valid_adx >= 0).all()
        assert (valid_adx <= 100).all()
```

**Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_indicators.py::TestMAIndicator -v
python -m pytest tests/test_indicators.py::TestEMAIndicator -v
python -m pytest tests/test_indicators.py::TestMACDIndicator -v
python -m pytest tests/test_indicators.py::TestADXIndicator -v
```
Expected: FAIL

**Step 3: 实现趋势指标**

`src/indicators/trend_indicators.py`:
```python
"""趋势类技术指标"""
from typing import List
import pandas as pd
import numpy as np
import talib

from src.indicators.base_indicator import BaseIndicator


class MAIndicator(BaseIndicator):
    """简单移动平均线指标"""

    def __init__(self, periods: List[int] = None):
        """
        Args:
            periods: MA周期列表，默认[5, 10, 20, 60]
        """
        self.periods = periods or [5, 10, 20, 60]

    @property
    def name(self) -> str:
        return "ma"

    @property
    def columns(self) -> List[str]:
        return [f"ma{p}" for p in self.periods]

    def _calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"].values

        for period in self.periods:
            df[f"ma{period}"] = talib.SMA(close, timeperiod=period)

        return df


class EMAIndicator(BaseIndicator):
    """指数移动平均线指标"""

    def __init__(self, periods: List[int] = None):
        """
        Args:
            periods: EMA周期列表，默认[12, 26]
        """
        self.periods = periods or [12, 26]

    @property
    def name(self) -> str:
        return "ema"

    @property
    def columns(self) -> List[str]:
        return [f"ema{p}" for p in self.periods]

    def _calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"].values

        for period in self.periods:
            df[f"ema{period}"] = talib.EMA(close, timeperiod=period)

        return df


class MACDIndicator(BaseIndicator):
    """MACD指标"""

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ):
        """
        Args:
            fast_period: 快线周期
            slow_period: 慢线周期
            signal_period: 信号线周期
        """
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

    @property
    def name(self) -> str:
        return "macd"

    @property
    def columns(self) -> List[str]:
        return ["macd", "macd_signal", "macd_hist"]

    def _calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"].values

        macd, signal, hist = talib.MACD(
            close,
            fastperiod=self.fast_period,
            slowperiod=self.slow_period,
            signalperiod=self.signal_period,
        )

        df["macd"] = macd
        df["macd_signal"] = signal
        df["macd_hist"] = hist

        return df


class ADXIndicator(BaseIndicator):
    """ADX趋势强度指标"""

    def __init__(self, period: int = 14):
        """
        Args:
            period: ADX计算周期
        """
        self.period = period

    @property
    def name(self) -> str:
        return "adx"

    @property
    def columns(self) -> List[str]:
        return ["adx", "plus_di", "minus_di"]

    def _calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        df["adx"] = talib.ADX(high, low, close, timeperiod=self.period)
        df["plus_di"] = talib.PLUS_DI(high, low, close, timeperiod=self.period)
        df["minus_di"] = talib.MINUS_DI(high, low, close, timeperiod=self.period)

        return df
```

**Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_indicators.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/indicators/trend_indicators.py tests/test_indicators.py
git commit -m "feat: add trend indicators (MA/EMA/MACD/ADX) using TA-Lib"
```

---

### Task 3: 动量指标（RSI/KDJ）

**Files:**
- Create: `src/indicators/momentum_indicators.py`
- Update: `tests/test_indicators.py`

**Step 1: 写失败测试**

在 `tests/test_indicators.py` 添加：
```python
from src.indicators.momentum_indicators import RSIIndicator, KDJIndicator


class TestRSIIndicator:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        n = 100
        close = 10 + np.cumsum(np.random.randn(n) * 0.1)
        return pd.DataFrame({"close": close})

    def test_rsi_calculation(self, sample_df):
        """测试RSI计算"""
        indicator = RSIIndicator()
        result = indicator.calculate(sample_df)

        assert "rsi" in result.columns

    def test_rsi_range(self, sample_df):
        """测试RSI值在0-100范围内"""
        indicator = RSIIndicator()
        result = indicator.calculate(sample_df)

        valid_rsi = result["rsi"].dropna()
        assert (valid_rsi >= 0).all()
        assert (valid_rsi <= 100).all()

    def test_rsi_overbought_oversold(self, sample_df):
        """测试超买超卖判断"""
        indicator = RSIIndicator()
        result = indicator.calculate(sample_df)

        result["overbought"] = result["rsi"] > 70
        result["oversold"] = result["rsi"] < 30

        assert "overbought" in result.columns
        assert "oversold" in result.columns


class TestKDJIndicator:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        n = 100
        close = 10 + np.cumsum(np.random.randn(n) * 0.1)
        return pd.DataFrame({
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
        })

    def test_kdj_calculation(self, sample_df):
        """测试KDJ计算"""
        indicator = KDJIndicator()
        result = indicator.calculate(sample_df)

        assert "k" in result.columns
        assert "d" in result.columns
        assert "j" in result.columns

    def test_kdj_range(self, sample_df):
        """测试K和D值在0-100范围内"""
        indicator = KDJIndicator()
        result = indicator.calculate(sample_df)

        valid_k = result["k"].dropna()
        valid_d = result["d"].dropna()

        assert (valid_k >= 0).all() and (valid_k <= 100).all()
        assert (valid_d >= 0).all() and (valid_d <= 100).all()
```

**Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_indicators.py::TestRSIIndicator -v
python -m pytest tests/test_indicators.py::TestKDJIndicator -v
```
Expected: FAIL

**Step 3: 实现动量指标**

`src/indicators/momentum_indicators.py`:
```python
"""动量类技术指标"""
from typing import List
import pandas as pd
import numpy as np
import talib

from src.indicators.base_indicator import BaseIndicator


class RSIIndicator(BaseIndicator):
    """RSI相对强弱指标"""

    def __init__(self, period: int = 14):
        """
        Args:
            period: RSI计算周期
        """
        self.period = period

    @property
    def name(self) -> str:
        return "rsi"

    @property
    def columns(self) -> List[str]:
        return ["rsi"]

    def _calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"].values

        df["rsi"] = talib.RSI(close, timeperiod=self.period)

        return df


class KDJIndicator(BaseIndicator):
    """KDJ随机指标"""

    def __init__(
        self,
        k_period: int = 9,
        d_period: int = 3,
        j_period: int = 3,
    ):
        """
        Args:
            k_period: K值周期
            d_period: D值周期
            j_period: J值计算用的周期
        """
        self.k_period = k_period
        self.d_period = d_period
        self.j_period = j_period

    @property
    def name(self) -> str:
        return "kdj"

    @property
    def columns(self) -> List[str]:
        return ["k", "d", "j"]

    def _calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        # 使用STOCH计算K和D
        k, d = talib.STOCH(
            high, low, close,
            fastk_period=self.k_period,
            slowk_period=self.d_period,
            slowk_matype=0,
            slowd_period=self.d_period,
            slowd_matype=0,
        )

        df["k"] = k
        df["d"] = d
        df["j"] = 3 * k - 2 * d  # J = 3K - 2D

        return df
```

**Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_indicators.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/indicators/momentum_indicators.py tests/test_indicators.py
git commit -m "feat: add momentum indicators (RSI/KDJ) using TA-Lib"
```

---

### Task 4: 量价指标（OBV/ATR）

**Files:**
- Create: `src/indicators/volume_indicators.py`
- Update: `tests/test_indicators.py`

**Step 1: 写失败测试**

在 `tests/test_indicators.py` 添加：
```python
from src.indicators.volume_indicators import OBVIndicator, ATRIndicator, VolumeMAIndicator


class TestOBVIndicator:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        n = 100
        close = 10 + np.cumsum(np.random.randn(n) * 0.1)
        return pd.DataFrame({
            "close": close,
            "vol": np.random.randint(500000, 1500000, n),
        })

    def test_obv_calculation(self, sample_df):
        """测试OBV计算"""
        indicator = OBVIndicator()
        result = indicator.calculate(sample_df)

        assert "obv" in result.columns


class TestATRIndicator:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        n = 100
        close = 10 + np.cumsum(np.random.randn(n) * 0.1)
        return pd.DataFrame({
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
        })

    def test_atr_calculation(self, sample_df):
        """测试ATR计算"""
        indicator = ATRIndicator()
        result = indicator.calculate(sample_df)

        assert "atr" in result.columns

    def test_atr_positive(self, sample_df):
        """测试ATR值为正"""
        indicator = ATRIndicator()
        result = indicator.calculate(sample_df)

        valid_atr = result["atr"].dropna()
        assert (valid_atr >= 0).all()


class TestVolumeMAIndicator:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        n = 100
        return pd.DataFrame({
            "vol": np.random.randint(500000, 1500000, n),
        })

    def test_volume_ma_calculation(self, sample_df):
        """测试成交量均线计算"""
        indicator = VolumeMAIndicator(periods=[5, 10])
        result = indicator.calculate(sample_df)

        assert "vol_ma5" in result.columns
        assert "vol_ma10" in result.columns

    def test_volume_ratio(self, sample_df):
        """测试量比计算"""
        indicator = VolumeMAIndicator(periods=[5])
        result = indicator.calculate(sample_df)

        result["vol_ratio"] = result["vol"] / result["vol_ma5"]
        assert "vol_ratio" in result.columns
```

**Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_indicators.py::TestOBVIndicator -v
python -m pytest tests/test_indicators.py::TestATRIndicator -v
python -m pytest tests/test_indicators.py::TestVolumeMAIndicator -v
```
Expected: FAIL

**Step 3: 实现量价指标**

`src/indicators/volume_indicators.py`:
```python
"""量价类技术指标"""
from typing import List
import pandas as pd
import numpy as np
import talib

from src.indicators.base_indicator import BaseIndicator


class OBVIndicator(BaseIndicator):
    """OBV能量潮指标"""

    @property
    def name(self) -> str:
        return "obv"

    @property
    def columns(self) -> List[str]:
        return ["obv"]

    def _calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"].values
        volume = df["vol"].values.astype(float)

        df["obv"] = talib.OBV(close, volume)

        return df


class ATRIndicator(BaseIndicator):
    """ATR平均真实波幅指标"""

    def __init__(self, period: int = 14):
        """
        Args:
            period: ATR计算周期
        """
        self.period = period

    @property
    def name(self) -> str:
        return "atr"

    @property
    def columns(self) -> List[str]:
        return ["atr"]

    def _calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        df["atr"] = talib.ATR(high, low, close, timeperiod=self.period)

        return df


class VolumeMAIndicator(BaseIndicator):
    """成交量移动平均指标"""

    def __init__(self, periods: List[int] = None):
        """
        Args:
            periods: 均线周期列表
        """
        self.periods = periods or [5, 10, 20]

    @property
    def name(self) -> str:
        return "vol_ma"

    @property
    def columns(self) -> List[str]:
        return [f"vol_ma{p}" for p in self.periods]

    def _calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        volume = df["vol"].values.astype(float)

        for period in self.periods:
            df[f"vol_ma{period}"] = talib.SMA(volume, timeperiod=period)

        return df
```

**Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_indicators.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/indicators/volume_indicators.py tests/test_indicators.py
git commit -m "feat: add volume indicators (OBV/ATR/VolumeMA) using TA-Lib"
```

---

### Task 5: 指标计算器

**Files:**
- Create: `src/indicators/indicator_calculator.py`
- Update: `tests/test_indicators.py`

**Step 1: 写失败测试**

在 `tests/test_indicators.py` 添加：
```python
from src.indicators.indicator_calculator import IndicatorCalculator
from src.indicators.trend_indicators import MAIndicator, MACDIndicator
from src.indicators.momentum_indicators import RSIIndicator


class TestIndicatorCalculator:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        n = 100
        close = 10 + np.cumsum(np.random.randn(n) * 0.1)
        return pd.DataFrame({
            "ts_code": ["000001.SZ"] * n,
            "trade_date": pd.date_range("2025-01-01", periods=n).strftime("%Y%m%d"),
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "vol": [1000000] * n,
        })

    def test_calculate_all_indicators(self, sample_df):
        """测试批量计算所有指标"""
        calculator = IndicatorCalculator([
            MAIndicator(periods=[5, 20]),
            MACDIndicator(),
            RSIIndicator(),
        ])

        result = calculator.calculate_all(sample_df)

        assert "ma5" in result.columns
        assert "ma20" in result.columns
        assert "macd" in result.columns
        assert "rsi" in result.columns

    def test_calculate_for_multiple_stocks(self, sample_df):
        """测试多只股票的指标计算"""
        # 创建两只股票的数据
        df2 = sample_df.copy()
        df2["ts_code"] = "600000.SH"
        combined = pd.concat([sample_df, df2], ignore_index=True)

        calculator = IndicatorCalculator([
            MAIndicator(periods=[5]),
            RSIIndicator(),
        ])

        result = calculator.calculate_by_stock(combined)

        assert len(result[result["ts_code"] == "000001.SZ"]) == 100
        assert len(result[result["ts_code"] == "600000.SH"]) == 100
        assert "ma5" in result.columns
        assert "rsi" in result.columns

    def test_get_default_calculator(self):
        """测试获取默认计算器"""
        calculator = IndicatorCalculator.get_default()

        assert len(calculator.indicators) > 0
```

**Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_indicators.py::TestIndicatorCalculator -v
```
Expected: FAIL

**Step 3: 实现指标计算器**

`src/indicators/indicator_calculator.py`:
```python
"""指标批量计算器"""
from typing import List
import pandas as pd

from src.indicators.base_indicator import BaseIndicator
from src.indicators.trend_indicators import MAIndicator, EMAIndicator, MACDIndicator, ADXIndicator
from src.indicators.momentum_indicators import RSIIndicator, KDJIndicator
from src.indicators.volume_indicators import OBVIndicator, ATRIndicator, VolumeMAIndicator
from src.utils.logger import get_logger

logger = get_logger(__name__)


class IndicatorCalculator:
    """指标批量计算器

    管理多个技术指标，支持批量计算和按股票分组计算。
    """

    def __init__(self, indicators: List[BaseIndicator]):
        """
        Args:
            indicators: 指标实例列表
        """
        self.indicators = indicators

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算所有指标

        Args:
            df: 单只股票的OHLCV数据

        Returns:
            添加了所有指标列的DataFrame
        """
        result = df.copy()

        for indicator in self.indicators:
            try:
                result = indicator.calculate(result)
            except Exception as e:
                logger.warning(f"计算指标 {indicator.name} 失败: {e}")

        return result

    def calculate_by_stock(self, df: pd.DataFrame) -> pd.DataFrame:
        """按股票分组计算指标

        Args:
            df: 包含多只股票的OHLCV数据，需有ts_code列

        Returns:
            添加了所有指标列的DataFrame
        """
        if "ts_code" not in df.columns:
            return self.calculate_all(df)

        results = []

        for ts_code, group in df.groupby("ts_code"):
            group_sorted = group.sort_values("trade_date").reset_index(drop=True)
            result = self.calculate_all(group_sorted)
            results.append(result)

        return pd.concat(results, ignore_index=True)

    @classmethod
    def get_default(cls) -> "IndicatorCalculator":
        """获取包含所有默认指标的计算器

        Returns:
            配置好的IndicatorCalculator实例
        """
        return cls([
            # 趋势指标
            MAIndicator(periods=[5, 10, 20, 60]),
            EMAIndicator(periods=[12, 26]),
            MACDIndicator(),
            ADXIndicator(),

            # 动量指标
            RSIIndicator(),
            KDJIndicator(),

            # 量价指标
            ATRIndicator(),
            VolumeMAIndicator(periods=[5, 10, 20]),
        ])

    def get_all_columns(self) -> List[str]:
        """获取所有指标生成的列名

        Returns:
            列名列表
        """
        columns = []
        for indicator in self.indicators:
            columns.extend(indicator.columns)
        return columns
```

**Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_indicators.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/indicators/indicator_calculator.py tests/test_indicators.py
git commit -m "feat: add IndicatorCalculator for batch indicator computation"
```

---

## 模块2: 信号生成

### Task 6: 信号基类和等级定义

**Files:**
- Create: `src/signals/base_signal.py`
- Create: `tests/test_signals.py`

**Step 1: 写失败测试**

`tests/test_signals.py`:
```python
import pytest
import pandas as pd
import numpy as np
from src.signals.base_signal import BaseSignal, SignalLevel, SignalResult


class MockSignal(BaseSignal):
    """测试用的Mock信号生成器"""

    @property
    def name(self) -> str:
        return "mock"

    def default_params(self) -> dict:
        return {"threshold": 50}

    def _generate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["mock_score"] = 75.0  # 固定分数用于测试
        return df


class TestSignalLevel:
    def test_signal_level_values(self):
        """测试信号等级值"""
        assert SignalLevel.STRONG_BUY == 5
        assert SignalLevel.WEAK_BUY == 4
        assert SignalLevel.HOLD == 3
        assert SignalLevel.WEAK_SELL == 2
        assert SignalLevel.STRONG_SELL == 1

    def test_signal_level_from_score(self):
        """测试从分数转换为信号等级"""
        assert SignalLevel.from_score(85) == SignalLevel.STRONG_BUY
        assert SignalLevel.from_score(70) == SignalLevel.WEAK_BUY
        assert SignalLevel.from_score(50) == SignalLevel.HOLD
        assert SignalLevel.from_score(30) == SignalLevel.WEAK_SELL
        assert SignalLevel.from_score(10) == SignalLevel.STRONG_SELL


class TestBaseSignal:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        n = 50
        close = 10 + np.cumsum(np.random.randn(n) * 0.1)
        return pd.DataFrame({
            "ts_code": ["000001.SZ"] * n,
            "trade_date": pd.date_range("2025-01-01", periods=n).strftime("%Y%m%d"),
            "close": close,
            "ma20": close - 0.1,
            "macd_hist": np.random.randn(n) * 0.1,
            "rsi": 50 + np.random.randn(n) * 10,
        })

    def test_generate_adds_score_column(self, sample_df):
        """测试生成信号后添加分数列"""
        signal = MockSignal()
        result = signal.generate(sample_df)

        assert "mock_score" in result.columns

    def test_default_params(self):
        """测试默认参数"""
        signal = MockSignal()
        assert signal.params["threshold"] == 50

    def test_custom_params(self):
        """测试自定义参数"""
        signal = MockSignal(params={"threshold": 70})
        assert signal.params["threshold"] == 70

    def test_signal_name_property(self):
        """测试信号名称"""
        signal = MockSignal()
        assert signal.name == "mock"
```

**Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_signals.py -v
```
Expected: FAIL

**Step 3: 实现信号基类**

`src/signals/base_signal.py`:
```python
"""信号生成基类"""
from abc import ABC, abstractmethod
from enum import IntEnum
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
import pandas as pd


class SignalLevel(IntEnum):
    """信号强度等级"""
    STRONG_BUY = 5    # 强买 (80-100分)
    WEAK_BUY = 4      # 弱买 (60-80分)
    HOLD = 3          # 持有 (40-60分)
    WEAK_SELL = 2     # 弱卖 (20-40分)
    STRONG_SELL = 1   # 强卖 (0-20分)

    @classmethod
    def from_score(cls, score: float) -> "SignalLevel":
        """从分数转换为信号等级

        Args:
            score: 0-100的分数

        Returns:
            对应的信号等级
        """
        if score >= 80:
            return cls.STRONG_BUY
        elif score >= 60:
            return cls.WEAK_BUY
        elif score >= 40:
            return cls.HOLD
        elif score >= 20:
            return cls.WEAK_SELL
        else:
            return cls.STRONG_SELL

    def to_action(self) -> str:
        """转换为操作建议

        Returns:
            BUY / HOLD / SELL
        """
        if self in (SignalLevel.STRONG_BUY, SignalLevel.WEAK_BUY):
            return "BUY"
        elif self == SignalLevel.HOLD:
            return "HOLD"
        else:
            return "SELL"


@dataclass
class SignalResult:
    """信号结果"""
    ts_code: str
    trade_date: str
    score: float
    level: SignalLevel
    action: str
    components: Dict[str, float]  # 各个条件的得分明细


class BaseSignal(ABC):
    """信号生成器抽象基类

    所有信号生成器都应继承此类，并实现_generate方法。
    信号分数范围为0-100，其中50为中性。
    """

    def __init__(self, params: Dict[str, Any] = None):
        """
        Args:
            params: 策略参数，如果不提供则使用default_params
        """
        self.params = self.default_params()
        if params:
            self.params.update(params)

    @property
    @abstractmethod
    def name(self) -> str:
        """信号名称"""
        pass

    @abstractmethod
    def default_params(self) -> Dict[str, Any]:
        """默认参数"""
        pass

    @abstractmethod
    def _generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成信号的具体实现

        Args:
            df: 包含指标数据的DataFrame

        Returns:
            添加了信号分数列的DataFrame
        """
        pass

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成信号（公共接口）

        Args:
            df: 包含指标数据的DataFrame

        Returns:
            添加了信号分数列的DataFrame
        """
        if df.empty:
            return df

        return self._generate(df)

    def score_to_level(self, score: float) -> SignalLevel:
        """分数转信号等级"""
        return SignalLevel.from_score(score)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name})"
```

**Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_signals.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/signals/base_signal.py tests/test_signals.py
git commit -m "feat: add BaseSignal class and SignalLevel enum"
```

---

### Task 7: 波段交易策略

**Files:**
- Create: `src/signals/swing_trading.py`
- Update: `tests/test_signals.py`

**Step 1: 写失败测试**

在 `tests/test_signals.py` 添加：
```python
from src.signals.swing_trading import SwingTradingSignal


class TestSwingTradingSignal:
    @pytest.fixture
    def bullish_df(self):
        """创建看涨条件的数据"""
        n = 30
        return pd.DataFrame({
            "ts_code": ["000001.SZ"] * n,
            "trade_date": pd.date_range("2025-01-01", periods=n).strftime("%Y%m%d"),
            "close": [10 + i * 0.1 for i in range(n)],  # 上涨趋势
            "ma20": [9.5 + i * 0.1 for i in range(n)],   # 价格在MA20上方
            "macd_hist": [-0.1] * 15 + [0.1] * 15,       # MACD金叉
            "vol": [1000000] * 15 + [2000000] * 15,      # 放量
            "vol_ma5": [1000000] * n,
            "rsi": [50] * n,
        })

    @pytest.fixture
    def bearish_df(self):
        """创建看跌条件的数据"""
        n = 30
        return pd.DataFrame({
            "ts_code": ["000001.SZ"] * n,
            "trade_date": pd.date_range("2025-01-01", periods=n).strftime("%Y%m%d"),
            "close": [12 - i * 0.1 for i in range(n)],  # 下跌趋势
            "ma20": [12.5 - i * 0.1 for i in range(n)],  # 价格在MA20下方
            "macd_hist": [0.1] * 15 + [-0.1] * 15,       # MACD死叉
            "vol": [1500000] * n,
            "vol_ma5": [1500000] * n,
            "rsi": [50] * n,
        })

    def test_bullish_signal_score(self, bullish_df):
        """测试看涨信号得分较高"""
        signal = SwingTradingSignal()
        result = signal.generate(bullish_df)

        assert "swing_score" in result.columns
        # 最后几天应该有较高分数（满足多个条件）
        last_score = result["swing_score"].iloc[-1]
        assert last_score > 50

    def test_bearish_signal_score(self, bearish_df):
        """测试看跌信号得分较低"""
        signal = SwingTradingSignal()
        result = signal.generate(bearish_df)

        # 最后几天应该有较低分数
        last_score = result["swing_score"].iloc[-1]
        assert last_score < 50

    def test_signal_score_range(self, bullish_df):
        """测试信号分数在0-100范围内"""
        signal = SwingTradingSignal()
        result = signal.generate(bullish_df)

        scores = result["swing_score"].dropna()
        assert (scores >= 0).all()
        assert (scores <= 100).all()

    def test_default_params(self):
        """测试默认参数"""
        signal = SwingTradingSignal()
        assert "ma_period" in signal.params
        assert "volume_ratio" in signal.params
```

**Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_signals.py::TestSwingTradingSignal -v
```
Expected: FAIL

**Step 3: 实现波段交易策略**

`src/signals/swing_trading.py`:
```python
"""波段交易信号生成器"""
from typing import Dict, Any
import pandas as pd
import numpy as np

from src.signals.base_signal import BaseSignal


class SwingTradingSignal(BaseSignal):
    """波段交易信号

    买入条件（满足越多，分数越高）：
    1. 收盘价 > MA20 (+20分)
    2. MACD金叉（macd_hist > 0 且前一天 < 0）(+25分)
    3. 成交量 > 5日均量 * volume_ratio (+15分)
    4. 收盘价在当日区间上半部 (+10分)
    5. RSI在30-70之间（非超买超卖）(+10分)

    卖出条件（相反逻辑，从基准分减去）
    """

    @property
    def name(self) -> str:
        return "swing_trading"

    def default_params(self) -> Dict[str, Any]:
        return {
            "ma_period": 20,           # 均线周期
            "volume_ratio": 1.5,       # 放量倍数
            "rsi_lower": 30,           # RSI下限
            "rsi_upper": 70,           # RSI上限
        }

    def _generate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # 基准分50
        scores = pd.Series(50.0, index=df.index)

        ma_col = f"ma{self.params['ma_period']}"

        # 条件1: 收盘价 > MA20
        if ma_col in df.columns:
            above_ma = df["close"] > df[ma_col]
            scores = scores + np.where(above_ma, 20, -20)

        # 条件2: MACD金叉/死叉
        if "macd_hist" in df.columns:
            macd_hist = df["macd_hist"]
            prev_macd_hist = macd_hist.shift(1)

            golden_cross = (macd_hist > 0) & (prev_macd_hist <= 0)
            death_cross = (macd_hist < 0) & (prev_macd_hist >= 0)
            macd_positive = macd_hist > 0

            scores = scores + np.where(golden_cross, 25, 0)
            scores = scores + np.where(death_cross, -25, 0)
            scores = scores + np.where(macd_positive & ~golden_cross, 10, 0)
            scores = scores + np.where(~macd_positive & ~death_cross, -10, 0)

        # 条件3: 放量
        if "vol" in df.columns and "vol_ma5" in df.columns:
            volume_ratio = df["vol"] / df["vol_ma5"]
            high_volume = volume_ratio > self.params["volume_ratio"]
            low_volume = volume_ratio < 0.7

            scores = scores + np.where(high_volume, 15, 0)
            scores = scores + np.where(low_volume, -10, 0)

        # 条件4: 收盘价位置
        if all(col in df.columns for col in ["high", "low", "close"]):
            price_range = df["high"] - df["low"]
            price_position = (df["close"] - df["low"]) / price_range.replace(0, np.nan)

            upper_half = price_position > 0.5
            lower_half = price_position < 0.3

            scores = scores + np.where(upper_half, 10, 0)
            scores = scores + np.where(lower_half, -10, 0)

        # 条件5: RSI
        if "rsi" in df.columns:
            rsi = df["rsi"]
            normal_rsi = (rsi >= self.params["rsi_lower"]) & (rsi <= self.params["rsi_upper"])
            overbought = rsi > self.params["rsi_upper"]
            oversold = rsi < self.params["rsi_lower"]

            scores = scores + np.where(normal_rsi, 10, 0)
            scores = scores + np.where(overbought, -15, 0)
            scores = scores + np.where(oversold, 5, 0)  # 超卖可能是买入机会

        # 限制分数范围
        scores = scores.clip(0, 100)

        df["swing_score"] = scores

        return df
```

**Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_signals.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/signals/swing_trading.py tests/test_signals.py
git commit -m "feat: add SwingTradingSignal with MA/MACD/Volume conditions"
```

---

### Task 8: 趋势跟踪策略

**Files:**
- Create: `src/signals/trend_following.py`
- Update: `tests/test_signals.py`

**Step 1: 写失败测试**

在 `tests/test_signals.py` 添加：
```python
from src.signals.trend_following import TrendFollowingSignal


class TestTrendFollowingSignal:
    @pytest.fixture
    def strong_trend_df(self):
        """创建强趋势数据"""
        n = 30
        return pd.DataFrame({
            "ts_code": ["000001.SZ"] * n,
            "trade_date": pd.date_range("2025-01-01", periods=n).strftime("%Y%m%d"),
            "close": [10 + i * 0.2 for i in range(n)],  # 强上涨
            "ma60": [9 + i * 0.15 for i in range(n)],   # 价格在MA60上方
            "ma20": [9.5 + i * 0.18 for i in range(n)], # MA20 > MA60
            "adx": [35] * n,                             # 强趋势
            "plus_di": [30] * n,                         # +DI > -DI
            "minus_di": [15] * n,
        })

    @pytest.fixture
    def weak_trend_df(self):
        """创建弱趋势数据"""
        n = 30
        return pd.DataFrame({
            "ts_code": ["000001.SZ"] * n,
            "trade_date": pd.date_range("2025-01-01", periods=n).strftime("%Y%m%d"),
            "close": [10 + (i % 5) * 0.1 for i in range(n)],  # 震荡
            "ma60": [10.5] * n,  # 价格在MA60下方
            "ma20": [10.2] * n,
            "adx": [15] * n,     # 弱趋势
            "plus_di": [20] * n,
            "minus_di": [25] * n,  # -DI > +DI
        })

    def test_strong_trend_high_score(self, strong_trend_df):
        """测试强趋势得分高"""
        signal = TrendFollowingSignal()
        result = signal.generate(strong_trend_df)

        assert "trend_score" in result.columns
        last_score = result["trend_score"].iloc[-1]
        assert last_score > 70

    def test_weak_trend_low_score(self, weak_trend_df):
        """测试弱趋势得分低"""
        signal = TrendFollowingSignal()
        result = signal.generate(weak_trend_df)

        last_score = result["trend_score"].iloc[-1]
        assert last_score < 40

    def test_signal_score_range(self, strong_trend_df):
        """测试信号分数在0-100范围内"""
        signal = TrendFollowingSignal()
        result = signal.generate(strong_trend_df)

        scores = result["trend_score"].dropna()
        assert (scores >= 0).all()
        assert (scores <= 100).all()
```

**Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_signals.py::TestTrendFollowingSignal -v
```
Expected: FAIL

**Step 3: 实现趋势跟踪策略**

`src/signals/trend_following.py`:
```python
"""趋势跟踪信号生成器"""
from typing import Dict, Any
import pandas as pd
import numpy as np

from src.signals.base_signal import BaseSignal


class TrendFollowingSignal(BaseSignal):
    """趋势跟踪信号

    买入条件：
    1. 收盘价 > MA60（站上长期均线）(+20分)
    2. ADX > 25（趋势明确）(+20分)
    3. ADX > 40（强趋势）(+15分额外加分)
    4. +DI > -DI（上升趋势）(+15分)
    5. MA20 > MA60（均线多头排列）(+10分)

    卖出条件（相反逻辑）
    """

    @property
    def name(self) -> str:
        return "trend_following"

    def default_params(self) -> Dict[str, Any]:
        return {
            "ma_long": 60,             # 长期均线
            "ma_short": 20,            # 短期均线
            "adx_threshold": 25,       # ADX趋势阈值
            "adx_strong": 40,          # 强趋势阈值
        }

    def _generate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # 基准分50
        scores = pd.Series(50.0, index=df.index)

        ma_long_col = f"ma{self.params['ma_long']}"
        ma_short_col = f"ma{self.params['ma_short']}"

        # 条件1: 收盘价 > MA60
        if ma_long_col in df.columns:
            above_ma60 = df["close"] > df[ma_long_col]
            scores = scores + np.where(above_ma60, 20, -20)

        # 条件2 & 3: ADX趋势强度
        if "adx" in df.columns:
            adx = df["adx"]

            trend_exists = adx > self.params["adx_threshold"]
            strong_trend = adx > self.params["adx_strong"]
            no_trend = adx < 20

            scores = scores + np.where(trend_exists, 20, 0)
            scores = scores + np.where(strong_trend, 15, 0)
            scores = scores + np.where(no_trend, -25, 0)

        # 条件4: +DI vs -DI
        if "plus_di" in df.columns and "minus_di" in df.columns:
            uptrend = df["plus_di"] > df["minus_di"]
            downtrend = df["minus_di"] > df["plus_di"]

            scores = scores + np.where(uptrend, 15, 0)
            scores = scores + np.where(downtrend, -15, 0)

        # 条件5: 均线多头排列
        if ma_short_col in df.columns and ma_long_col in df.columns:
            ma_bullish = df[ma_short_col] > df[ma_long_col]
            ma_bearish = df[ma_short_col] < df[ma_long_col]

            scores = scores + np.where(ma_bullish, 10, 0)
            scores = scores + np.where(ma_bearish, -10, 0)

        # 限制分数范围
        scores = scores.clip(0, 100)

        df["trend_score"] = scores

        return df
```

**Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_signals.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/signals/trend_following.py tests/test_signals.py
git commit -m "feat: add TrendFollowingSignal with ADX/DI/MA conditions"
```

---

### Task 9: 信号组合器

**Files:**
- Create: `src/signals/signal_combiner.py`
- Update: `tests/test_signals.py`

**Step 1: 写失败测试**

在 `tests/test_signals.py` 添加：
```python
from src.signals.signal_combiner import SignalCombiner


class TestSignalCombiner:
    @pytest.fixture
    def signals_df(self):
        """创建包含多个信号的数据"""
        return pd.DataFrame({
            "ts_code": ["000001.SZ", "600000.SH", "000002.SZ"],
            "trade_date": ["20250115"] * 3,
            "swing_score": [75, 45, 85],
            "trend_score": [80, 50, 60],
            "ml_score": [70, 55, 90],
        })

    def test_combine_signals(self, signals_df):
        """测试信号组合"""
        combiner = SignalCombiner()
        result = combiner.combine(signals_df)

        assert "combined_score" in result.columns
        assert "signal_level" in result.columns
        assert "signal_action" in result.columns

    def test_combined_score_weighted(self, signals_df):
        """测试加权计算"""
        combiner = SignalCombiner(weights={
            "swing_score": 0.35,
            "trend_score": 0.35,
            "ml_score": 0.30,
        })
        result = combiner.combine(signals_df)

        # 验证第一行的加权计算
        expected = 75 * 0.35 + 80 * 0.35 + 70 * 0.30
        assert abs(result.iloc[0]["combined_score"] - expected) < 0.01

    def test_risk_adjustment_neutral(self, signals_df):
        """测试中性风险状态调整"""
        combiner = SignalCombiner()
        result = combiner.combine(signals_df, risk_status="neutral")

        # neutral状态下买入信号权重降低
        result_risk_on = combiner.combine(signals_df, risk_status="risk_on")

        # 高分股票在neutral下分数应该更低
        assert result.iloc[0]["combined_score"] <= result_risk_on.iloc[0]["combined_score"]

    def test_risk_adjustment_risk_off(self, signals_df):
        """测试Risk-off状态"""
        combiner = SignalCombiner()
        result = combiner.combine(signals_df, risk_status="risk_off")

        # risk_off状态下不应该有买入信号
        assert all(result["signal_action"] != "BUY")

    def test_signal_level_assignment(self, signals_df):
        """测试信号等级分配"""
        combiner = SignalCombiner()
        result = combiner.combine(signals_df)

        # 高分股票应该是STRONG_BUY或WEAK_BUY
        high_score = result[result["combined_score"] >= 60]
        assert all(high_score["signal_action"] == "BUY")
```

**Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_signals.py::TestSignalCombiner -v
```
Expected: FAIL

**Step 3: 实现信号组合器**

`src/signals/signal_combiner.py`:
```python
"""信号组合器"""
from typing import Dict, Optional
import pandas as pd
import numpy as np

from src.signals.base_signal import SignalLevel


class SignalCombiner:
    """信号组合器

    将多个策略信号加权组合成最终信号
    """

    DEFAULT_WEIGHTS = {
        "swing_score": 0.35,
        "trend_score": 0.35,
        "ml_score": 0.30,
    }

    def __init__(
        self,
        weights: Dict[str, float] = None,
    ):
        """
        Args:
            weights: 各信号权重，如 {"swing_score": 0.35, "trend_score": 0.35, "ml_score": 0.30}
        """
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()

    def combine(
        self,
        df: pd.DataFrame,
        risk_status: str = "risk_on",
    ) -> pd.DataFrame:
        """组合所有信号

        Args:
            df: 包含各策略分数列的DataFrame
            risk_status: 风险状态 (risk_on/neutral/risk_off)

        Returns:
            添加了combined_score, signal_level, signal_action的DataFrame
        """
        df = df.copy()

        # 计算加权组合分数
        combined = pd.Series(0.0, index=df.index)
        total_weight = 0.0

        for col, weight in self.weights.items():
            if col in df.columns:
                combined += df[col].fillna(50) * weight
                total_weight += weight

        if total_weight > 0:
            combined = combined / total_weight * sum(self.weights.values())

        # 应用风险状态调整
        combined = self._apply_risk_adjustment(combined, risk_status)

        df["combined_score"] = combined.clip(0, 100)

        # 计算信号等级
        df["signal_level"] = df["combined_score"].apply(
            lambda x: SignalLevel.from_score(x).value
        )

        # 计算操作建议
        df["signal_action"] = df["combined_score"].apply(
            lambda x: SignalLevel.from_score(x).to_action()
        )

        # Risk-off状态强制不买入
        if risk_status == "risk_off":
            df.loc[df["signal_action"] == "BUY", "signal_action"] = "HOLD"

        return df

    def _apply_risk_adjustment(
        self,
        scores: pd.Series,
        risk_status: str,
    ) -> pd.Series:
        """根据风险状态调整信号分数

        Args:
            scores: 原始组合分数
            risk_status: 风险状态

        Returns:
            调整后的分数
        """
        if risk_status == "risk_on":
            return scores

        elif risk_status == "neutral":
            # 中性状态：将高分向中间压缩
            # 分数 > 50 的部分减少50%
            adjustment = (scores - 50).clip(lower=0) * 0.5
            return scores - adjustment

        else:  # risk_off
            # 防御状态：将所有分数向下调整
            # 最高分不超过55
            return scores.clip(upper=55)

    def get_top_signals(
        self,
        df: pd.DataFrame,
        top_n: int = 20,
        min_score: float = 60,
    ) -> pd.DataFrame:
        """获取评分最高的股票

        Args:
            df: 组合后的DataFrame
            top_n: 返回数量
            min_score: 最低分数

        Returns:
            筛选后的DataFrame
        """
        filtered = df[df["combined_score"] >= min_score]
        return filtered.nlargest(top_n, "combined_score")

    def get_sell_signals(
        self,
        df: pd.DataFrame,
        holdings: list,
        max_score: float = 40,
    ) -> pd.DataFrame:
        """获取应该卖出的股票

        Args:
            df: 组合后的DataFrame
            holdings: 当前持仓股票代码列表
            max_score: 触发卖出的最高分数

        Returns:
            需要卖出的股票
        """
        in_holdings = df[df["ts_code"].isin(holdings)]
        return in_holdings[in_holdings["combined_score"] <= max_score]
```

**Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_signals.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/signals/signal_combiner.py tests/test_signals.py
git commit -m "feat: add SignalCombiner with weighted combination and risk adjustment"
```

---

## 模块3: 机器学习

### Task 10: 特征工程

**Files:**
- Create: `src/ml_models/feature_engineering.py`
- Create: `tests/test_ml_models.py`

**Step 1: 写失败测试**

`tests/test_ml_models.py`:
```python
import pytest
import pandas as pd
import numpy as np
from src.ml_models.feature_engineering import FeatureEngineer


class TestFeatureEngineer:
    @pytest.fixture
    def sample_df(self):
        """创建测试数据"""
        np.random.seed(42)
        n = 100
        close = 10 + np.cumsum(np.random.randn(n) * 0.1)
        return pd.DataFrame({
            "ts_code": ["000001.SZ"] * n,
            "trade_date": pd.date_range("2025-01-01", periods=n).strftime("%Y%m%d"),
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "vol": np.random.randint(500000, 1500000, n),
            "amount": np.random.randint(5000000, 15000000, n),
            # 指标数据
            "ma5": close - 0.05,
            "ma20": close - 0.1,
            "ma60": close - 0.2,
            "rsi": 50 + np.random.randn(n) * 10,
            "macd_hist": np.random.randn(n) * 0.1,
            "adx": 25 + np.random.randn(n) * 5,
            "atr": 0.2 + np.random.rand(n) * 0.1,
            "vol_ma5": 1000000,
        })

    def test_build_features(self, sample_df):
        """测试构建特征"""
        engineer = FeatureEngineer()
        result = engineer.build_features(sample_df)

        # 检查价格特征
        assert "pct_chg_5d" in result.columns
        assert "pct_chg_20d" in result.columns
        assert "price_vs_ma20" in result.columns

    def test_feature_count(self, sample_df):
        """测试特征数量"""
        engineer = FeatureEngineer()
        result = engineer.build_features(sample_df)

        feature_cols = engineer.get_feature_columns()
        assert len(feature_cols) >= 10

    def test_no_nan_in_features(self, sample_df):
        """测试特征没有NaN（在足够数据后）"""
        engineer = FeatureEngineer()
        result = engineer.build_features(sample_df)

        # 跳过前60行（需要60日数据计算特征）
        valid_data = result.iloc[60:]
        feature_cols = engineer.get_feature_columns()

        for col in feature_cols:
            if col in valid_data.columns:
                nan_count = valid_data[col].isna().sum()
                assert nan_count < len(valid_data) * 0.1, f"{col} has too many NaN"
```

**Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_ml_models.py -v
```
Expected: FAIL

**Step 3: 实现特征工程**

`src/ml_models/feature_engineering.py`:
```python
"""特征工程模块"""
from typing import List
import pandas as pd
import numpy as np


class FeatureEngineer:
    """特征工程

    从OHLCV和技术指标数据构建机器学习特征。
    """

    # 特征列名
    PRICE_FEATURES = [
        "pct_chg_5d", "pct_chg_20d", "pct_chg_60d",
        "price_vs_ma20", "price_vs_ma60",
    ]

    VOLUME_FEATURES = [
        "volume_ratio_5d", "turnover_rate",
    ]

    MOMENTUM_FEATURES = [
        "rsi_norm", "macd_hist_norm", "adx_norm",
    ]

    VOLATILITY_FEATURES = [
        "atr_pct", "high_low_range",
    ]

    def __init__(self):
        pass

    def build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """构建所有特征

        Args:
            df: 包含OHLCV和技术指标的DataFrame

        Returns:
            添加了特征列的DataFrame
        """
        df = df.copy()

        # 价格特征
        df = self._build_price_features(df)

        # 量价特征
        df = self._build_volume_features(df)

        # 动量特征
        df = self._build_momentum_features(df)

        # 波动率特征
        df = self._build_volatility_features(df)

        return df

    def _build_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """构建价格相关特征"""
        close = df["close"]

        # 涨跌幅
        df["pct_chg_5d"] = close.pct_change(5) * 100
        df["pct_chg_20d"] = close.pct_change(20) * 100
        df["pct_chg_60d"] = close.pct_change(60) * 100

        # 相对均线位置
        if "ma20" in df.columns:
            df["price_vs_ma20"] = (close / df["ma20"] - 1) * 100

        if "ma60" in df.columns:
            df["price_vs_ma60"] = (close / df["ma60"] - 1) * 100

        return df

    def _build_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """构建量价相关特征"""
        if "vol" in df.columns and "vol_ma5" in df.columns:
            df["volume_ratio_5d"] = df["vol"] / df["vol_ma5"].replace(0, np.nan)

        # 简化的换手率（如果有流通股本数据可以更准确）
        if "vol" in df.columns and "amount" in df.columns:
            avg_price = df["amount"] / df["vol"].replace(0, np.nan)
            df["turnover_rate"] = df["vol"] / 1e8  # 假设流通盘1亿股

        return df

    def _build_momentum_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """构建动量相关特征"""
        # RSI归一化到-1到1
        if "rsi" in df.columns:
            df["rsi_norm"] = (df["rsi"] - 50) / 50

        # MACD柱归一化
        if "macd_hist" in df.columns:
            macd_std = df["macd_hist"].rolling(20).std()
            df["macd_hist_norm"] = df["macd_hist"] / macd_std.replace(0, np.nan)
            df["macd_hist_norm"] = df["macd_hist_norm"].clip(-3, 3)

        # ADX归一化
        if "adx" in df.columns:
            df["adx_norm"] = df["adx"] / 100

        return df

    def _build_volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """构建波动率相关特征"""
        # ATR占价格比例
        if "atr" in df.columns:
            df["atr_pct"] = df["atr"] / df["close"] * 100

        # 日内振幅
        if "high" in df.columns and "low" in df.columns:
            df["high_low_range"] = (df["high"] - df["low"]) / df["close"] * 100

        return df

    def get_feature_columns(self) -> List[str]:
        """获取所有特征列名

        Returns:
            特征列名列表
        """
        return (
            self.PRICE_FEATURES +
            self.VOLUME_FEATURES +
            self.MOMENTUM_FEATURES +
            self.VOLATILITY_FEATURES
        )

    def prepare_training_data(
        self,
        df: pd.DataFrame,
        target_col: str = "label",
    ) -> tuple:
        """准备训练数据

        Args:
            df: 包含特征和标签的DataFrame
            target_col: 标签列名

        Returns:
            (X, y) 特征矩阵和标签
        """
        feature_cols = [c for c in self.get_feature_columns() if c in df.columns]

        # 删除含NaN的行
        valid_df = df.dropna(subset=feature_cols + [target_col])

        X = valid_df[feature_cols]
        y = valid_df[target_col]

        return X, y
```

**Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_ml_models.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/ml_models/feature_engineering.py tests/test_ml_models.py
git commit -m "feat: add FeatureEngineer for ML feature construction"
```

---

### Task 11: 标签构建和模型训练

**Files:**
- Create: `src/ml_models/model_trainer.py`
- Update: `tests/test_ml_models.py`

**Step 1: 写失败测试**

在 `tests/test_ml_models.py` 添加：
```python
from src.ml_models.model_trainer import LabelBuilder, XGBModelTrainer


class TestLabelBuilder:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        n = 100
        close = 10 + np.cumsum(np.random.randn(n) * 0.1)
        return pd.DataFrame({
            "ts_code": ["000001.SZ"] * n,
            "trade_date": pd.date_range("2025-01-01", periods=n).strftime("%Y%m%d"),
            "close": close,
        })

    def test_build_labels(self, sample_df):
        """测试标签构建"""
        builder = LabelBuilder(forward_days=5)
        result = builder.build_labels(sample_df)

        assert "label" in result.columns
        assert "future_return" in result.columns

    def test_label_values(self, sample_df):
        """测试标签值在0-4范围"""
        builder = LabelBuilder()
        result = builder.build_labels(sample_df)

        valid_labels = result["label"].dropna()
        assert valid_labels.isin([0, 1, 2, 3, 4]).all()

    def test_label_distribution(self, sample_df):
        """测试标签有分布（不全是同一个值）"""
        builder = LabelBuilder()
        result = builder.build_labels(sample_df)

        valid_labels = result["label"].dropna()
        unique_labels = valid_labels.unique()
        assert len(unique_labels) >= 2


class TestXGBModelTrainer:
    @pytest.fixture
    def training_data(self):
        """创建训练数据"""
        np.random.seed(42)
        n = 500
        X = pd.DataFrame({
            "feature1": np.random.randn(n),
            "feature2": np.random.randn(n),
            "feature3": np.random.randn(n),
        })
        # 创建与特征相关的标签
        y = pd.Series(
            np.clip(
                (X["feature1"] > 0).astype(int) * 2 +
                (X["feature2"] > 0).astype(int) +
                np.random.randint(0, 2, n),
                0, 4
            )
        )
        return X, y

    def test_train_model(self, training_data):
        """测试模型训练"""
        X, y = training_data
        trainer = XGBModelTrainer()

        metrics = trainer.train(X, y)

        assert "accuracy" in metrics
        assert metrics["accuracy"] > 0.2  # 至少比随机好

    def test_predict(self, training_data):
        """测试模型预测"""
        X, y = training_data
        trainer = XGBModelTrainer()
        trainer.train(X, y)

        predictions = trainer.predict(X.head(10))

        assert len(predictions) == 10
        assert "predicted_label" in predictions.columns
        assert "ml_score" in predictions.columns

    def test_save_and_load(self, training_data, tmp_path):
        """测试模型保存和加载"""
        X, y = training_data
        trainer = XGBModelTrainer()
        trainer.train(X, y)

        model_path = tmp_path / "model.pkl"
        trainer.save(str(model_path))

        new_trainer = XGBModelTrainer()
        new_trainer.load(str(model_path))

        predictions = new_trainer.predict(X.head(5))
        assert len(predictions) == 5
```

**Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_ml_models.py::TestLabelBuilder -v
python -m pytest tests/test_ml_models.py::TestXGBModelTrainer -v
```
Expected: FAIL

**Step 3: 实现标签构建和模型训练**

`src/ml_models/model_trainer.py`:
```python
"""模型训练模块"""
from typing import Dict, Any, Optional, Tuple
import pandas as pd
import numpy as np
import joblib
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

from src.utils.logger import get_logger

logger = get_logger(__name__)


class LabelBuilder:
    """标签构建器

    根据未来收益率构建5分类标签:
    - 4: 强买（收益 > strong_buy_threshold）
    - 3: 弱买（weak_buy_threshold ~ strong_buy_threshold）
    - 2: 持有（weak_sell_threshold ~ weak_buy_threshold）
    - 1: 弱卖（strong_sell_threshold ~ weak_sell_threshold）
    - 0: 强卖（收益 < strong_sell_threshold）
    """

    def __init__(
        self,
        forward_days: int = 5,
        strong_buy_threshold: float = 0.05,
        weak_buy_threshold: float = 0.02,
        weak_sell_threshold: float = -0.02,
        strong_sell_threshold: float = -0.05,
    ):
        """
        Args:
            forward_days: 预测未来天数
            strong_buy_threshold: 强买阈值（5%）
            weak_buy_threshold: 弱买阈值（2%）
            weak_sell_threshold: 弱卖阈值（-2%）
            strong_sell_threshold: 强卖阈值（-5%）
        """
        self.forward_days = forward_days
        self.thresholds = {
            "strong_buy": strong_buy_threshold,
            "weak_buy": weak_buy_threshold,
            "weak_sell": weak_sell_threshold,
            "strong_sell": strong_sell_threshold,
        }

    def build_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """构建标签

        Args:
            df: 包含close列的DataFrame

        Returns:
            添加了label和future_return列的DataFrame
        """
        df = df.copy()

        # 计算未来收益率
        future_close = df["close"].shift(-self.forward_days)
        df["future_return"] = (future_close - df["close"]) / df["close"]

        # 构建标签
        def _to_label(ret):
            if pd.isna(ret):
                return np.nan
            elif ret > self.thresholds["strong_buy"]:
                return 4  # 强买
            elif ret > self.thresholds["weak_buy"]:
                return 3  # 弱买
            elif ret > self.thresholds["weak_sell"]:
                return 2  # 持有
            elif ret > self.thresholds["strong_sell"]:
                return 1  # 弱卖
            else:
                return 0  # 强卖

        df["label"] = df["future_return"].apply(_to_label)

        return df


class XGBModelTrainer:
    """XGBoost模型训练器"""

    def __init__(self, params: Dict[str, Any] = None):
        """
        Args:
            params: XGBoost参数
        """
        self.params = params or {
            "objective": "multi:softprob",
            "num_class": 5,
            "max_depth": 6,
            "learning_rate": 0.1,
            "n_estimators": 100,
            "min_child_weight": 3,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "random_state": 42,
            "verbosity": 0,
        }
        self.model: Optional[XGBClassifier] = None
        self.feature_names: Optional[list] = None

    def train(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        test_size: float = 0.2,
    ) -> Dict[str, Any]:
        """训练模型

        Args:
            X: 特征DataFrame
            y: 标签Series
            test_size: 测试集比例

        Returns:
            训练指标
        """
        logger.info(f"开始训练模型，样本数: {len(X)}")

        self.feature_names = list(X.columns)

        # 划分训练集和测试集
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42
        )

        # 训练模型
        self.model = XGBClassifier(**self.params)
        self.model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        # 评估
        y_pred = self.model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)

        logger.info(f"模型训练完成，测试集准确率: {accuracy:.4f}")

        return {
            "accuracy": accuracy,
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "feature_count": len(self.feature_names),
        }

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        """预测

        Args:
            X: 特征DataFrame

        Returns:
            包含预测结果和概率的DataFrame
        """
        if self.model is None:
            raise ValueError("模型未训练")

        # 确保特征顺序一致
        X = X[self.feature_names]

        # 预测概率
        probs = self.model.predict_proba(X)
        predicted_labels = self.model.predict(X)

        result = pd.DataFrame(index=X.index)
        result["predicted_label"] = predicted_labels

        # 各类别概率
        result["prob_strong_sell"] = probs[:, 0]
        result["prob_weak_sell"] = probs[:, 1]
        result["prob_hold"] = probs[:, 2]
        result["prob_weak_buy"] = probs[:, 3]
        result["prob_strong_buy"] = probs[:, 4]

        # 计算综合评分 (0-100)
        result["ml_score"] = (
            probs[:, 0] * 0 +
            probs[:, 1] * 25 +
            probs[:, 2] * 50 +
            probs[:, 3] * 75 +
            probs[:, 4] * 100
        )

        return result

    def save(self, path: str) -> None:
        """保存模型

        Args:
            path: 保存路径
        """
        if self.model is None:
            raise ValueError("模型未训练")

        data = {
            "model": self.model,
            "feature_names": self.feature_names,
            "params": self.params,
        }
        joblib.dump(data, path)
        logger.info(f"模型已保存: {path}")

    def load(self, path: str) -> None:
        """加载模型

        Args:
            path: 模型路径
        """
        data = joblib.load(path)
        self.model = data["model"]
        self.feature_names = data["feature_names"]
        self.params = data["params"]
        logger.info(f"模型已加载: {path}")

    def get_feature_importance(self) -> pd.Series:
        """获取特征重要性

        Returns:
            特征重要性Series
        """
        if self.model is None:
            raise ValueError("模型未训练")

        importance = pd.Series(
            self.model.feature_importances_,
            index=self.feature_names,
        ).sort_values(ascending=False)

        return importance
```

**Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_ml_models.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/ml_models/model_trainer.py tests/test_ml_models.py
git commit -m "feat: add LabelBuilder and XGBModelTrainer for 5-class prediction"
```

---

### Task 12: 每日信号生成器

**Files:**
- Create: `src/signals/daily_signal_generator.py`
- Update: `tests/test_signals.py`

**Step 1: 写失败测试**

在 `tests/test_signals.py` 添加：
```python
from unittest.mock import Mock, patch
from src.signals.daily_signal_generator import DailySignalGenerator


class TestDailySignalGenerator:
    @pytest.fixture
    def mock_components(self):
        """创建Mock组件"""
        storage = Mock()
        database = Mock()

        # Mock存储返回测试数据
        np.random.seed(42)
        n = 100
        close = 10 + np.cumsum(np.random.randn(n) * 0.1)
        test_data = pd.DataFrame({
            "ts_code": ["000001.SZ"] * n,
            "trade_date": pd.date_range("2025-01-01", periods=n).strftime("%Y%m%d"),
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "vol": [1000000] * n,
        })
        storage.load_daily_multi_year.return_value = test_data

        return storage, database

    def test_generate_signals(self, mock_components):
        """测试生成信号"""
        storage, database = mock_components

        generator = DailySignalGenerator(storage, database)
        result = generator.generate("20250415")

        assert "combined_score" in result.columns
        assert "signal_level" in result.columns
        assert "signal_action" in result.columns

    def test_generate_with_ml(self, mock_components, tmp_path):
        """测试使用ML模型生成信号"""
        storage, database = mock_components

        generator = DailySignalGenerator(
            storage, database,
            ml_model_path=None,  # 不使用ML模型
        )
        result = generator.generate("20250415")

        # 没有ML模型时ml_score应该是50
        assert "ml_score" in result.columns or "swing_score" in result.columns
```

**Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_signals.py::TestDailySignalGenerator -v
```
Expected: FAIL

**Step 3: 实现每日信号生成器**

`src/signals/daily_signal_generator.py`:
```python
"""每日信号生成器"""
from typing import Optional
from datetime import datetime, timedelta
import pandas as pd

from src.data_storage.parquet_storage import ParquetStorage
from src.data_storage.database import Database
from src.indicators.indicator_calculator import IndicatorCalculator
from src.signals.swing_trading import SwingTradingSignal
from src.signals.trend_following import TrendFollowingSignal
from src.signals.signal_combiner import SignalCombiner
from src.ml_models.model_trainer import XGBModelTrainer
from src.ml_models.feature_engineering import FeatureEngineer
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DailySignalGenerator:
    """每日信号生成器

    协调指标计算、策略信号、ML预测的完整流程
    """

    def __init__(
        self,
        storage: ParquetStorage,
        database: Database,
        indicator_calculator: Optional[IndicatorCalculator] = None,
        swing_signal: Optional[SwingTradingSignal] = None,
        trend_signal: Optional[TrendFollowingSignal] = None,
        signal_combiner: Optional[SignalCombiner] = None,
        ml_model_path: Optional[str] = None,
    ):
        """
        Args:
            storage: Parquet存储
            database: 数据库
            indicator_calculator: 指标计算器
            swing_signal: 波段策略
            trend_signal: 趋势策略
            signal_combiner: 信号组合器
            ml_model_path: ML模型路径（可选）
        """
        self.storage = storage
        self.database = database

        self.indicator_calculator = indicator_calculator or IndicatorCalculator.get_default()
        self.swing_signal = swing_signal or SwingTradingSignal()
        self.trend_signal = trend_signal or TrendFollowingSignal()
        self.signal_combiner = signal_combiner or SignalCombiner()

        self.ml_trainer: Optional[XGBModelTrainer] = None
        self.feature_engineer = FeatureEngineer()

        if ml_model_path:
            self.ml_trainer = XGBModelTrainer()
            self.ml_trainer.load(ml_model_path)

    def generate(
        self,
        trade_date: str,
        lookback_days: int = 120,
        risk_status: str = "risk_on",
    ) -> pd.DataFrame:
        """生成指定日期的全市场信号

        Args:
            trade_date: 交易日期 (YYYYMMDD)
            lookback_days: 回溯天数（用于计算指标）
            risk_status: 风险状态

        Returns:
            包含所有股票信号的DataFrame
        """
        logger.info(f"开始生成 {trade_date} 的交易信号...")

        # 1. 计算回溯日期
        end_date = trade_date
        start_date = self._calc_start_date(trade_date, lookback_days)

        # 2. 加载历史数据
        logger.info(f"加载历史数据: {start_date} - {end_date}")
        df = self.storage.load_daily_multi_year(start_date, end_date)

        if df.empty:
            logger.warning("未获取到历史数据")
            return pd.DataFrame()

        # 3. 按股票计算指标
        logger.info("计算技术指标...")
        df = self.indicator_calculator.calculate_by_stock(df)

        # 4. 生成策略信号
        logger.info("生成策略信号...")
        df = self._generate_strategy_signals(df)

        # 5. ML预测（如果有模型）
        if self.ml_trainer:
            logger.info("ML模型预测...")
            df = self._generate_ml_signals(df)
        else:
            df["ml_score"] = 50.0  # 默认中性分

        # 6. 只保留目标日期的数据
        result = df[df["trade_date"] == trade_date].copy()

        # 7. 组合信号
        logger.info("组合信号...")
        result = self.signal_combiner.combine(result, risk_status=risk_status)

        # 8. 排序
        result = result.sort_values("combined_score", ascending=False)

        logger.info(f"信号生成完成，共 {len(result)} 只股票")

        return result

    def _calc_start_date(self, end_date: str, days: int) -> str:
        """计算开始日期"""
        end = datetime.strptime(end_date, "%Y%m%d")
        start = end - timedelta(days=days * 1.5)  # 多取一些以应对节假日
        return start.strftime("%Y%m%d")

    def _generate_strategy_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成策略信号"""
        results = []

        for ts_code, group in df.groupby("ts_code"):
            group = group.sort_values("trade_date").reset_index(drop=True)

            # 波段信号
            group = self.swing_signal.generate(group)

            # 趋势信号
            group = self.trend_signal.generate(group)

            results.append(group)

        return pd.concat(results, ignore_index=True)

    def _generate_ml_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成ML信号"""
        # 构建特征
        df = self.feature_engineer.build_features(df)

        # 获取特征列
        feature_cols = [c for c in self.feature_engineer.get_feature_columns() if c in df.columns]

        # 预测
        results = []
        for ts_code, group in df.groupby("ts_code"):
            group = group.sort_values("trade_date").reset_index(drop=True)

            # 只预测最后一行
            if len(group) > 0:
                last_row = group.iloc[[-1]]

                if not last_row[feature_cols].isna().any().any():
                    try:
                        pred = self.ml_trainer.predict(last_row[feature_cols])
                        group.loc[group.index[-1], "ml_score"] = pred["ml_score"].values[0]
                    except Exception as e:
                        logger.warning(f"ML预测失败 {ts_code}: {e}")
                        group.loc[group.index[-1], "ml_score"] = 50.0
                else:
                    group.loc[group.index[-1], "ml_score"] = 50.0

            results.append(group)

        return pd.concat(results, ignore_index=True)

    def get_top_signals(
        self,
        trade_date: str,
        top_n: int = 20,
        min_score: float = 60,
        risk_status: str = "risk_on",
    ) -> pd.DataFrame:
        """获取评分最高的股票

        Args:
            trade_date: 交易日期
            top_n: 返回数量
            min_score: 最低分数
            risk_status: 风险状态

        Returns:
            筛选后的信号DataFrame
        """
        signals = self.generate(trade_date, risk_status=risk_status)
        return self.signal_combiner.get_top_signals(signals, top_n, min_score)
```

**Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_signals.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/signals/daily_signal_generator.py tests/test_signals.py
git commit -m "feat: add DailySignalGenerator for orchestrating signal generation"
```

---

## 最终验证

### Task 13: 集成测试

**Step 1: 运行所有测试**

```bash
python -m pytest tests/ -v --cov=src --cov-report=term-missing
```

**Step 2: 检查覆盖率**

目标覆盖率 > 80%

**Step 3: 最终Commit**

```bash
git add -A
git commit -m "chore: complete phase 2 strategy layer implementation"
```

---

## 交付物清单

完成本阶段后，你将拥有：

1. **技术指标模块** (`src/indicators/`)
   - [x] base_indicator.py - 指标基类
   - [x] trend_indicators.py - MA/EMA/MACD/ADX
   - [x] momentum_indicators.py - RSI/KDJ
   - [x] volume_indicators.py - OBV/ATR/VolumeMA
   - [x] indicator_calculator.py - 批量计算器

2. **信号生成模块** (`src/signals/`)
   - [x] base_signal.py - 信号基类和等级定义
   - [x] swing_trading.py - 波段交易策略
   - [x] trend_following.py - 趋势跟踪策略
   - [x] signal_combiner.py - 信号组合器
   - [x] daily_signal_generator.py - 每日信号生成器

3. **机器学习模块** (`src/ml_models/`)
   - [x] feature_engineering.py - 特征工程
   - [x] model_trainer.py - 标签构建和XGBoost训练

4. **测试** (`tests/`)
   - [x] test_indicators.py
   - [x] test_signals.py
   - [x] test_ml_models.py
