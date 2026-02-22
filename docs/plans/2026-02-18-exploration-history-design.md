# AI Lab 探索历史 Tab 设计

## 目标

在 AI 实验室页面新增"探索历史"标签页，记录每次执行 `/explore-strategies` 的完整过程和结论。探索历史通过 API 写入数据库，支持查询、分页和详情查看。

## 架构

explore-strategies skill 每轮结束时 curl 调用 `POST /api/lab/exploration-rounds` 写入摘要。前端 Lab 页面新增第 4 个 tab 展示时间轴式列表，支持展开查看完整报告。

## 数据模型

### `exploration_rounds` 表

```python
class ExplorationRound(Base):
    __tablename__ = "exploration_rounds"
    id: Mapped[int] = mapped_column(primary_key=True)
    round_number: Mapped[int] = mapped_column(Integer, index=True)
    mode: Mapped[str] = mapped_column(String(20), default="semi-auto")  # auto / semi-auto
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime] = mapped_column(DateTime)
    experiment_ids: Mapped[dict] = mapped_column(JSON, default=list)     # [177, 178, 179]
    total_experiments: Mapped[int] = mapped_column(Integer, default=0)
    total_strategies: Mapped[int] = mapped_column(Integer, default=0)
    profitable_count: Mapped[int] = mapped_column(Integer, default=0)
    profitability_pct: Mapped[float] = mapped_column(Float, default=0.0)
    std_a_count: Mapped[int] = mapped_column(Integer, default=0)
    best_strategy_name: Mapped[str] = mapped_column(String(200), default="")
    best_strategy_score: Mapped[float] = mapped_column(Float, default=0.0)
    best_strategy_return: Mapped[float] = mapped_column(Float, default=0.0)
    best_strategy_dd: Mapped[float] = mapped_column(Float, default=0.0)
    insights: Mapped[dict] = mapped_column(JSON, default=list)           # ["TP14是最优", ...]
    promoted: Mapped[dict] = mapped_column(JSON, default=list)           # [{id, name, label, score}]
    issues_resolved: Mapped[dict] = mapped_column(JSON, default=list)    # ["修复了xxx"]
    next_suggestions: Mapped[dict] = mapped_column(JSON, default=list)   # ["建议探索xxx"]
    summary: Mapped[str] = mapped_column(Text, default="")               # 完整 Markdown 摘要
    memory_synced: Mapped[bool] = mapped_column(Boolean, default=False)   # memory notes 更新成功
    pinecone_synced: Mapped[bool] = mapped_column(Boolean, default=False) # Pinecone 同步成功
```

## API 端点

### `GET /api/lab/exploration-rounds`

分页列表，按 finished_at 倒序。

参数: `page=1`, `size=20`

返回:
```json
{
  "items": [...],
  "total": 25,
  "page": 1,
  "size": 20
}
```

### `GET /api/lab/exploration-rounds/{id}`

单条详情，包含完整 summary。

### `POST /api/lab/exploration-rounds`

创建记录。Body = 全部字段的 JSON。

## 前端

### Tab 结构

Lab 页面 tabs 变为 4 个：

```
发起实验 | 实验历史 | 探索历史 | 模板管理
```

### 探索历史列表

时间轴式卡片列表，每张卡片显示：

```
┌─────────────────────────────────────────────────┐
│ R22 · auto · 2026-02-18 14:00 - 16:30          │
│                                                  │
│ 实验 10个 · 策略 42个 · 盈利 12 (28.6%)         │
│ StdA: 8个 · Promote: 3个                        │
│ 最佳: PSAR趋势动量_v2 — 0.815 / +88.3% / 11.2% │
│                                          ✓ synced│
└─────────────────────────────────────────────────┘
```

### 展开详情

点击卡片展开，显示完整 Markdown 摘要：
- 新洞察 (insights) — bullet list
- Auto-Promote 列表 — 策略名 + 标签 + 评分
- 问题修复 (issues_resolved)
- 下一步建议 (next_suggestions)
- 关联实验 ID — 可点击跳转到实验历史 tab

### 同步状态图标

| 状态 | 显示 |
|------|------|
| memory + pinecone 都成功 | 绿色 ✓ synced |
| memory 成功, pinecone 失败 | 黄色 ⚠ partial |
| 都失败 | 红色 ✗ not synced |

## Skill 改动

explore-strategies SKILL.md 新增 Step 9b:

在 Step 9 输出摘要之后，调用 API 保存记录：

```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST http://127.0.0.1:8050/api/lab/exploration-rounds \
  -H "Content-Type: application/json" \
  -d '{
    "round_number": 22,
    "mode": "auto",
    "started_at": "2026-02-18T14:00:00",
    "finished_at": "2026-02-18T16:30:00",
    "experiment_ids": [320, 321, 322],
    "total_experiments": 10,
    "total_strategies": 42,
    "profitable_count": 12,
    "profitability_pct": 28.6,
    "std_a_count": 8,
    "best_strategy_name": "PSAR趋势动量_v2",
    "best_strategy_score": 0.815,
    "best_strategy_return": 88.3,
    "best_strategy_dd": 11.2,
    "insights": ["TP14是最优止盈点", "SL7对全指标综合有效"],
    "promoted": [{"id": 1500, "name": "xxx", "label": "[AI]", "score": 0.82}],
    "issues_resolved": ["修复了信号爆炸检测"],
    "next_suggestions": ["探索PSAR+新指标组合"],
    "summary": "## 本轮探索结果\n\n...",
    "memory_synced": true,
    "pinecone_synced": true
  }'
```

## 关键文件

| 文件 | 操作 |
|------|------|
| `api/models/ai_lab.py` | 修改 — 添加 ExplorationRound model |
| `api/routers/ai_lab.py` | 修改 — 添加 3 个 exploration-rounds 端点 |
| `web/src/types/index.ts` | 修改 — 添加 ExplorationRound 类型 |
| `web/src/lib/api.ts` | 修改 — 添加 lab.explorationRounds API |
| `web/src/hooks/use-queries.ts` | 修改 — 添加 useExplorationRounds hook |
| `web/src/app/lab/page.tsx` | 修改 — 添加第 4 个 tab + 探索历史 UI |
| `.claude/skills/explore-strategies/SKILL.md` | 修改 — 添加 Step 9b |
