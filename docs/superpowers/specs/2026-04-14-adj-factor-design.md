# 前复权因子重构 — 不复权存储 + 实时复权

## 目标

将 `daily_prices` 表从存储前复权价格改为存储不复权原始价格 + adj_factor（复权因子），查询和回测时实时计算前复权价格。解决当前"入库后除权事件导致历史价格失真"的问题。

## 背景

当前 `daily_prices` 存的是入库时刻的前复权价格。如果股票在入库后发生除权除息（分红/送股/配股），DB 中的历史价格不会更新，导致：
- 回测用的价格与当前前复权价格不一致
- 涨跌幅计算可能出错
- 越早入库的数据偏差越大

行业标准（万得/米筐/聚宽）是存不复权价 + 复权因子，查询时实时计算。

## 设计

### DB Schema 变更

`daily_prices` 表新增一列：

```sql
ALTER TABLE daily_prices ADD COLUMN adj_factor FLOAT DEFAULT 1.0;
```

变更后语义：
- `open/high/low/close` — 不复权原始价格（交易所原始数据）
- `adj_factor` — 前复权因子。`前复权价 = 不复权价 × adj_factor`
- `volume/amount` — 保持不变（成交量不复权）

### adj_factor 计算方法

使用 TDX `get_xdxr_info()` 获取除权除息记录，计算比例法前复权因子：

```
对于每个除权日:
  preclose = (close_prev × 10 - 分红 + 配股 × 配股价) / (10 + 配股 + 送转股)
  ratio = preclose / close_prev

adj_factor[i] = product(所有在 i 日之后发生的 ratio)
adj_factor[最新日] = 1.0（最新一天的前复权价 = 不复权价）
```

这与当前 `tdx_collector._apply_qfq()` 的算法一致，只是不再直接修改 OHLC，而是单独输出 adj_factor 列。

### 数据写入流程

**TDX 采集改动 (`tdx_collector.py`)：**

新增 `fetch_daily_raw()` 方法：
1. 拉不复权 K 线（跳过 `_apply_qfq`）
2. 拉 `get_xdxr_info()` 计算 adj_factor
3. 返回 DataFrame: date, open, high, low, close, volume, adj_factor

**DB 缓存改动 (`data_collector.py`)：**

`_cache_daily()` 和 `_cache_daily_batch()` 同时写入 adj_factor。

### 数据读取流程

**`get_daily_df()` 改动：**

从 DB 读出原始 OHLCV 后，乘以 adj_factor 再返回：
```python
df["open"]  = df["open"]  * df["adj_factor"]
df["high"]  = df["high"]  * df["adj_factor"]
df["low"]   = df["low"]   * df["adj_factor"]
df["close"] = df["close"] * df["adj_factor"]
```

返回的 DataFrame 仍然是 `date, open, high, low, close, volume` 六列（不含 adj_factor），对所有调用方透明。

**直接 ORM 查询的地方：**

7 个文件直接通过 ORM 读 `DailyPrice.close` 等字段（不经过 `get_daily_df()`）。这些地方需要改为 `row.close * row.adj_factor`。

涉及的文件和函数：
- `bot_trading_engine.py: _get_prev_close()`
- `bot_trading.py: _latest_close(), _get_today_prices()`
- `signals.py: _create_sell_plans_from_signals()` 中的 price_map
- `stocks.py: get_watchlist(), get_portfolio()`
- `beta_engine.py: _compute_ml_features()` 中的 prices[i].close
- `beta_tracker.py: track_daily_holdings()` 中的 price.close
- `news_stock_matcher.py: align_news_prices()` 中的 SQL close

### adj_factor 更新策略

**每日增量（do_refresh 中）：**

Signal scheduler Step 0b 阶段，检查当天是否有股票除权：
1. 查 TDX `get_xdxr_info()` 中 category=1 且日期=今天的记录
2. 对有除权的股票，重算该股票全部历史的 adj_factor
3. 更新 DB

**每周全量兜底（周日）：**

遍历所有活跃股票，重算 adj_factor。作为增量更新的安全网。
在 `_run_loop` 中检测 `weekday() == 6`（周日）触发。

### 全量重灌方案

新建 `scripts/rebuild_daily_prices.py`：

1. 停 uvicorn
2. `ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS adj_factor FLOAT DEFAULT 1.0`
3. `TRUNCATE daily_prices`
4. 遍历 stocks 表全部 ~5400 只股票：
   - TDX `fetch_daily_raw(code, "2015-01-01", today)` 拉不复权数据 + adj_factor
   - 批量插入 DB
   - 每 100 只打印进度
5. VACUUM ANALYZE
6. 启动 uvicorn

预计耗时：2-4 小时（受 TDX 连接速度限制）。

### 文件清单

| 文件 | 动作 | 改动内容 |
|------|------|---------|
| `api/models/stock.py` | 修改 | DailyPrice 加 `adj_factor` 列 |
| `api/services/tdx_collector.py` | 修改 | 新增 `fetch_daily_raw()` 返回不复权+adj_factor |
| `api/services/data_collector.py` | 修改 | 写入 adj_factor；`get_daily_df()` 读取时乘以 adj_factor |
| `api/services/bot_trading_engine.py` | 修改 | `_get_prev_close()` 用 adj_factor |
| `api/routers/bot_trading.py` | 修改 | `_latest_close()`, `_get_today_prices()` 用 adj_factor |
| `api/routers/signals.py` | 修改 | price_map 用 adj_factor |
| `api/routers/stocks.py` | 修改 | watchlist/portfolio 价格用 adj_factor |
| `api/services/beta_engine.py` | 修改 | ML features 用 adj_factor |
| `api/services/beta_tracker.py` | 修改 | daily tracking 用 adj_factor |
| `api/services/news_stock_matcher.py` | 修改 | SQL 查 close 改为 close * adj_factor |
| `api/services/signal_scheduler.py` | 修改 | 加每日/每周 adj_factor 更新逻辑 |
| `scripts/rebuild_daily_prices.py` | 新建 | 全量重灌脚本 |

### 不需要改的

- `src/backtest/portfolio_engine.py` — 消费 `get_daily_df()` 返回的已复权 DataFrame
- `src/indicators/indicator_calculator.py` — 接收已复权的 DataFrame
- `src/signals/rule_engine.py` — 不直接读价格
- 前端 — 不直接读 DB

### 回滚方案

如果重灌后发现问题：
1. 全部 OHLCV 是不复权原始值，adj_factor 有值 → 仍可正确计算前复权
2. 最坏情况：用 TDX 重新拉前复权数据覆盖（回到旧方案）
