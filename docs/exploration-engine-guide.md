# 策略探索引擎 (Exploration Engine) — 技术文档

> 版本: 2026-04-15 | 状态: 生产就绪 | 维护者: AI Lab Team

## 1. 概述

策略探索引擎是一个全自动化的量化策略发现系统，通过 REST API 控制，在后台线程中运行完整的"规划→回测→验证→入池"流水线。

**核心能力**：
- 自动调用 LLM（Qwen/DeepSeek）规划实验方向
- 批量提交回测并轮询等待
- Walk-Forward 验证过滤过拟合策略
- 自动 promote 到策略池 + rebalance
- 经验反馈循环（越跑越聪明）
- Checkpoint 断点恢复（任何步骤崩溃后可恢复）

**关键数据**：
- 90 个注册因子，76 个可探索因子
- ~1,980 万种理论因子组合（2-5 因子）
- 已探索 464 种组合（0.002%）
- 历史最佳 StdA+ 率：25-47%

---

## 2. 架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         REST API (FastAPI)                          │
│  POST /start  POST /resume  POST /stop  GET /status  GET /history  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                     ExplorationEngine (单例)                        │
│                     后台 daemon 线程运行                             │
│                                                                     │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌──────────┐ │
│  │ 因子注册 │  │ 经验知识 │  │ LLM规划 │  │ 配置验证 │  │ Checkpoint│ │
│  │ Registry │  │ 库(JSON) │  │ Planner │  │ Validator│  │ Recovery │ │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬─────┘ │
│       └────────────┴────────────┴────────────┴────────────┘        │
│                               │                                     │
│  14-Step Workflow Loop:                                             │
│  promote_check → sync_rounds → load_state → retry_pending          │
│  → plan (LLM) → submit → poll → self_heal                          │
│  → promote+WalkForward → rebalance → update_doc → sync_pinecone    │
│  → record → resolve_problems → update_experience                   │
└─────────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                     现有回测基础设施                                  │
│  batch-clone-backtest API → PortfolioBacktestEngine → walk_forward  │
│  promote API → StrategyPoolManager → Strategy DB                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 文件结构

### 3.1 核心文件

| 文件 | 行数 | 职责 |
|------|------|------|
| `api/services/exploration_engine.py` | 2106 | 引擎核心：因子注册、LLM规划、工作流循环、checkpoint |
| `api/routers/exploration_workflow.py` | 82 | REST API 端点（5个） |
| `api/main.py` | — | 路由注册（`app.include_router(exploration_workflow.router)`） |

### 3.2 因子系统

| 文件 | 行数 | 因子数 | 类别 |
|------|------|--------|------|
| `src/factors/registry.py` | 100 | — | 注册中心：`@register_factor` 装饰器 + `FACTORS` 全局字典 |
| `src/factors/__init__.py` | 17 | — | 自动发现：`pkgutil.iter_modules` 导入所有因子模块 |
| `src/factors/builtin.py` | 240 | 9 | KDJ, RSI, MACD, ATR, ADX, MA, EMA, OBV, VOLUME_MA |
| `src/factors/oscillator.py` | 255 | 11 | STOCH, STOCHRSI, ULTOSC, MFI, KAMA, ROC, WR, PPO, PVO, TSI, AO |
| `src/factors/trend.py` | 236 | 11 | PSAR, CCI, AROON, ICHIMOKU, VORTEX, KST, TRIX, DPO, MASS, STC, WMA |
| `src/factors/volatility.py` | 176 | 6 | BOLL, DONCHIAN, KELTNER, ULCER, REALVOL, AMPVOL |
| `src/factors/volatility_advanced.py` | 154 | 7 | 🆕 GARMAN_KLASS, ROGERS_SATCHELL, YANG_ZHANG, VOLSPLIT, VOL_OF_VOL, OVERNIGHT_VOL, INTRADAY_VOL |
| `src/factors/volume.py` | 119 | 7 | ADI, CMF, EMV, FI, NVI, VPT, VWAP |
| `src/factors/price_action.py` | 161 | 4 | KBAR, MOM, PPOS, RSTR |
| `src/factors/liquidity.py` | 80 | 2 | LIQ, PVOL |
| `src/factors/alpha_classic.py` | 291 | 14 | 🆕 CORR_VOL_RET, RANK_REVERSAL, DECAY_LINEAR_RET, OBV_SLOPE, VOLUME_RATIO, PV_FIT 等 |
| `src/factors/trend_advanced.py` | 291 | 12 | 🆕 TREND_STRENGTH, HURST, EFFICIENCY_RATIO, GAP_SIZE, N_DAY_BREAKOUT 等 |
| `src/factors/microstructure.py` | 166 | 6 | 🆕 ILLIQ, KYLE_LAMBDA, PIN_PROXY, SPREAD_EST, AMIHUD_RATIO, VOLUME_CLOCK |
| `src/factors/sentiment.py` | 27 | 1 | NEWS_SENTIMENT（非alpha因子，排除在探索之外） |

**总计：90 个注册因子，76 个可探索因子（排除 builtin + 已弃 + 非alpha）**

### 3.3 回测与验证

| 文件 | 职责 |
|------|------|
| `src/backtest/portfolio_engine.py` | 投资组合回测引擎（核心） |
| `src/backtest/vectorized_signals.py` | 向量化信号生成 |
| `src/backtest/walk_forward.py` (329行) | Walk-Forward 滚动验证（6窗口，2yr train + 6mo test） |

### 3.4 经验知识库

| 文件 | 职责 |
|------|------|
| `config/experience.json` | 经验数据库：84因子成功率、464组合成功率、20策略模板 |
| `config/exploration_checkpoint.json` | Checkpoint 断点文件（运行时自动创建/清理） |
| `scripts/init_experience.py` (231行) | 初始化脚本：扫描历史实验数据构建 experience.json |

### 3.5 配置

| 文件 | 相关配置 |
|------|---------|
| `config/config.yaml` | `deepseek.api_key` — DeepSeek API 密钥（LLM 备用） |
| `docs/lab-experiment-analysis.md` | 探索历史文档（引擎读取洞察 + 每轮自动更新） |

---

## 4. REST API

### 4.1 端点列表

| 方法 | 路径 | 功能 |
|------|------|------|
| `POST` | `/api/exploration-workflow/start` | 启动探索 |
| `POST` | `/api/exploration-workflow/resume` | 从 checkpoint 恢复 |
| `POST` | `/api/exploration-workflow/stop` | 优雅停止（当前步骤完成后） |
| `GET` | `/api/exploration-workflow/status` | 实时状态 |
| `GET` | `/api/exploration-workflow/history` | 历史轮次记录 |

### 4.2 Start

```bash
curl -X POST "http://localhost:8050/api/exploration-workflow/start?\
rounds=3&experiments_per_round=50&source_strategy_id=116987"
```

参数：
- `rounds` (1-100, 默认1)：探索轮数
- `experiments_per_round` (5-200, 默认50)：每轮实验数
- `source_strategy_id` (默认116987)：克隆源策略 ID

响应：
```json
{"state": "running", "round_number": 1222, "rounds": 3}
// 或有 checkpoint 时:
{"state": "running", "round_number": 1222, "resumed_from": "poll", "rounds": 3}
```

### 4.3 Resume

```bash
curl -X POST "http://localhost:8050/api/exploration-workflow/resume"
```

自动检测 `config/exploration_checkpoint.json`，从断点恢复。无 checkpoint 时等同于 `start`。

### 4.4 Stop

```bash
curl -X POST "http://localhost:8050/api/exploration-workflow/stop"
```

设置 `stop_event`，当前步骤完成后停止。不中断回测。

### 4.5 Status

```bash
curl "http://localhost:8050/api/exploration-workflow/status"
```

响应：
```json
{
  "state": "running",
  "current_round": 1222,
  "current_step": "poll",
  "step_detail": "done=142/300, StdA+=48",
  "rounds_total": 3,
  "rounds_completed": 1,
  "strategies_total": 300,
  "strategies_done": 142,
  "strategies_invalid": 6,
  "strategies_pending": 152,
  "stda_count": 48,
  "best_score": 0.8734,
  "pool_families": 7,
  "pool_active": 159,
  "pool_gap": 511,
  "started_at": "2026-04-15T08:00:00",
  "elapsed_seconds": 3600,
  "eta_seconds": 7200,
  "llm_provider": "qwen",
  "last_error": "",
  "experiment_ids": [13345, 13346, ...],
  "checkpoint": {"exists": false}
}
```

---

## 5. 工作流详解（14 步）

每轮探索按以下顺序执行。每步完成后自动保存 checkpoint。

### Step 1: promote_check

**检查历史未 promote 的 StdA+ 策略**

扫描最近 300 个实验，找到符合 StdA+ 标准但未 promote 的策略并 promote。

StdA+ 标准：`score >= 0.80 AND return > 60% AND drawdown < 18% AND trades >= 50 AND win_rate > 60%`

*失败处理：可跳过*

### Step 2: sync_rounds

**同步未完成的探索轮次**

检查 `memory_synced=false` 的历史轮次，标记为已同步。

*失败处理：可跳过*

### Step 3: load_state

**查询策略池状态**

调用 `GET /api/strategies/pool/status`，获取家族列表、gap、配额、活跃数。

*失败处理：关键步骤，中止轮次*

### Step 4: retry_pending

**恢复 stuck 实验队列**

调用 `POST /api/lab/experiments/retry-pending`，确保回测引擎在处理。

*失败处理：可跳过*

### Step 5: plan (LLM 规划)

**调用 LLM 生成实验配置**

输入注入：
1. **因子注册表**（76 个因子 + 阈值范围）
2. **经验知识库**（464 个组合成功率 + 最优阈值）
3. **池状态**（家族 gap）
4. **骨架候选**（未探索的因子组合，按经验成功率排序）
5. **策略模板**（top 策略的 few-shot 示例）
6. **上轮建议**

LLM 输出简化格式（代码自动添加 operator 和 params）：
```json
[{"name": "...", "buy_factors": [{"factor": "KBAR_amplitude", "value": 0.03}], ...}]
```

降级链：**Qwen 本地 (192.168.100.172:8680)** → DeepSeek API → 纯规则引擎

分批调用：每次 10 个实验，共 5 批 = 50 个。

*失败处理：关键步骤，中止轮次*

### Step 6: submit

**提交 batch-clone-backtest**

每个配置生成 1 个实验 × 6 个 exit config = 6 个策略。50 配置 = 300 个策略。

`_factor_to_condition()` 将简化的 `{factor, value}` 转换为完整条件，operator 从注册表读取（不依赖 LLM）。阈值从经验知识库的 `optimal_range` 优先 clamp。

*失败处理：关键步骤，中止轮次*

### Step 7: poll

**轮询等待回测完成**

2 分钟间隔查询所有实验状态。内置 stall 检测：10 分钟无进展自动 `retry-pending`。

实时更新 `strategies_done/invalid/pending/stda_count/best_score`。

*失败处理：关键步骤，中止轮次*

### Step 8: self_heal

**自愈机制**

如果 `invalid > done`（invalid 率 > 50%），自动将所有配置的阈值放宽 20% 重新提交。

*失败处理：关键步骤，中止轮次*

### Step 9: promote_and_rebalance

**Promote + Walk-Forward 验证 + Rebalance**

1. **Standard A promote**：所有 StdA+ 策略调用 promote API
2. **Walk-Forward 验证**（在 promote API 内部）：
   - 加载 200 只股票 × 5 年日线数据
   - 6 个滚动窗口（2yr train + 6mo test）
   - 过滤条件：`overfit_ratio <= 2.5 AND consistency_pct >= 40%`
   - 不通过 → archived
3. **Standard B promote**：牛/熊/震荡 regime 冠军分别 promote
4. **Rebalance**：每 fingerprint 家族最多保留 15 个策略

*失败处理：关键步骤，中止轮次*

### Step 10: update_memory_doc

**更新 lab-experiment-analysis.md**

更新 3 个段落：Auto-Promote 记录（含累计数）、下一步优先级（含 top-gap 家族）、历史摘要轮次数。

*失败处理：可跳过*

### Step 11: sync_pinecone

**Pinecone 向量数据库同步**

运行 `scripts/sync-memory.py`。

*失败处理：可跳过*

### Step 12: record

**保存探索轮次记录**

调用 `POST /api/lab/exploration-rounds`，记录本轮所有数据。

*失败处理：关键步骤，中止轮次*

### Step 13: resolve_problems

**问题检测与解决**

1. Zombie 实验检测 → retry-pending
2. 补漏 promote 扫描
3. 池 cleanup（删除低于 StdA+ 标准的策略）

*失败处理：可跳过*

### Step 14: update_experience

**经验反馈循环（P3）**

分析本轮结果，更新 `config/experience.json` 中各因子和组合的成功率。下一轮自动读取最新经验。

*失败处理：可跳过*

---

## 6. 因子系统

### 6.1 注册机制

新增因子只需在 `src/factors/` 下创建 `.py` 文件，使用 `@register_factor` 装饰器：

```python
# src/factors/my_new_factor.py
from .registry import register_factor

@register_factor(
    name="MY_FACTOR",
    label="我的因子",
    sub_fields=[("MY_FACTOR_value", "因子值")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"MY_FACTOR_value": (0, 100)},
    category="my_category",
)
def compute_my_factor(df, params):
    period = params.get("period", 20)
    result = df["close"].rolling(period).mean()  # 示例
    return pd.DataFrame({f"MY_FACTOR_value_{period}": result}, index=df.index)
```

**零额外配置**：`__init__.py` 自动发现，引擎的 `_build_valid_factors()` 自动将有 `field_ranges` 的因子加入可探索列表。

### 6.2 因子分类（90个）

| 类别 | 数量 | 说明 |
|------|------|------|
| builtin | 9 | KDJ, RSI, MACD, ATR 等基础指标 |
| oscillator | 11 | STOCH, STOCHRSI, ULTOSC, MFI 等振荡指标 |
| trend | 11 | PSAR, CCI, AROON 等趋势指标 |
| trend_advanced | 7 | HURST, EFFICIENCY_RATIO, TREND_QUALITY 等高级趋势 |
| pattern | 5 | GAP_SIZE, N_DAY_BREAKOUT, PRICE_CHANNEL_POS 等形态 |
| volatility | 13 | BOLL, REALVOL, AMPVOL + GARMAN_KLASS, YANG_ZHANG 等 |
| volume | 7 | ADI, CMF, VPT 等量能指标 |
| alpha_classic | 14 | WorldQuant Alpha101 经典因子 |
| price_action | 4 | KBAR, MOM, PPOS, RSTR |
| liquidity | 2 | LIQ, PVOL |
| microstructure | 6 | ILLIQ, KYLE_LAMBDA, PIN_PROXY 等微观结构 |
| sentiment | 1 | NEWS_SENTIMENT（排除在探索之外） |

### 6.3 数据源

所有因子仅使用以下字段计算（纯价量因子）：

| 字段 | 说明 | 来源 |
|------|------|------|
| `open` | 开盘价 | daily_prices 表 |
| `high` | 最高价 | daily_prices 表 |
| `low` | 最低价 | daily_prices 表 |
| `close` | 收盘价 | daily_prices 表 |
| `volume` | 成交量 | daily_prices 表 |
| `amount` | 成交额 | daily_prices 表 |
| `adj_factor` | 复权因子 | daily_prices 表 |

---

## 7. 经验知识库 (Experience Distillation)

### 7.1 结构

`config/experience.json`：

```json
{
  "factor_scores": {
    "KBAR_amplitude": {
      "total": 1212,
      "stda_count": 405,
      "stda_rate_pct": 33.4,
      "best_score": 0.8790,
      "optimal_range": [0.025, 0.04]
    }
  },
  "combo_scores": {
    "PVOL_amount_conc+W_REALVOL": {
      "total": 107,
      "stda_count": 55,
      "stda_rate_pct": 51.4,
      "best_score": 0.8762
    }
  },
  "top_templates": [
    {
      "score": 0.8595,
      "buy_conditions": [{"field": "REALVOL", "operator": "<", ...}],
      "exit_config": {"stop_loss_pct": -20, ...}
    }
  ]
}
```

### 7.2 初始化

```bash
python3 scripts/init_experience.py
```

扫描数据库中所有 `ExperimentStrategy`（~85,000 条），统计每个因子和组合的 StdA+ 成功率、最优阈值范围。

### 7.3 反馈循环

引擎每轮结束后自动调用 `_update_experience()`，将本轮结果增量更新到 experience.json。

---

## 8. Checkpoint 恢复

### 8.1 机制

每个步骤成功完成后，引擎写入 `config/exploration_checkpoint.json`：

```json
{
  "round_number": 1222,
  "current_step": "poll",
  "experiment_ids": [13345, 13346, ...],
  "configs": [...],
  "promoted_count": 0,
  "updated_at": "2026-04-15T09:30:00"
}
```

### 8.2 恢复流程

```
引擎启动 (start/resume)
    ↓
检查 checkpoint.json
    ├─ 不存在 → 正常从头开始
    ↓ 存在
    读取: {round=1222, step="poll", experiment_ids=[...]}
    ↓
    从 "poll" 的下一步继续（poll 已完成，执行 self_heal）
    ↓
轮次完成 → 删除 checkpoint → 继续下一轮
```

### 8.3 步骤失败策略

| 步骤 | 失败处理 | 原因 |
|------|---------|------|
| promote_check | ⚠️ 跳过继续 | 非关键，下轮会重试 |
| sync_rounds | ⚠️ 跳过继续 | 非关键 |
| load_state | ❌ 中止轮次 | 没有池状态无法规划 |
| retry_pending | ⚠️ 跳过继续 | 非关键 |
| plan | ❌ 中止轮次 | 没有配置无法提交 |
| submit | ❌ 中止轮次 | 提交失败整轮无意义 |
| poll | ❌ 中止轮次 | 回测结果丢失 |
| self_heal | ❌ 中止轮次 | 可能有大量 invalid 需处理 |
| promote_and_rebalance | ❌ 中止轮次 | promote 是核心产出 |
| update_memory_doc | ⚠️ 跳过继续 | 文档更新非关键 |
| sync_pinecone | ⚠️ 跳过继续 | 外部服务不阻塞 |
| record | ❌ 中止轮次 | 不记录等于白跑 |
| resolve_problems | ⚠️ 跳过继续 | 下轮会重试 |
| update_experience | ⚠️ 跳过继续 | 经验数据可重建 |

---

## 9. Walk-Forward 验证

### 9.1 机制

策略在进入策略池之前，必须通过 Walk-Forward 验证。验证在 `promote_strategy()` API 内部执行。

```
ExperimentStrategy (回测完成, StdA+ 通过)
    ↓
score > skeleton 门槛 → can_compete = True
    ↓
Walk-Forward 验证 (6 个滚动窗口)
    ├─ overfit_ratio > 2.5 → archived (过拟合)
    ├─ consistency_pct < 40% → archived (不稳定)
    └─ PASS → enabled=True, 进入池
```

### 9.2 参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 数据范围 | 最近 5 年 | start_date = now - 5yr |
| 训练窗口 | 2 年 | train_years = 2.0 |
| 测试窗口 | 6 个月 | test_months = 6 |
| 步进 | 6 个月 | step_months = 6 |
| 股票数 | 200 只 | 性能优化，取前 200 只有数据的 |
| 过拟合阈值 | 2.5 | train_return / test_return |
| 一致性阈值 | 40% | 盈利轮次 / 总轮次 |

### 9.3 文件

- `src/backtest/walk_forward.py` — Walk-Forward 核心逻辑
- `api/routers/ai_lab.py` 中 `_run_walk_forward_check()` — promote 时调用

---

## 10. LLM 规划

### 10.1 Provider 链

| 优先级 | Provider | 地址 | 模型 | 认证 |
|--------|----------|------|------|------|
| 1 | Qwen (本地) | `http://192.168.100.172:8680/v1` | `qwen3.5-35b-a3b` | 无需 |
| 2 | DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` | API Key |
| 3 | 规则引擎 | — | — | — |

### 10.2 简化输出格式

LLM 只输出因子名 + 阈值，代码自动添加 operator 和 params：

```json
{"name": "...", "buy_factors": [{"factor": "KBAR_amplitude", "value": 0.03}]}
```

`_factor_to_condition("KBAR_amplitude", 0.03, for_sell=False)` →
```json
{"field": "KBAR_amplitude", "operator": "<", "compare_type": "value", "compare_value": 0.03}
```

operator 从 `VALID_BUY_FACTORS` 注册表读取（`<` = 买低卖高，`>` = 买高卖低）。

### 10.3 分批调用

每次请求 10 个实验（避免 token 截断），共 5 批 = 50 个。

---

## 11. 骨架候选生成

### 11.1 组合空间

| 因子数 | 组合数 |
|--------|--------|
| 1 | 76 |
| 2 | 2,850 |
| 3 | 70,300 |
| 4 | 1,282,975 |
| 5 | 18,474,840 |
| **总计** | **19,831,041** |

### 11.2 排序逻辑

`generate_skeleton_candidates()` 按经验成功率排序：
- 因子得分 = `stda_count / total * confidence`（confidence 随实验数增长）
- 未测试因子得分 = 0.20（适度探索奖励）
- 排除已知失败组合（0% StdA+, ≥10 次实验）
- 4-5 因子只用 rate > 15% 的已验证因子

### 11.3 分层配额

| 因子数 | 配额比例 | 说明 |
|--------|---------|------|
| 2 因子 | 20% | 基础组合 |
| 3 因子 | 30% | 甜蜜区 |
| 4 因子 | 30% | 多因子验证 |
| 5 因子 | 20% | 复杂组合 |

---

## 12. 快速上手

### 12.1 首次使用

```bash
# 1. 初始化经验知识库（只需一次）
python3 scripts/init_experience.py

# 2. 确保服务器运行
uvicorn api.main:app --host 0.0.0.0 --port 8050

# 3. 启动探索（1轮，50实验）
curl -X POST "http://localhost:8050/api/exploration-workflow/start?rounds=1&experiments_per_round=50"

# 4. 监控状态
watch -n 30 'curl -s http://localhost:8050/api/exploration-workflow/status | python3 -m json.tool'

# 5. 查看结果
curl "http://localhost:8050/api/exploration-workflow/history?limit=5" | python3 -m json.tool
```

### 12.2 崩溃恢复

```bash
# 服务器重启后，自动从断点恢复
curl -X POST "http://localhost:8050/api/exploration-workflow/resume"

# 查看 checkpoint 状态
curl "http://localhost:8050/api/exploration-workflow/status" | jq '.checkpoint'
```

### 12.3 添加新因子

```bash
# 1. 创建因子文件
cat > src/factors/my_factor.py << 'EOF'
import pandas as pd
from .registry import register_factor

@register_factor(
    name="MY_FACTOR", label="我的因子",
    sub_fields=[("MY_FACTOR_value", "因子值")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"MY_FACTOR_value": (0, 100)},
    category="custom",
)
def compute(df, params):
    p = params.get("period", 20)
    result = df["close"].pct_change(p) * 100
    return pd.DataFrame({f"MY_FACTOR_value_{p}": result}, index=df.index)
EOF

# 2. 验证注册
python3 -c "import src.factors; from src.factors.registry import FACTORS; print('MY_FACTOR' in FACTORS)"

# 3. 验证引擎发现
python3 -c "from api.services.exploration_engine import VALID_BUY_FACTORS; print('MY_FACTOR_value' in VALID_BUY_FACTORS)"

# 4. 重启服务器，新因子自动出现在 LLM prompt 中
```

### 12.4 日常运维

```bash
# 夜间无人值守（3轮，共~150实验/900策略，约6-8小时）
curl -X POST "http://localhost:8050/api/exploration-workflow/start?rounds=3&experiments_per_round=50"

# 优雅停止
curl -X POST "http://localhost:8050/api/exploration-workflow/stop"

# 查看策略池状态
curl "http://localhost:8050/api/strategies/pool/status" | python3 -m json.tool
```

---

## 13. 性能参考

| 指标 | 典型值 |
|------|--------|
| LLM 规划时间 | ~90s (5批 × 18s) |
| 实验提交时间 | ~30s (50实验) |
| 回测总时间 | ~120min (300策略) |
| Walk-Forward / 策略 | ~2min |
| 每轮 StdA+ 产出 | 60-80 个 (20-25%) |
| 每轮总耗时 | ~2.5 小时 |
| 经验更新 | <5s |
| Checkpoint 保存 | <1s |
