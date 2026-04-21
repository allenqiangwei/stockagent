# 因子系统重构 — 装饰器自注册 + 文件夹自发现

## 目标

将所有 51 个因子（9 内置 + 42 扩展）从分散在 3 个文件的硬编码方式，迁移到 `src/factors/` 目录下用 `@register_factor` 装饰器统一注册。添加新因子只需一个文件一个装饰器，零改动其他文件。现有所有消费者代码零破坏。

## 背景

当前问题：
- `indicator_registry.py` 1144 行且持续膨胀
- 添加一个因子需改 4 处（2 个文件）
- 元数据分散在 `EXTENDED_INDICATORS`（registry）和 `FIELD_RANGES`（rule_engine）
- 9 个内置指标在 `indicator_calculator.py` 用完全不同的模式

## 设计

### 新目录结构

```
src/factors/
├── __init__.py           # auto-discover: 扫描同目录所有 .py 文件并 import
├── registry.py           # FactorDef 数据类 + @register_factor 装饰器 + 全局 FACTORS 注册表
├── builtin.py            # MA, EMA, RSI, MACD, KDJ, ADX, OBV, ATR, VOLUME_MA
├── volatility.py         # BOLL, DONCHIAN, KELTNER, ULCER, REALVOL, AMPVOL
├── trend.py              # CCI, AROON, ICHIMOKU, KST, MASS, PSAR, STC, VORTEX, DPO, WMA, TRIX
├── oscillator.py         # ROC, WR, MFI, STOCHRSI, STOCH, AO, KAMA, PPO, PVO, TSI, ULTOSC
├── volume.py             # VWAP, CMF, ADI, EMV, FI, NVI, VPT
├── price_action.py       # MOM, RSTR, PPOS, KBAR
├── liquidity.py          # LIQ, PVOL
└── sentiment.py          # NEWS_SENTIMENT
```

### registry.py — 核心注册机制

```python
@dataclass
class FactorDef:
    name: str                    # "MOM"
    label: str                   # "动量"
    sub_fields: list[tuple]      # [("MOM", "动量%")]
    params: dict                 # {"period": {"label": "周期", "default": 20, "type": "int"}}
    field_ranges: dict           # {"MOM": (-100, 500)}
    compute_fn: Callable         # (df, params) -> DataFrame
    category: str = ""           # "momentum" (来自所在文件名)

FACTORS: dict[str, FactorDef] = {}

def register_factor(name, label, sub_fields, params, field_ranges=None, category=""):
    def decorator(fn):
        FACTORS[name] = FactorDef(
            name=name, label=label, sub_fields=sub_fields,
            params=params, field_ranges=field_ranges or {},
            compute_fn=fn, category=category,
        )
        return fn
    return decorator
```

公开 API：
- `get_factor(name) -> FactorDef` — 获取单个因子定义
- `get_all_factors() -> dict[str, FactorDef]` — 获取所有因子
- `compute_factor(df, name, params) -> DataFrame` — 计算因子
- `get_all_field_ranges() -> dict[str, tuple]` — 汇总所有因子的取值范围
- `get_all_sub_fields() -> list[str]` — 汇总所有子字段名
- `get_factor_docs() -> str` — 生成因子文档字符串（给 AI prompt 用）

### __init__.py — 自动发现

```python
import importlib
import pkgutil

# 自动 import 同目录下所有 .py 文件（除 __init__ 和 registry）
# import 时 @register_factor 装饰器自动触发注册
for _, module_name, _ in pkgutil.iter_modules([__path__[0]]):
    if module_name not in ("registry",):
        importlib.import_module(f".{module_name}", __package__)
```

### 因子文件格式（每个 .py 文件）

```python
# src/factors/price_action.py
"""价格行为因子 — 动量、相对强弱、价格位置、K线形态"""

import numpy as np
import pandas as pd
from src.factors.registry import register_factor

@register_factor(
    name="MOM",
    label="动量",
    sub_fields=[("MOM", "动量%")],
    params={"period": {"label": "回看周期", "default": 20, "type": "int"}},
    field_ranges={"MOM": (-100, 500)},
)
def compute_mom(df, params):
    period = int(params.get("period", 20))
    close = df["close"]
    mom = (close - close.shift(period)) / close.shift(period) * 100
    return pd.DataFrame({f"MOM_{period}": mom}, index=df.index)

# ... more @register_factor in same file
```

### builtin.py — 内置指标迁移

9 个内置指标（MA/EMA/RSI/MACD/KDJ/ADX/OBV/ATR/VOLUME_MA）迁移到 `src/factors/builtin.py`，用同样的 `@register_factor` 注册。

内置指标的特殊点：
- 支持多参数集（如 RSI_14 和 RSI_7 同时计算）
- 列名命名规则略不同（如 `MACD_12_26_9`、`KDJ_K_9_3_3`）

这些通过 `params` 中指定多值来处理，`compute_fn` 返回的 DataFrame 包含所有参数组合的列。

### 兼容层 — 现有代码零破坏

**`api/services/indicator_registry.py`** — 变成薄代理：

```python
"""Backward-compatible facade — delegates to src.factors.registry."""
from src.factors.registry import (
    get_all_factors, compute_factor, get_factor,
    get_all_sub_fields, get_all_field_ranges, get_factor_docs,
)

# Legacy dict format for existing consumers
EXTENDED_INDICATORS = {
    name: {
        "label": f.label,
        "sub_fields": f.sub_fields,
        "params": f.params,
    }
    for name, f in get_all_factors().items()
    if name not in _BUILTIN_NAMES  # 9 个内置不在 EXTENDED 里
}

_COMPUTE_FUNCTIONS = {name: f.compute_fn for name, f in get_all_factors().items()}

def compute_extended_indicator(df, group, params=None):
    return compute_factor(df, group, params)

def is_extended_indicator(field):
    # 保持原有行为
    ...

def resolve_extended_column(field, params=None):
    # 保持原有行为
    ...

def get_extended_field_group(field):
    # 保持原有行为
    ...

def get_all_fields():
    return get_all_sub_fields()

def get_all_indicator_docs():
    return get_factor_docs()

def register_extended_indicators():
    pass  # No-op, auto-discovery already done on import
```

所有 6 个消费者的 `from api.services.indicator_registry import X` 继续工作，签名和行为不变。

**`src/indicators/indicator_calculator.py`** — 改用 registry：

```python
class IndicatorCalculator:
    def calculate_all(self, df):
        from src.factors.registry import get_all_factors, compute_factor
        result = pd.DataFrame(index=df.index)

        # 内置指标：按 config 中指定的参数计算
        for name in ["MA", "EMA", "RSI", "MACD", "KDJ", "ADX", "OBV", "ATR", "VOLUME_MA"]:
            if self._should_compute(name):
                params = self._get_params_for(name)
                cols = compute_factor(df, name, params)
                result = pd.concat([result, cols], axis=1)

        # 扩展指标：从 config.extended 读取
        for group_key, param_sets in self.config.extended.items():
            for params in param_sets:
                cols = compute_factor(df, group_key.upper(), params)
                result = pd.concat([result, cols], axis=1)

        return result
```

**`src/signals/rule_engine.py`** — FIELD_RANGES 自动生成：

```python
# 原来的硬编码 FIELD_RANGES dict 删除
# 改为从 registry 动态获取
from src.factors.registry import get_all_field_ranges
FIELD_RANGES = get_all_field_ranges()
```

INDICATOR_GROUPS（内置指标的元数据）也从 registry 读取。

### 不改动的文件

- `src/backtest/portfolio_engine.py` — 不直接依赖因子系统
- `src/backtest/vectorized_signals.py` — 消费 DataFrame 列，不关心因子来源
- 所有 router/service 文件 — 通过 indicator_registry.py 兼容层访问

### 迁移顺序

1. 创建 `src/factors/registry.py`（核心注册机制）
2. 创建 `src/factors/__init__.py`（自动发现）
3. 迁移 42 个扩展因子到 7 个分类文件
4. 迁移 9 个内置指标到 `builtin.py`
5. 改 `indicator_registry.py` 为兼容层
6. 改 `indicator_calculator.py` 用 registry
7. 改 `rule_engine.py` 的 FIELD_RANGES
8. 运行全部测试验证

### 验证标准

1. `python -m pytest tests/test_quant_factors.py` — 73 个测试全部通过
2. 对同一只股票运行回测，重构前后结果完全一致
3. `get_all_fields()` 返回的字段列表不变
4. `get_all_indicator_docs()` 输出不变
5. `compute_extended_indicator("MOM", {"period": 5})` 结果不变
