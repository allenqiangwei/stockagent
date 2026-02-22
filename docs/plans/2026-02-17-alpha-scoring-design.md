# Alpha评分排名层设计

## 目标

在现有规则引擎信号系统之上添加Alpha评分排名层。当多个股票触发买入信号时，对它们进行评分排名，只推荐Top 5。评分基于三个维度：技术指标超卖深度、多策略共识度、量价配合。

## 架构

在 `SignalEngine._evaluate_stock()` 内部，当买入信号触发后，利用已计算好的指标DataFrame立即计算Alpha评分，复用现有 `final_score`/`swing_score`/`trend_score` 字段存储，零DDL改动。API层新增排序和Top N过滤，前端信号页顶部新增Alpha Top 5卡片区域。

## 评分模型（总分100）

| 因子 | 权重 | 子项 | 说明 |
|------|------|------|------|
| 超卖深度 | 30分 | RSI偏离(15) + KDJ偏离(10) + MACD拐头(5) | 越深超卖分越高 |
| 多策略共识 | 40分 | 触发策略数/总启用策略数 × 40 | 共识度最重要 |
| 量价配合 | 30分 | 量比(15) + 均线位置(15) | 放量+靠近支撑位加分 |

### 超卖深度（0-30分）

- **RSI分量(0-15)**：`max(0, (30 - RSI_14) / 30 × 15)`
  - RSI=14 → 15分, RSI=30 → 0分, RSI>30 → 0分
- **KDJ分量(0-10)**：`max(0, (20 - KDJ_K) / 20 × 10)`
  - K=0 → 10分, K=20 → 0分, K>20 → 0分
- **MACD拐头(0-5)**：MACD_hist今天 > MACD_hist昨天 → 5分，否则0分

### 多策略共识（0-40分）

- `len(buy_strategies) / total_enabled_strategies × 40`
- 例如5个策略中有3个触发 → 3/5 × 40 = 24分

### 量价配合（0-30分）

- **量比分量(0-15)**：`min(15, max(0, (today_volume / vol_ma5 - 1) × 10))`
  - 量比1.0 → 0分, 1.5 → 5分, 2.0 → 10分, 2.5+ → 15分
- **均线位置(0-15)**：`min(15, max(0, (MA_20 - close) / MA_20 × 100 × 3))`
  - 价格低于MA20 5% → 15分（深度回调，支撑位附近）
  - 价格等于MA20 → 0分
  - 价格高于MA20 → 0分（已经拉起，不加分）

## 后端改动

### 1. `api/services/signal_engine.py`

新增方法：

```python
def _compute_alpha_score(
    self,
    full_df: pd.DataFrame,
    buy_strategies: list[str],
    total_strategies: int,
) -> tuple[float, dict]:
    """计算Alpha评分。

    Returns:
        (total_score, {"oversold": x, "consensus": y, "volume_price": z})
    """
```

在 `_evaluate_stock()` 中，当 `buy_triggered=True` 时调用此方法，将结果加入返回字典。

**问题**：当前 `_evaluate_stock()` 对每个策略单独计算 `full_df`（因为不同策略的指标参数可能不同）。评分需要标准化的指标值（RSI_14, KDJ_K_9_3_3, MA_20, volume_ma_5）。

**解决方案**：在 `_evaluate_stock()` 末尾，如果 `buy_triggered=True`，额外计算一次标准参数的指标（RSI_14, KDJ_9_3_3, MACD_12_26_9, MA_20）。由于 `df`（原始OHLCV）已经在手，只需一次 `indicator_engine.compute(df, scoring_config)` 调用。

### 2. 字段复用

| DB字段 | 用途 | 类型 |
|--------|------|------|
| `final_score` | Alpha总分 (0-100) | Float, 已有 |
| `swing_score` | 超卖深度分 (0-30) | Float, 已有 |
| `trend_score` | 量价配合分 (0-30) | Float, 已有 |
| 共识度分 | `final_score - swing_score - trend_score` | 计算得出 |

零DDL改动。

### 3. `_save_signal()` 改动

将 `alpha_score` 写入 `final_score`，`oversold_score` 写入 `swing_score`，`volume_price_score` 写入 `trend_score`。

## API改动

### `/api/signals/today`

- 返回结果中每条signal增加 `alpha_score`, `oversold_score`, `volume_price_score` 字段
- 新增查询参数 `top_n`（默认不限）
- 返回数据按 `alpha_score` 降序排列（买入信号）
- 返回结构增加 `alpha_top` 字段：前5条按alpha_score排序的买入信号

### 响应结构变化

```json
{
  "signals": [...],
  "alpha_top": [
    {
      "stock_code": "600519",
      "stock_name": "贵州茅台",
      "action": "buy",
      "alpha_score": 72.5,
      "oversold_score": 18.5,
      "consensus_score": 26.7,
      "volume_price_score": 12.3,
      "reasons": ["PSAR趋势动量", "全指标综合_中性版C"]
    }
  ],
  "trade_date": "2026-02-17"
}
```

## 前端改动

### 信号页 (`web/src/app/signals/page.tsx`)

在"今日信号"Tab顶部增加 **Alpha Top 5** 卡片行：

- 横向排列5张卡片（响应式：移动端竖向）
- 每张卡片显示：
  - 排名序号 + 股票名称 + 代码
  - Alpha总分（大字体）
  - 三色分段条形图：超卖(蓝) / 共识(紫) / 量价(橙)
  - 触发策略列表
- 点击卡片 → 路由到 `/market?code=xxx`
- 当没有买入信号时 → 显示"今日无Alpha推荐"

### 类型定义 (`web/src/types/index.ts`)

```typescript
interface AlphaSignal {
  stock_code: string;
  stock_name: string;
  action: string;
  alpha_score: number;
  oversold_score: number;
  consensus_score: number;
  volume_price_score: number;
  reasons: string[];
}
```

## 数据流

```
每日信号生成 (signal_scheduler)
  → SignalEngine.generate_signals_stream()
  → 扫描5000+股票
  → _evaluate_stock() per stock:
      → 各策略 evaluate_conditions → buy_triggered?
      → 如果买入触发: _compute_alpha_score(df, buy_strategies, total)
      → 存储 final_score/swing_score/trend_score
  → API: /api/signals/today
      → 查询 TradingSignal, 按 final_score DESC 排序
      → 返回 alpha_top (前5条买入)
  → 前端: Alpha Top 5 卡片渲染
```

## 不做的事情

- 不做因子权重可调（YAGNI，先验证效果）
- 不做独立页面（信号页增强即可）
- 不做历史评分回测（先专注实时）
- 不做卖出信号评分（只对买入信号排名）
