"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useLabTemplates,
  useLabExperiments,
  useLabExperiment,
  useCreateTemplate,
  useUpdateTemplate,
  useDeleteTemplate,
  useDeleteExperiment,
  usePromoteStrategy,
  useBacktestDetail,
  useExplorationRounds,
} from "@/hooks/use-queries";
import { lab as labApi } from "@/lib/api";
import type { LabTemplate, LabExperimentListItem, LabExperimentStrategy, ExplorationRound } from "@/types";
import { EquityCurveChart } from "@/components/charts/equity-curve-chart";
import {
  BrainCircuit,
  Play,
  Loader2,
  Plus,
  Pencil,
  Trash2,
  ArrowUpFromLine,
  Trophy,
  ChevronDown,
  ChevronUp,
  TrendingUp,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

// ── Status badge ────────────────────────────────
const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  pending: { label: "等待中", cls: "bg-zinc-600 text-zinc-300" },
  generating: { label: "AI 生成中", cls: "bg-blue-600 text-white" },
  backtesting: { label: "回测中", cls: "bg-amber-600 text-white" },
  done: { label: "已完成", cls: "bg-emerald-600 text-white" },
  invalid: { label: "无效", cls: "bg-orange-600 text-white" },
  failed: { label: "失败", cls: "bg-red-600 text-white" },
};

function statusBadge(status: string) {
  const s = STATUS_MAP[status] ?? STATUS_MAP.pending;
  return <Badge className={`text-xs ${s.cls}`}>{s.label}</Badge>;
}

// ── Template categories ─────────────────────────
const CATEGORIES = ["动量", "均线", "波动率", "量价", "组合"];

// ── SSE progress types ──────────────────────────
interface ExperimentProgress {
  running: boolean;
  phase: string;
  message: string;
  strategies: { id: number; name: string; status: string; score?: number }[];
  backtestIndex: number;
  backtestTotal: number;
  done: boolean;
  bestName: string;
  bestScore: number;
}

const INIT_PROGRESS: ExperimentProgress = {
  running: false,
  phase: "",
  message: "",
  strategies: [],
  backtestIndex: 0,
  backtestTotal: 0,
  done: false,
  bestName: "",
  bestScore: 0,
};

// ═══════════════════════════════════════════════════
// Main page
// ═══════════════════════════════════════════════════
export default function LabPage() {
  return (
    <div className="p-3 sm:p-4 space-y-3 sm:space-y-4">
      <div className="flex items-center gap-2 text-base sm:text-lg font-semibold">
        <BrainCircuit className="h-5 w-5" />
        AI 策略实验室
      </div>

      <Tabs defaultValue="new">
        <TabsList>
          <TabsTrigger value="new">发起实验</TabsTrigger>
          <TabsTrigger value="history">实验历史</TabsTrigger>
          <TabsTrigger value="exploration">探索历史</TabsTrigger>
          <TabsTrigger value="templates">模板管理</TabsTrigger>
        </TabsList>

        <TabsContent value="new">
          <NewExperimentTab />
        </TabsContent>
        <TabsContent value="history">
          <ExperimentHistoryTab />
        </TabsContent>
        <TabsContent value="exploration">
          <ExplorationHistoryTab />
        </TabsContent>
        <TabsContent value="templates">
          <TemplateManagerTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ═══════════════════════════════════════════════════
// Tab 1: 发起实验
// ═══════════════════════════════════════════════════
function NewExperimentTab() {
  const { data: templates } = useLabTemplates();
  const queryClient = useQueryClient();

  const [sourceType, setSourceType] = useState<"template" | "custom">("template");
  const [selectedTemplate, setSelectedTemplate] = useState<LabTemplate | null>(null);
  const [customText, setCustomText] = useState("");
  const [initialCapital, setInitialCapital] = useState(100000);
  const [maxPositions, setMaxPositions] = useState(10);
  const [maxPositionPct, setMaxPositionPct] = useState(30);
  const [progress, setProgress] = useState<ExperimentProgress>(INIT_PROGRESS);
  const abortRef = useRef<AbortController | null>(null);

  const canStart =
    !progress.running &&
    ((sourceType === "template" && selectedTemplate) ||
      (sourceType === "custom" && customText.trim().length > 10));

  const startExperiment = useCallback(async () => {
    if (!canStart) return;

    const theme =
      sourceType === "template"
        ? selectedTemplate!.name
        : customText.slice(0, 50);
    const sourceText =
      sourceType === "template"
        ? selectedTemplate!.description
        : customText;

    const abort = new AbortController();
    abortRef.current = abort;
    setProgress({ ...INIT_PROGRESS, running: true, phase: "starting" });

    try {
      const res = await labApi.createExperimentSSE({
        theme,
        source_type: sourceType,
        source_text: sourceText,
        initial_capital: initialCapital,
        max_positions: maxPositions,
        max_position_pct: maxPositionPct,
      });

      if (!res.ok || !res.body) {
        const text = await res.text().catch(() => "");
        console.error("Experiment SSE failed:", res.status, text);
        setProgress((p) => ({ ...p, running: false, phase: "error", message: text }));
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";

        for (const chunk of chunks) {
          const match = chunk.match(/^data:\s*(.+)/);
          if (!match) continue;
          try {
            const evt = JSON.parse(match[1]);
            handleSSE(evt, setProgress);
          } catch {
            // skip malformed
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        console.error("SSE error:", err);
      }
    } finally {
      setProgress((p) => ({ ...p, running: false }));
      abortRef.current = null;
      queryClient.invalidateQueries({ queryKey: ["lab", "experiments"] });
    }
  }, [canStart, sourceType, selectedTemplate, customText, queryClient]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  // Group templates by category
  const grouped = (templates ?? []).reduce<Record<string, LabTemplate[]>>((acc, t) => {
    (acc[t.category] ??= []).push(t);
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      {/* Source selector */}
      <Card>
        <CardContent className="p-4 space-y-4">
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium">策略来源:</span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant={sourceType === "template" ? "default" : "outline"}
                onClick={() => setSourceType("template")}
              >
                内置模板
              </Button>
              <Button
                size="sm"
                variant={sourceType === "custom" ? "default" : "outline"}
                onClick={() => setSourceType("custom")}
              >
                自定义描述
              </Button>
            </div>
          </div>

          {sourceType === "template" ? (
            <div className="space-y-3">
              {Object.entries(grouped).map(([cat, tpls]) => (
                <div key={cat}>
                  <div className="text-xs text-muted-foreground mb-1.5">{cat}</div>
                  <div className="flex flex-wrap gap-2">
                    {tpls.map((t) => (
                      <Button
                        key={t.id}
                        size="sm"
                        variant={selectedTemplate?.id === t.id ? "default" : "outline"}
                        className="text-xs"
                        onClick={() => setSelectedTemplate(t)}
                      >
                        {t.name}
                      </Button>
                    ))}
                  </div>
                </div>
              ))}
              {selectedTemplate && (
                <div className="text-sm text-muted-foreground bg-muted/30 rounded p-3">
                  {selectedTemplate.description}
                </div>
              )}
            </div>
          ) : (
            <Textarea
              placeholder="粘贴或描述你的策略思路（至少 10 个字符）..."
              value={customText}
              onChange={(e) => setCustomText(e.target.value)}
              className="min-h-[120px]"
            />
          )}

          {/* Portfolio config */}
          <div className="border-t border-border/50 pt-4 space-y-3">
            <span className="text-sm font-medium">回测参数</span>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
              <div className="space-y-1">
                <span className="text-xs text-muted-foreground">初始资金</span>
                <Input
                  type="number"
                  min={10000}
                  step={10000}
                  value={initialCapital}
                  onChange={(e) => setInitialCapital(Number(e.target.value) || 100000)}
                />
              </div>
              <div className="space-y-1">
                <span className="text-xs text-muted-foreground">最大持仓数</span>
                <Input
                  type="number"
                  min={1}
                  max={50}
                  value={maxPositions}
                  onChange={(e) => setMaxPositions(Number(e.target.value) || 10)}
                />
              </div>
              <div className="space-y-1">
                <span className="text-xs text-muted-foreground">单股最大占比 (%)</span>
                <Input
                  type="number"
                  min={5}
                  max={100}
                  value={maxPositionPct}
                  onChange={(e) => setMaxPositionPct(Number(e.target.value) || 30)}
                />
              </div>
            </div>
          </div>

          <Button onClick={startExperiment} disabled={!canStart}>
            {progress.running ? (
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
            ) : (
              <Play className="h-4 w-4 mr-2" />
            )}
            开始实验
          </Button>
        </CardContent>
      </Card>

      {/* Progress */}
      {(progress.running || progress.done) && (
        <ExperimentProgressCard progress={progress} />
      )}
    </div>
  );
}

// ── SSE event handler ───────────────────────────
function handleSSE(
  evt: Record<string, unknown>,
  setProgress: React.Dispatch<React.SetStateAction<ExperimentProgress>>,
) {
  const type = evt.type as string;

  switch (type) {
    case "generating":
      setProgress((p) => ({
        ...p,
        phase: "generating",
        message: evt.message as string,
      }));
      break;

    case "strategies_ready":
      setProgress((p) => ({
        ...p,
        phase: "strategies_ready",
        message: `AI 生成了 ${evt.count} 个策略变体`,
        strategies: (evt.strategies as { id: number; name: string; status: string }[]),
        backtestTotal: (evt.count as number),
      }));
      break;

    case "loading_data":
      setProgress((p) => ({
        ...p,
        phase: "loading_data",
        message: evt.message as string,
      }));
      break;

    case "data_loaded":
      setProgress((p) => ({
        ...p,
        phase: "data_loaded",
        message: `已加载 ${evt.stock_count} 只股票 (${evt.start_date} ~ ${evt.end_date})`,
      }));
      break;

    case "computing_regimes":
      setProgress((p) => ({
        ...p,
        phase: "computing_regimes",
        message: evt.message as string,
      }));
      break;

    case "regime_warning":
      setProgress((p) => ({
        ...p,
        message: evt.message as string,
      }));
      break;

    case "backtest_start":
      setProgress((p) => ({
        ...p,
        phase: "backtesting",
        backtestIndex: evt.index as number,
        backtestTotal: evt.total as number,
        message: `回测 ${evt.index}/${evt.total}: ${evt.name}`,
      }));
      break;

    case "backtest_done":
      setProgress((p) => ({
        ...p,
        backtestIndex: evt.index as number,
        strategies: p.strategies.map((s) =>
          s.name === evt.name
            ? { ...s, status: "done", score: evt.score as number }
            : s
        ),
        message: `${evt.name}: 收益 ${evt.total_return_pct}%, 回撤 ${evt.max_drawdown_pct}%, 评分 ${evt.score}`,
      }));
      break;

    case "backtest_skip":
      setProgress((p) => ({
        ...p,
        backtestIndex: evt.index as number,
        strategies: p.strategies.map((s) =>
          s.name === evt.name ? { ...s, status: "failed" } : s
        ),
      }));
      break;

    case "backtest_error":
      setProgress((p) => ({
        ...p,
        backtestIndex: evt.index as number,
        strategies: p.strategies.map((s) =>
          s.name === evt.name ? { ...s, status: "failed" } : s
        ),
        message: `${evt.name}: 回测失败 — ${evt.error}`,
      }));
      break;

    case "experiment_done":
      setProgress((p) => ({
        ...p,
        running: false,
        done: true,
        phase: "done",
        bestName: (evt.best_name as string) || "",
        bestScore: (evt.best_score as number) || 0,
        message: `实验完成！成功 ${evt.done_count} 个，失败 ${evt.failed_count} 个`,
      }));
      break;

    case "error":
      setProgress((p) => ({
        ...p,
        running: false,
        phase: "error",
        message: evt.message as string,
      }));
      break;
  }
}

// ── Progress card ───────────────────────────────
function ExperimentProgressCard({ progress }: { progress: ExperimentProgress }) {
  const pct =
    progress.backtestTotal > 0
      ? Math.round((progress.backtestIndex / progress.backtestTotal) * 100)
      : 0;

  return (
    <Card>
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-medium">
            {progress.running && <Loader2 className="h-4 w-4 animate-spin" />}
            {progress.done && <Trophy className="h-4 w-4 text-amber-500" />}
            {progress.phase === "error" ? "实验失败" : progress.done ? "实验完成" : "实验进行中"}
          </div>
          {progress.done && progress.bestName && (
            <span className="text-sm text-muted-foreground">
              最佳: {progress.bestName} (评分 {progress.bestScore})
            </span>
          )}
        </div>

        <div className="text-sm text-muted-foreground">{progress.message}</div>

        {progress.phase === "backtesting" && (
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>回测进度</span>
              <span>{progress.backtestIndex}/{progress.backtestTotal}</span>
            </div>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-primary transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}

        {progress.strategies.length > 0 && (
          <div className="space-y-1">
            {progress.strategies.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between text-xs py-1 px-2 rounded bg-muted/30"
              >
                <span>{s.name}</span>
                <div className="flex items-center gap-2">
                  {s.score != null && (
                    <span className="font-mono text-muted-foreground">
                      评分: {s.score}
                    </span>
                  )}
                  {statusBadge(s.status)}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ═══════════════════════════════════════════════════
// Tab 2: 实验历史
// ═══════════════════════════════════════════════════
function ExperimentHistoryTab() {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useLabExperiments(page);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const deleteExp = useDeleteExperiment();

  return (
    <div className="space-y-3">
      {isLoading ? (
        <div className="py-12 text-center text-sm text-muted-foreground">加载中...</div>
      ) : !data?.items?.length ? (
        <div className="py-12 text-center text-sm text-muted-foreground">
          暂无实验记录，去"发起实验"开始吧
        </div>
      ) : (
        <>
          <div className="space-y-2">
            {data.items.map((exp) => (
              <ExperimentRow
                key={exp.id}
                exp={exp}
                expanded={expandedId === exp.id}
                onToggle={() => setExpandedId(expandedId === exp.id ? null : exp.id)}
                onDelete={() => {
                  if (confirm("确定删除该实验及所有相关数据？")) {
                    deleteExp.mutate(exp.id, {
                      onSuccess: () => {
                        if (expandedId === exp.id) setExpandedId(null);
                      },
                      onError: (err) => {
                        alert(err instanceof Error ? err.message : "删除失败");
                      },
                    });
                  }
                }}
                deleting={deleteExp.isPending}
              />
            ))}
          </div>
          <div className="flex justify-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              上一页
            </Button>
            <span className="text-sm text-muted-foreground leading-8">
              第 {page} 页 · 共 {data.total} 条
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={(data.items.length ?? 0) < 20}
              onClick={() => setPage((p) => p + 1)}
            >
              下一页
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

function ExperimentRow({
  exp,
  expanded,
  onToggle,
  onDelete,
  deleting,
}: {
  exp: LabExperimentListItem;
  expanded: boolean;
  onToggle: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  return (
    <Card>
      <CardContent className="p-0">
        <div className="flex items-center">
          <button
            onClick={onToggle}
            className="flex-1 flex flex-col sm:flex-row sm:items-center sm:justify-between p-3 text-left hover:bg-muted/30 transition-colors min-w-0 gap-1 sm:gap-0"
          >
            <div className="flex items-center gap-2 sm:gap-3 min-w-0">
              {statusBadge(exp.status)}
              <span className="text-sm font-medium truncate">{exp.theme}</span>
              <span className="text-xs text-muted-foreground shrink-0">
                {exp.strategy_count} 个策略
              </span>
            </div>
            <div className="flex items-center gap-2 sm:gap-3 shrink-0 pl-0 sm:pl-2">
              {exp.best_name && (
                <span className="text-xs text-muted-foreground truncate max-w-[150px] sm:max-w-none">
                  最佳: {exp.best_name} ({exp.best_score.toFixed(2)})
                </span>
              )}
              <span className="text-xs text-muted-foreground shrink-0">{exp.created_at}</span>
              {expanded ? (
                <ChevronUp className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              )}
            </div>
          </button>
          {!["pending", "generating", "backtesting"].includes(exp.status) && (
            <Button
              variant="ghost"
              size="icon"
              className="shrink-0 mr-1 text-muted-foreground hover:text-destructive"
              disabled={deleting}
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
        {expanded && <ExperimentDetail experimentId={exp.id} />}
      </CardContent>
    </Card>
  );
}

function ExperimentDetail({ experimentId }: { experimentId: number }) {
  const { data, isLoading } = useLabExperiment(experimentId);
  const promote = usePromoteStrategy();

  if (isLoading) {
    return (
      <div className="p-4 text-sm text-muted-foreground">加载策略详情...</div>
    );
  }

  if (!data?.strategies?.length) {
    return (
      <div className="p-4 text-sm text-muted-foreground">无策略数据</div>
    );
  }

  return (
    <div className="border-t border-border overflow-x-auto">
      <Table className="min-w-[720px]">
        <TableHeader>
          <TableRow>
            <TableHead>排名</TableHead>
            <TableHead>策略名称</TableHead>
            <TableHead className="text-right">评分</TableHead>
            <TableHead className="text-right">总收益%</TableHead>
            <TableHead className="text-right">最大回撤%</TableHead>
            <TableHead className="text-right">胜率%</TableHead>
            <TableHead className="text-right">交易数</TableHead>
            <TableHead className="text-right">平均持仓天</TableHead>
            <TableHead>状态</TableHead>
            <TableHead className="text-right">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.strategies.map((s: LabExperimentStrategy, idx: number) => (
            <StrategyRow
              key={s.id}
              strategy={s}
              rank={idx + 1}
              onPromote={() => promote.mutate(s.id)}
              promoting={promote.isPending}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

const SELL_REASON_LABEL: Record<string, string> = {
  strategy_exit: "策略卖出",
  stop_loss: "止损",
  take_profit: "止盈",
  max_hold: "持有到期",
  end_of_backtest: "回测结束",
};

function StrategyRow({
  strategy: s,
  rank,
  onPromote,
  promoting,
}: {
  strategy: LabExperimentStrategy;
  rank: number;
  onPromote: () => void;
  promoting: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <TableRow
        className="cursor-pointer hover:bg-muted/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <TableCell>
          <div className="flex items-center gap-1">
            {rank <= 3 && <Trophy className={`h-3.5 w-3.5 ${rank === 1 ? "text-amber-500" : rank === 2 ? "text-zinc-400" : "text-amber-700"}`} />}
            <span className="text-sm">{rank}</span>
          </div>
        </TableCell>
        <TableCell>
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-medium">{s.name}</span>
            {s.promoted && (
              <Badge className="text-[10px] bg-emerald-600 text-white">已推广</Badge>
            )}
          </div>
        </TableCell>
        <TableCell className="text-right font-mono text-sm">
          {s.status === "done" ? s.score.toFixed(2) : "—"}
        </TableCell>
        <TableCell className={`text-right font-mono text-sm ${s.total_return_pct >= 0 ? "text-emerald-500" : "text-red-500"}`}>
          {s.status === "done" ? s.total_return_pct.toFixed(1) : "—"}
        </TableCell>
        <TableCell className="text-right font-mono text-sm text-red-400">
          {s.status === "done" ? s.max_drawdown_pct.toFixed(1) : "—"}
        </TableCell>
        <TableCell className="text-right font-mono text-sm">
          {s.status === "done" ? s.win_rate.toFixed(1) : "—"}
        </TableCell>
        <TableCell className="text-right font-mono text-sm">
          {s.status === "done" ? s.total_trades : "—"}
        </TableCell>
        <TableCell className="text-right font-mono text-sm">
          {s.status === "done" ? s.avg_hold_days.toFixed(1) : "—"}
        </TableCell>
        <TableCell>{statusBadge(s.status)}</TableCell>
        <TableCell className="text-right">
          <div className="flex items-center justify-end gap-1">
            {expanded ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
            {s.status === "done" && !s.promoted && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 w-7 p-0 text-emerald-500 hover:text-emerald-400"
                onClick={(e) => { e.stopPropagation(); onPromote(); }}
                disabled={promoting}
                title="推广到正式策略"
              >
                <ArrowUpFromLine className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </TableCell>
      </TableRow>
      {expanded && (
        <TableRow>
          <TableCell colSpan={10} className="p-0">
            <StrategyDetailPanel strategy={s} />
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

function StrategyDetailPanel({ strategy: s }: { strategy: LabExperimentStrategy }) {
  const { data: btDetail, isLoading } = useBacktestDetail(s.backtest_run_id ?? 0);
  const [showTrades, setShowTrades] = useState(false);

  return (
    <div className="bg-muted/10 border-t border-border p-4 space-y-4">
      {/* Description */}
      <div className="text-sm text-muted-foreground">{s.description}</div>
      {s.error_message && (
        <div className="text-red-400 text-xs">错误: {s.error_message}</div>
      )}

      {/* Metrics cards */}
      {s.status === "done" && (
        <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
          <MetricCard label="评分" value={s.score.toFixed(2)} />
          <MetricCard
            label="总收益"
            value={`${s.total_return_pct >= 0 ? "+" : ""}${s.total_return_pct.toFixed(1)}%`}
            cls={s.total_return_pct >= 0 ? "text-emerald-500" : "text-red-500"}
          />
          <MetricCard label="最大回撤" value={`${s.max_drawdown_pct.toFixed(1)}%`} cls="text-red-400" />
          <MetricCard label="胜率" value={`${s.win_rate.toFixed(1)}%`} />
          <MetricCard label="交易数" value={String(s.total_trades)} />
          <MetricCard label="平均持仓" value={`${s.avg_hold_days.toFixed(1)}天`} />
        </div>
      )}

      {/* Equity curve */}
      {s.backtest_run_id && (
        <div>
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载收益曲线...
            </div>
          ) : btDetail?.equity_curve?.length ? (
            <div>
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
                <TrendingUp className="h-3.5 w-3.5" />
                收益曲线 ({btDetail.start_date} ~ {btDetail.end_date})
              </div>
              <EquityCurveChart data={btDetail.equity_curve} height={200} />
            </div>
          ) : null}

          {/* Sell reason stats */}
          {btDetail?.sell_reason_stats && Object.keys(btDetail.sell_reason_stats).length > 0 && (
            <div className="mt-3">
              <div className="text-xs text-muted-foreground mb-1">卖出原因分布</div>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(btDetail.sell_reason_stats).map(([reason, count]) => (
                  <Badge key={reason} variant="outline" className="text-xs">
                    {SELL_REASON_LABEL[reason] || reason}: {count}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Market regime stats */}
          {s.regime_stats && Object.keys(s.regime_stats).length > 0 && (
            <RegimeStatsTable regimeStats={s.regime_stats} />
          )}

          {/* Trade list toggle */}
          {btDetail?.trades?.length ? (
            <div className="mt-3">
              <Button
                size="sm"
                variant="outline"
                className="text-xs h-7"
                onClick={() => setShowTrades(!showTrades)}
              >
                {showTrades ? "收起" : "展开"} 交易明细 ({btDetail.trades.length} 笔)
              </Button>
              {showTrades && (
                <div className="mt-2 max-h-64 overflow-auto border rounded">
                  <Table className="min-w-[600px]">
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-xs">代码</TableHead>
                        <TableHead className="text-xs">买入日期</TableHead>
                        <TableHead className="text-xs">买入价</TableHead>
                        <TableHead className="text-xs">卖出日期</TableHead>
                        <TableHead className="text-xs">卖出价</TableHead>
                        <TableHead className="text-xs">收益率</TableHead>
                        <TableHead className="text-xs">持有天</TableHead>
                        <TableHead className="text-xs">卖出原因</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {btDetail.trades.map((t, i) => (
                        <TableRow key={i}>
                          <TableCell className="font-mono text-xs">{t.stock_code}</TableCell>
                          <TableCell className="text-xs">{t.buy_date}</TableCell>
                          <TableCell className="font-mono text-xs">{t.buy_price.toFixed(2)}</TableCell>
                          <TableCell className="text-xs">{t.sell_date}</TableCell>
                          <TableCell className="font-mono text-xs">{t.sell_price.toFixed(2)}</TableCell>
                          <TableCell className={`font-mono text-xs ${t.pnl_pct >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                            {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                          </TableCell>
                          <TableCell className="font-mono text-xs">{t.hold_days}</TableCell>
                          <TableCell className="text-xs">{SELL_REASON_LABEL[t.sell_reason] || t.sell_reason}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          ) : null}
        </div>
      )}

      {/* Conditions */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
        <div>
          <div className="text-xs font-medium mb-1">买入条件</div>
          <div className="space-y-1">
            {s.buy_conditions.map((c, i) => (
              <ConditionBadge key={i} cond={c} />
            ))}
          </div>
        </div>
        <div>
          <div className="text-xs font-medium mb-1">卖出条件</div>
          <div className="space-y-1">
            {s.sell_conditions.map((c, i) => (
              <ConditionBadge key={i} cond={c} />
            ))}
          </div>
        </div>
      </div>

      {/* Exit config */}
      <div className="flex gap-3 text-xs">
        <span className="text-muted-foreground">
          止损: <span className="font-mono text-red-400">{s.exit_config.stop_loss_pct}%</span>
        </span>
        <span className="text-muted-foreground">
          止盈: <span className="font-mono text-emerald-500">+{s.exit_config.take_profit_pct}%</span>
        </span>
        <span className="text-muted-foreground">
          最大持仓: <span className="font-mono">{s.exit_config.max_hold_days}天</span>
        </span>
      </div>
    </div>
  );
}

// ── Regime colors ───────────────────────────────
const REGIME_STYLE: Record<string, { label: string; cls: string }> = {
  trending_bull: { label: "趋势上涨", cls: "text-emerald-500" },
  trending_bear: { label: "趋势下跌", cls: "text-red-500" },
  ranging: { label: "震荡整理", cls: "text-zinc-400" },
  volatile: { label: "高波动", cls: "text-amber-500" },
  unknown: { label: "未知", cls: "text-zinc-500" },
};

function RegimeStatsTable({
  regimeStats,
}: {
  regimeStats: Record<string, { trades: number; wins: number; win_rate: number; avg_pnl: number; total_pnl: number }>;
}) {
  const entries = Object.entries(regimeStats).filter(([k]) => k !== "unknown");
  if (!entries.length) return null;

  return (
    <div className="mt-3">
      <div className="text-xs text-muted-foreground mb-1">市场阶段分析</div>
      <div className="border rounded overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs">阶段</TableHead>
              <TableHead className="text-xs text-right">交易数</TableHead>
              <TableHead className="text-xs text-right">胜率</TableHead>
              <TableHead className="text-xs text-right">平均收益</TableHead>
              <TableHead className="text-xs text-right">总收益</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map(([regime, data]) => {
              const style = REGIME_STYLE[regime] ?? REGIME_STYLE.unknown;
              return (
                <TableRow key={regime}>
                  <TableCell>
                    <span className={`text-xs font-medium ${style.cls}`}>{style.label}</span>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">{data.trades}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{data.win_rate.toFixed(1)}%</TableCell>
                  <TableCell className={`text-right font-mono text-xs ${data.avg_pnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                    {data.avg_pnl >= 0 ? "+" : ""}{data.avg_pnl.toFixed(2)}%
                  </TableCell>
                  <TableCell className={`text-right font-mono text-xs ${data.total_pnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                    {data.total_pnl >= 0 ? "+" : ""}{data.total_pnl.toFixed(1)}%
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function MetricCard({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="rounded-md border border-border/50 bg-muted/20 px-3 py-2">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className={`text-sm font-bold font-mono ${cls || ""}`}>{value}</div>
    </div>
  );
}

function ConditionBadge({ cond }: { cond: Record<string, unknown> }) {
  const field = cond.field as string;
  const op = cond.operator as string;
  const ctype = cond.compare_type as string;
  const label = cond.label as string | undefined;

  let text: string;
  if (label) {
    text = label;
  } else if (ctype === "field") {
    text = `${field} ${op} ${cond.compare_field}`;
  } else {
    text = `${field} ${op} ${cond.compare_value}`;
  }

  return (
    <div className="text-xs bg-muted/40 rounded px-2 py-1 inline-block mr-1 mb-1">
      {text}
    </div>
  );
}

// ═══════════════════════════════════════════════════
// Tab 3: 探索历史
// ═══════════════════════════════════════════════════

function SyncBadge({ memory, pinecone }: { memory: boolean; pinecone: boolean }) {
  if (memory && pinecone)
    return <Badge variant="outline" className="text-green-600 border-green-300 text-[10px]">✓ synced</Badge>;
  if (memory)
    return <Badge variant="outline" className="text-yellow-600 border-yellow-300 text-[10px]">⚠ partial</Badge>;
  return <Badge variant="outline" className="text-red-600 border-red-300 text-[10px]">✗ not synced</Badge>;
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
        <Card
          key={r.id}
          className="cursor-pointer hover:bg-accent/30 transition-colors"
          onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}
        >
          <CardContent className="pt-4 pb-3">
            {/* Header row */}
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

            {/* Stats row */}
            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-sm">
              <span>实验 <b>{r.total_experiments}</b>个</span>
              <span>策略 <b>{r.total_strategies}</b>个</span>
              <span>盈利 <b>{r.profitable_count}</b> ({r.profitability_pct.toFixed(1)}%)</span>
              <span>StdA: <b>{r.std_a_count}</b>个</span>
              {r.promoted.length > 0 && <span>Promote: <b>{r.promoted.length}</b>个</span>}
            </div>

            {/* Best strategy */}
            {r.best_strategy_name && (
              <div className="mt-1 text-sm text-muted-foreground">
                最佳: {r.best_strategy_name} — {r.best_strategy_score.toFixed(3)} / +{r.best_strategy_return.toFixed(1)}% / {r.best_strategy_dd.toFixed(1)}%
              </div>
            )}

            {/* Expanded detail */}
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
                      {r.promoted.map((p: Record<string, unknown>, i: number) => (
                        <Badge key={i} variant="outline">
                          {p.name
                            ? `${p.name} ${p.label || ""} ${typeof p.score === "number" ? p.score.toFixed(2) : ""}`
                            : p.families
                              ? `${p.count || 0}个: ${p.families}`
                              : JSON.stringify(p)}
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

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center gap-2 pt-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            上一页
          </Button>
          <span className="text-sm leading-8">{page} / {totalPages}</span>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
            下一页
          </Button>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════
// Tab 4: 模板管理
// ═══════════════════════════════════════════════════
function TemplateManagerTab() {
  const { data: templates, isLoading } = useLabTemplates();
  const createMut = useCreateTemplate();
  const updateMut = useUpdateTemplate();
  const deleteMut = useDeleteTemplate();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<LabTemplate | null>(null);
  const [form, setForm] = useState({ name: "", category: "组合", description: "" });

  const openCreate = () => {
    setEditingTemplate(null);
    setForm({ name: "", category: "组合", description: "" });
    setDialogOpen(true);
  };

  const openEdit = (t: LabTemplate) => {
    setEditingTemplate(t);
    setForm({ name: t.name, category: t.category, description: t.description });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) return;
    if (editingTemplate) {
      await updateMut.mutateAsync({
        id: editingTemplate.id,
        name: form.name,
        category: form.category,
        description: form.description,
      });
    } else {
      await createMut.mutateAsync(form);
    }
    setDialogOpen(false);
  };

  const handleDelete = async (id: number) => {
    if (!confirm("确定删除此模板？")) return;
    await deleteMut.mutateAsync(id);
  };

  const grouped = (templates ?? []).reduce<Record<string, LabTemplate[]>>((acc, t) => {
    (acc[t.category] ??= []).push(t);
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4 mr-1" />
          新建模板
        </Button>
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-sm text-muted-foreground">加载中...</div>
      ) : (
        Object.entries(grouped).map(([cat, tpls]) => (
          <div key={cat} className="space-y-2">
            <div className="text-sm font-medium text-muted-foreground">{cat}</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {tpls.map((t) => (
                <Card key={t.id}>
                  <CardContent className="p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">{t.name}</span>
                          {t.is_builtin && (
                            <Badge variant="secondary" className="text-[10px]">内置</Badge>
                          )}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                          {t.description}
                        </div>
                      </div>
                      <div className="flex gap-1 shrink-0">
                        {!t.is_builtin && (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 w-7 p-0"
                            onClick={() => openEdit(t)}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 w-7 p-0 text-red-400 hover:text-red-300"
                          onClick={() => handleDelete(t.id)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        ))
      )}

      {/* Create/Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingTemplate ? "编辑模板" : "新建模板"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              placeholder="模板名称"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
            <Select
              value={form.category}
              onValueChange={(v) => setForm((f) => ({ ...f, category: v }))}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CATEGORIES.map((c) => (
                  <SelectItem key={c} value={c}>{c}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Textarea
              placeholder="策略描述 — 越详细，AI 生成的策略质量越高"
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              className="min-h-[100px]"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button
              onClick={handleSave}
              disabled={!form.name.trim() || createMut.isPending || updateMut.isPending}
            >
              {(createMut.isPending || updateMut.isPending) && (
                <Loader2 className="h-4 w-4 animate-spin mr-1" />
              )}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
