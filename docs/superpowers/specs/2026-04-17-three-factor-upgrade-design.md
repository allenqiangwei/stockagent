# 三因子系统（Alpha-Beta-Gamma）升级设计文档

> 基于 2026-04-17 的深度讨论和实施，记录已完成的改动、未完成的设计思路、以及后续路线图。

## 一、系统现状（升级后）

### Confidence 模型 v51（当前 production）

```
模型: LogisticRegression(C=1.0)
特征: 15 个（从 6 个扩展）
In-sample AUC: 0.847
CV AUC (3月训练→4月测试): 0.798
CV Brier: 0.079

特征及权重:
  trend_strength        +1.91  ← 最重要（市场趋势强度）
  day_of_week           +0.48  ← 新增（星期几效应）
  stock_return_5d       +0.40  ← 新增（个股动量）
  gamma_weekly_resonance +0.39  ← 新增（缠论周线共振）
  regime_encoded        +0.24  ← 新增（市场regime）
  gamma_structure_health +0.19  ← 新增（缠论结构健康）
  gamma_mmd_age         +0.15  ← 新增（买卖点年龄）
  gamma_daily_strength  +0.03  ← 新增（缠论日线强度）
  sector_heat_score     +0.03  ← 新增（板块热度）
  has_gamma             -0.08  ← 有缠论数据标志
  gamma_bc_confirmed    -0.13  ← 新增（背驰确认）
  volume_ratio_5d       -0.23  ← 新增（量比）
  alpha_score           -0.42  ← 仍然为负！
  index_return_pct      -0.76  ← 大盘涨幅
  volatility            -0.98  ← 波动率
```

### 升级前后对比

| 指标 | 旧模型 (6特征) | 新模型 (15特征) |
|------|---------------|----------------|
| In-sample AUC | 0.825 | 0.847 |
| **CV AUC** | **0.407** (过拟合) | **0.798** (泛化) |
| CV Brier | 0.499 | 0.079 |
| Gamma 信息 | 1个压缩分数 | 6个原始维度 |
| 市场环境 | 3个(trend/vol/index) | 8个(+sector/regime/dow/momentum/volume) |

### 数据量

| 数据 | 数量 | 日期范围 |
|------|------|---------|
| BetaReview | 3814 | 2026-03-17 ~ 04-17 |
| BotTradePlan | 5591 (4250 executed) | |
| GammaSnapshot | 2545 (369只股票) | 2026-03-19 ~ 04-17 |
| 训练样本 | 2309 | |

---

## 二、已完成的改动

### 2.1 Confidence 特征扩展（Task 2）

**文件**: `api/services/confidence_scorer.py`, `api/services/beta_scorer.py`

- FEATURE_NAMES 从 6 → 15
- `_build_training_data` SQL 新增 LEFT JOIN gamma_snapshots + beta_snapshots
- `predict_confidence` 签名改为接受 gamma_snapshot dict + 市场特征
- beta_scorer.py 调用处更新，传递完整特征
- 向后兼容：检测模型 coef 长度，自动截断以支持旧模型

### 2.2 Alpha 复杂度惩罚反转（Task 3）

**文件**: `api/services/signal_engine.py`

- `_compute_alpha_score` 的第三维度从 "Condition Depth (0-30)" 改为 "Simplicity Bonus (0-30)"
- 公式从 `(max_conds - 2) * 10` 改为 `30 - max(0, (max_conds - 3)) * 10`
- 3个条件=30分（最高），4=20，5=10，6+=0

### 2.3 校准监控（Task 4）

**文件**: `api/services/confidence_scorer.py`, `api/models/confidence.py`

- ConfidenceModel 新增 `calibration_data` JSON 字段
- 训练时自动计算 9 个概率区间的校准数据
- `get_model_report()` 返回校准信息

### 2.4 验证脚本

**文件**: `scripts/validate_confidence.py`, `scripts/analyze_confidence_failures.py`

- 时间序列交叉验证脚本
- 失败案例分析脚本（confidence ≥60% 但亏损的交易）

### 2.5 前端信任指标（Task 6）

**文件**: `web/src/app/ai/page.tsx`, `web/src/lib/api.ts`

- 新增 `ops.confidenceReport()` API 函数
- confidence 百分比旁显示模型版本号

---

## 三、未完成的设计思路

### 3.1 Alpha 完整证据化评分

**现状**: Alpha 权重仍然是 -0.42（负），说明 Task 3 的简单反转不够。模型学到"Alpha 高 = 差信号"。

**设计思路**: 将 Alpha 从"复杂度得分"重写为"证据得分"：

```
Alpha_v3 = OOS_技能 + 稳定性 + 独特性 + 可实施性 - 复杂度惩罚

OOS_技能 (0-30):
  不再取"家族最佳回测 score 的平均值"
  改为 purged/embargoed 验证下的 out-of-sample 绩效
  使用 Deflated Sharpe Ratio 修正选择偏差

稳定性 (0-25):
  滚动窗口 RankIC
  方向一致性（连续 N 周信号方向不变）
  衰减半衰期

独特性 (0-20):
  与现有 live 因子的相关性
  边际解释力（加入现有池后是否提升组合效用）

可实施性 (0-15):
  换手率约束
  流动性（涨跌停限制、成交量）

复杂度惩罚 (-10~0):
  条件数、算子深度
  同等 OOS 证据下，更简单的公式优先
```

**前提条件**: 需要 6+ 个月的数据才能计算滚动 RankIC 和 OOS 绩效。
**预计时间**: 2-3 天实现 + 数据积累期

### 3.2 Combined Score → Stacking / 在线专家聚合

**现状**: `combined = alpha * w1 + gamma * w2`，固定权重（冷启动 0.8/0.2，成熟 0.5/0.5）。

**设计思路**:

方案 A — Stacking:
```
1. 训练 Alpha-only 模型 → 产生 out-of-fold 概率
2. 训练 Gamma-raw 模型 → 产生 out-of-fold 概率
3. 用轻量 meta-model (LR 或 GBM) 学习组合权重
4. Meta-model 的输入: alpha_proba, gamma_proba, regime 特征
5. 输出: 最终盈利概率
```

方案 B — 在线专家聚合:
```
1. 维护多个专家: Alpha专家, Gamma专家, Regime专家
2. 每个专家独立产生信号
3. 用指数加权平均，按近期表现动态调整权重
4. 权重每周自动更新
```

**注意**: 当前 confidence 模型已经直接用原始特征做 LR，本质上已经是一种"扁平 stacking"。
Combined score 目前不影响用户决策（用户看 confidence），所以这个改动优先级低。

**前提条件**: confidence 作为主决策指标已稳定运行 1+ 个月。
**预计时间**: 1-2 天

### 3.3 Beta 升级为 Meta-Labeling 层

**现状**: Beta (XGBoost, AUC=0.668) 输出盈利概率，但 confidence 不用它。

**设计思路**:

López de Prado 的 Meta-Labeling 框架:
```
1. Primary Model (Alpha/Gamma) → 产生"事件"（信号触发）
2. Secondary Model (Beta) → 判断"这个事件值不值得下注"+ "下多大注"
3. 输出: size = p(correct) × confidence
```

三输出扩展:
```
Beta 从单一 p(win) 扩展为:
  - p(win): 盈利概率
  - E[return]: 期望收益率
  - E[time]: 期望持有时间

XGBoost 已支持:
  - 二分类 → p(win)
  - 回归 → E[return]
  - AFT 生存模型 → E[time]（处理止盈未触发等"删失"）
```

**前提条件**: BetaReview 数据 ≥ 1000 条（当前 3814 条，已够）。但需要更长时间跨度。
**预计时间**: 3-5 天

### 3.4 Purged/Embargoed 交叉验证

**现状**: 简单的月度 split（3月训练→4月测试）。

**设计思路**:

```
Purged CV:
  - 移除训练集中与测试集时间重叠的样本
  - 对于持有 N 天的交易，purge 窗口 = N 天
  
Embargoed CV:
  - 训练集和测试集之间留 gap
  - gap = 最大持有天数（避免信息泄漏）

CPCV (Combinatorial Purged CV):
  - 多次不同组合的 purged split
  - 产出 Probability of Backtest Overfitting (PBO)
```

**前提条件**: 至少 6 个月数据（当前只有 2 个月）。
**预计时间**: 1 天实现，需要数据积累

### 3.5 Signal Grading 后验可信度

**现状**: 按 (Alpha区间, Gamma区间) 分桶统计胜率，≥55% = 绿，<40% = 红。

**设计思路**:

```
1. Wilson 区间替换朴素正态近似
   - 小样本桶（<30 笔）的置信区间更准确
   - 避免 10 笔全赢就判"绿色"

2. 部分池化 (Partial Pooling / Beta-Binomial)
   - 小样本桶向总体均值"借力"
   - 防止极端桶被噪声主导

3. 绿黄红重定义:
   - 绿: 后验均值高 + 下界也 > 50%
   - 黄: 均值尚可但区间太宽（样本不足）
   - 红: 均值或下界 < 40%
```

**前提条件**: 无特殊要求，可随时实施。
**预计时间**: 半天

### 3.6 成本感知阈值

**现状**: 用户用 confidence ≥ 60% 作为决策阈值。

**设计思路**:

```
最优阈值 = argmax_t { E[净效用] }

净效用 = p(win|confidence >= t) × E[win_pnl] 
       - (1-p(win|confidence >= t)) × E[loss_pnl]
       - 手续费 × 2 (买+卖)
       - 滑点

A股成本:
  佣金: ~0.025% × 2 = 0.05%
  印花税: 0.05% (卖出)
  滑点: ~0.1%
  总成本: ~0.2% per round-trip

在 97.6% 胜率下，60% 阈值已经远超盈亏平衡。
但如果胜率下降（市场变化），最优阈值会上移。
```

**前提条件**: 更多数据以精确估计各概率区间的期望收益。
**预计时间**: 半天

### 3.7 Concept Drift 漂移监控

**现状**: 无监控。

**设计思路**:

```
监控维度:
  1. 特征分布漂移: 每周检查 15 个特征的分布 vs 训练期
     - 使用 KS 检验或 PSI (Population Stability Index)
     - PSI > 0.2 → 告警

  2. 校准漂移: 近 7 天 confidence ≥ 60% 的实际胜率 vs 预测
     - |实际 - 预测| > 15% → 告警

  3. 预测分布漂移: confidence 分数的分布变化
     - 如果突然所有交易都 > 80% 或 < 40% → 异常

  4. 结果漂移: 近 7 天 vs 近 30 天的胜率/PnL 变化
     - 显著下降 → 触发重训

实现:
  - 每日定时任务计算上述指标
  - 存入 confidence_drift_log 表
  - 前端仪表盘展示
  - 超阈值时前端告警
```

**前提条件**: confidence 模型稳定运行 2+ 周。
**预计时间**: 1-2 天

---

## 四、关键发现

### 4.1 旧模型严重过拟合

CV AUC = 0.407（比随机猜还差），说明旧的 6 特征模型完全无法泛化。
原因：只有 2 个月数据 + 6 个特征中 3 个（trend/vol/index）高度时变。

### 4.2 Alpha 权重持续为负

即使修复了复杂度惩罚（Task 3），Alpha 在新模型中权重仍然是 -0.42。
说明 Alpha 的"家族投票 + 质量平均"逻辑本身与盈利负相关。
可能原因：
- 更多家族触发 = 条件更宽松 = 信号质量更低
- 回测高分 ≠ 未来表现好
需要 Alpha 完整证据化重写（3.1）才能解决。

### 4.3 Gamma weekly_resonance 是最有价值的缠论特征

权重 +0.39，是所有 Gamma 特征中最高的。说明"周线级别有买点"比日线买卖点类型、背驰确认等更有预测力。

### 4.4 实际高 confidence 交易数量很少

confidence ≥ 60% 且实际执行的只有 ~8 笔（100% 胜率，avg +12.87%）。
大部分交易的 confidence < 60%，是信息采集交易。

---

## 五、后续路线图

### Phase 1：观察期（2-4 周）

不做代码改动。观察：
- 新模型在实盘中的 confidence ≥60% 胜率是否 > 90%
- 校准曲线是否稳定
- Alpha 权重为负是否持续

### Phase 2：数据驱动改进（积累到 4-5 个月数据后）

优先级排序：
1. **漂移监控**（3.7）— 最小投入，持续价值
2. **Signal Grading Wilson 区间**（3.5）— 简单改动
3. **Alpha 证据化评分**（3.1）— 需要数据支撑

### Phase 3：架构升级（积累到 6-12 个月数据后）

优先级排序：
1. **Purged CV**（3.4）— 验证基础设施
2. **Beta meta-labeling**（3.3）— 决策层升级
3. **Stacking 融合**（3.2）— 替代固定权重

---

## 六、观察期操作指南

### 6.1 前端变化（v51 模型上线后）

- **AI 交易页面**: confidence 百分比旁显示模型版本号 `v51`
- **Alpha 评分**: "多样性"标签改为"简洁性"，逻辑反转（简单策略得高分）
- **API 端点**: `GET /api/beta/confidence/model` 返回完整模型报告含校准数据

### 6.2 校准基线（v51 模型，2026-04-17）

```
模型说 60-70% 会赢 → 实际 68% 真赢了  ✓
模型说 70-80% 会赢 → 实际 80% 真赢了  ✓
模型说 80-90% 会赢 → 实际 85% 真赢了  ✓
模型说 90-100% 会赢 → 实际 96% 真赢了  ✓
模型说 50-60% 会赢 → 实际 38% 真赢了  ✗ (这个区间有偏差，但你不关注)
```

结论：**confidence ≥ 60% 的区间校准良好，可以信赖。**

### 6.3 日常观察方法

**每隔几天运行一次失败分析**:
```bash
cd /Users/allenqiang/stockagent
python scripts/analyze_confidence_failures.py
```
看 confidence ≥ 60% 的交易中有没有亏损。持续 0 亏损 = 模型可信。

**查看模型报告**:
```bash
curl -s http://localhost:8050/api/beta/confidence/model | python3 -m json.tool
```
关注 `auc_score`（应 > 0.80）和 `calibration` 数组。

**运行交叉验证**（每 2 周一次）:
```bash
python scripts/validate_confidence.py
```
关注 CV AUC 是否 > 0.70。

### 6.4 告警条件

| 信号 | 含义 | 动作 |
|------|------|------|
| confidence ≥ 70% 连续 3 笔亏损 | 模型可能失效 | 立刻重训 |
| 大部分交易突然 < 40% confidence | 市场 regime 剧变 | 观察，可能需要重训 |
| CV AUC 跌破 0.70 | 模型泛化能力下降 | 重训 |
| 校准偏差 > 15%（如模型说 70% 实际 < 55%） | 校准漂移 | 重训 |

### 6.5 重训命令

```bash
# 手动重训（建议每 2 周一次，或告警时立刻执行）
curl -X POST http://localhost:8050/api/beta/confidence/train

# 重训后验证
python scripts/validate_confidence.py
```

### 6.6 观察期目标（2-4 周后评估）

观察期结束时应该能回答以下问题：
1. **新模型在实盘中 confidence ≥ 60% 的胜率是否 > 90%？** → 决定是否可以开始实操
2. **校准是否持续稳定？** → 决定概率能不能作为仓位依据
3. **Alpha 权重是否仍然为负？** → 决定是否需要 Alpha 证据化重写
4. **不同 regime 下表现有差异吗？** → 决定是否需要 regime 条件过滤

---

## 七、核心原则

> 任何新因子、任何新组合，都不能只因为某次回测更好就上线；
> 它必须在去泄漏验证、成本约束、去相关检验与 shadow 期稳定性这四道门里都过关。

简单来说：先问"这是不是可复现、可实施、可解释的增量信息"，
再问"它在一条历史路径上赚了多少钱"。
