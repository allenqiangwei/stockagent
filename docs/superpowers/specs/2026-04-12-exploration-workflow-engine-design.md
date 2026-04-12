# Exploration Workflow Engine — Design Spec

**Date**: 2026-04-12
**Status**: Draft
**Goal**: 将策略探索流程从 Claude skill + 临时脚本 固化为 FastAPI 集成的自动化工作流引擎，提供 REST API 控制和状态查询。

---

## 1. Problem Statement

当前策略探索流程分散在：
- Claude skill (`explore-strategies`) — 需要人工启动 Claude session
- 临时 Python 脚本 (`/tmp/r12XX_batch.py`, `/tmp/r12XX_auto_finish.py`) — 每轮手写
- 手动操作 — promote 检查、memory 更新、retry-pending

**痛点**：
1. 每次探索需要启动 Claude session，无法无人值守运行
2. 临时脚本没有状态持久化，服务重启后丢失
3. 无法通过 API 控制启停
4. 前端无法直接调用探索功能

## 2. Solution Overview

在现有 FastAPI 服务（8050 端口）中新增 **Exploration Workflow Engine**：
- 后台线程运行探索循环
- REST API 控制启停、查询状态
- LLM（Qwen 主力 + DeepSeek 备用）生成完整实验配置
- 代码验证 + 自动提交 + 轮询 + promote + 内存更新

## 3. Architecture

### 3.1 Components

```
api/services/exploration_engine.py    # 引擎核心（~800行）
api/routers/exploration_workflow.py   # REST API（4个端点）
```

### 3.2 Engine Class Structure

```python
class ExplorationEngine:
    """单例，后台线程运行探索循环"""

    # ── 状态 ──
    state: str           # IDLE | RUNNING | STOPPING | ERROR
    current_round: int
    current_step: str    # loading_state | planning | submitting | polling | promoting | updating
    stop_event: Event

    # ── 统计 ──
    stats: WorkflowStats  # 实时更新的统计数据

    # ── 主循环 ──
    def start(rounds, experiments_per_round) → None
    def stop() → None
    def get_status() → dict

    # ── 步骤（私有）──
    def _run_loop(rounds, exp_per_round)
    def _step_load_state() → PoolState
    def _step_plan(pool_state) → list[ExperimentConfig]
    def _step_submit(configs) → list[int]  # experiment_ids
    def _step_poll(experiment_ids) → RoundResults
    def _step_promote(results) → int  # promoted_count
    def _step_update_memory(results, promoted) → None
```

### 3.3 LLM Planner

```python
class LLMPlanner:
    """LLM 规划器，Qwen 主力 + DeepSeek 备用 + 规则兜底"""

    providers = [
        ("qwen", "http://192.168.100.172:8680/v1", "qwen3.5-35b-a3b", None),
        ("deepseek", "https://api.deepseek.com/v1", "deepseek-chat", API_KEY),
        ("rules", None, None, None),  # 纯规则兜底
    ]

    def plan(pool_state, n_experiments) → list[ExperimentConfig]:
        """尝试 providers 直到成功"""
        for provider in providers:
            try:
                configs = _call_llm(provider, pool_state, n_experiments)
                validated = _validate_configs(configs)
                if len(validated) >= n_experiments * 0.8:  # 80%通过率即可
                    return validated
            except:
                continue
        return _rule_based_plan(pool_state, n_experiments)  # 兜底
```

### 3.4 Few-Shot Prompt（已验证有效）

System prompt 包含：
1. 可用因子列表（field name + operator + 典型值范围 + params）
2. 已弃因子黑名单
3. **正确的 sell 条件示例**（Few-Shot，解决 Qwen 格式幻觉问题）
4. Exit config 格式说明
5. 池状态摘要

User prompt：
1. 当前池状态（家族 + gap + avg_score）
2. 请求 N 个实验（按 fill/new/opt 分配）
3. 输出格式要求

### 3.5 Config Validator

```python
def validate_experiment_config(config: dict) → tuple[bool, list[str]]:
    """验证单个实验配置"""
    issues = []

    # 1. 检查 type 有效性
    # 2. 检查 extra_buy_conditions 中每个条件:
    #    - field 在允许列表中
    #    - field 不在禁用列表中
    #    - operator 是 < 或 >
    #    - compare_type == "value"
    #    - compare_value 在合理范围内
    #    - 需要 params 的字段有 params
    # 3. 检查 extra_sell_conditions 同上
    # 4. 检查 exit_configs:
    #    - 至少 3 个
    #    - stop_loss_pct 为负数
    #    - take_profit_pct 为正数
    #    - max_hold_days 为正整数

    return len(issues) == 0, issues
```

无效配置直接丢弃，不重试。只要 80%+ 有效即可提交。

## 4. REST API

### 4.1 Endpoints

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/exploration-workflow/start` | POST | 启动探索 |
| `/api/exploration-workflow/stop` | POST | 停止（当前轮完成后） |
| `/api/exploration-workflow/status` | GET | 实时状态 |
| `/api/exploration-workflow/history` | GET | 历史轮次（代理到 exploration-rounds） |

### 4.2 Start Request

```json
POST /api/exploration-workflow/start
{
    "rounds": 3,                    // 探索轮数，默认1
    "experiments_per_round": 50,    // 每轮实验数，默认50
    "source_strategy_id": 116987    // 克隆源策略ID，默认116987
}
```

Response: `{"message": "Exploration started", "round_number": 1218}`

### 4.3 Status Response

```json
GET /api/exploration-workflow/status
{
    "state": "RUNNING",
    "current_round": 1218,
    "current_step": "polling",
    "step_detail": "等待回测: 142/385 done, 48 StdA+",
    "rounds_config": {"total": 3, "completed": 0},
    "strategies": {
        "total": 385,
        "done": 142,
        "invalid": 12,
        "pending": 231,
        "stda_count": 48,
        "best_score": 0.8805
    },
    "pool": {
        "families": 95,
        "active": 1313,
        "gap": 7077
    },
    "timing": {
        "started_at": "2026-04-12T10:00:00",
        "elapsed_seconds": 3600,
        "estimated_remaining_seconds": 7200
    },
    "llm_provider": "qwen",
    "last_error": null
}
```

### 4.4 Stop

```json
POST /api/exploration-workflow/stop
```
Response: `{"message": "Stop requested, will finish current round"}`

设置 `stop_event`，当前轮的 polling 完成后停止。不会中断正在跑的回测。

## 5. Workflow State Machine

```
IDLE ──start()──→ RUNNING
                    │
                    ├─ loading_state   查询池状态、sync 未完成轮次、promote 检查
                    ├─ planning        调用 LLM 生成实验配置
                    ├─ submitting      提交 batch-clone-backtest + retry-pending
                    ├─ polling         轮询等待回测完成（2分钟间隔）
                    ├─ promoting       StdA+ promote + rebalance
                    ├─ updating        更新 exploration-rounds API
                    │
                    ├─ [round_complete] → 检查 stop_event / rounds 剩余
                    │     ├─ 继续 → loading_state（下一轮）
                    │     └─ 停止 → IDLE
                    │
                    └─ [error] → ERROR → IDLE（记录 last_error）

RUNNING ──stop()──→ STOPPING ──(当前轮完成)──→ IDLE
```

## 6. Data Flow

```
                    ┌─────────────┐
                    │  Pool API   │ GET /strategies/pool/status
                    └──────┬──────┘
                           │ family_summary[]
                           ▼
                    ┌─────────────┐
                    │ LLM Planner │ Qwen → DeepSeek → Rules
                    └──────┬──────┘
                           │ list[ExperimentConfig]
                           ▼
                    ┌─────────────┐
                    │  Validator  │ 丢弃无效配置
                    └──────┬──────┘
                           │ validated configs
                           ▼
                    ┌─────────────┐
                    │  Submitter  │ POST /batch-clone-backtest × N
                    └──────┬──────┘
                           │ experiment_ids[]
                           ▼
                    ┌─────────────┐
                    │   Poller    │ GET /experiments/{id} × 2min
                    └──────┬──────┘
                           │ RoundResults
                           ▼
                    ┌─────────────┐
                    │  Promoter   │ POST /promote + POST /rebalance
                    └──────┬──────┘
                           │ promoted_count
                           ▼
                    ┌─────────────┐
                    │  Recorder   │ POST /exploration-rounds
                    └─────────────┘
```

## 7. LLM Provider Chain

| 优先级 | Provider | Base URL | Model | Auth | 特点 |
|--------|----------|----------|-------|------|------|
| 1 | Qwen (本地) | `http://192.168.100.172:8680/v1` | `qwen3.5-35b-a3b` | 无需 | 52s/次, 免费, Few-Shot后格式正确 |
| 2 | DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` | API Key | 97s/次, 付费, 格式天然正确 |
| 3 | 规则引擎 | N/A | N/A | N/A | 0s, 按gap排序+预设参数grid |

降级触发条件：
- 网络超时（30s）
- JSON 解析失败
- 有效配置 < 80% 要求数量

## 8. Rule-Based Fallback

当 LLM 全部不可用时，纯规则生成：

```python
def _rule_based_plan(pool_state, n):
    configs = []
    # Fill: 按 gap 降序选家族，每个家族用预设的 threshold grid
    for family in sorted(pool_state.families, key=lambda f: -f.gap)[:n//3]:
        configs.append(make_fill_config(family))
    # New: 从未测试组合矩阵中顺序选取
    for combo in untested_combos[:n*3//5]:
        configs.append(make_new_config(combo))
    # Opt: 用预设的 sell 条件列表
    for sell_template in SELL_TEMPLATES[:n//10]:
        configs.append(make_opt_config(sell_template))
    return configs
```

## 9. Key Design Decisions

1. **单实例**：同一时间只运行一个探索流程（和 backtest Semaphore=1 一致）
2. **优雅停止**：`/stop` 不中断回测，等当前轮完成
3. **服务重启恢复**：不自动恢复。手动 `/start` 即可，Step 1 会自动 sync 未完成轮次
4. **LLM 输出验证**：严格校验后丢弃无效配置，不重试 LLM
5. **Qwen Few-Shot**：system prompt 必须包含正确的 sell 条件示例（已验证解决格式幻觉）
6. **Memory 更新简化**：只更新 `exploration-rounds` API 记录，不修改 markdown 文件（减少复杂度）
7. **不依赖 /tmp**：所有状态通过 API 记录持久化，不写临时文件

## 10. File Structure

```
api/
├── services/
│   └── exploration_engine.py    # ExplorationEngine + LLMPlanner + Validator (~800行)
└── routers/
    └── exploration_workflow.py  # 4个 REST 端点 (~80行)
```

两个文件，保持简单。引擎内部用方法划分步骤，不过度拆分成多个类。

## 11. Dependencies

- `openai` Python package（已在 requirements.txt 中）— 用于调用 Qwen/DeepSeek 的 OpenAI 兼容 API
- 现有内部 API（batch-clone-backtest, experiments, promote, pool/status, exploration-rounds）

## 12. Not In Scope

- 前端 UI（可后续添加，API 已就绪）
- 自动 memory markdown 更新（复杂度高，保留给 Claude session 手动 sync）
- 多实例并行探索
- 实验结果可视化分析
