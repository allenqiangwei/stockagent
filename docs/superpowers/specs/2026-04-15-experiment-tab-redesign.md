# 实验 Tab 重新设计 — 进度追踪 + 结果摘要

## 目标

重构量化工作台的"实验"Tab，提供三层信息：统计概览、进行中实验置顶、探索轮次历史。不增加数据存储，纯前端展示优化。

## 布局

### 顶部：统计卡片

```
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ 总实验    │ │ 进行中    │ │ 已promote │ │ 最新轮次  │
│  13,342  │ │    5     │ │   3,021  │ │  R1221   │
└──────────┘ └──────────┘ └──────────┘ └──────────┘
```

数据来源：
- 总实验 / 进行中：`GET /api/lab/experiments` 的 total + 按 status 筛选
- 已 promote：新增 API 或前端从 experiment detail 聚合
- 最新轮次：`GET /api/lab/exploration-rounds` 第一条

需要新增一个轻量 API：`GET /api/lab/stats`，返回：
```json
{
  "total_experiments": 13342,
  "in_progress": 5,
  "total_promoted": 3021,
  "latest_round": 1221
}
```

### 中间：进行中实验（始终置顶）

显示 status 为 `pending`/`generating`/`backtesting` 的实验，按 created_at 降序。

每条显示：
- 实验 ID + theme
- 状态 badge（generating / backtesting）
- 策略进度：已完成/总数（如 "3/8 策略已回测"）
- 开始时间
- 操作：重试卡住的（调用 `POST /api/lab/experiments/retry-pending`）

如果没有进行中实验，显示"当前无进行中实验"。

数据来源：`GET /api/lab/experiments?status=pending,generating,backtesting`（需要后端支持 status 筛选参数）

### 下方：探索轮次时间线

复用现有 `ExplorationRounds` 组件，但增强展开内容：

点击某轮展开后显示：
1. 轮次统计（已有）：实验数、策略数、StdA+ 数、promote 数
2. **实验列表**（新增）：该轮包含的实验，每个实验显示：
   - theme + status
   - 策略数 + 最佳 score
   - promote 了哪些策略（名称 + score）
3. 洞察/建议（已有）

数据来源：`exploration_rounds.experiment_ids` → 批量查 `GET /api/lab/experiments/{id}`

### 底部：发起实验

保留现有的"发起实验"按钮和 SSE 创建面板。

## API 变更

### 新增：`GET /api/lab/stats`

```python
@router.get("/stats")
def lab_stats(db: Session = Depends(get_db)):
    total = db.query(Experiment).count()
    in_progress = db.query(Experiment).filter(
        Experiment.status.in_(["pending", "generating", "backtesting"])
    ).count()
    promoted = db.query(ExperimentStrategy).filter(
        ExperimentStrategy.promoted == True
    ).count()
    latest = db.query(ExplorationRound).order_by(
        ExplorationRound.round_number.desc()
    ).first()
    return {
        "total_experiments": total,
        "in_progress": in_progress,
        "total_promoted": promoted,
        "latest_round": latest.round_number if latest else 0,
    }
```

### 修改：`GET /api/lab/experiments` 增加 status 筛选

```
GET /api/lab/experiments?status=backtesting,generating&page=1&size=20
```

后端 `status` 参数为可选的逗号分隔字符串。

## 前端文件变更

| 文件 | 变更 |
|------|------|
| `web/src/app/lab/page.tsx` | ExperimentsTab 重写为三段式布局 |
| `web/src/components/quant/experiment-list.tsx` | 可能简化，进行中列表独立 |
| `web/src/components/quant/exploration-rounds.tsx` | 展开区域增加实验列表 |
| `web/src/hooks/use-queries.ts` | 新增 useLabStats、修改 useLabExperiments 支持 status 筛选 |
| `web/src/lib/api.ts` | 新增 lab.stats()、修改 lab.experiments() |

## 不做的事

- 不存储额外的回测详情（equity_curve/trades）
- 不改动 explore-strategies 的数据管道
- 不改动策略池 Tab 和探索 Tab
