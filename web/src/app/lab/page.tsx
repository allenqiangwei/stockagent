"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useLabTemplates,
  useLabStats,
  useLabExperiments,
} from "@/hooks/use-queries";
import { lab as labApi } from "@/lib/api";
import type { LabTemplate } from "@/types";
import { useQueryClient } from "@tanstack/react-query";
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
} from "lucide-react";

// Quant components
import { PoolOverview } from "@/components/quant/pool-overview";
import { StrategyFamilies } from "@/components/quant/strategy-families";
import { ExperimentList } from "@/components/quant/experiment-list";
import { ExplorationRounds } from "@/components/quant/exploration-rounds";

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

// ── Exploration Cron Toggle ────────────────────────
function ExplorationCronToggle() {
  const [status, setStatus] = useState<{
    enabled: boolean; interval_minutes: number; state: string;
    current_step: string; current_round: number; elapsed_seconds: number;
  } | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const { exploration } = await import("@/lib/api");
      const data = await exploration.status();
      setStatus({
        enabled: data.cron?.enabled ?? false,
        interval_minutes: data.cron?.interval_minutes ?? 15,
        state: data.state,
        current_step: data.current_step,
        current_round: data.current_round,
        elapsed_seconds: data.elapsed_seconds,
      });
    } catch {}
  }, []);

  useEffect(() => {
    fetchStatus();
    const t = setInterval(fetchStatus, 30000);
    return () => clearInterval(t);
  }, [fetchStatus]);

  const toggle = async () => {
    setLoading(true);
    try {
      const { exploration } = await import("@/lib/api");
      if (status?.enabled) {
        await exploration.cronStop();
      } else {
        await exploration.cronStart(15);
      }
      await fetchStatus();
    } finally {
      setLoading(false);
    }
  };

  const startNow = async () => {
    setLoading(true);
    try {
      const { exploration } = await import("@/lib/api");
      await exploration.start(1, 50);
      await fetchStatus();
    } finally {
      setLoading(false);
    }
  };

  const stopNow = async () => {
    setLoading(true);
    try {
      const { exploration } = await import("@/lib/api");
      await exploration.stop();
      await fetchStatus();
    } finally {
      setLoading(false);
    }
  };

  if (!status) return null;

  const isRunning = status.state === "running";

  return (
    <Card className={status.enabled ? "border-emerald-500/30 bg-emerald-500/5" : "border-zinc-700"}>
      <CardContent className="p-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">自动探索</span>
              <Badge className={status.enabled ? "bg-emerald-600 text-white text-[10px]" : "bg-zinc-700 text-zinc-400 text-[10px]"}>
                {status.enabled ? `每${status.interval_minutes}分钟` : "已关闭"}
              </Badge>
              {isRunning && (
                <Badge className="bg-blue-600 text-white text-[10px]">
                  R{status.current_round} {status.current_step} {Math.floor(status.elapsed_seconds / 60)}m
                </Badge>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isRunning ? (
            <Button size="sm" variant="outline" onClick={stopNow} disabled={loading} className="h-7 text-xs border-red-500/50 text-red-400 hover:bg-red-500/10">
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : "停止"}
            </Button>
          ) : (
            <Button size="sm" variant="outline" onClick={startNow} disabled={loading} className="h-7 text-xs">
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <><Play className="h-3 w-3 mr-1" />立即跑</>}
            </Button>
          )}
          <Button
            size="sm"
            variant={status.enabled ? "default" : "outline"}
            onClick={toggle}
            disabled={loading}
            className={`h-7 text-xs ${status.enabled ? "bg-emerald-600 hover:bg-emerald-700" : ""}`}
          >
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : status.enabled ? "关闭定时" : "开启定时"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ═══════════════════════════════════════════════════
// Main page
// ═══════════════════════════════════════════════════
export default function QuantDashboard() {
  const searchParams = useSearchParams();
  const defaultTab = searchParams.get("tab") || "pool";

  const { data: stats } = useLabStats();

  return (
    <div className="p-3 sm:p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2 text-base sm:text-lg font-semibold">
        <FlaskConical className="h-5 w-5" />
        量化工作台
      </div>

      {/* Pool Overview KPIs */}
      <PoolOverview />

      {/* Exploration Cron Toggle */}
      <ExplorationCronToggle />

      {/* Engine running status — always visible */}
      {stats?.current_round && (
        <Card className="border-blue-500/30 bg-blue-500/5">
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Loader2 className="h-4 w-4 animate-spin text-blue-400" />
                探索引擎 R{stats.current_round.round_number} — {stats.current_round.step}
              </div>
              <span className="text-xs text-muted-foreground">
                {Math.floor(stats.current_round.elapsed_seconds / 60)}分钟
                {stats.current_round.llm_provider && ` · ${stats.current_round.llm_provider}`}
              </span>
            </div>
            <div className="text-xs text-muted-foreground">
              {stats.current_round.step_detail}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
              <span>策略 <b>{stats.current_round.strategies_done}</b>/{stats.current_round.strategies || stats.current_round.strategies_pending}</span>
              {stats.current_round.stda_count > 0 && (
                <span className="text-emerald-400">StdA+ <b>{stats.current_round.stda_count}</b></span>
              )}
              {stats.current_round.best_score > 0 && (
                <span>最佳 <b className="font-mono">{stats.current_round.best_score.toFixed(4)}</b></span>
              )}
            </div>
            {(stats.current_round.strategies || stats.current_round.strategies_pending) > 0 && (
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full bg-blue-500 transition-all duration-500"
                  style={{
                    width: `${Math.round(
                      (stats.current_round.strategies_done /
                        (stats.current_round.strategies || stats.current_round.strategies_pending)) *
                        100
                    )}%`,
                  }}
                />
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Main Tabs */}
      <Tabs defaultValue={defaultTab}>
        <TabsList className="grid w-full grid-cols-3 max-w-sm">
          <TabsTrigger value="pool" className="text-xs sm:text-sm">
            <Layers className="h-3.5 w-3.5 mr-1 hidden sm:inline" />
            策略池
          </TabsTrigger>
          <TabsTrigger value="experiments" className="text-xs sm:text-sm">
            <Beaker className="h-3.5 w-3.5 mr-1 hidden sm:inline" />
            实验
          </TabsTrigger>
          <TabsTrigger value="exploration" className="text-xs sm:text-sm">
            <History className="h-3.5 w-3.5 mr-1 hidden sm:inline" />
            探索
          </TabsTrigger>
        </TabsList>

        <TabsContent value="pool" className="mt-4">
          <StrategyFamilies />
        </TabsContent>

        <TabsContent value="experiments" className="mt-4">
          <ExperimentsTab />
        </TabsContent>

        <TabsContent value="exploration" className="mt-4">
          <ExplorationRounds />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ═══════════════════════════════════════════════════
// Experiments Tab: New experiment + History
// ═══════════════════════════════════════════════════
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

// ── New experiment panel (with SSE) ──────────────
function NewExperimentPanel() {
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
      sourceType === "template" ? selectedTemplate!.description : customText;

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
        setProgress((p) => ({
          ...p,
          running: false,
          phase: "error",
          message: text,
        }));
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
  }, [
    canStart,
    sourceType,
    selectedTemplate,
    customText,
    initialCapital,
    maxPositions,
    maxPositionPct,
    queryClient,
  ]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const grouped = (templates ?? []).reduce<Record<string, LabTemplate[]>>(
    (acc, t) => {
      (acc[t.category] ??= []).push(t);
      return acc;
    },
    {}
  );

  return (
    <div className="space-y-4">
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
                  <div className="text-xs text-muted-foreground mb-1.5">
                    {cat}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {tpls.map((t) => (
                      <Button
                        key={t.id}
                        size="sm"
                        variant={
                          selectedTemplate?.id === t.id ? "default" : "outline"
                        }
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
                  onChange={(e) =>
                    setInitialCapital(Number(e.target.value) || 100000)
                  }
                />
              </div>
              <div className="space-y-1">
                <span className="text-xs text-muted-foreground">
                  最大持仓数
                </span>
                <Input
                  type="number"
                  min={1}
                  max={50}
                  value={maxPositions}
                  onChange={(e) =>
                    setMaxPositions(Number(e.target.value) || 10)
                  }
                />
              </div>
              <div className="space-y-1">
                <span className="text-xs text-muted-foreground">
                  单股最大占比 (%)
                </span>
                <Input
                  type="number"
                  min={5}
                  max={100}
                  value={maxPositionPct}
                  onChange={(e) =>
                    setMaxPositionPct(Number(e.target.value) || 30)
                  }
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

      {(progress.running || progress.done) && (
        <ExperimentProgressCard progress={progress} />
      )}
    </div>
  );
}

// ── SSE event handler ───────────────────────────
function handleSSE(
  evt: Record<string, unknown>,
  setProgress: React.Dispatch<React.SetStateAction<ExperimentProgress>>
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
        strategies: evt.strategies as {
          id: number;
          name: string;
          status: string;
        }[],
        backtestTotal: evt.count as number,
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
      setProgress((p) => ({ ...p, message: evt.message as string }));
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
function ExperimentProgressCard({
  progress,
}: {
  progress: ExperimentProgress;
}) {
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
            {progress.phase === "error"
              ? "实验失败"
              : progress.done
              ? "实验完成"
              : "实验进行中"}
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
              <span>
                {progress.backtestIndex}/{progress.backtestTotal}
              </span>
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

