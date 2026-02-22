# AI Lab 探索历史功能 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 AI 实验室页面新增"探索历史"标签页，记录每次 `/explore-strategies` 的完整过程和结论，支持查询、分页和详情查看。

**Architecture:** explore-strategies skill 每轮结束时 curl 调用 `POST /api/lab/exploration-rounds` 写入摘要。FastAPI 后端新增 ExplorationRound model + 3 个端点。Next.js 前端 Lab 页面新增第 4 个 tab 展示时间轴式卡片列表。

**Tech Stack:** FastAPI + SQLAlchemy (backend), Next.js 16 + React Query + shadcn/ui (frontend)

**Design Doc:** `docs/plans/2026-02-18-exploration-history-design.md`

---

### Task 1: Backend — ExplorationRound Model

**Files:**
- Modify: `api/models/ai_lab.py` (append after line 79)

**Step 1: Add ExplorationRound model**

在 `api/models/ai_lab.py` 文件末尾添加:

```python
class ExplorationRound(Base):
    __tablename__ = "exploration_rounds"

    id: Mapped[int] = mapped_column(primary_key=True)
    round_number: Mapped[int] = mapped_column(Integer, index=True)
    mode: Mapped[str] = mapped_column(String(20), default="semi-auto")
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime] = mapped_column(DateTime)
    experiment_ids: Mapped[dict] = mapped_column(JSON, default=list)
    total_experiments: Mapped[int] = mapped_column(Integer, default=0)
    total_strategies: Mapped[int] = mapped_column(Integer, default=0)
    profitable_count: Mapped[int] = mapped_column(Integer, default=0)
    profitability_pct: Mapped[float] = mapped_column(Float, default=0.0)
    std_a_count: Mapped[int] = mapped_column(Integer, default=0)
    best_strategy_name: Mapped[str] = mapped_column(String(200), default="")
    best_strategy_score: Mapped[float] = mapped_column(Float, default=0.0)
    best_strategy_return: Mapped[float] = mapped_column(Float, default=0.0)
    best_strategy_dd: Mapped[float] = mapped_column(Float, default=0.0)
    insights: Mapped[dict] = mapped_column(JSON, default=list)
    promoted: Mapped[dict] = mapped_column(JSON, default=list)
    issues_resolved: Mapped[dict] = mapped_column(JSON, default=list)
    next_suggestions: Mapped[dict] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    memory_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    pinecone_synced: Mapped[bool] = mapped_column(Boolean, default=False)
```

**Step 2: Update router import**

在 `api/routers/ai_lab.py` 第 11 行，更新 import:

```python
from api.models.ai_lab import StrategyTemplate, Experiment, ExperimentStrategy, ExplorationRound
```

**Step 3: Verify — restart FastAPI, table auto-created**

```bash
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/lab/templates | head -c 100
```

Expected: 200 OK (表 auto-create 由 Base.metadata.create_all 处理)

**Step 4: Commit**

```bash
git add api/models/ai_lab.py api/routers/ai_lab.py
git commit -m "feat(lab): add ExplorationRound model for exploration history"
```

---

### Task 2: Backend — Pydantic Schemas + 3 API Endpoints

**Files:**
- Modify: `api/schemas/ai_lab.py` (append after line 116)
- Modify: `api/routers/ai_lab.py` (append new section)

**Step 1: Add Pydantic schemas**

在 `api/schemas/ai_lab.py` 末尾添加:

```python
from typing import Optional
from datetime import datetime as dt


# ── Exploration Rounds ───────────────────────────

class ExplorationRoundCreate(BaseModel):
    round_number: int
    mode: str = "semi-auto"
    started_at: str  # ISO datetime string
    finished_at: str
    experiment_ids: list[int] = []
    total_experiments: int = 0
    total_strategies: int = 0
    profitable_count: int = 0
    profitability_pct: float = 0.0
    std_a_count: int = 0
    best_strategy_name: str = ""
    best_strategy_score: float = 0.0
    best_strategy_return: float = 0.0
    best_strategy_dd: float = 0.0
    insights: list[str] = []
    promoted: list[dict] = []
    issues_resolved: list[str] = []
    next_suggestions: list[str] = []
    summary: str = ""
    memory_synced: bool = False
    pinecone_synced: bool = False


class ExplorationRoundResponse(BaseModel):
    id: int
    round_number: int
    mode: str
    started_at: str
    finished_at: str
    experiment_ids: list[int]
    total_experiments: int
    total_strategies: int
    profitable_count: int
    profitability_pct: float
    std_a_count: int
    best_strategy_name: str
    best_strategy_score: float
    best_strategy_return: float
    best_strategy_dd: float
    insights: list[str]
    promoted: list[dict]
    issues_resolved: list[str]
    next_suggestions: list[str]
    summary: str
    memory_synced: bool
    pinecone_synced: bool

    model_config = {"from_attributes": True}
```

**Step 2: Update router schema imports**

在 `api/routers/ai_lab.py` 的 import 块中，添加新 schemas:

```python
from api.schemas.ai_lab import (
    TemplateCreate, TemplateUpdate, TemplateResponse,
    ExperimentCreate, ExperimentResponse, ExperimentListItem,
    CloneBacktestRequest, ComboExperimentCreate,
    ExplorationRoundCreate, ExplorationRoundResponse,
)
```

**Step 3: Add 3 API endpoints**

在 `api/routers/ai_lab.py` 末尾添加:

```python
# ── Exploration Rounds ────────────────────────────

@router.get("/exploration-rounds")
def list_exploration_rounds(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    total = db.query(ExplorationRound).count()
    items = (
        db.query(ExplorationRound)
        .order_by(ExplorationRound.finished_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return {
        "items": [ExplorationRoundResponse.model_validate(r) for r in items],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/exploration-rounds/{round_id}", response_model=ExplorationRoundResponse)
def get_exploration_round(round_id: int, db: Session = Depends(get_db)):
    row = db.query(ExplorationRound).filter(ExplorationRound.id == round_id).first()
    if not row:
        raise HTTPException(404, "Exploration round not found")
    return row


@router.post("/exploration-rounds", response_model=ExplorationRoundResponse)
def create_exploration_round(data: ExplorationRoundCreate, db: Session = Depends(get_db)):
    from datetime import datetime as dt
    row = ExplorationRound(
        round_number=data.round_number,
        mode=data.mode,
        started_at=dt.fromisoformat(data.started_at),
        finished_at=dt.fromisoformat(data.finished_at),
        experiment_ids=data.experiment_ids,
        total_experiments=data.total_experiments,
        total_strategies=data.total_strategies,
        profitable_count=data.profitable_count,
        profitability_pct=data.profitability_pct,
        std_a_count=data.std_a_count,
        best_strategy_name=data.best_strategy_name,
        best_strategy_score=data.best_strategy_score,
        best_strategy_return=data.best_strategy_return,
        best_strategy_dd=data.best_strategy_dd,
        insights=data.insights,
        promoted=data.promoted,
        issues_resolved=data.issues_resolved,
        next_suggestions=data.next_suggestions,
        summary=data.summary,
        memory_synced=data.memory_synced,
        pinecone_synced=data.pinecone_synced,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
```

**Step 4: Verify — test POST + GET**

```bash
# Create a test record
NO_PROXY=localhost,127.0.0.1 curl -s -X POST http://127.0.0.1:8050/api/lab/exploration-rounds \
  -H "Content-Type: application/json" \
  -d '{"round_number":1,"mode":"auto","started_at":"2026-02-18T14:00:00","finished_at":"2026-02-18T16:30:00","total_experiments":3,"total_strategies":15,"profitable_count":5,"profitability_pct":33.3,"std_a_count":2,"best_strategy_name":"Test_v1","best_strategy_score":0.8,"best_strategy_return":50.0,"best_strategy_dd":10.0,"insights":["test insight"],"summary":"## Test round"}'

# List
NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/lab/exploration-rounds | python3 -m json.tool | head -20
```

Expected: POST returns 200 with created record; GET returns `{ items: [...], total: 1, page: 1, size: 20 }`

**Step 5: Commit**

```bash
git add api/schemas/ai_lab.py api/routers/ai_lab.py
git commit -m "feat(lab): add exploration-rounds API endpoints (GET list, GET detail, POST create)"
```

---

### Task 3: Frontend — TypeScript Types + API Client + React Query Hooks

**Files:**
- Modify: `web/src/types/index.ts` (append after line 415, after `LabExperimentListItem`)
- Modify: `web/src/lib/api.ts` (extend `lab` object, around line 198)
- Modify: `web/src/hooks/use-queries.ts` (append after Lab section, around line 290)

**Step 1: Add ExplorationRound type**

在 `web/src/types/index.ts` 的 `LabExperimentListItem` 接口后添加:

```typescript
export interface ExplorationRound {
  id: number;
  round_number: number;
  mode: string;
  started_at: string;
  finished_at: string;
  experiment_ids: number[];
  total_experiments: number;
  total_strategies: number;
  profitable_count: number;
  profitability_pct: number;
  std_a_count: number;
  best_strategy_name: string;
  best_strategy_score: number;
  best_strategy_return: number;
  best_strategy_dd: number;
  insights: string[];
  promoted: { id: number; name: string; label: string; score: number }[];
  issues_resolved: string[];
  next_suggestions: string[];
  summary: string;
  memory_synced: boolean;
  pinecone_synced: boolean;
}
```

**Step 2: Add API functions**

在 `web/src/lib/api.ts` 中:

1. 在顶部 import 区域添加 `ExplorationRound` 到 import 列表
2. 在 `lab` 对象的 `promoteStrategy` 后，`};` 之前，添加:

```typescript
  explorationRounds: (page = 1, size = 20) =>
    request<{ items: ExplorationRound[]; total: number; page: number; size: number }>(
      `/lab/exploration-rounds?page=${page}&size=${size}`
    ),
  explorationRound: (id: number) =>
    request<ExplorationRound>(`/lab/exploration-rounds/${id}`),
```

**Step 3: Add React Query hook**

在 `web/src/hooks/use-queries.ts` 的 Lab section 末尾添加:

```typescript
export function useExplorationRounds(page = 1, size = 20) {
  return useQuery({
    queryKey: ["lab", "exploration-rounds", page, size],
    queryFn: () => lab.explorationRounds(page, size),
  });
}
```

确保 `lab` 已在文件顶部 import（已有: `import { lab } from "@/lib/api"`）。

**Step 4: Verify — TypeScript build**

```bash
cd web && npx tsc --noEmit 2>&1 | head -20
```

Expected: No errors (或只有已存在的 warnings)

**Step 5: Commit**

```bash
git add web/src/types/index.ts web/src/lib/api.ts web/src/hooks/use-queries.ts
git commit -m "feat(lab): add ExplorationRound type, API client, and React Query hook"
```

---

### Task 4: Frontend — 探索历史 Tab UI

**Files:**
- Modify: `web/src/app/lab/page.tsx`

**Step 1: Add imports and hook**

在 `web/src/app/lab/page.tsx` 顶部添加:

```typescript
import { useExplorationRounds } from "@/hooks/use-queries";
import type { ExplorationRound } from "@/types";
import { Clock, CheckCircle, AlertTriangle, XCircle, ChevronDown, ChevronUp } from "lucide-react";
```

注意: `ChevronDown` 和 `ChevronUp` 可能已被 import，不要重复。

**Step 2: Add ExplorationHistoryTab component**

在 page.tsx 的 `export default function LabPage()` 之前，添加组件:

```tsx
/* ── Exploration History Tab ───────────────────── */

function SyncBadge({ memory, pinecone }: { memory: boolean; pinecone: boolean }) {
  if (memory && pinecone) return <Badge variant="outline" className="text-green-600 border-green-300">✓ synced</Badge>;
  if (memory) return <Badge variant="outline" className="text-yellow-600 border-yellow-300">⚠ partial</Badge>;
  return <Badge variant="outline" className="text-red-600 border-red-300">✗ not synced</Badge>;
}

function ExplorationHistoryTab() {
  const [page, setPage] = useState(1);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const { data, isLoading } = useExplorationRounds(page, 20);

  if (isLoading) {
    return <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin" /></div>;
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / 20);

  if (items.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        暂无探索记录。运行 /explore-strategies 后将自动记录。
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {items.map((r) => (
        <Card key={r.id} className="cursor-pointer hover:bg-accent/30 transition-colors"
              onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold">R{r.round_number}</span>
                <Badge variant="secondary" className="text-xs">{r.mode}</Badge>
                <span className="text-sm text-muted-foreground">
                  {r.started_at.slice(0, 16).replace("T", " ")} — {r.finished_at.slice(11, 16)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <SyncBadge memory={r.memory_synced} pinecone={r.pinecone_synced} />
                {expandedId === r.id ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </div>
            </div>
            <div className="flex gap-4 mt-2 text-sm">
              <span>实验 <b>{r.total_experiments}</b>个</span>
              <span>策略 <b>{r.total_strategies}</b>个</span>
              <span>盈利 <b>{r.profitable_count}</b> ({r.profitability_pct.toFixed(1)}%)</span>
              <span>StdA: <b>{r.std_a_count}</b>个</span>
              {r.promoted.length > 0 && <span>Promote: <b>{r.promoted.length}</b>个</span>}
            </div>
            {r.best_strategy_name && (
              <div className="mt-1 text-sm text-muted-foreground">
                最佳: {r.best_strategy_name} — {r.best_strategy_score.toFixed(3)} / +{r.best_strategy_return.toFixed(1)}% / {r.best_strategy_dd.toFixed(1)}%
              </div>
            )}

            {expandedId === r.id && (
              <div className="mt-4 space-y-3 border-t pt-3" onClick={(e) => e.stopPropagation()}>
                {r.insights.length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold mb-1">新洞察</h4>
                    <ul className="list-disc list-inside text-sm space-y-0.5">
                      {r.insights.map((s, i) => <li key={i}>{s}</li>)}
                    </ul>
                  </div>
                )}
                {r.promoted.length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold mb-1">Auto-Promote</h4>
                    <div className="flex flex-wrap gap-2">
                      {r.promoted.map((p, i) => (
                        <Badge key={i} variant="outline">
                          {p.name} {p.label} {p.score.toFixed(2)}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
                {r.issues_resolved.length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold mb-1">问题修复</h4>
                    <ul className="list-disc list-inside text-sm space-y-0.5">
                      {r.issues_resolved.map((s, i) => <li key={i}>{s}</li>)}
                    </ul>
                  </div>
                )}
                {r.next_suggestions.length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold mb-1">下一步建议</h4>
                    <ul className="list-disc list-inside text-sm space-y-0.5">
                      {r.next_suggestions.map((s, i) => <li key={i}>{s}</li>)}
                    </ul>
                  </div>
                )}
                {r.experiment_ids.length > 0 && (
                  <div className="text-sm text-muted-foreground">
                    关联实验: {r.experiment_ids.map((id) => `#${id}`).join(", ")}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      ))}

      {totalPages > 1 && (
        <div className="flex justify-center gap-2 pt-2">
          <Button variant="outline" size="sm" disabled={page <= 1}
                  onClick={() => setPage(page - 1)}>上一页</Button>
          <span className="text-sm leading-8">{page} / {totalPages}</span>
          <Button variant="outline" size="sm" disabled={page >= totalPages}
                  onClick={() => setPage(page + 1)}>下一页</Button>
        </div>
      )}
    </div>
  );
}
```

**Step 3: Add 4th tab to TabsList**

在 Lab page 的 `<TabsList>` 中，在 `模板管理` 之后添加:

```tsx
<TabsTrigger value="exploration">探索历史</TabsTrigger>
```

**Step 4: Add TabsContent**

在最后一个 `</TabsContent>` (templates tab) 之后添加:

```tsx
<TabsContent value="exploration">
  <ExplorationHistoryTab />
</TabsContent>
```

**Step 5: Verify — dev server**

```bash
cd web && npm run dev
# 浏览器打开 http://localhost:3000/lab，确认第 4 个 tab "探索历史" 存在
```

Expected: 4 个 tab 正常显示，探索历史 tab 显示 "暂无探索记录" 空状态

**Step 6: Commit**

```bash
git add web/src/app/lab/page.tsx
git commit -m "feat(lab): add exploration history tab with timeline card UI"
```

---

### Task 5: Skill — explore-strategies Step 9b

**Files:**
- Modify: `.claude/skills/explore-strategies/SKILL.md`

**Step 1: Add Step 9b**

在 SKILL.md 的 Step 9 (输出最终摘要) 之后，Step 10 之前，添加:

```markdown
### Step 9b — Save Exploration Round to API

在 Step 9 输出摘要之后，调用 API 保存本轮探索记录:

\```bash
NO_PROXY=localhost,127.0.0.1 curl -s -X POST http://127.0.0.1:8050/api/lab/exploration-rounds \
  -H "Content-Type: application/json" \
  -d '{
    "round_number": <本轮轮次>,
    "mode": "<auto|semi-auto>",
    "started_at": "<ISO datetime>",
    "finished_at": "<ISO datetime>",
    "experiment_ids": [<关联实验ID列表>],
    "total_experiments": <实验数>,
    "total_strategies": <策略总数>,
    "profitable_count": <盈利策略数>,
    "profitability_pct": <盈利比例>,
    "std_a_count": <StdA数量>,
    "best_strategy_name": "<最佳策略名>",
    "best_strategy_score": <最高分>,
    "best_strategy_return": <最高收益>,
    "best_strategy_dd": <最高分策略回撤>,
    "insights": ["<洞察1>", "<洞察2>"],
    "promoted": [{"id": <id>, "name": "<名>", "label": "<标签>", "score": <分>}],
    "issues_resolved": ["<修复1>"],
    "next_suggestions": ["<建议1>"],
    "summary": "<Step 9 的完整 Markdown 摘要，转义换行为\\n>",
    "memory_synced": <true|false>,
    "pinecone_synced": <true|false>
  }'
\```

字段说明:
- `memory_synced`: Step 8b 中 strategy-knowledge.md 更新 + sync-memory.py 是否成功
- `pinecone_synced`: Step 8b 中 sync-memory.py 的 Pinecone upsert 是否成功
- `summary`: 将 Step 9 输出的完整 Markdown 摘要放入，注意 JSON 转义
```

**Step 2: Verify — read skill file**

```bash
grep "Step 9b" .claude/skills/explore-strategies/SKILL.md
```

Expected: 找到 "Step 9b"

**Step 3: Commit**

```bash
git add .claude/skills/explore-strategies/SKILL.md
git commit -m "feat(skill): add Step 9b to explore-strategies for exploration round API recording"
```

---

## Execution Summary

| Task | Description | Files |
|------|------------|-------|
| 1 | ExplorationRound SQLAlchemy Model | `api/models/ai_lab.py`, `api/routers/ai_lab.py` |
| 2 | Pydantic Schemas + 3 API Endpoints | `api/schemas/ai_lab.py`, `api/routers/ai_lab.py` |
| 3 | TypeScript Types + API + Hooks | `web/src/types/index.ts`, `web/src/lib/api.ts`, `web/src/hooks/use-queries.ts` |
| 4 | 探索历史 Tab UI Component | `web/src/app/lab/page.tsx` |
| 5 | explore-strategies Skill Step 9b | `.claude/skills/explore-strategies/SKILL.md` |
