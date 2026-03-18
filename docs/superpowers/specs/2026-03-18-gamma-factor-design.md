# Gamma 因子设计：缠论买卖点信号

**日期**: 2026-03-18
**状态**: 已批准
**作者**: AI + Allen

## 概述

引入 Gamma 因子，基于缠论（Chan Theory）多周期买卖点信号，作为第三个评分因子。Alpha（策略共识）+ Gamma（缠论）为决策因子，Beta（ML 预测）降级为参考因子。

## 数据源

通过 HTTP 调用本机运行的 chanlun-pro 服务（端口 9900）获取缠论数据。

**API 端点**:
```
GET http://127.0.0.1:9900/tv/history
  ?symbol=a%3A{SH|SZ|BJ}.{stock_code}
  &resolution={1D|1W}
  &from={unix_timestamp}
  &to={unix_timestamp}
  &firstDataRequest=true
```

**认证**: 需要先 GET `/login` 获取 session cookie（密码为空，自动登录）。

**Session 管理规范**:
- `gamma_service.py` 使用模块级 `requests.Session` 对象
- 启动时调用 `/login` 获取 cookie（302 → set-cookie → remember_token + session）
- 每次 API 调用检查 HTTP 状态码：非 200 时自动重新 `/login` 并重试一次
- 每个 HTTP 请求设置 `timeout=5` 秒（connect + read）
- 熔断机制：单轮连续 10 次失败后中止本轮 Gamma 计算，所有未计算股票 gamma_score = null

**响应字段**:
- `mmds`: 买卖点列表，每项 `{"points": {"price": float, "time": int}, "text": "笔:1B"}`
- `bcs`: 背驰列表，每项 `{"points": {"price": float, "time": int}, "text": "BI:bc"}`
- `bi_zss`: 笔中枢列表，每项包含 `[{time, price}, {time, price}, ...]`（中枢边界坐标）
- `bis`: 笔列表，每项 `[{time, price}, {time, price}]`（起点和终点坐标）。最后一笔方向判断：若 `bis[-1][1]["price"] > bis[-1][0]["price"]` 则为 `"up"`，否则为 `"down"`
- `xds`: 段列表

**MMD text 格式**: `{线型}:{买卖点类型}[,类型2]`
- 线型: `笔`（stroke）/ `段`（segment）
- 买点: `1B`/`2B`/`3B`/`L2B`/`L3B`
- 卖点: `1S`/`2S`/`3S`/`L2S`/`L3S`
- 可叠加: `2S,1S` 表示同时触发多个信号

**股票代码映射**: stockagent `600519` → chanlun `SH.600519`（6/9开头=SH，0/2/3开头=SZ，4/8开头=BJ）

## 架构

### 调度器插入点

在 `signal_scheduler.py` 的 `_do_refresh()` 方法中，Gamma 步骤插入在**信号生成（Step 5）之后、Beta 评分（Step 5d）之前**：

```
每日 15:30 调度流程 (_do_refresh):
Step 1.  数据同步 (已有, ~line 230)
Step 2.  执行交易计划 (已有, ~line 250)
Step 3.  退出监控 (已有, ~line 260)
Step 4.  池健康检查 (已有, ~line 270)
Step 5.  信号生成 → Alpha 评分 (已有, ~line 280)
         db.commit()  ← Alpha 写入 TradingSignal 后提交
Step 5a. 新闻匹配 (已有, ~line 290)
Step 5b. Beta 持仓跟踪 (已有, ~line 300)
Step 5c. Beta ML 训练 (已有, ~line 306)
─── ★ 新增插入点 ───
Step 5c2. Gamma 评分 (新增)
         ├─ 查询本日 buy 信号: SELECT * FROM trading_signals WHERE trade_date=X AND market_regime='buy'
         ├─ 对每只股票调用 gamma_service.compute_gamma(stock_code, trade_date)
         ├─ 更新 TradingSignal.gamma_score (已提交的记录做 UPDATE)
         ├─ 插入 GammaSnapshot 记录
         └─ db.commit()  ← Gamma 写入后提交，确保 Step 5d 可读取
─── ★ 新增插入点结束 ───
Step 5d. 综合评分 + 创建交易计划 (改造, ~line 310)
         ├─ 读取 signal.final_score (Alpha)
         ├─ 读取 signal.gamma_score (Gamma) ← 新增
         └─ combined = (alpha/100)*w_α + (gamma/100)*w_γ
Step 6.  卖出计划 (已有, ~line 320)
```

## Gamma 评分算法 (0-100)

### 维度 1: 日线买卖点强度 (0-45)

取日线最新 MMD（距今最近的买卖点），按类型映射分值：

| 日线最新 MMD | 基础分 |
|---|---|
| 笔:1B / 段:1B | 45 / 42 |
| 笔:2B / 段:2B | 35 / 33 |
| 笔:L2B / 段:L2B | 30 / 28 |
| 笔:3B / 段:3B | 25 / 23 |
| 笔:L3B / 段:L3B | 20 / 18 |
| 卖点 (xS) 或无信号 | 0 |

**时效衰减**（基于交易日数，从 MMD 的 `points.time` 到当日收盘的自然日换算）:
- MMD 距今 ≤ 5 个交易日: 100% 分值
- 6-10 个交易日: 50% 分值
- \> 10 个交易日: 25% 分值

### 维度 2: 周线共振确认 (0-30)

从周线 API 获取 `mmds` 和 `bis` 数据。"最近 4 周"定义为**周线 K 线数据的最后 4 根 bar**（即 `t[-4:]` 对应的时间范围内的 MMDs）。

| 优先级 | 周线状态 | 分值 | 判定方法 |
|---|---|---|---|
| 1 | 最近 4 根周线 bar 内有买点 | 30 | `mmds` 中 time >= t[-4] 且 text 含 B |
| 2 | 最近 4 根周线 bar 内有卖点 | 0 | `mmds` 中 time >= t[-4] 且 text 含 S |
| 3 | 最后一笔方向 = up | 20 | `bis[-1][1].price > bis[-1][0].price` |
| 4 | 中枢内（无明确方向） | 10 | 不满足以上任何条件 |

**评估顺序**: 从优先级 1 到 4 依次判断，**第一个命中即返回**。注意：买卖点同时存在时买点优先（优先级 1 > 2）；有卖点时即使笔方向为 up 也返回 0（优先级 2 > 3）。

### 维度 3: 结构健康度 (0-25)

| 指标 | 分值范围 | 计算 |
|---|---|---|
| 背驰确认 (bcs) | 0-10 | 日线 `bcs` 列表中最后一条的 time 在近 10 根 bar 内 = 10, 否则 = 0 |
| 中枢距离 | 0-8 | 当前价格 < 最近笔中枢 `bi_zss[-1]` 的最低坐标 = 8；在中枢内 = 4；在中枢上方 = 0 |
| 买点密度 | 0-7 | 日线 `mmds` 中 time 在近 30 根 bar 内的买点数: ≥3=7, 2=5, 1=3, 0=0 |

**总分 = 日线强度 + 周线共振 + 结构健康**

## 数据模型

### 新表: gamma_snapshots

```python
class GammaSnapshot(Base):
    __tablename__ = "gamma_snapshots"

    id: int                     # PK
    stock_code: str             # "600519", indexed
    snapshot_date: str          # "2026-03-18", indexed

    # Gamma 评分
    gamma_score: float          # 总分 0-100
    daily_strength: float       # 日线强度 0-45
    weekly_resonance: float     # 周线共振 0-30
    structure_health: float     # 结构健康 0-25

    # 缠论原始信号 (ML 特征)
    daily_mmd_type: str|None    # "1B", "2B", "3B", "L2B", "L3B", "1S"...
    daily_mmd_level: str|None   # "笔" or "段"
    daily_mmd_age: int          # 距今交易日数
    weekly_mmd_type: str|None
    weekly_mmd_level: str|None
    daily_bc_count: int         # 日线背驰数量
    daily_bi_zs_count: int      # 日线笔中枢数量
    daily_last_bi_dir: str|None # 最后一笔方向 "up"/"down"

    created_at: datetime
```

索引: `(stock_code, snapshot_date)` 联合索引。

### TradingSignal 扩展

新增字段: `gamma_score: Mapped[float | None] = mapped_column(Float, nullable=True)`

### BotTradePlan 扩展

新增字段: `gamma_score: Mapped[float | None] = mapped_column(Float, nullable=True)`

## 决策评分改造

### 新的综合评分公式

```python
# 两个因子都归一化到 [0, 1] 后加权
combined = (alpha / 100.0) * w_alpha + (gamma / 100.0) * w_gamma
```

**注意**: `TradingSignal.final_score` 存储的是 `_compute_alpha_score()` 返回的原始分数（0-100，由 count+quality+diversity 组成）。Gamma 原始值同样为 0-100。**两者都必须 /100 归一化到 [0,1]** 后再乘以权重。最终 combined 范围 [0, 1]。现有 `beta_scorer.py` 第 169 行 `combined = round(alpha * alpha_w + beta * beta_w, 4)` 需要一并修改为新公式。

当 `gamma_score` 为 null（chanlun-pro 不可用时），退化为仅用 Alpha:
```python
if gamma is None:
    combined = alpha / 100.0  # 纯 Alpha 决策
else:
    combined = (alpha / 100.0) * w_alpha + (gamma / 100.0) * w_gamma
```

### 动态权重

基于 **有 GammaSnapshot 记录的已完成交易（BotTradeReview）数量**。使用 INNER JOIN 语义：只有在入场日期当天或之前存在对应 GammaSnapshot 的交易才会被计数。

```python
def _get_gamma_phase(db: Session) -> str:
    """Count completed trades that had gamma data available at entry time.

    Uses INNER JOIN to GammaSnapshot — only reviews where a snapshot
    existed on or before the first_buy_date are counted. This naturally
    filters out trades made before the Gamma feature was deployed.
    """
    n = (
        db.query(func.count(distinct(BotTradeReview.id)))
        .join(GammaSnapshot, and_(
            GammaSnapshot.stock_code == BotTradeReview.stock_code,
            GammaSnapshot.snapshot_date <= BotTradeReview.first_buy_date,
        ))
        .scalar()
    ) or 0
    if n < 30:
        return "cold"
    elif n < 100:
        return "warm"
    return "mature"
```

**注意**: 不需要额外 `.filter(pnl.isnot(None))`，因为 `pnl` 字段 default=0.0 永远非 None。INNER JOIN 本身就完成了"有 Gamma 数据"的过滤。

**边界情况**: 如果在 Gamma 部署后批量回填了历史 GammaSnapshot 数据，部署前的旧交易也可能被计入 phase 计数。这在早期是可接受的（加速冷启动），成熟期后影响可忽略。

| 阶段 | 条件 | Alpha 权重 | Gamma 权重 |
|---|---|---|---|
| 冷启动 | < 30 笔完成交易有 Gamma 数据 | 80% | 20% |
| 暖启动 | 30-99 笔 | 60% | 40% |
| 成熟期 | ≥ 100 笔 | 50% | 50% |

### Beta 降级

`beta_scorer.py` 的 `score_and_create_plans()` 函数改造：

```python
# 原代码 (line 169):
# combined = round(alpha * alpha_w + beta * beta_w, 4)
# 新代码:
alpha = signal.final_score or 0.0  # ⚠️ 旧代码是 `or 0.5` (基于[0,1]刻度), 改为 0.0 (新[0,100]刻度)
gamma = signal.gamma_score  # 从 TradingSignal 读取, 可能为 None
alpha_w, gamma_w = GAMMA_WEIGHT_TABLE[gamma_phase]
if gamma is not None:
    combined = round((alpha / 100.0) * alpha_w + (gamma / 100.0) * gamma_w, 4)
else:
    combined = round(alpha / 100.0, 4)  # Gamma 不可用时退化

# Beta 仍然计算但只存储参考
beta = predict_beta_score(db, features)
```

- `BotTradePlan.combined_score` = 新的 alpha+gamma 综合分
- `BotTradePlan.beta_score` = Beta 预测值（仅参考）
- `BotTradePlan.gamma_score` = Gamma 原始分（0-100）

## ML 集成

### 特征扩展策略

在 `beta_ml.py` 的 `FEATURE_NAMES` 中新增 Gamma 特征。**由于改变特征维度会导致已训练模型不兼容**，需要以下迁移步骤：

1. **部署时**: 执行 `UPDATE beta_model_states SET is_active = false` 使现有模型失效
2. **首次运行**: `train_model()` 检测无 active 模型时自动触发重训练
3. **新特征填充**: Gamma 特征在训练数据中初期为 null，XGBoost 原生支持缺失值处理（`missing=np.nan`），无需额外处理
4. **特征列表与 `_features_to_array()` 同步更新**:

```python
FEATURE_NAMES = [
    # 原有 12 个特征...
    "gamma_score",              # Gamma 总分 (0-100)
    "daily_mmd_type_encoded",   # 日线 MMD 类型 (label encoded: 1B=6, 2B=5, L2B=4, 3B=3, L3B=2, sell=1, none=0)
    "daily_mmd_age",            # MMD 距今天数
    "weekly_resonance",         # 周线共振分 (0-30)
]

# Label encoding 映射 (prediction 和 training 共用)
MMD_TYPE_ENCODING = {"1B": 6, "2B": 5, "L2B": 4, "3B": 3, "L3B": 2,
                     "1S": 1, "2S": 1, "3S": 1, "L2S": 1, "L3S": 1}
```

**`_features_to_array()` 必须同步新增以下 4 行** (在现有 12 项之后):

```python
def _features_to_array(features: dict) -> list[float]:
    return [
        # ... 原有 12 行 ...
        features.get("gamma_score", 0.0),
        MMD_TYPE_ENCODING.get(features.get("daily_mmd_type"), 0),
        features.get("daily_mmd_age", 0),
        features.get("weekly_resonance", 0.0),
    ]
```

**特征填充入口** (`beta_scorer.py` 构建 features dict 时):
```python
# 在 features = { ... } 中新增:
"gamma_score": signal.gamma_score or 0.0,
"daily_mmd_type": snapshot.daily_mmd_type if snapshot else None,
"daily_mmd_age": snapshot.daily_mmd_age if snapshot else 0,
"weekly_resonance": snapshot.weekly_resonance if snapshot else 0.0,
```
其中 `snapshot` 通过 `db.query(GammaSnapshot).filter_by(stock_code=code, snapshot_date=trade_date).first()` 获取。

## 前端展示

### Alpha Top Cards 升级

双行 ScoreBar 展示:
- Alpha bar: 蓝(数量) + 紫(质量) + 橙(多样性)
- Gamma bar: 绿(日线) + 青(周线) + 黄(结构)
- 综合决策分: `combined_score`
- 缠论标签: 日线/周线 MMD 类型 + 方向箭头

### SignalItem 类型扩展

```typescript
export interface SignalItem {
  // ... existing fields
  gamma_score: number;
  gamma_daily_strength: number;
  gamma_weekly_resonance: number;
  gamma_structure_health: number;
  gamma_daily_mmd: string | null;   // "笔:1B"
  gamma_weekly_mmd: string | null;  // "笔:2B"
  combined_score: number;           // (alpha/100)*wα + (gamma/100)*wγ
  beta_score: number;               // 参考
}
```

### signal_engine.py 查询与 _signal_to_dict 改造

**查询改造**: `get_signals_by_date()` 在现有 `outerjoin(Stock, ...)` 之后新增第二个 `outerjoin` 加载 GammaSnapshot：

```python
def get_signals_by_date(self, trade_date: str) -> list[dict]:
    rows = (
        self.db.query(TradingSignal, Stock.name, GammaSnapshot)
        .outerjoin(Stock, TradingSignal.stock_code == Stock.code)
        .outerjoin(GammaSnapshot, and_(
            GammaSnapshot.stock_code == TradingSignal.stock_code,
            GammaSnapshot.snapshot_date == TradingSignal.trade_date,
        ))
        .filter(TradingSignal.trade_date == trade_date)
        .order_by(TradingSignal.final_score.desc())
        .all()
    )
    return [self._signal_to_dict(sig, name or "", snap) for sig, name, snap in rows]
```

**`_signal_to_dict` 签名变更**: `(row: TradingSignal, stock_name: str, snapshot: GammaSnapshot | None = None)`。第三个参数默认 `None`，确保 `get_signal_history()` 等仅传 2 参数的调用方无需修改（gamma 字段默认为 0/null）。新增以下字段返回：

```python
# 从 TradingSignal 读取
"gamma_score": row.gamma_score or 0.0,

# 从 GammaSnapshot 读取 (第二个 outerjoin 已加载)
"gamma_daily_strength": snapshot.daily_strength if snapshot else 0.0,
"gamma_weekly_resonance": snapshot.weekly_resonance if snapshot else 0.0,
"gamma_structure_health": snapshot.structure_health if snapshot else 0.0,
"gamma_daily_mmd": f"{snapshot.daily_mmd_level}:{snapshot.daily_mmd_type}" if snapshot and snapshot.daily_mmd_type else None,
"gamma_weekly_mmd": f"{snapshot.weekly_mmd_level}:{snapshot.weekly_mmd_type}" if snapshot and snapshot.weekly_mmd_type else None,

# 综合决策分
"combined_score": _compute_combined(row.final_score, row.gamma_score),
"beta_score": 0.0,  # Beta 暂无直接关联 (已知临时限制, 前端显示为0)
```

## 新增文件清单

| 文件 | 作用 |
|---|---|
| `api/models/gamma_factor.py` | GammaSnapshot ORM 模型 |
| `api/services/gamma_service.py` | Gamma 计算服务（HTTP 调用 chanlun-pro、评分算法、Session 管理） |

## 修改文件清单

| 文件 | 改动 |
|---|---|
| `api/models/signal.py` | TradingSignal 新增 `gamma_score: Float, nullable=True` |
| `api/models/bot_trading.py` | BotTradePlan 新增 `gamma_score: Float, nullable=True` |
| `api/services/signal_scheduler.py` | `_do_refresh` 在 Step 5c 和 5d 之间新增 Gamma 计算步骤 |
| `api/services/beta_scorer.py` | `combined_score` 改为 `(alpha/100)*w_α + (gamma/100)*w_γ`; beta 降级为参考; 新增 `_get_gamma_phase()` |
| `api/services/beta_ml.py` | `FEATURE_NAMES` 新增 4 个 gamma 特征; 部署时需使现有模型失效 |
| `api/services/signal_engine.py` | `_signal_to_dict` 新增 gamma_score, gamma_daily_strength, gamma_weekly_resonance, gamma_structure_health, gamma_daily_mmd, gamma_weekly_mmd, combined_score, beta_score 字段 |
| `web/src/types/index.ts` | `SignalItem` 新增 8 个 gamma/combined/beta 字段 |
| `web/src/components/signal/alpha-top-cards.tsx` | 双条 ScoreBar + 缠论标签 + 综合决策分 |

## chanlun-pro 股票代码映射

```python
def stockagent_code_to_chanlun(code: str) -> str:
    """600519 → SH.600519, 002495 → SZ.002495, 830799 → BJ.830799"""
    if code.startswith(("6", "9")):
        return f"SH.{code}"
    elif code.startswith(("4", "8")):
        return f"BJ.{code}"
    else:
        return f"SZ.{code}"
```

注意：北交所 (4xxxxx/8xxxxx) 股票能否在 chanlun-pro 中查询取决于其数据源配置。如不支持，这些股票的 gamma_score 将为 null，不影响 Alpha 决策。

## 性能与容错

- 仅对 buy 信号股票计算 Gamma（通常 100-300 只），非全市场 5000+
- 每只需 2 次 HTTP 调用（日线 + 周线），每次 `timeout=5s`
- 总耗时预估: 200 只 × 2 次 × 300ms = ~2 分钟（可接受）
- **熔断**: 连续 10 次 HTTP 失败后中止本轮，剩余股票 gamma_score = null
- **退化策略**: gamma_score = null 时，combined 退化为纯 Alpha 决策，不影响系统可用性
- **chanlun-pro 重启**: Session 自动重建（lazy re-login on non-200）
