# P0 量化因子 — 纯价量因子接入回测系统

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 16 个纯价量因子注册进指标系统，使其可作为 buy/sell conditions 参与 explore-strategies 回测。

**Architecture:** 新因子作为 extended indicators 注册到 `indicator_registry.py`，与 BOLL/CCI/MFI 等完全相同的模式。每个因子有 `_compute_xxx` 函数、`EXTENDED_INDICATORS` 元数据、`_COMPUTE_FUNCTIONS` 映射。因子仅依赖 OHLCV 数据（`open/high/low/close/volume/amount`），不需要额外数据库表。

**Tech Stack:** pandas, numpy, 现有 indicator_registry 框架

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `api/services/indicator_registry.py` | Modify | 添加 16 个因子的元数据 + 计算函数 + 注册到映射表 |
| `src/signals/rule_engine.py` | Modify | 添加新因子到 `FIELD_RANGES` |
| `tests/test_quant_factors.py` | Create | 全部因子的单元测试 |

不需要修改 `indicator_calculator.py` 和 `portfolio_engine.py` — 所有 extended indicators 已通过 `config.extended[key]` → `calculate_all()` → `_add_extended_with_params()` 自动流入回测。

---

### Task 1: 动量因子 — MOM (多周期动量)

**Files:**
- Modify: `api/services/indicator_registry.py`
- Modify: `src/signals/rule_engine.py`
- Create: `tests/test_quant_factors.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_quant_factors.py
"""Tests for P0 quantitative factors."""
import numpy as np
import pandas as pd
import pytest

def _make_df(n=30, seed=42):
    """Create a realistic OHLCV DataFrame for testing."""
    rng = np.random.default_rng(seed)
    close = 10.0 + np.cumsum(rng.normal(0, 0.3, n))
    close = np.maximum(close, 1.0)
    high = close + rng.uniform(0, 0.5, n)
    low = close - rng.uniform(0, 0.5, n)
    low = np.maximum(low, 0.5)
    opn = low + rng.uniform(0, 1, n) * (high - low)
    volume = rng.integers(1000, 100000, n).astype(float)
    amount = close * volume
    dates = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({
        "date": dates, "open": opn, "high": high, "low": low,
        "close": close, "volume": volume, "amount": amount,
    }).set_index("date")


def test_mom_columns():
    from api.services.indicator_registry import compute_extended_indicator
    df = _make_df(30)
    result = compute_extended_indicator(df, "MOM", {"period": 5})
    assert "MOM_5" in result.columns
    # MOM_5 = (close - close_5d_ago) / close_5d_ago * 100
    expected = (df["close"].iloc[-1] - df["close"].iloc[-6]) / df["close"].iloc[-6] * 100
    assert abs(result["MOM_5"].iloc[-1] - expected) < 0.01


def test_mom_20d():
    from api.services.indicator_registry import compute_extended_indicator
    df = _make_df(30)
    result = compute_extended_indicator(df, "MOM", {"period": 20})
    assert "MOM_20" in result.columns
    assert pd.notna(result["MOM_20"].iloc[-1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/allenqiang/stockagent && NO_PROXY='*' python -m pytest tests/test_quant_factors.py::test_mom_columns -xvs 2>&1 | tail -5`
Expected: FAIL — `ValueError: No compute function for extended indicator: MOM`

- [ ] **Step 3: Implement MOM in indicator_registry.py**

Add to `EXTENDED_INDICATORS` dict (after the `# ── Momentum` section, near ROC):

```python
    "MOM": {
        "label": "动量",
        "sub_fields": [("MOM", "动量%")],
        "params": {
            "period": {"label": "回看周期", "default": 20, "type": "int"},
        },
    },
```

Add compute function:

```python
def _compute_mom(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Momentum: percentage price change over N periods."""
    period = int(params.get("period", 20))
    close = df["close"]
    mom = (close - close.shift(period)) / close.shift(period) * 100
    col = f"MOM_{period}"
    return pd.DataFrame({col: mom}, index=df.index)
```

Add to `_COMPUTE_FUNCTIONS`:

```python
    "MOM": _compute_mom,
```

- [ ] **Step 4: Add FIELD_RANGES entry in rule_engine.py**

```python
    "MOM": (-100, 500),
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd /Users/allenqiang/stockagent && NO_PROXY='*' python -m pytest tests/test_quant_factors.py -xvs 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/services/indicator_registry.py src/signals/rule_engine.py tests/test_quant_factors.py
git commit -m "feat(factors): add MOM momentum factor to indicator registry"
```

---

### Task 2: 波动率因子 — REALVOL (已实现波动率)

**Files:**
- Modify: `api/services/indicator_registry.py`
- Modify: `src/signals/rule_engine.py`
- Modify: `tests/test_quant_factors.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_quant_factors.py`:

```python
def test_realvol_columns():
    from api.services.indicator_registry import compute_extended_indicator
    df = _make_df(30)
    result = compute_extended_indicator(df, "REALVOL", {"period": 20})
    assert "REALVOL_20" in result.columns
    # Should be std of daily returns * 100
    returns = df["close"].pct_change()
    expected = returns.rolling(20).std().iloc[-1] * 100
    assert abs(result["REALVOL_20"].iloc[-1] - expected) < 0.01


def test_realvol_skew_kurt():
    from api.services.indicator_registry import compute_extended_indicator
    df = _make_df(30)
    result = compute_extended_indicator(df, "REALVOL", {"period": 20})
    assert "REALVOL_skew_20" in result.columns
    assert "REALVOL_kurt_20" in result.columns
    assert "REALVOL_downside_20" in result.columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/allenqiang/stockagent && NO_PROXY='*' python -m pytest tests/test_quant_factors.py::test_realvol_columns -xvs 2>&1 | tail -5`
Expected: FAIL

- [ ] **Step 3: Implement REALVOL**

Add to `EXTENDED_INDICATORS`:

```python
    "REALVOL": {
        "label": "已实现波动率",
        "sub_fields": [
            ("REALVOL", "波动率%"),
            ("REALVOL_skew", "收益偏度"),
            ("REALVOL_kurt", "收益峰度"),
            ("REALVOL_downside", "下行波动率%"),
        ],
        "params": {
            "period": {"label": "回看周期", "default": 20, "type": "int"},
        },
    },
```

Add compute function:

```python
def _compute_realvol(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Realized volatility, skewness, kurtosis, and downside volatility."""
    period = int(params.get("period", 20))
    returns = df["close"].pct_change()
    suffix = f"_{period}"
    vol = returns.rolling(period).std() * 100
    skew = returns.rolling(period).skew()
    kurt = returns.rolling(period).kurt()
    # Downside: std of negative returns only, use full window
    neg_returns = returns.where(returns < 0, 0.0)
    downside = neg_returns.rolling(period).std() * 100
    return pd.DataFrame({
        f"REALVOL{suffix}": vol,
        f"REALVOL_skew{suffix}": skew,
        f"REALVOL_kurt{suffix}": kurt,
        f"REALVOL_downside{suffix}": downside,
    }, index=df.index)
```

Add to `_COMPUTE_FUNCTIONS`:

```python
    "REALVOL": _compute_realvol,
```

- [ ] **Step 4: Add FIELD_RANGES**

```python
    "REALVOL": (0, 30),
    "REALVOL_skew": (-5, 5),
    "REALVOL_kurt": (-5, 30),
    "REALVOL_downside": (0, 30),
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd /Users/allenqiang/stockagent && NO_PROXY='*' python -m pytest tests/test_quant_factors.py -xvs 2>&1 | tail -10`

- [ ] **Step 6: Commit**

```bash
git add api/services/indicator_registry.py src/signals/rule_engine.py tests/test_quant_factors.py
git commit -m "feat(factors): add REALVOL realized volatility factor"
```

---

### Task 3: K线形态因子 — KBAR (K线结构)

- [ ] **Step 1: Write failing test**

Append to `tests/test_quant_factors.py`:

```python
def test_kbar_columns():
    from api.services.indicator_registry import compute_extended_indicator
    df = _make_df(30)
    result = compute_extended_indicator(df, "KBAR")
    expected_cols = [
        "KBAR_upper_shadow", "KBAR_lower_shadow", "KBAR_body_ratio",
        "KBAR_amplitude", "KBAR_overnight_ret", "KBAR_intraday_ret",
    ]
    for col in expected_cols:
        assert col in result.columns, f"Missing {col}"
    # Amplitude = (high - low) / close, should be positive
    amp = result["KBAR_amplitude"].dropna()
    assert (amp >= 0).all()
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement KBAR**

Add to `EXTENDED_INDICATORS`:

```python
    "KBAR": {
        "label": "K线形态",
        "sub_fields": [
            ("KBAR_upper_shadow", "上影线比率"),
            ("KBAR_lower_shadow", "下影线比率"),
            ("KBAR_body_ratio", "实体比率"),
            ("KBAR_amplitude", "振幅"),
            ("KBAR_overnight_ret", "隔夜收益率%"),
            ("KBAR_intraday_ret", "日内收益率%"),
        ],
        "params": {},
    },
```

Add compute function:

```python
def _compute_kbar(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """K-bar shape factors: shadow ratios, amplitude, overnight/intraday returns."""
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    bar_range = (h - l).replace(0, np.nan)
    body_top = pd.concat([o, c], axis=1).max(axis=1)
    body_bot = pd.concat([o, c], axis=1).min(axis=1)
    upper_shadow = (h - body_top) / bar_range
    lower_shadow = (body_bot - l) / bar_range
    body_ratio = (body_top - body_bot) / bar_range
    amplitude = bar_range / c
    overnight_ret = (o - c.shift(1)) / c.shift(1) * 100
    intraday_ret = (c - o) / o * 100
    return pd.DataFrame({
        "KBAR_upper_shadow": upper_shadow,
        "KBAR_lower_shadow": lower_shadow,
        "KBAR_body_ratio": body_ratio,
        "KBAR_amplitude": amplitude,
        "KBAR_overnight_ret": overnight_ret,
        "KBAR_intraday_ret": intraday_ret,
    }, index=df.index)
```

Register: `"KBAR": _compute_kbar,`

- [ ] **Step 4: Add FIELD_RANGES**

```python
    "KBAR_upper_shadow": (0, 1),
    "KBAR_lower_shadow": (0, 1),
    "KBAR_body_ratio": (0, 1),
    "KBAR_amplitude": (0, 0.3),
    "KBAR_overnight_ret": (-15, 15),
    "KBAR_intraday_ret": (-15, 15),
```

- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Commit**

```bash
git add api/services/indicator_registry.py src/signals/rule_engine.py tests/test_quant_factors.py
git commit -m "feat(factors): add KBAR k-bar shape factor"
```

---

### Task 4: 量价相关因子 — PVOL (Price-Volume)

- [ ] **Step 1: Write failing test**

```python
def test_pvol_columns():
    from api.services.indicator_registry import compute_extended_indicator
    df = _make_df(30)
    result = compute_extended_indicator(df, "PVOL", {"period": 20})
    expected_cols = [
        "PVOL_corr_20", "PVOL_amount_conc_20", "PVOL_vwap_bias_20",
    ]
    for col in expected_cols:
        assert col in result.columns, f"Missing {col}"
    # Correlation should be in [-1, 1]
    corr = result["PVOL_corr_20"].dropna()
    assert (corr >= -1.01).all() and (corr <= 1.01).all()
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement PVOL**

Add to `EXTENDED_INDICATORS`:

```python
    "PVOL": {
        "label": "量价关系",
        "sub_fields": [
            ("PVOL_corr", "量价相关性"),
            ("PVOL_amount_conc", "成交额集中度"),
            ("PVOL_vwap_bias", "VWAP偏离度%"),
        ],
        "params": {
            "period": {"label": "回看周期", "default": 20, "type": "int"},
        },
    },
```

Add compute function:

```python
def _compute_pvol(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Price-volume relationship factors."""
    period = int(params.get("period", 20))
    close = df["close"]
    volume = df["volume"]
    amount = df.get("amount", close * volume)
    suffix = f"_{period}"
    # 1. Price-volume correlation
    ret = close.pct_change()
    corr = ret.rolling(period).corr(volume)
    # 2. Amount concentration: max(amount, period) / sum(amount, period)
    roll_sum = amount.rolling(period).sum()
    roll_max = amount.rolling(period).max()
    conc = roll_max / roll_sum.replace(0, np.nan)
    # 3. VWAP bias: (close - vwap) / vwap * 100
    roll_amt = amount.rolling(period).sum()
    roll_vol = volume.rolling(period).sum()
    vwap = roll_amt / roll_vol.replace(0, np.nan)
    vwap_bias = (close - vwap) / vwap * 100
    return pd.DataFrame({
        f"PVOL_corr{suffix}": corr,
        f"PVOL_amount_conc{suffix}": conc,
        f"PVOL_vwap_bias{suffix}": vwap_bias,
    }, index=df.index)
```

Register: `"PVOL": _compute_pvol,`

- [ ] **Step 4: Add FIELD_RANGES**

```python
    "PVOL_corr": (-1, 1),
    "PVOL_amount_conc": (0, 1),
    "PVOL_vwap_bias": (-20, 20),
```

- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Commit**

```bash
git add api/services/indicator_registry.py src/signals/rule_engine.py tests/test_quant_factors.py
git commit -m "feat(factors): add PVOL price-volume relationship factor"
```

---

### Task 5: 流动性因子 — LIQ (Liquidity)

- [ ] **Step 1: Write failing test**

```python
def test_liq_columns():
    from api.services.indicator_registry import compute_extended_indicator
    df = _make_df(30)
    result = compute_extended_indicator(df, "LIQ", {"period": 20})
    expected_cols = ["LIQ_amihud_20", "LIQ_turnover_vol_20", "LIQ_log_amount_20"]
    for col in expected_cols:
        assert col in result.columns, f"Missing {col}"
    # Amihud should be non-negative
    ami = result["LIQ_amihud_20"].dropna()
    assert (ami >= 0).all()
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement LIQ**

Add to `EXTENDED_INDICATORS`:

```python
    "LIQ": {
        "label": "流动性",
        "sub_fields": [
            ("LIQ_amihud", "Amihud非流动性"),
            ("LIQ_turnover_vol", "换手波动率"),
            ("LIQ_log_amount", "对数成交额"),
        ],
        "params": {
            "period": {"label": "回看周期", "default": 20, "type": "int"},
        },
    },
```

Add compute function:

```python
def _compute_liq(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Liquidity factors: Amihud illiquidity, turnover volatility, log amount."""
    period = int(params.get("period", 20))
    close = df["close"]
    volume = df["volume"]
    amount = df.get("amount", close * volume)
    suffix = f"_{period}"
    # 1. Amihud illiquidity: avg(|return| / amount)
    ret = close.pct_change().abs()
    illiq = (ret / amount.replace(0, np.nan)).rolling(period).mean() * 1e9  # scale up
    # 2. Turnover volatility (proxy: volume std / volume mean)
    vol_std = volume.rolling(period).std()
    vol_mean = volume.rolling(period).mean()
    turnover_vol = vol_std / vol_mean.replace(0, np.nan)
    # 3. Log average amount
    log_amount = np.log1p(amount.rolling(period).mean())
    return pd.DataFrame({
        f"LIQ_amihud{suffix}": illiq,
        f"LIQ_turnover_vol{suffix}": turnover_vol,
        f"LIQ_log_amount{suffix}": log_amount,
    }, index=df.index)
```

Register: `"LIQ": _compute_liq,`

- [ ] **Step 4: Add FIELD_RANGES**

```python
    "LIQ_amihud": (0, 100),
    "LIQ_turnover_vol": (0, 5),
    "LIQ_log_amount": (0, 30),
```

- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Commit**

```bash
git add api/services/indicator_registry.py src/signals/rule_engine.py tests/test_quant_factors.py
git commit -m "feat(factors): add LIQ liquidity factor"
```

---

### Task 6: 价格位置因子 — PPOS (Price Position)

- [ ] **Step 1: Write failing test**

```python
def test_ppos_columns():
    from api.services.indicator_registry import compute_extended_indicator
    df = _make_df(60)
    result = compute_extended_indicator(df, "PPOS", {"period": 20})
    expected_cols = [
        "PPOS_close_pos_20", "PPOS_high_dist_20", "PPOS_low_dist_20",
        "PPOS_drawdown_20", "PPOS_consec_dir_20",
    ]
    for col in expected_cols:
        assert col in result.columns, f"Missing {col}"
    # close_pos should be in [0, 1]
    pos = result["PPOS_close_pos_20"].dropna()
    assert (pos >= -0.01).all() and (pos <= 1.01).all()
    # drawdown should be non-positive
    dd = result["PPOS_drawdown_20"].dropna()
    assert (dd <= 0.01).all()
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement PPOS**

Add to `EXTENDED_INDICATORS`:

```python
    "PPOS": {
        "label": "价格位置",
        "sub_fields": [
            ("PPOS_close_pos", "收盘价位置(0-1)"),
            ("PPOS_high_dist", "距N日高点%"),
            ("PPOS_low_dist", "距N日低点%"),
            ("PPOS_drawdown", "N日最大回撤%"),
            ("PPOS_consec_dir", "连涨/跌天数"),
        ],
        "params": {
            "period": {"label": "回看周期", "default": 20, "type": "int"},
        },
    },
```

Add compute function:

```python
def _compute_ppos(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Price position factors: relative position, distance to extremes, drawdown."""
    period = int(params.get("period", 20))
    close = df["close"]
    high = df["high"]
    low = df["low"]
    suffix = f"_{period}"
    # 1. Close position within N-day range: (close - N_low) / (N_high - N_low)
    roll_high = high.rolling(period).max()
    roll_low = low.rolling(period).min()
    rng = (roll_high - roll_low).replace(0, np.nan)
    close_pos = (close - roll_low) / rng
    # 2. Distance to N-day high: (close / N_high - 1) * 100
    high_dist = (close / roll_high - 1) * 100
    # 3. Distance to N-day low: (close / N_low - 1) * 100
    low_dist = (close / roll_low - 1) * 100
    # 4. Max drawdown in N days
    roll_peak = close.rolling(period).max()
    drawdown = (close / roll_peak - 1) * 100
    # 5. Consecutive direction: count consecutive up/down days
    direction = (close.diff() > 0).astype(int) * 2 - 1  # +1 or -1
    groups = (direction != direction.shift()).cumsum()
    consec = direction.groupby(groups).cumsum()
    return pd.DataFrame({
        f"PPOS_close_pos{suffix}": close_pos,
        f"PPOS_high_dist{suffix}": high_dist,
        f"PPOS_low_dist{suffix}": low_dist,
        f"PPOS_drawdown{suffix}": drawdown,
        f"PPOS_consec_dir{suffix}": consec,
    }, index=df.index)
```

Register: `"PPOS": _compute_ppos,`

- [ ] **Step 4: Add FIELD_RANGES**

```python
    "PPOS_close_pos": (0, 1),
    "PPOS_high_dist": (-50, 0),
    "PPOS_low_dist": (0, 200),
    "PPOS_drawdown": (-50, 0),
    "PPOS_consec_dir": (-15, 15),
```

- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Commit**

```bash
git add api/services/indicator_registry.py src/signals/rule_engine.py tests/test_quant_factors.py
git commit -m "feat(factors): add PPOS price position factor"
```

---

### Task 7: 相对强弱因子 — RSTR (Relative Strength)

- [ ] **Step 1: Write failing test**

```python
def test_rstr_columns():
    from api.services.indicator_registry import compute_extended_indicator
    df = _make_df(30)
    result = compute_extended_indicator(df, "RSTR", {"period": 20})
    assert "RSTR_20" in result.columns
    assert "RSTR_weighted_20" in result.columns
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement RSTR**

Add to `EXTENDED_INDICATORS`:

```python
    "RSTR": {
        "label": "相对强弱",
        "sub_fields": [
            ("RSTR", "N日收益率%"),
            ("RSTR_weighted", "加权动量"),
        ],
        "params": {
            "period": {"label": "回看周期", "default": 20, "type": "int"},
        },
    },
```

Add compute function:

```python
def _compute_rstr(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Relative strength: N-day return and time-weighted momentum."""
    period = int(params.get("period", 20))
    close = df["close"]
    suffix = f"_{period}"
    # 1. Simple N-day return
    ret_n = (close - close.shift(period)) / close.shift(period) * 100
    # 2. Weighted momentum: recent days get higher weight
    # weights = [N, N-1, ..., 1] / sum
    weights = np.arange(period, 0, -1, dtype=float)
    weights /= weights.sum()
    daily_ret = close.pct_change() * 100
    weighted = daily_ret.rolling(period).apply(
        lambda x: np.dot(x, weights), raw=True
    )
    return pd.DataFrame({
        f"RSTR{suffix}": ret_n,
        f"RSTR_weighted{suffix}": weighted,
    }, index=df.index)
```

Register: `"RSTR": _compute_rstr,`

- [ ] **Step 4: Add FIELD_RANGES**

```python
    "RSTR": (-50, 100),
    "RSTR_weighted": (-10, 10),
```

- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Commit**

```bash
git add api/services/indicator_registry.py src/signals/rule_engine.py tests/test_quant_factors.py
git commit -m "feat(factors): add RSTR relative strength factor"
```

---

### Task 8: 振幅波动因子 — AMPVOL (Amplitude Volatility)

- [ ] **Step 1: Write failing test**

```python
def test_ampvol_columns():
    from api.services.indicator_registry import compute_extended_indicator
    df = _make_df(30)
    result = compute_extended_indicator(df, "AMPVOL", {"period": 5})
    assert "AMPVOL_std_5" in result.columns
    assert "AMPVOL_parkinson_5" in result.columns
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement AMPVOL**

Add to `EXTENDED_INDICATORS`:

```python
    "AMPVOL": {
        "label": "振幅波动",
        "sub_fields": [
            ("AMPVOL_std", "振幅标准差"),
            ("AMPVOL_parkinson", "Parkinson波动率"),
        ],
        "params": {
            "period": {"label": "回看周期", "default": 5, "type": "int"},
        },
    },
```

Add compute function:

```python
def _compute_ampvol(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Amplitude-based volatility: amplitude std and Parkinson estimator."""
    period = int(params.get("period", 5))
    h, l, c = df["high"], df["low"], df["close"]
    suffix = f"_{period}"
    # 1. Amplitude std
    amplitude = (h - l) / c
    amp_std = amplitude.rolling(period).std()
    # 2. Parkinson volatility: sqrt(1/(4*ln2) * mean(ln(H/L)^2))
    log_hl = np.log(h / l.replace(0, np.nan))
    parkinson = np.sqrt(
        (log_hl ** 2).rolling(period).mean() / (4 * np.log(2))
    ) * 100  # as percentage
    return pd.DataFrame({
        f"AMPVOL_std{suffix}": amp_std,
        f"AMPVOL_parkinson{suffix}": parkinson,
    }, index=df.index)
```

Register: `"AMPVOL": _compute_ampvol,`

- [ ] **Step 4: Add FIELD_RANGES**

```python
    "AMPVOL_std": (0, 0.2),
    "AMPVOL_parkinson": (0, 20),
```

- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Commit**

```bash
git add api/services/indicator_registry.py src/signals/rule_engine.py tests/test_quant_factors.py
git commit -m "feat(factors): add AMPVOL amplitude volatility factor"
```

---

### Task 9: Integration Test — 新因子参与回测

- [ ] **Step 1: Write integration test**

Append to `tests/test_quant_factors.py`:

```python
def test_factors_in_backtest_conditions():
    """Verify new factors can be used in buy_conditions and evaluated."""
    from src.signals.rule_engine import evaluate_conditions, collect_indicator_params
    from src.indicators.indicator_calculator import IndicatorConfig, IndicatorCalculator

    df = _make_df(60)

    # Strategy using new factors
    buy_conditions = [
        {"field": "MOM", "operator": ">", "compare_type": "value",
         "compare_value": 0, "params": {"period": 5}},
        {"field": "PPOS_close_pos", "operator": "<", "compare_type": "value",
         "compare_value": 0.5, "params": {"period": 20}},
        {"field": "REALVOL", "operator": "<", "compare_type": "value",
         "compare_value": 5, "params": {"period": 20}},
    ]

    # 1. Collect params
    collected = collect_indicator_params(buy_conditions)
    assert "mom" in collected or "MOM" in collected

    # 2. Build config and compute
    config = IndicatorConfig.from_collected_params(collected)
    calculator = IndicatorCalculator(config)
    indicators = calculator.calculate_all(df)
    df_full = pd.concat([df, indicators], axis=1)

    # 3. Verify columns exist
    assert "MOM_5" in df_full.columns
    assert "PPOS_close_pos_20" in df_full.columns
    assert "REALVOL_20" in df_full.columns

    # 4. Evaluate conditions (should not raise)
    triggered, labels = evaluate_conditions(buy_conditions, df_full, mode="AND")
    assert isinstance(triggered, bool)


def test_factors_vectorize():
    """Verify new factors work with vectorized signal generation."""
    from src.signals.rule_engine import collect_indicator_params
    from src.indicators.indicator_calculator import IndicatorConfig, IndicatorCalculator
    from src.backtest.vectorized_signals import vectorize_conditions

    df = _make_df(60)

    conditions = [
        {"field": "MOM", "operator": ">", "compare_type": "value",
         "compare_value": 0, "params": {"period": 20}},
    ]

    collected = collect_indicator_params(conditions)
    config = IndicatorConfig.from_collected_params(collected)
    calculator = IndicatorCalculator(config)
    indicators = calculator.calculate_all(df)
    df_full = pd.concat([df, indicators], axis=1)

    signals = vectorize_conditions(conditions, df_full, mode="AND")
    assert len(signals) == len(df_full)
    assert signals.dtype == bool
```

- [ ] **Step 2: Run integration tests**

Run: `cd /Users/allenqiang/stockagent && NO_PROXY='*' python -m pytest tests/test_quant_factors.py -xvs 2>&1 | tail -20`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_quant_factors.py
git commit -m "test(factors): add integration tests for new factors in backtest pipeline"
```

---

### Task 10: API 验证 — explore-strategies 可见新因子

- [ ] **Step 1: Verify factors appear in indicator docs API**

```bash
NO_PROXY='*' python3 -c "
import sys; sys.path.insert(0, '.')
from api.services.indicator_registry import get_all_fields, get_all_indicator_docs
fields = get_all_fields()
new_factors = ['MOM', 'REALVOL', 'REALVOL_skew', 'REALVOL_kurt', 'REALVOL_downside',
               'KBAR_upper_shadow', 'KBAR_lower_shadow', 'KBAR_body_ratio',
               'KBAR_amplitude', 'KBAR_overnight_ret', 'KBAR_intraday_ret',
               'PVOL_corr', 'PVOL_amount_conc', 'PVOL_vwap_bias',
               'LIQ_amihud', 'LIQ_turnover_vol', 'LIQ_log_amount',
               'PPOS_close_pos', 'PPOS_high_dist', 'PPOS_low_dist',
               'PPOS_drawdown', 'PPOS_consec_dir',
               'RSTR', 'RSTR_weighted',
               'AMPVOL_std', 'AMPVOL_parkinson']
for f in new_factors:
    status = '✓' if f in fields else '✗ MISSING'
    print(f'  {f:30s} {status}')
print(f'\nTotal fields: {len(fields)} (was ~80, now should be ~105+)')
"
```

Expected: All 26 new sub-fields show ✓

- [ ] **Step 2: Commit all remaining changes**

```bash
git add -A
git commit -m "feat(factors): P0 quantitative factors — 8 groups, 26 sub-fields for backtest"
```

---

## Summary

| Task | Factor Group | Sub-fields | Description |
|------|-------------|------------|-------------|
| 1 | MOM | 1 | N日动量(%) |
| 2 | REALVOL | 4 | 已实现波动率 + 偏度 + 峰度 + 下行波动率 |
| 3 | KBAR | 6 | 上下影线 + 实体比 + 振幅 + 隔夜/日内收益 |
| 4 | PVOL | 3 | 量价相关 + 成交集中度 + VWAP偏离 |
| 5 | LIQ | 3 | Amihud + 换手波动 + 对数成交额 |
| 6 | PPOS | 5 | 价格位置 + 距高低点 + 回撤 + 连涨跌 |
| 7 | RSTR | 2 | N日收益 + 加权动量 |
| 8 | AMPVOL | 2 | 振幅标准差 + Parkinson波动率 |
| **Total** | **8 groups** | **26 sub-fields** | 全部纯价量，零额外数据依赖 |
