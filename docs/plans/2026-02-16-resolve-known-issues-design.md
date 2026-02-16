# 已知问题批量修复设计

> **目标**: 解决实验室 5 个未解决问题 (P4/P14/P18/P21/P22)，提升回测性能和策略生成质量。

**实施顺序**: P14(并发) → P18(combo缓存) → P4(零交易预检) → P21(few-shot) → P22(field比较)

**总改动量**: ~4 个文件，~170 行代码

---

## P14: 回测并发控制

**问题**: 无并发限制，14个 clone-backtest 同时启动导致 SQLite 竞争超时。

**方案**: 全局 `threading.Semaphore(3)` 控制最多 3 个并发回测。

**改动**:
1. `api/services/ai_lab_engine.py` — 模块级 `_BACKTEST_SEMAPHORE = threading.Semaphore(3)`
2. `_run_single_backtest()` 入口 acquire/release
3. `api/routers/ai_lab.py` clone-backtest 的 `_run_backtest()` 同样加信号量
4. 单策略超时 300s → 600s（排队等待增加了总时间）

---

## P18: 组合策略指标缓存

**问题**: Combo 5 成员 × 5000 股 = 每只股票算 5 次指标，18 成员直接超时。

**方案**: 合并所有成员的 indicator params，每只股票只算一次指标。

**改动**:
1. `src/backtest/portfolio_engine.py` — `_precompute_indicators()` 中检测 combo 策略时：
   - 收集所有成员的 buy/sell conditions 的 indicator params
   - 合并为一个 `IndicatorConfig`
   - 每只股票只调一次 `calculator.calculate_all(df, merged_config)`
2. 投票逻辑短路评估：达到 vote_threshold 后跳过剩余成员

---

## P4: 零交易预检（快速信号扫描）

**问题**: 50% 策略回测后零交易，浪费 5 分钟回测时间。

**方案**: 完整回测前，取 100 只股票 × 60 天做快速信号预扫描，0 信号则直接标 invalid。

**改动**:
1. `api/services/ai_lab_engine.py` — 新增 `_quick_signal_check()` 方法
   - 随机抽样 100 只股票，取最近 60 天数据
   - 计算指标 + 评估买入条件
   - 任一信号触发 → 返回 True（通过）
   - 全部无信号 → 返回 False（标 invalid，跳过回测）
2. 在 `_run_single_backtest()` 开头调用预扫描
3. 预扫描耗时 ~3-5 秒 vs 完整回测 5 分钟

---

## P21: DeepSeek 新条件类型 few-shot 示例

**问题**: 6 种新 compare_type 有格式说明但无 few-shot 示例，DeepSeek 默认只用 value/field。

**方案**: 添加完整示例策略 + 关键词触发强制要求。

**改动**:
1. `api/services/deepseek_client.py` — 添加示例策略 D（使用 lookback_min + pct_change）:
   ```json
   {
     "name": "N日新低反弹_保守版",
     "buy_conditions": [
       {"field": "close", "compare_type": "lookback_min", "lookback_field": "close", "lookback_n": 20, "operator": "<=", "label": "创20日新低"},
       {"field": "close", "compare_type": "pct_change", "lookback_n": 3, "operator": ">", "compare_value": 2.0, "label": "3日涨幅>2%"},
       {"field": "KDJ_K", "compare_type": "value", "compare_value": 25, "operator": "<", "params": {"fastk":9,"slowk":3,"slowd":3}, "label": "KDJ超卖"}
     ],
     "sell_conditions": [
       {"field": "close", "compare_type": "lookback_max", "lookback_field": "close", "lookback_n": 10, "operator": ">=", "label": "创10日新高止盈"}
     ],
     "exit_config": {"stop_loss_pct": -8.0, "take_profit_pct": 15.0, "max_hold_days": 20}
   }
   ```
2. 关键词触发：source_text 含 "N日新低/连续涨跌/偏离度/涨跌幅" 时追加强制指令

---

## P22: DeepSeek field 比较生成优化

**问题**: 明确要求 field 比较时 90%+ invalid，DeepSeek 搞混 operand 顺序和 params。

**方案**: 三层改进。

1. **Prompt 简化**: 列出 3-5 个固定有效的 field 比较模板：
   ```
   - close > PSAR: {"field":"close", "compare_type":"field", "compare_field":"PSAR", "compare_params":{"step":0.02,"max_step":0.2}}
   - close > MA_20: {"field":"close", "compare_type":"field", "compare_field":"MA", "compare_params":{"period":20}}
   - close < BOLL_lower: {"field":"close", "compare_type":"field", "compare_field":"BOLL_lower", "compare_params":{"length":20,"std":2.0}}
   ```

2. **后处理自动修正** (ai_lab_engine.py validate 阶段):
   - `field != "close"` 且 `compare_field == "close"` → 自动交换
   - `compare_params` 为空但 `compare_field` 需要参数 → 自动填充默认值

3. **explore-strategies skill**: 去掉 source_text 中 "使用 field 比较" 的指令
