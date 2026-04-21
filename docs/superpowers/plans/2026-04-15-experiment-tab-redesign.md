# 实验 Tab 重新设计 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构实验 Tab 为三段式布局：统计卡片 + 进行中实验置顶 + 探索轮次时间线（含实验详情展开）

**Architecture:** 后端新增 `/api/lab/stats` 端点 + experiments 列表支持 status 筛选。前端重写 ExperimentsTab 组件，探索轮次展开时按 experiment_ids 批量加载实验详情。

**Tech Stack:** FastAPI, SQLAlchemy, React, TanStack Query, shadcn/ui

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `api/routers/ai_lab.py` | Modify | 新增 `/stats` 端点，`/experiments` 增加 status 筛选 |
| `web/src/lib/api.ts` | Modify | 新增 `lab.stats()`，修改 `lab.experiments()` 支持 status |
| `web/src/hooks/use-queries.ts` | Modify | 新增 `useLabStats`，修改 `useLabExperiments` |
| `web/src/app/lab/page.tsx` | Modify | 重写 `ExperimentsTab` 为三段式 |
| `web/src/components/quant/exploration-rounds.tsx` | Modify | 展开区域增加实验列表 |

---

### Task 1: 后端 — 新增 `/api/lab/stats` 端点

**Files:**
- Modify: `api/routers/ai_lab.py`

- [ ] **Step 1: 在 router 中添加 stats 端点**

在 `api/routers/ai_lab.py` 的 experiments 路由之前（约第 79 行），添加：

```python
@router.get("/stats")
def lab_stats(db: Session = Depends(get_db)):
    """Lightweight stats for experiment dashboard."""
    from sqlalchemy import func
    total = db.query(func.count(Experiment.id)).scalar() or 0
    in_progress = (
        db.query(func.count(Experiment.id))
        .filter(Experiment.status.in_(["pending", "generating", "backtesting"]))
        .scalar() or 0
    )
    promoted = (
        db.query(func.count(ExperimentStrategy.id))
        .filter(ExperimentStrategy.promoted == True)
        .scalar() or 0
    )
    latest = (
        db.query(ExplorationRound.round_number)
        .order_by(ExplorationRound.round_number.desc())
        .limit(1)
        .scalar() or 0
    )
    return {
        "total_experiments": total,
        "in_progress": in_progress,
        "total_promoted": promoted,
        "latest_round": latest,
    }
```

- [ ] **Step 2: 验证**

```bash
curl -s http://127.0.0.1:8050/api/lab/stats | python3 -m json.tool
```

Expected: `{"total_experiments": 13342, "in_progress": 5, "total_promoted": 3021, "latest_round": 1221}`

---

### Task 2: 后端 — experiments 列表支持 status 筛选

**Files:**
- Modify: `api/routers/ai_lab.py`

- [ ] **Step 1: 给 list_experiments 加 status 参数**

修改 `list_experiments` 函数签名和查询逻辑（约第 81-116 行）：

```python
@router.get("/experiments")
def list_experiments(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="Comma-separated status filter"),
    db: Session = Depends(get_db),
):
    q = db.query(Experiment)
    if status:
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if status_list:
            q = q.filter(Experiment.status.in_(status_list))
    total = q.count()
    rows = (
        q.order_by(Experiment.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    items = []
    for exp in rows:
        best = (
            db.query(ExperimentStrategy)
            .filter(
                ExperimentStrategy.experiment_id == exp.id,
                ExperimentStrategy.status == "done",
            )
            .order_by(ExperimentStrategy.score.desc())
            .first()
        )
        # Count done strategies for progress tracking
        done_count = (
            db.query(ExperimentStrategy)
            .filter(
                ExperimentStrategy.experiment_id == exp.id,
                ExperimentStrategy.status.in_(["done", "invalid", "failed"]),
            )
            .count()
        )
        items.append({
            "id": exp.id,
            "theme": exp.theme,
            "source_type": exp.source_type,
            "status": exp.status,
            "strategy_count": exp.strategy_count,
            "done_count": done_count,
            "best_score": best.score if best else 0.0,
            "best_name": best.name if best else "",
            "created_at": exp.created_at.strftime("%Y-%m-%d %H:%M") if exp.created_at else "",
        })
    return {"total": total, "items": items}
```

- [ ] **Step 2: 验证**

```bash
curl -s "http://127.0.0.1:8050/api/lab/experiments?status=backtesting,generating&size=5" | python3 -m json.tool
```

Expected: only experiments with status backtesting or generating, each item has `done_count` field.

- [ ] **Step 3: Commit**

```bash
git add api/routers/ai_lab.py
git commit -m "feat(lab): add /stats endpoint + status filter for experiments"
```

---

### Task 3: 前端 — API client 和 hooks

**Files:**
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/hooks/use-queries.ts`
- Modify: `web/src/types/index.ts`

- [ ] **Step 1: 更新 LabExperimentListItem 类型**

在 `web/src/types/index.ts` 中，找到 `LabExperimentListItem` 接口，添加 `done_count` 字段：

```typescript
export interface LabExperimentListItem {
  id: number;
  theme: string;
  source_type: string;
  status: string;
  strategy_count: number;
  done_count: number;  // ← 新增
  best_score: number;
  best_name: string;
  created_at: string;
}
```

- [ ] **Step 2: 添加 lab.stats() 到 API client**

在 `web/src/lib/api.ts` 的 `lab` 对象中，在 `experiments` 之前添加：

```typescript
  stats: () =>
    request<{ total_experiments: number; in_progress: number; total_promoted: number; latest_round: number }>(
      "/lab/stats"
    ),
```

- [ ] **Step 3: 修改 lab.experiments() 支持 status 参数**

```typescript
  experiments: (page = 1, size = 20, status?: string) =>
    request<{ total: number; items: LabExperimentListItem[] }>(
      `/lab/experiments?page=${page}&size=${size}${status ? `&status=${encodeURIComponent(status)}` : ""}`
    ),
```

- [ ] **Step 4: 添加 useLabStats hook**

在 `web/src/hooks/use-queries.ts` 中，lab 区域添加：

```typescript
export function useLabStats() {
  return useQuery({
    queryKey: ["lab", "stats"],
    queryFn: () => lab.stats(),
    staleTime: 30 * 1000,
  });
}
```

- [ ] **Step 5: 修改 useLabExperiments 支持 status**

```typescript
export function useLabExperiments(page = 1, size = 20, status?: string) {
  return useQuery({
    queryKey: ["lab", "experiments", page, size, status],
    queryFn: () => lab.experiments(page, size, status),
  });
}
```

- [ ] **Step 6: Commit**

```bash
git add web/src/types/index.ts web/src/lib/api.ts web/src/hooks/use-queries.ts
git commit -m "feat(lab): add stats hook + status filter for experiments"
```

---

### Task 4: 前端 — 重写 ExperimentsTab

**Files:**
- Modify: `web/src/app/lab/page.tsx`

- [ ] **Step 1: 更新 imports**

在 `web/src/app/lab/page.tsx` 顶部，修改 hooks import：

```typescript
import {
  useLabTemplates,
  useLabStats,
  useLabExperiments,
} from "@/hooks/use-queries";
```

添加 icon imports（如果没有）：

```typescript
import {
  FlaskConical,
  Play,
  Loader2,
  Plus,
  Trophy,
  Layers,
  Beaker,
  History,
  AlertCircle,
  BarChart3,
} from "lucide-react";
```

- [ ] **Step 2: 重写 ExperimentsTab 函数**

替换整个 `ExperimentsTab` 函数为：

```typescript
function ExperimentsTab() {
  const [showCreate, setShowCreate] = useState(false);
  const { data: stats } = useLabStats();
  const { data: inProgress } = useLabExperiments(1, 50, "pending,generating,backtesting");

  const inProgressItems = inProgress?.items ?? [];

  return (
    <div className="space-y-4">
      {/* Stats cards */}
      {stats && (
        <div className="flex flex-wrap gap-3">
          <LabStatCard label="总实验" value={stats.total_experiments.toLocaleString()} />
          <LabStatCard
            label="进行中"
            value={stats.in_progress}
            cls={stats.in_progress > 0 ? "text-amber-400" : undefined}
          />
          <LabStatCard label="已 Promote" value={stats.total_promoted.toLocaleString()} />
          <LabStatCard label="最新轮次" value={`R${stats.latest_round}`} />
        </div>
      )}

      {/* In-progress experiments (pinned) */}
      {inProgressItems.length > 0 && (
        <Card>
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              <AlertCircle className="h-4 w-4 text-amber-400" />
              进行中的实验 ({inProgressItems.length})
            </div>
            {inProgressItems.map((exp) => (
              <div
                key={exp.id}
                className="flex items-center justify-between py-2 px-3 rounded bg-muted/30 text-sm"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <Badge
                    className={`text-xs ${
                      exp.status === "generating"
                        ? "bg-blue-600 text-white"
                        : exp.status === "backtesting"
                        ? "bg-amber-600 text-white"
                        : "bg-zinc-600 text-zinc-300"
                    }`}
                  >
                    {exp.status === "generating"
                      ? "AI 生成中"
                      : exp.status === "backtesting"
                      ? "回测中"
                      : "等待中"}
                  </Badge>
                  <span className="truncate">{exp.theme}</span>
                </div>
                <div className="flex items-center gap-3 shrink-0 text-xs text-muted-foreground">
                  <span>
                    {exp.done_count}/{exp.strategy_count} 策略
                  </span>
                  <span>{exp.created_at}</span>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Create experiment */}
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">探索轮次</span>
        <Button size="sm" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? (
            "收起"
          ) : (
            <>
              <Plus className="h-4 w-4 mr-1" />
              发起实验
            </>
          )}
        </Button>
      </div>

      {showCreate && <NewExperimentPanel />}

      {/* Exploration rounds timeline */}
      <ExplorationRounds />
    </div>
  );
}

function LabStatCard({
  label,
  value,
  cls,
}: {
  label: string;
  value: string | number;
  cls?: string;
}) {
  return (
    <Card className="flex-1 min-w-[100px]">
      <CardContent className="p-3">
        <div className="text-[10px] text-muted-foreground">{label}</div>
        <div className={`text-lg font-bold font-mono ${cls || ""}`}>{value}</div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add web/src/app/lab/page.tsx
git commit -m "feat(lab): redesign ExperimentsTab with stats + in-progress pinning"
```

---

### Task 5: 前端 — 探索轮次展开增加实验列表

**Files:**
- Modify: `web/src/components/quant/exploration-rounds.tsx`

- [ ] **Step 1: 添加 imports**

在 `exploration-rounds.tsx` 顶部添加：

```typescript
import { useLabExperiment } from "@/hooks/use-queries";
import type { LabExperiment, LabExperimentStrategy } from "@/types";
```

- [ ] **Step 2: 创建 RoundExperimentList 组件**

在 `ExplorationRounds` 组件之前添加：

```typescript
function RoundExperimentList({ experimentIds }: { experimentIds: number[] }) {
  if (!experimentIds.length) {
    return <div className="text-xs text-muted-foreground">无关联实验</div>;
  }

  return (
    <div className="space-y-1.5">
      <h4 className="text-sm font-semibold">实验列表</h4>
      {experimentIds.map((eid) => (
        <RoundExperimentItem key={eid} experimentId={eid} />
      ))}
    </div>
  );
}

function RoundExperimentItem({ experimentId }: { experimentId: number }) {
  const { data, isLoading } = useLabExperiment(experimentId);

  if (isLoading) {
    return (
      <div className="text-xs text-muted-foreground py-1">
        #{experimentId} 加载中...
      </div>
    );
  }

  if (!data) {
    return (
      <div className="text-xs text-muted-foreground py-1">
        #{experimentId} 未找到
      </div>
    );
  }

  const promoted = data.strategies?.filter(
    (s: LabExperimentStrategy) => s.promoted
  ) ?? [];
  const bestStrategy = data.strategies
    ?.filter((s: LabExperimentStrategy) => s.status === "done")
    .sort((a: LabExperimentStrategy, b: LabExperimentStrategy) => b.score - a.score)[0];

  return (
    <div className="text-xs bg-muted/20 rounded px-3 py-2 space-y-1">
      <div className="flex items-center justify-between">
        <span className="font-medium truncate">
          #{data.id} {data.theme}
        </span>
        <span className="text-muted-foreground shrink-0 ml-2">
          {data.strategy_count} 策略
        </span>
      </div>
      {bestStrategy && (
        <div className="text-muted-foreground">
          最佳: {bestStrategy.name?.slice(0, 40)} (score={bestStrategy.score.toFixed(2)},
          ret={bestStrategy.total_return_pct.toFixed(1)}%)
        </div>
      )}
      {promoted.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {promoted.map((p: LabExperimentStrategy) => (
            <Badge
              key={p.id}
              className="text-[10px] bg-emerald-600/20 text-emerald-400 border-emerald-500/30"
            >
              ↑ {p.name?.slice(0, 30)} ({p.score.toFixed(2)})
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: 在展开区域中使用 RoundExperimentList**

在 `ExplorationRounds` 组件的展开详情区域中（`expandedId === r.id` 条件内），在现有的 insights 之前插入实验列表：

找到：
```typescript
              <div
                className="mt-4 space-y-3 border-t pt-3"
                onClick={(e) => e.stopPropagation()}
              >
                {r.insights.length > 0 && (
```

替换为：
```typescript
              <div
                className="mt-4 space-y-3 border-t pt-3"
                onClick={(e) => e.stopPropagation()}
              >
                {r.experiment_ids.length > 0 && (
                  <RoundExperimentList experimentIds={r.experiment_ids} />
                )}
                {r.insights.length > 0 && (
```

- [ ] **Step 4: 添加 Badge import**

确保文件顶部已有 Badge import。如果没有，添加：

```typescript
import { Badge } from "@/components/ui/badge";
```

- [ ] **Step 5: Commit**

```bash
git add web/src/components/quant/exploration-rounds.tsx
git commit -m "feat(lab): show experiment details inside exploration round expand"
```

---

### Task 6: 验证 + 最终提交

- [ ] **Step 1: TypeScript 编译检查**

```bash
cd web && npx tsc --noEmit 2>&1 | grep -E "lab/page|exploration-rounds|use-queries" | head -10
```

Expected: no errors.

- [ ] **Step 2: 功能验证**

1. 打开 http://localhost:3050/lab → 实验 Tab
2. 确认顶部有 4 个统计卡片
3. 确认进行中实验（如果有）置顶显示，带状态 badge 和进度
4. 确认探索轮次列表正常显示
5. 展开一个探索轮次，确认能看到实验列表和 promote 的策略

- [ ] **Step 3: 重启 API（如果修改了后端）**

```bash
kill $(pgrep -f "uvicorn.*8050") && sleep 2
NO_PROXY=localhost,127.0.0.1 nohup python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8050 > /tmp/uvicorn-stockagent.log 2>&1 &
```
