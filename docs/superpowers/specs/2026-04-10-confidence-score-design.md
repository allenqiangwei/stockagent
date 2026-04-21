# Confidence Score — 可跟单置信度系统

## 目标

为每条交易计划生成一个 0-100 的 `confidence` 分数，代表"这笔交易盈利的概率"。用户自行决定跟单阈值。分数每天基于最新完成交易数据自动重新校准。

## 问题背景

实盘数据显示：
- ranging（震荡）环境下胜率仅 11%，但系统仍以满仓力度买入
- 当前 Alpha/Beta/Gamma 三因子的 combined_score 无法有效区分好坏信号
- Beta XGBoost 模型过拟合（regime_encoded 占 50% importance），高置信度反而是反向指标
- 需要一个统一的、基于历史实际胜率的概率模型

## 设计

### 模型选择：Logistic Regression

| 考量 | LR | XGBoost |
|------|----|---------|
| 训练数据量 | 2182 条，LR 足够 | 容易过拟合 |
| 输出校准 | 天然输出校准概率 | 需额外校准 |
| 可解释性 | 系数直观可读 | 黑盒 |
| 历史教训 | — | Beta XGBoost 已证明过拟合 |

### 特征（6个）

| # | 特征 | 来源 | 可用率 | 说明 |
|---|------|------|--------|------|
| 1 | `alpha_score` | bot_trade_plans | 100% | 技术信号强度 0-100 |
| 2 | `gamma_score` | bot_trade_plans | 58% | 缠论评分 0-100，缺失填 0 |
| 3 | `has_gamma` | 计算 | 100% | gamma_score 是否有值（布尔→0/1） |
| 4 | `trend_strength` | market_regimes | 100% | ADX 归一化 0-1 |
| 5 | `volatility` | market_regimes | 100% | ATR/Close 归一化 0-1 |
| 6 | `index_return_pct` | market_regimes | 100% | 当周大盘涨跌幅 |

**预留特征（当前数据不足，未来自动纳入）：**
- `index_return_5d` — beta_snapshots，当前仅 1.6% 有值
- `market_sentiment` — news_sentiment_results，当前仅 12.9% 有值

### 标签

`pnl_pct > 0` → 1（盈利），否则 → 0。来自 `bot_trade_reviews.pnl_pct`。

### 训练数据构建

```sql
SELECT p.alpha_score, p.gamma_score, p.combined_score,
       mr.trend_strength, mr.volatility, mr.index_return_pct,
       CASE WHEN r.pnl_pct > 0 THEN 1 ELSE 0 END as label
FROM bot_trade_plans p
JOIN bot_trade_reviews r
    ON r.stock_code = p.stock_code
    AND r.strategy_id = p.strategy_id
    AND r.first_buy_date = p.plan_date
JOIN market_regimes mr
    ON r.first_buy_date BETWEEN mr.week_start::text AND mr.week_end::text
WHERE p.status = 'executed' AND p.direction = 'buy'
    AND p.alpha_score IS NOT NULL
```

### 训练流程

1. 构建 (X, y) 数据集
2. StandardScaler 标准化特征
3. `LogisticRegression(C=1.0, max_iter=1000)` 训练
4. 输出 `model.predict_proba(X)[:, 1]` → 0-1 概率 → ×100 = confidence 分数
5. 序列化 model + scaler 系数为 JSON（不用 pickle — 安全且可移植）存储到 DB

### 序列化方式

LR 模型参数量很小（6个系数 + 6个 scaler 参数），直接存 JSON：

```json
{
  "coef": [0.12, -0.05, 0.23, ...],
  "intercept": -1.34,
  "scaler_mean": [65.2, 30.1, ...],
  "scaler_scale": [15.3, 25.8, ...]
}
```

预测时手工还原：`z = dot(scaler_transform(X), coef) + intercept → sigmoid(z)` — 不依赖 sklearn。

### 校准验证

训练后计算：
- AUC-ROC（区分度）
- Brier Score（校准度 — LR 天然优势）
- 分桶校准检查：confidence 50-60 的交易，实际胜率是否在 50-60%？

### 自动重训练

在 `signal_scheduler._do_refresh()` 中，Step 5d-pre 位置（当前已有 signal_grader.calibrate）：
1. 每天重新训练 LR（全量数据，不做 train/test split — 数据量不大，目标是校准而非泛化）
2. 存储新模型到 `confidence_models` 表
3. 如果 AUC < 0.52（比随机猜好不了多少），保留旧模型不更新

### 预测流程

在 `beta_scorer.score_and_create_plans()` 中，为每个 plan：
1. 查当周 market_regimes 获取 trend_strength, volatility, index_return_pct
2. 构建特征向量 [alpha, gamma, has_gamma, trend_strength, volatility, index_return]
3. `sigmoid(dot(scaler_transform(X), coef) + intercept) * 100` → confidence 分数
4. 写入 `bot_trade_plans.confidence`

### 数据库变更

**新表 `confidence_models`：**

| 列 | 类型 | 说明 |
|----|------|------|
| id | int PK | 自增 |
| version | int | 版本号 |
| model_params | json | {coef, intercept, scaler_mean, scaler_scale} |
| feature_names | json | 特征名列表 |
| auc_score | float | ROC-AUC |
| brier_score | float | Brier Score（越低越好） |
| training_samples | int | 训练样本数 |
| positive_rate | float | 正样本比例 |
| is_active | bool | 是否为当前模型 |
| created_at | timestamp | 训练时间 |

**修改 `bot_trade_plans`：**

| 列 | 类型 | 说明 |
|----|------|------|
| confidence | float | 0-100 置信度分数 |

保留 `signal_grade` 和 `signal_win_rate`（向后兼容），但前端改为展示 confidence。

### 前端展示

交易计划列表：
- 每条计划显示 `confidence` 分数（0-100）
- 按 confidence 降序排序
- 颜色编码：≥60 绿色，40-60 灰色，<40 红色（纯视觉辅助，用户自定阈值）

### 与现有系统的关系

| 组件 | 动作 |
|------|------|
| Alpha 信号生成 | 保留不变 — 作为 confidence 输入特征 |
| Gamma 评分 | 保留不变 — 作为 confidence 输入特征 |
| Beta XGBoost | 保留运行（收集数据）但不再影响排序 |
| signal_grader 红黄绿 | 被 confidence 替代 |
| combined_score | 不再用于排序，confidence 替代 |

### 文件结构

| 文件 | 动作 | 内容 |
|------|------|------|
| `api/services/confidence_scorer.py` | 新建 | 训练 + 预测 + 校准验证 |
| `api/models/confidence.py` | 新建 | ConfidenceModel ORM |
| `api/services/beta_scorer.py` | 修改 | 调用 confidence_scorer 为 plan 打分 |
| `api/services/signal_scheduler.py` | 修改 | do_refresh 中触发重训练 |
| `api/routers/beta.py` | 修改 | 添加 confidence API 端点 |
| `api/schemas/bot_trading.py` | 修改 | BotTradePlanItem 加 confidence 字段 |
| `api/models/bot_trading.py` | 修改 | BotTradePlan 加 confidence 列 |
| `web/src/types/index.ts` | 修改 | 加 confidence 字段 |
| `web/src/app/ai/page.tsx` | 修改 | 展示 confidence，按此排序 |
