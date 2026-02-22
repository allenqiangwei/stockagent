"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
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
  useTodaySignals,
  useSignalHistory,
  useSignalMeta,
  useStrategies,
  useNewsSignalsToday,
  useTriggerNewsAnalysis,
  useNewsAnalysisPoll,
} from "@/hooks/use-queries";
import { signals as signalsApi } from "@/lib/api";
import { SignalCard } from "@/components/signal/signal-card";
import { AlphaTopCards } from "@/components/signal/alpha-top-cards";
import { Zap, Play, Loader2, Clock, BarChart3, Calendar } from "lucide-react";
import { useAppStore } from "@/lib/store";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import type { SignalItem } from "@/types";

// ── Action filter tabs ───────────────────────────
const ACTION_FILTERS = [
  { key: "all", label: "全部" },
  { key: "buy", label: "买入" },
  { key: "sell", label: "卖出" },
  { key: "hold", label: "持有" },
] as const;

const ACTION_BADGE: Record<string, { label: string; cls: string }> = {
  buy: { label: "买入", cls: "bg-emerald-600 text-white" },
  sell: { label: "卖出", cls: "bg-red-600 text-white" },
  hold: { label: "持有", cls: "bg-zinc-600 text-zinc-300" },
};

function actionBadge(action: string) {
  const s = ACTION_BADGE[action] ?? ACTION_BADGE.hold;
  return <Badge className={`text-xs ${s.cls}`}>{s.label}</Badge>;
}

// ── Countdown hook (to next scheduled run) ──────
function useCountdown(nextRunTime: string | null) {
  const [remaining, setRemaining] = useState("");

  useEffect(() => {
    if (!nextRunTime) {
      setRemaining("");
      return;
    }

    function calc() {
      const target = new Date(nextRunTime!).getTime();
      const diff = target - Date.now();
      if (diff <= 0) {
        setRemaining("即将执行");
        return;
      }
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      setRemaining(
        `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
      );
    }

    calc();
    const timer = setInterval(calc, 1000);
    return () => clearInterval(timer);
  }, [nextRunTime]);

  return remaining;
}

// ── SSE progress state ───────────────────────────
interface GenerateProgress {
  running: boolean;
  current: number;
  total: number;
  pct: number;
  stockCode: string;
  stockName: string;
  generated: number;
  cachedCount: number;
}

export default function SignalsPage() {
  const [date, setDate] = useState("");
  const [histPage, setHistPage] = useState(1);
  const [histAction, setHistAction] = useState("");
  const [histDate, setHistDate] = useState("");
  const [histStrategy, setHistStrategy] = useState("");
  const [actionFilter, setActionFilter] = useState("all");
  const [strategyFilter, setStrategyFilter] = useState("all");
  const [progress, setProgress] = useState<GenerateProgress>({
    running: false,
    current: 0,
    total: 0,
    pct: 0,
    stockCode: "",
    stockName: "",
    generated: 0,
    cachedCount: 0,
  });
  const [streamSignals, setStreamSignals] = useState<SignalItem[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const router = useRouter();
  const queryClient = useQueryClient();
  const setCurrentStock = useAppStore((s) => s.setCurrentStock);

  const [newsAnalysisJobId, setNewsAnalysisJobId] = useState<string | null>(null);

  const { data: meta } = useSignalMeta();
  const { data: today, isLoading: todayLoading } = useTodaySignals(date);
  const { data: history, isLoading: histLoading } = useSignalHistory(histPage, 50, histAction, histDate, histStrategy);
  const { data: allStrategies } = useStrategies();
  const countdown = useCountdown(meta?.next_run_time ?? null);

  const { data: newsSignalsData } = useNewsSignalsToday();
  const triggerNews = useTriggerNewsAnalysis();
  const newsPoll = useNewsAnalysisPoll(newsAnalysisJobId);

  // Use streamed signals if available, otherwise use query data
  const displaySignals =
    streamSignals.length > 0 ? streamSignals : today?.items ?? [];

  const alphaTop = today?.alpha_top ?? [];

  // Collect unique strategy names from signals
  const strategyNames = useMemo(() => {
    const names = new Set<string>();
    for (const s of displaySignals) {
      for (const r of s.reasons || []) names.add(r);
    }
    return Array.from(names).sort();
  }, [displaySignals]);

  // Two-stage filtering: action → strategy
  const filteredSignals = useMemo(() => {
    let list = displaySignals;
    if (actionFilter !== "all") {
      list = list.filter((s) => (s.action || "hold") === actionFilter);
    }
    if (strategyFilter !== "all") {
      list = list.filter((s) => (s.reasons || []).includes(strategyFilter));
    }
    return list;
  }, [displaySignals, actionFilter, strategyFilter]);

  // Count per action (from full set, not filtered)
  const actionCounts = displaySignals.reduce<Record<string, number>>(
    (acc, s) => {
      const a = s.action || "hold";
      acc[a] = (acc[a] || 0) + 1;
      return acc;
    },
    {}
  );

  // Count per strategy (from action-filtered set)
  const strategyCounts = useMemo(() => {
    const base =
      actionFilter === "all"
        ? displaySignals
        : displaySignals.filter((s) => (s.action || "hold") === actionFilter);
    const counts: Record<string, number> = {};
    for (const s of base) {
      for (const r of s.reasons || []) {
        counts[r] = (counts[r] || 0) + 1;
      }
    }
    return counts;
  }, [displaySignals, actionFilter]);

  const navigateToStock = useCallback(
    (code: string, name: string) => {
      setCurrentStock(code, name);
      router.push("/market");
    },
    [setCurrentStock, router]
  );

  // ── SSE generation ──────────────────────────────
  const startGenerate = useCallback(async () => {
    if (progress.running) return;

    const abort = new AbortController();
    abortRef.current = abort;
    setStreamSignals([]);
    setProgress({
      running: true,
      current: 0,
      total: 0,
      pct: 0,
      stockCode: "",
      stockName: "",
      generated: 0,
      cachedCount: 0,
    });

    try {
      const targetDate = date || new Date().toISOString().slice(0, 10);
      const res = await signalsApi.generateStream(targetDate);
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        console.error("Generate failed:", res.status, text);
        setProgress((p) => ({ ...p, running: false }));
        return;
      }
      if (!res.body) return;

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let genCount = 0;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const match = line.match(/^data:\s*(.+)/);
          if (!match) continue;

          try {
            const evt = JSON.parse(match[1]);

            if (evt.type === "start") {
              setProgress((p) => ({
                ...p,
                total: evt.total,
                cachedCount: evt.cached_count ?? evt.total,
              }));
            } else if (evt.type === "progress") {
              setProgress((p) => ({
                ...p,
                current: evt.current,
                total: evt.total,
                pct: evt.pct,
                stockCode: evt.stock_code,
                stockName: evt.stock_name,
              }));
            } else if (evt.type === "signal") {
              genCount++;
              setProgress((p) => ({ ...p, generated: genCount }));
              setStreamSignals((prev) => {
                const next = [...prev, evt.data as SignalItem];
                next.sort((a, b) => b.final_score - a.final_score);
                return next;
              });
            } else if (evt.type === "done") {
              setProgress((p) => ({
                ...p,
                running: false,
                pct: 100,
                generated: evt.total_generated,
              }));
            } else if (evt.type === "error") {
              setProgress((p) => ({ ...p, running: false }));
            }
          } catch {
            // skip malformed JSON
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
      queryClient.invalidateQueries({ queryKey: ["signals"] });
    }
  }, [date, progress.running, queryClient]);

  // Cleanup on unmount
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  return (
    <div className="p-3 sm:p-4 space-y-3 sm:space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div className="flex items-center gap-2 text-base sm:text-lg font-semibold">
          <Zap className="h-5 w-5" />
          交易信号
        </div>
        <div className="flex items-center gap-2">
          <Input
            type="date"
            value={date}
            onChange={(e) => {
              setDate(e.target.value);
              setStreamSignals([]);
            }}
            className="h-8 w-36 text-sm"
          />
          <Button
            size="sm"
            onClick={startGenerate}
            disabled={progress.running}
          >
            {progress.running ? (
              <Loader2 className="h-4 w-4 animate-spin mr-1" />
            ) : (
              <Play className="h-4 w-4 mr-1" />
            )}
            <span className="hidden sm:inline">生成全部信号</span>
            <span className="sm:hidden">生成</span>
          </Button>
        </div>
      </div>

      {/* Meta info bar */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Card>
          <CardContent className="flex items-center gap-3 p-3">
            <Clock className="h-4 w-4 text-muted-foreground shrink-0" />
            <div className="min-w-0">
              <div className="text-xs text-muted-foreground">最后生成</div>
              <div className="text-sm font-mono truncate">
                {meta?.last_generated_at ?? "—"}
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-3">
            <Calendar className="h-4 w-4 text-muted-foreground shrink-0" />
            <div className="min-w-0">
              <div className="text-xs text-muted-foreground">
                下次自动生成{meta?.refresh_hour != null ? ` (${String(meta.refresh_hour).padStart(2, "0")}:${String(meta.refresh_minute ?? 0).padStart(2, "0")})` : ""}
              </div>
              <div className="text-sm font-mono">{countdown || "—"}</div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-3">
            <BarChart3 className="h-4 w-4 text-muted-foreground shrink-0" />
            <div className="min-w-0">
              <div className="text-xs text-muted-foreground">信号数量</div>
              <div className="text-sm font-mono">
                {meta?.signal_count ?? 0}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Progress bar (only when generating) */}
      {progress.running && (
        <Card>
          <CardContent className="p-3 space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span>
                正在分析 {progress.current}/{progress.total}
                {progress.stockName
                  ? `... ${progress.stockName}`
                  : progress.stockCode
                    ? `... ${progress.stockCode}`
                    : ""}
              </span>
              <span className="font-mono text-muted-foreground">
                已生成 {progress.generated} 条
              </span>
            </div>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-primary transition-all duration-300"
                style={{ width: `${progress.pct}%` }}
              />
            </div>
            {progress.total > 0 && progress.cachedCount < progress.total && (
              <div className="text-xs text-muted-foreground">
                首次扫描需拉取 {progress.total - progress.cachedCount} 只股票数据，预计 {Math.ceil((progress.total - progress.cachedCount) / 60)} 分钟（之后会很快）
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Main tabs: today / history */}
      <Tabs defaultValue="today">
        <TabsList>
          <TabsTrigger value="today">今日信号</TabsTrigger>
          <TabsTrigger value="news">新闻驱动</TabsTrigger>
          <TabsTrigger value="history">历史信号</TabsTrigger>
        </TabsList>

        {/* ── Today signals (card grid) ── */}
        <TabsContent value="today" className="space-y-3">
          {/* Alpha Top 5 ranking */}
          <AlphaTopCards
            items={alphaTop}
            onCardClick={navigateToStock}
          />

          {/* Action filter */}
          <div className="flex flex-wrap items-center gap-1.5">
            {ACTION_FILTERS.map((f) => {
              const count =
                f.key === "all"
                  ? displaySignals.length
                  : actionCounts[f.key] || 0;
              const active = actionFilter === f.key;
              return (
                <Button
                  key={f.key}
                  size="sm"
                  variant={active ? "default" : "outline"}
                  className="h-7 text-xs px-2.5"
                  onClick={() => setActionFilter(f.key)}
                >
                  {f.label}
                  <span className="ml-1 opacity-60">{count}</span>
                </Button>
              );
            })}

            {/* Strategy filter (divider + buttons) */}
            {strategyNames.length > 0 && (
              <>
                <div className="w-px h-5 bg-border mx-1" />
                <Button
                  size="sm"
                  variant={strategyFilter === "all" ? "default" : "outline"}
                  className="h-7 text-xs px-2.5"
                  onClick={() => setStrategyFilter("all")}
                >
                  全部策略
                </Button>
                {strategyNames.map((name) => {
                  const count = strategyCounts[name] || 0;
                  const active = strategyFilter === name;
                  return (
                    <Button
                      key={name}
                      size="sm"
                      variant={active ? "default" : "outline"}
                      className="h-7 text-xs px-2.5"
                      onClick={() => setStrategyFilter(name)}
                    >
                      {name}
                      <span className="ml-1 opacity-60">{count}</span>
                    </Button>
                  );
                })}
              </>
            )}
          </div>

          {todayLoading && !streamSignals.length ? (
            <div className="py-12 text-center text-sm text-muted-foreground">
              加载中...
            </div>
          ) : filteredSignals.length === 0 ? (
            <div className="py-12 text-center text-sm text-muted-foreground">
              {displaySignals.length === 0
                ? '暂无信号，点击"生成全部信号"按钮生成'
                : "当前筛选无结果"}
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
              {filteredSignals.map((s) => (
                <SignalCard
                  key={`${s.stock_code}-${s.trade_date}`}
                  signal={s}
                  onClick={() =>
                    navigateToStock(s.stock_code, s.stock_name || "")
                  }
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* ── News-driven signals ── */}
        <TabsContent value="news" className="space-y-3">
          <div className="flex items-center gap-2 mb-2">
            <Button
              size="sm"
              onClick={() => {
                triggerNews.mutate(undefined, {
                  onSuccess: (data) => setNewsAnalysisJobId(data.job_id),
                });
              }}
              disabled={triggerNews.isPending || newsPoll?.data?.status === "processing"}
            >
              {newsPoll?.data?.status === "processing" ? (
                <><Loader2 className="h-4 w-4 animate-spin mr-1" />分析中...</>
              ) : (
                <><Zap className="h-4 w-4 mr-1" />触发新闻分析</>
              )}
            </Button>
            {newsPoll?.data?.status === "completed" && (
              <Badge variant="outline" className="text-emerald-400">分析完成</Badge>
            )}
            {newsPoll?.data?.status === "error" && (
              <Badge variant="destructive">{newsPoll.data.error || "分析失败"}</Badge>
            )}
          </div>

          <div className="grid gap-3">
            {(newsSignalsData?.signals ?? []).map((sig) => (
              <Card key={sig.id} className="bg-zinc-900 border-zinc-800">
                <CardContent className="p-4">
                  <div className="flex items-center justify-between">
                    <div
                      className="cursor-pointer hover:underline"
                      onClick={() => navigateToStock(sig.stock_code, sig.stock_name)}
                    >
                      <span className="font-bold">{sig.stock_name}</span>
                      <span className="text-zinc-500 ml-2">{sig.stock_code}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {actionBadge(sig.action)}
                      <Badge variant="outline">{sig.confidence}%</Badge>
                    </div>
                  </div>
                  <p className="text-sm text-zinc-400 mt-2">{sig.reason}</p>
                  <div className="flex gap-2 mt-2">
                    {sig.sector_name && (
                      <Badge variant="secondary" className="text-xs">{sig.sector_name}</Badge>
                    )}
                    <Badge variant="outline" className="text-xs">{sig.signal_source}</Badge>
                    <span className="text-xs text-zinc-600 ml-auto">{sig.created_at}</span>
                  </div>
                </CardContent>
              </Card>
            ))}
            {(newsSignalsData?.signals ?? []).length === 0 && (
              <p className="text-zinc-500 text-center py-8">暂无新闻驱动信号，点击上方按钮触发分析</p>
            )}
          </div>
        </TabsContent>

        {/* ── History signals (table) ── */}
        <TabsContent value="history" className="space-y-3">
          {/* History filters */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5">
              {[
                { key: "", label: "全部" },
                { key: "buy", label: "买入" },
                { key: "sell", label: "卖出" },
              ].map((f) => (
                <Button
                  key={f.key}
                  size="sm"
                  variant={histAction === f.key ? "default" : "outline"}
                  className="h-7 text-xs px-2.5"
                  onClick={() => { setHistAction(f.key); setHistPage(1); }}
                >
                  {f.label}
                </Button>
              ))}
            </div>
            {/* Strategy filter */}
            {allStrategies && allStrategies.length > 0 && (
              <>
                <div className="w-px h-5 bg-border" />
                <Button
                  size="sm"
                  variant={histStrategy === "" ? "default" : "outline"}
                  className="h-7 text-xs px-2.5"
                  onClick={() => { setHistStrategy(""); setHistPage(1); }}
                >
                  全部策略
                </Button>
                {allStrategies.filter((s) => s.enabled).map((s) => (
                  <Button
                    key={s.name}
                    size="sm"
                    variant={histStrategy === s.name ? "default" : "outline"}
                    className="h-7 text-xs px-2.5"
                    onClick={() => { setHistStrategy(s.name); setHistPage(1); }}
                  >
                    {s.name}
                  </Button>
                ))}
              </>
            )}
            <div className="w-px h-5 bg-border" />
            <Input
              type="date"
              value={histDate}
              onChange={(e) => { setHistDate(e.target.value); setHistPage(1); }}
              className="h-7 w-36 text-xs"
              placeholder="按日期筛选"
            />
            {histDate && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs px-2"
                onClick={() => { setHistDate(""); setHistPage(1); }}
              >
                清除日期
              </Button>
            )}
          </div>

          <Card>
            <CardContent className="px-4 py-4">
              {histLoading ? (
                <div className="py-8 text-center text-sm text-muted-foreground">
                  加载中...
                </div>
              ) : !history?.items?.length ? (
                <div className="py-8 text-center text-sm text-muted-foreground">
                  暂无历史信号
                </div>
              ) : (
                <>
                <div className="overflow-x-auto">
                  <Table className="min-w-[500px]">
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-20">代码</TableHead>
                        <TableHead>名称</TableHead>
                        <TableHead>日期</TableHead>
                        <TableHead>操作</TableHead>
                        <TableHead>符合策略</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {history.items.map((s, i) => (
                        <TableRow
                          key={`${s.stock_code}-${s.trade_date}-${i}`}
                          className="cursor-pointer"
                          onClick={() =>
                            navigateToStock(s.stock_code, s.stock_name || "")
                          }
                        >
                          <TableCell className="font-mono">
                            {s.stock_code}
                          </TableCell>
                          <TableCell className="text-sm">
                            {s.stock_name || "—"}
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {s.trade_date}
                          </TableCell>
                          <TableCell>
                            {actionBadge(s.action || "hold")}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {s.reasons.join("、")}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                  <div className="flex justify-center gap-2 mt-3">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={histPage <= 1}
                      onClick={() => setHistPage((p) => p - 1)}
                    >
                      上一页
                    </Button>
                    <span className="text-sm text-muted-foreground leading-8">
                      第 {histPage} 页 · 共 {history.total} 条
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={(history?.items?.length ?? 0) < 50}
                      onClick={() => setHistPage((p) => p + 1)}
                    >
                      下一页
                    </Button>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
