# 策略探索器设计 — `/explore-strategies` Skill

> 日期: 2026-02-14 | 状态: 已批准

## 目标

通过"实验→洞察→计划→再实验"循环，持续发现适合中国牛市/熊市/震荡市的高收益策略。半自动为主（Claude 分析+提方案，用户审批后执行），支持切换全自动模式。

## 方案

创建 Claude Code Skill `/explore-strategies`，无需新 UI 或后端服务。Skill 在对话中调用已有 API 完成实验创建、结果查询、策略 promote。记忆持久化到 `docs/lab-experiment-analysis.md`。

---

## 核心工作流

```
1. 加载记忆 (lab-experiment-analysis.md)
2. 查询 DB 最新实验数据 (GET /api/lab/experiments)
3. 分析 → 生成洞察
4. 制定实验计划 (1-3 个主题)
5. [半自动] 展示计划等审批 / [全自动] 跳过
6. POST /api/lab/experiments 创建实验 → 等待完成
7. 分析结果 → 更新记忆文件
8. Auto-promote 达标策略
9. [全自动] 回到步骤 2 / [半自动] 输出总结
```

模式切换: `/explore-strategies` = 半自动，`/explore-strategies auto` = 全自动。

---

## 探索优先级

### P1: 震荡市策略攻克

| 子主题 | 逻辑 |
|--------|------|
| KDJ 短周期+震荡专属参数 | KDJ(6,3,3)震荡市最佳，尝试更极端参数+更紧止损 |
| VWAP 均值回归 | VWAP 盈利率 30%（扩展指标最高），适合区间交易 |
| BOLL 收窄+KDJ | 布林带收窄=低波动，突破方向由 KDJ 确认 |
| CMF 资金流反转 | CMF 21% 盈利率，震荡市资金流方向变化有效 |

### P2: 指标组合拓展

| 子主题 | 逻辑 |
|--------|------|
| VWAP + KDJ | 两个最有效指标的组合，未测试 |
| BOLL_lower + MACD | BOLL_lower 最佳收益+59%，加 MACD 趋势确认 |
| CMF + KDJ 金叉 | 资金流确认+技术信号 |
| EMA(5,20) + ATR 止损 | KDJ+EMA 43% 盈利率最高，EMA 单独+动态止损未测 |

### P3: 策略组合（待解锁）

将已有盈利策略按信号投票/加权组合。需后端新增机制，后续实现。

### 主题选择规则

1. P1 优先于 P2 优先于 P3
2. 同优先级内选预期盈利率最高的
3. 某方向连续 2 轮盈利率 < 5% 则降级
4. 全部探索完毕后，盈利率 > 15% 的方向做参数微调

---

## Auto-Promote 规则

满足任一条件即 promote:

**标准 A — 高评分**:
- score >= 0.65
- 收益 > 10%
- 回撤 < 30%
- 交易数 >= 50

**标准 B — 市场阶段冠军**:
- 某市场阶段(牛/熊/震荡)盈亏为该轮最高
- 该阶段盈亏 > 0
- 总收益 > 0%

Promote 标签:
- 标准 A: `[AI] 策略名`
- 标准 B: `[AI-牛市]` / `[AI-熊市]` / `[AI-震荡]`

Promote 后 `enabled=False`，用户手动启用。

---

## 记忆文件管理

文件: `docs/lab-experiment-analysis.md`

### 结构

```markdown
# AI 策略实验室 — 实验结果分析
## 核心洞察 (持续更新)
## 探索状态 (跟踪进度表)
## 最新一轮实验 (详细数据)
## Auto-Promote 记录
## 历史统计摘要 (压缩旧数据)
## 已知问题与修复记录 (精简版)
```

### 清理规则

- 亏损策略只保留统计摘要，不列明细
- 超过 3 轮无新洞察的方向合并为一行
- 已修复问题压缩为一行记录
- 文件目标 < 500 行

---

## 技术实现

### Skill 文件

`.claude/skills/explore-strategies.md` — prompt 文件指导 Claude 执行探索流程。

### 使用的 API（全部已有）

| API | 用途 |
|-----|------|
| `GET /api/lab/experiments` | 查询实验列表 |
| `GET /api/lab/experiments/{id}` | 获取策略详情 |
| `POST /api/lab/experiments` | 创建实验 |
| `POST /api/lab/strategies/{id}/promote` | 推广策略 |
| `GET /api/lab/regimes` | 获取市场阶段 |

### 后端改动（极小）

promote 端点支持自定义标签前缀（当前固定 `[AI]`），改为接受可选 `label` 参数。一行代码改动。

### 全自动终止条件

- 所有方向已探索且无新方向
- 连续 2 轮零盈利策略
- 单次会话上限 5 轮
