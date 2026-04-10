"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sparkles,
  Calendar,
  ChevronDown,
  ChevronUp,
  Loader2,
  Send,
  MessageSquare,
  Plus,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Minus,
  ShieldAlert,
  Zap,
  Brain,
  ArrowUpRight,
  ArrowDownRight,
  Clock,
  CircleCheck,
  CircleX,
  FileDown,
  Filter,
  X,
} from "lucide-react";
import {
  useAIReports,
  useAIReport,
  useAIReportDates,
  useAIChatSend,
  useAIChatPoll,
  useTriggerAnalysis,
  useAnalysisPoll,
  useBotPortfolio,
  useBotSummary,
  useBotReviews,
  useBotPlans,
  useAISchedulerStatus,
  useDiary,
} from "@/hooks/use-queries";
import { ai, bot } from "@/lib/api";
import type { AIReport, AIReportListItem, BotTradeItem, BotStockTimeline, BotTradePlanItem } from "@/types";

// ── helpers ────────────────────────────────────────────

/** Format a buy/sell condition for display, handling all compare_types. */
function formatCondition(c: Record<string, unknown>): string {
  // Prefer explicit label if available
  if (c.label) return String(c.label);

  const field = String(c.field || "");
  const op = String(c.operator || "");
  const ct = String(c.compare_type || "");
  const n = c.lookback_n ?? c.lookback;

  switch (ct) {
    case "value":
      return `${field}${op}${c.compare_value ?? ""}`;
    case "field":
      return `${field}${op}${c.compare_field || ""}`;
    case "consecutive": {
      const dir = c.consecutive_type === "rising" ? "连升" : "连降";
      return `${field}${dir}${n ?? ""}`;
    }
    case "lookback_min":
      return `${field}${op}${n ?? ""}日低`;
    case "lookback_max":
      return `${field}${op}${n ?? ""}日高`;
    case "pct_change":
      return `${field}变${c.compare_value ?? ""}%/${n ?? 1}日`;
    case "pct_diff":
      return `${field}差${op}${c.compare_value ?? ""}%`;
    default:
      // Legacy format or missing compare_type
      return `${field}${op}${c.compare_value ?? c.value ?? ""}`;
  }
}

function regimeLabel(regime: string | null): string {
  if (!regime) return "未知";
  const map: Record<string, string> = {
    bull: "牛市",
    bear: "熊市",
    range: "震荡",
    sideways: "震荡",
    neutral: "中性",
    transition: "过渡期",
  };
  return map[regime.toLowerCase()] ?? regime;
}

function regimeBadge(regime: string | null) {
  const label = regimeLabel(regime);
  const variant =
    regime?.toLowerCase() === "bull"
      ? "default"
      : regime?.toLowerCase() === "bear"
        ? "destructive"
        : "secondary";
  return <Badge variant={variant}>{label}</Badge>;
}

// ── ReportViewer ───────────────────────────────────────

function regimeConfig(regime: string | null) {
  const r = regime?.toLowerCase();
  if (r === "bull") return { icon: TrendingUp, color: "text-emerald-400", bg: "bg-emerald-400/10", border: "border-emerald-400/20" };
  if (r === "bear") return { icon: TrendingDown, color: "text-red-400", bg: "bg-red-400/10", border: "border-red-400/20" };
  if (r === "sideways" || r === "range") return { icon: Minus, color: "text-amber-400", bg: "bg-amber-400/10", border: "border-amber-400/20" };
  if (r === "transition") return { icon: Zap, color: "text-blue-400", bg: "bg-blue-400/10", border: "border-blue-400/20" };
  return { icon: Minus, color: "text-muted-foreground", bg: "bg-muted/50", border: "border-border/50" };
}

function actionLabel(action: string) {
  const map: Record<string, string> = { buy: "买入", sell: "卖出", hold: "持有", monitor: "观察", adjust: "调整" };
  return map[action] ?? action;
}

function ReportViewer({ report }: { report: AIReport | undefined }) {
  const [showThinking, setShowThinking] = useState(false);

  if (!report) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        <div className="text-center space-y-2">
          <Sparkles className="h-10 w-10 mx-auto opacity-30" />
          <p>选择一份报告查看详情</p>
        </div>
      </div>
    );
  }

  const regime = regimeConfig(report.market_regime);
  const RegimeIcon = regime.icon;
  const buyRecs = report.recommendations?.filter(r => r.action === "buy") ?? [];
  const sellRecs = report.recommendations?.filter(r => r.action !== "buy") ?? [];

  return (
    <ScrollArea className="flex-1">
      <div className="p-5 space-y-5 max-w-3xl mx-auto">

        {/* ── Header: Date + Regime Gauge ── */}
        <div className="flex items-start justify-between">
          <div>
            <div className="text-xs text-muted-foreground font-mono tracking-wider uppercase mb-1">
              AI 市场分析
            </div>
            <h1 className="text-xl font-semibold tracking-tight">
              {report.report_date}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.open(`/api/ai/reports/${report.id}/pdf`, '_blank')}
              title="导出PDF报告"
            >
              <FileDown className="h-4 w-4 mr-1.5" />
              导出PDF
            </Button>
            <div className={`flex items-center gap-2.5 px-3.5 py-2 rounded-lg border ${regime.bg} ${regime.border}`}>
              <RegimeIcon className={`h-5 w-5 ${regime.color}`} />
              <div>
                <div className={`text-sm font-semibold ${regime.color}`}>
                  {regimeLabel(report.market_regime)}
                </div>
                {report.market_regime_confidence != null && (
                  <div className="text-[10px] text-muted-foreground font-mono">
                    置信度 {(report.market_regime_confidence * 100).toFixed(0)}%
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* ── Summary ── */}
        {report.summary && (
          <div className="rounded-lg border border-border/50 bg-card/50 p-4">
            <p className="text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap">
              {report.summary}
            </p>
          </div>
        )}

        {/* ── Recommendations: Buy ── */}
        {buyRecs.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <ArrowUpRight className="h-4 w-4 text-emerald-400" />
              <h2 className="text-sm font-semibold">买入推荐</h2>
              <span className="text-xs text-muted-foreground">{buyRecs.length} 只</span>
            </div>
            <div className="grid gap-2">
              {buyRecs.map((rec, i) => (
                <div
                  key={i}
                  className="group rounded-lg border border-emerald-500/10 bg-emerald-500/[0.03] p-3 transition-colors hover:bg-emerald-500/[0.06]"
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm">{rec.stock_name}</span>
                      <span className="text-xs font-mono text-muted-foreground">{rec.stock_code}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Alpha</span>
                      <span className={`text-sm font-mono font-bold tabular-nums ${
                        rec.alpha_score >= 30 ? "text-emerald-400" :
                        rec.alpha_score >= 15 ? "text-emerald-400/70" :
                        "text-foreground/70"
                      }`}>
                        {rec.alpha_score.toFixed(1)}
                      </span>
                    </div>
                  </div>
                  {/* ── Price / Position / StopLoss ── */}
                  {(rec.target_price || rec.position_pct || rec.stop_loss) && (
                    <div className="flex flex-wrap gap-3 my-2 py-1.5 px-2 rounded-md bg-emerald-500/[0.06] border border-emerald-500/10">
                      {rec.target_price != null && (
                        <div className="flex items-center gap-1">
                          <span className="text-[10px] text-muted-foreground">买入价</span>
                          <span className="text-sm font-mono font-semibold text-emerald-400">¥{rec.target_price.toFixed(2)}</span>
                        </div>
                      )}
                      {rec.position_pct != null && (
                        <div className="flex items-center gap-1">
                          <span className="text-[10px] text-muted-foreground">仓位</span>
                          <span className="text-sm font-mono font-semibold text-foreground">{rec.position_pct.toFixed(0)}%</span>
                        </div>
                      )}
                      {rec.stop_loss != null && (
                        <div className="flex items-center gap-1">
                          <span className="text-[10px] text-muted-foreground">止损</span>
                          <span className="text-sm font-mono font-semibold text-red-400">¥{rec.stop_loss.toFixed(2)}</span>
                        </div>
                      )}
                    </div>
                  )}
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {rec.reason}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Recommendations: Sell ── */}
        {sellRecs.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <ArrowDownRight className="h-4 w-4 text-red-400" />
              <h2 className="text-sm font-semibold">卖出 / 减持</h2>
              <span className="text-xs text-muted-foreground">{sellRecs.length} 只</span>
            </div>
            <div className="grid gap-2">
              {sellRecs.map((rec, i) => (
                <div
                  key={i}
                  className="group rounded-lg border border-red-500/10 bg-red-500/[0.03] p-3 transition-colors hover:bg-red-500/[0.06]"
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm">{rec.stock_name}</span>
                      <span className="text-xs font-mono text-muted-foreground">{rec.stock_code}</span>
                    </div>
                    <Badge variant="destructive" className="text-[10px] h-5 px-1.5">
                      {actionLabel(rec.action)}
                    </Badge>
                  </div>
                  {/* ── Price / Position / StopLoss ── */}
                  {(rec.target_price || rec.position_pct || rec.stop_loss) && (
                    <div className="flex flex-wrap gap-3 my-2 py-1.5 px-2 rounded-md bg-red-500/[0.06] border border-red-500/10">
                      {rec.target_price != null && (
                        <div className="flex items-center gap-1">
                          <span className="text-[10px] text-muted-foreground">卖出价</span>
                          <span className="text-sm font-mono font-semibold text-red-400">¥{rec.target_price.toFixed(2)}</span>
                        </div>
                      )}
                      {rec.position_pct != null && (
                        <div className="flex items-center gap-1">
                          <span className="text-[10px] text-muted-foreground">卖出比例</span>
                          <span className="text-sm font-mono font-semibold text-foreground">{rec.position_pct.toFixed(0)}%</span>
                        </div>
                      )}
                      {rec.stop_loss != null && (
                        <div className="flex items-center gap-1">
                          <span className="text-[10px] text-muted-foreground">止损</span>
                          <span className="text-sm font-mono font-semibold text-red-400">¥{rec.stop_loss.toFixed(2)}</span>
                        </div>
                      )}
                    </div>
                  )}
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {rec.reason}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Strategy Actions ── */}
        {report.strategy_actions && report.strategy_actions.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <ShieldAlert className="h-4 w-4 text-chart-1" />
              <h2 className="text-sm font-semibold">策略动态</h2>
            </div>
            <div className="rounded-lg border border-border/50 overflow-hidden">
              {report.strategy_actions.map((sa, i) => (
                <div
                  key={i}
                  className={`flex items-start gap-3 p-3 ${
                    i > 0 ? "border-t border-border/30" : ""
                  }`}
                >
                  <div className="mt-0.5 h-6 w-6 rounded-md bg-muted/80 flex items-center justify-center shrink-0">
                    <Zap className="h-3 w-3 text-muted-foreground" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-sm font-medium truncate">{sa.strategy_name}</span>
                      <Badge variant="outline" className="text-[10px] h-5 px-1.5 shrink-0">
                        {actionLabel(sa.action)}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed">{sa.reason}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Thinking Process (collapsible) ── */}
        {report.thinking_process && (
          <div className="rounded-lg border border-border/30">
            <button
              className="flex items-center gap-2 w-full text-left p-3 hover:bg-muted/30 transition-colors"
              onClick={() => setShowThinking(!showThinking)}
            >
              <Brain className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">分析过程</span>
              <span className="text-xs text-muted-foreground ml-auto mr-1">
                {showThinking ? "收起" : "展开"}
              </span>
              {showThinking ? (
                <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
              )}
            </button>
            {showThinking && (
              <div className="px-3 pb-3 border-t border-border/30">
                <p className="text-xs text-muted-foreground whitespace-pre-wrap leading-relaxed pt-3 font-mono">
                  {report.thinking_process}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </ScrollArea>
  );
}

// ── ChatWidget ─────────────────────────────────────────

interface LocalMsg {
  role: "user" | "assistant" | "progress" | "error";
  content: string;
}

function ChatWidget() {
  const [messages, setMessages] = useState<LocalMsg[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [pendingMessageId, setPendingMessageId] = useState<string | null>(null);
  const sendMutation = useAIChatSend();
  const pollQuery = useAIChatPoll(pendingMessageId);
  const scrollRef = useRef<HTMLDivElement>(null);

  const isProcessing = !!pendingMessageId;

  // Auto-scroll on message changes or poll progress
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, pollQuery.data?.progress]);

  // Handle poll results
  useEffect(() => {
    if (!pollQuery.data || !pendingMessageId) return;

    const { status, content, errorMessage, sessionId: newSessionId } = pollQuery.data;

    if (status === "completed" && content) {
      setMessages((prev) => [...prev, { role: "assistant", content }]);
      if (newSessionId) setSessionId(newSessionId);
      setPendingMessageId(null);
    } else if (status === "error") {
      setMessages((prev) => [
        ...prev,
        { role: "error", content: errorMessage || "未知错误" },
      ]);
      setPendingMessageId(null);
    }
  }, [pollQuery.data, pendingMessageId]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || isProcessing) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);

    sendMutation.mutate(
      { message: text, sessionId },
      {
        onSuccess: (data) => {
          setSessionId(data.sessionId);
          setPendingMessageId(data.messageId);
        },
        onError: (err) => {
          setMessages((prev) => [
            ...prev,
            {
              role: "error",
              content: err instanceof Error ? err.message : "发送失败",
            },
          ]);
        },
      },
    );
  }, [input, sessionId, isProcessing, sendMutation]);

  const handleRetry = useCallback(() => {
    // Remove the last error message and resend the last user message
    setMessages((prev) => {
      const lastErrorIdx = prev.length - 1;
      if (prev[lastErrorIdx]?.role !== "error") return prev;
      return prev.slice(0, lastErrorIdx);
    });
    // Find last user message to retry
    const lastUserMsg = [...messages].reverse().find((m) => m.role === "user");
    if (lastUserMsg) {
      sendMutation.mutate(
        { message: lastUserMsg.content, sessionId },
        {
          onSuccess: (data) => {
            setSessionId(data.sessionId);
            setPendingMessageId(data.messageId);
          },
          onError: (err) => {
            setMessages((prev) => [
              ...prev,
              {
                role: "error",
                content: err instanceof Error ? err.message : "发送失败",
              },
            ]);
          },
        },
      );
    }
  }, [messages, sessionId, sendMutation]);

  const handleNewChat = useCallback(() => {
    setMessages([]);
    setSessionId(undefined);
    setPendingMessageId(null);
  }, []);

  // Current progress text from polling
  const progressText = pollQuery.data?.progress || "正在思考...";

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/40">
        <div className="flex items-center gap-2 text-sm font-medium">
          <MessageSquare className="h-4 w-4" />
          AI 对话
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={handleNewChat}
          title="新对话"
          disabled={isProcessing}
        >
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 && !isProcessing && (
          <div className="text-center text-xs text-muted-foreground pt-8 space-y-1">
            <MessageSquare className="h-8 w-8 mx-auto opacity-30" />
            <p>向 AI 提问关于市场、策略的问题</p>
          </div>
        )}
        {messages.map((msg, i) => {
          if (msg.role === "error") {
            return (
              <div key={i} className="flex justify-start">
                <div className="max-w-[90%] rounded-lg px-3 py-2 text-sm bg-destructive/10 text-destructive border border-destructive/20">
                  <p>{msg.content}</p>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mt-1.5 h-6 px-2 text-xs"
                    onClick={handleRetry}
                  >
                    <RefreshCw className="h-3 w-3 mr-1" />
                    重试
                  </Button>
                </div>
              </div>
            );
          }
          return (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[90%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-foreground"
                }`}
              >
                {msg.content}
              </div>
            </div>
          );
        })}
        {isProcessing && (
          <div className="flex justify-start">
            <div className="bg-muted rounded-lg px-3 py-2 text-sm flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {progressText}
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-border/40 p-2">
        <div className="flex gap-2">
          <input
            className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
            placeholder={isProcessing ? "AI 正在回复..." : "输入问题..."}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            disabled={isProcessing}
          />
          <Button
            size="icon"
            className="h-8 w-8 shrink-0"
            disabled={!input.trim() || isProcessing}
            onClick={handleSend}
          >
            <Send className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── BotTradingPanel ─────────────────────────────────────

function BotTradingPanel() {
  const { data: summary } = useBotSummary();
  const { data: portfolio } = useBotPortfolio();
  const { data: reviews } = useBotReviews();
  const { data: plans } = useBotPlans();
  const [subTab, setSubTab] = useState<"holding" | "plans" | "closed" | "diary">("holding");
  const [diaryDate, setDiaryDate] = useState(() => new Date().toISOString().slice(0, 10));
  const { data: diary } = useDiary(subTab === "diary" ? diaryDate : "");
  const [expandedCode, setExpandedCode] = useState<string | null>(null);
  const [timelines, setTimelines] = useState<Record<string, BotStockTimeline>>({});
  const [selectedStrategies, setSelectedStrategies] = useState<Set<string>>(new Set());
  const [stratFilterOpen, setStratFilterOpen] = useState(false);

  // Collect all unique strategy names across tabs
  const allStrategyNames = useMemo(() => {
    const names = new Set<string>();
    portfolio?.forEach(h => { if (h.strategy_name) names.add(h.strategy_name); });
    plans?.forEach(p => { if (p.strategy_name) names.add(p.strategy_name); });
    // reviews don't have strategy_name at top level
    return Array.from(names).sort();
  }, [portfolio, plans]);

  // Filter helpers
  const matchesStrategyFilter = (name?: string | null) =>
    selectedStrategies.size === 0 || (name != null && selectedStrategies.has(name));

  const filteredPortfolio = useMemo(
    () => portfolio?.filter(h => matchesStrategyFilter(h.strategy_name)),
    [portfolio, selectedStrategies]
  );
  const filteredPlans = useMemo(
    () => plans?.filter(p => matchesStrategyFilter(p.strategy_name)),
    [plans, selectedStrategies]
  );
  // reviews pass through (no strategy_name field)
  const filteredReviews = reviews;

  // Close strategy filter dropdown on click outside
  const stratFilterRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!stratFilterOpen) return;
    const handler = (e: MouseEvent) => {
      if (stratFilterRef.current && !stratFilterRef.current.contains(e.target as Node)) {
        setStratFilterOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [stratFilterOpen]);

  const loadTimeline = async (code: string, strategyId?: number) => {
    const key = strategyId != null ? `${code}_${strategyId}` : code;
    if (timelines[key]) {
      setExpandedCode(expandedCode === key ? null : key);
      return;
    }
    try {
      const data = await bot.timeline(code, strategyId);
      setTimelines(prev => ({ ...prev, [key]: data }));
      setExpandedCode(key);
    } catch { setExpandedCode(key); }
  };

  const pnlColor = (v: number) => v > 0 ? "text-red-400" : v < 0 ? "text-green-400" : "text-muted-foreground";
  const pnlSign = (v: number) => v > 0 ? "+" : "";

  return (
    <div className="p-5 space-y-5 max-w-3xl mx-auto">
      {/* Summary row */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="rounded-lg border border-border/50 bg-card/50 p-3">
            <div className="text-[10px] text-muted-foreground mb-1">总投入</div>
            <div className="text-sm font-mono font-semibold">¥{(summary.total_invested || 0).toLocaleString()}</div>
          </div>
          <div className="rounded-lg border border-border/50 bg-card/50 p-3">
            <div className="text-[10px] text-muted-foreground mb-1">当前市值</div>
            <div className="text-sm font-mono font-semibold">¥{(summary.current_market_value || 0).toLocaleString()}</div>
          </div>
          <div className="rounded-lg border border-border/50 bg-card/50 p-3">
            <div className="text-[10px] text-muted-foreground mb-1">总盈亏</div>
            <div className={`text-sm font-mono font-semibold ${pnlColor(summary.total_pnl)}`}>
              {pnlSign(summary.total_pnl)}¥{Math.abs(summary.total_pnl).toLocaleString()} ({pnlSign(summary.total_pnl_pct)}{summary.total_pnl_pct.toFixed(1)}%)
            </div>
          </div>
          <div className="rounded-lg border border-border/50 bg-card/50 p-3">
            <div className="text-[10px] text-muted-foreground mb-1">持仓/完结</div>
            <div className="text-sm font-mono font-semibold">{summary.active_positions}只 / {summary.completed_trades}笔</div>
          </div>
        </div>
      )}
      {/* Exit stats row */}
      {summary && (summary.sl_count > 0 || summary.tp_count > 0 || summary.mhd_count > 0 || summary.ai_sell_count > 0) && (
        <div className="flex gap-3 text-[10px] text-muted-foreground px-1">
          <span>止损 <span className="text-red-400 font-mono">{summary.sl_count}</span></span>
          <span>止盈 <span className="text-green-400 font-mono">{summary.tp_count}</span></span>
          <span>超期 <span className="text-amber-400 font-mono">{summary.mhd_count}</span></span>
          <span>AI卖出 <span className="text-blue-400 font-mono">{summary.ai_sell_count}</span></span>
        </div>
      )}

      {/* Sub-tabs */}
      <div className="flex gap-1 border-b border-border/30 pb-0">
        {(["holding", "plans", "closed", "diary"] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setSubTab(tab)}
            className={`px-3 py-1.5 text-xs font-medium transition-colors border-b-2 -mb-[1px] ${
              subTab === tab
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab === "holding" ? `当前持仓 (${filteredPortfolio?.length || 0})` : tab === "plans" ? `计划 (${filteredPlans?.filter((p: BotTradePlanItem) => p.status === "pending").length || 0})` : tab === "closed" ? `已完结 (${filteredReviews?.length || 0})` : "日记"}
          </button>
        ))}
      </div>

      {/* Strategy filter */}
      {allStrategyNames.length > 0 && (
        <div className="relative" ref={stratFilterRef}>
          <button
            onClick={() => setStratFilterOpen(v => !v)}
            className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-colors ${
              selectedStrategies.size > 0
                ? "border-primary/50 bg-primary/5 text-primary"
                : "border-border/50 text-muted-foreground hover:text-foreground"
            }`}
          >
            <Filter className="h-3 w-3" />
            {selectedStrategies.size > 0
              ? `已选 ${selectedStrategies.size} 个策略`
              : `筛选策略 (${allStrategyNames.length})`}
            {selectedStrategies.size > 0 && (
              <span
                role="button"
                onClick={e => { e.stopPropagation(); setSelectedStrategies(new Set()); }}
                className="ml-1 hover:text-destructive"
              >
                <X className="h-3 w-3" />
              </span>
            )}
          </button>
          {stratFilterOpen && (
            <div className="absolute z-50 mt-1 w-80 max-h-64 overflow-y-auto rounded-lg border border-border bg-popover shadow-lg p-1">
              {/* Select all / clear */}
              <div className="flex gap-2 px-2 py-1.5 border-b border-border/30 mb-1">
                <button
                  onClick={() => setSelectedStrategies(new Set(allStrategyNames))}
                  className="text-[10px] text-primary hover:underline"
                >全选</button>
                <button
                  onClick={() => setSelectedStrategies(new Set())}
                  className="text-[10px] text-muted-foreground hover:underline"
                >清除</button>
              </div>
              {allStrategyNames.map(name => (
                <label
                  key={name}
                  className="flex items-center gap-2 px-2 py-1 rounded hover:bg-accent/50 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    className="rounded border-border"
                    checked={selectedStrategies.has(name)}
                    onChange={() => {
                      setSelectedStrategies(prev => {
                        const next = new Set(prev);
                        if (next.has(name)) next.delete(name);
                        else next.add(name);
                        return next;
                      });
                    }}
                  />
                  <span className="text-[11px] truncate">{name}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Holdings */}
      {subTab === "holding" && (
        <div className="space-y-3">
          {(!filteredPortfolio || filteredPortfolio.length === 0) ? (
            <div className="text-center text-muted-foreground text-sm py-10">暂无持仓</div>
          ) : filteredPortfolio.map(h => { const tlKey = h.strategy_id != null ? `${h.stock_code}_${h.strategy_id}` : h.stock_code; return (
            <div key={h.id} className="rounded-lg border border-border/50 bg-card/30 overflow-hidden">
              <button
                onClick={() => loadTimeline(h.stock_code, h.strategy_id ?? undefined)}
                className="w-full text-left p-3 hover:bg-accent/30 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-medium text-sm">{h.stock_name}</span>
                    <span className="text-xs text-muted-foreground ml-2">{h.stock_code}</span>
                  </div>
                  <div className="text-right">
                    {h.close != null && (
                      <div className="text-sm font-mono">¥{h.close.toFixed(2)}</div>
                    )}
                    {h.pnl != null && (
                      <div className={`text-xs font-mono ${pnlColor(h.pnl)}`}>
                        {pnlSign(h.pnl)}¥{Math.abs(h.pnl).toLocaleString()} ({pnlSign(h.pnl_pct || 0)}{(h.pnl_pct || 0).toFixed(1)}%)
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex gap-4 mt-1 text-[10px] text-muted-foreground">
                  <span>{h.quantity}股 × ¥{h.avg_cost.toFixed(2)}</span>
                  <span>投入 ¥{h.total_invested.toLocaleString()}</span>
                  <span>首买 {h.first_buy_date}</span>
                </div>
                {/* Exit config display */}
                {h.exit_config && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {h.exit_config.stop_loss_pct != null && h.sl_price != null && (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
                        h.close != null && h.close < h.sl_price * 1.03
                          ? "border-red-500/50 bg-red-500/10 text-red-400"
                          : "border-border/50 text-muted-foreground"
                      }`}>
                        止损 {h.exit_config.stop_loss_pct}% ¥{h.sl_price.toFixed(2)}
                        {h.close != null && <span className="ml-1">({((h.close - h.sl_price) / h.sl_price * 100).toFixed(1)}%)</span>}
                      </span>
                    )}
                    {h.exit_config.take_profit_pct != null && h.tp_price != null && (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
                        h.close != null && h.close > h.tp_price * 0.97
                          ? "border-green-500/50 bg-green-500/10 text-green-400"
                          : "border-border/50 text-muted-foreground"
                      }`}>
                        止盈 +{h.exit_config.take_profit_pct}% ¥{h.tp_price.toFixed(2)}
                        {h.close != null && <span className="ml-1">({((h.tp_price - h.close) / h.close * 100).toFixed(1)}%)</span>}
                      </span>
                    )}
                    {h.exit_config.max_hold_days != null && h.days_remaining != null && (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
                        h.days_remaining <= 2
                          ? "border-amber-500/50 bg-amber-500/10 text-amber-400"
                          : "border-border/50 text-muted-foreground"
                      }`}>
                        剩余{h.days_remaining}天/{h.exit_config.max_hold_days}天
                      </span>
                    )}
                  </div>
                )}
                {h.strategy_name && (
                  <div className="mt-1 text-[10px] text-muted-foreground/70">策略: {h.strategy_name}</div>
                )}
              </button>

              {/* Expanded timeline */}
              {expandedCode === tlKey && timelines[tlKey] && (
                <div className="border-t border-border/30 p-3 space-y-2">
                  <div className="text-[10px] text-muted-foreground font-medium">交易记录 ({timelines[tlKey].trades.length}笔)</div>
                  {timelines[tlKey].trades.map((t: BotTradeItem) => (
                    <div key={t.id} className="flex items-start gap-2 text-xs">
                      <span className={`mt-0.5 ${t.action === "buy" ? "text-red-400" : t.action === "hold" ? "text-muted-foreground" : "text-green-400"}`}>
                        {t.action === "buy" ? "+" : t.action === "hold" ? "=" : "-"}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-muted-foreground">{t.trade_date}</span>
                          <span className="font-medium">
                            {t.action === "buy" ? "买入" : t.action === "sell" ? "卖出" : t.action === "reduce" ? "减仓" : "持有"}
                          </span>
                          {t.sell_reason && t.action !== "buy" && t.action !== "hold" && (
                            <span className={`text-[10px] px-1 py-0.5 rounded ${
                              t.sell_reason === "stop_loss" ? "bg-red-500/10 text-red-400" :
                              t.sell_reason === "take_profit" ? "bg-green-500/10 text-green-400" :
                              t.sell_reason === "max_hold" ? "bg-amber-500/10 text-amber-400" :
                              "bg-blue-500/10 text-blue-400"
                            }`}>
                              {t.sell_reason === "stop_loss" ? "止损" :
                               t.sell_reason === "take_profit" ? "止盈" :
                               t.sell_reason === "max_hold" ? "超期" : "AI"}
                            </span>
                          )}
                          {t.quantity > 0 && <span className="font-mono">{t.quantity}股 @¥{t.price.toFixed(2)}</span>}
                        </div>
                        {t.thinking && (
                          <div className="text-muted-foreground mt-0.5 line-clamp-2">{t.thinking}</div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ); })}
        </div>
      )}

      {/* Plans */}
      {subTab === "plans" && (
        <div className="space-y-2">
          {!filteredPlans?.length ? (
            <p className="text-center text-muted-foreground py-8">暂无交易计划</p>
          ) : (
            <>
              {/* Pending count header */}
              {(() => {
                const pending = filteredPlans.filter((p: BotTradePlanItem) => p.status === "pending");
                return pending.length > 0 ? (
                  <div className="text-xs text-muted-foreground mb-1">
                    待执行 {pending.length} 个计划 · 按置信度排序
                  </div>
                ) : null;
              })()}

              {/* Pending plans */}
              {filteredPlans.filter((p: BotTradePlanItem) => p.status === "pending").map((plan: BotTradePlanItem, idx: number) => (
                <details key={plan.id} className="group" open={idx < 5}>
                  <summary className={`cursor-pointer list-none rounded-lg border p-3 transition-colors hover:bg-accent/30 ${
                    plan.confidence != null && plan.confidence >= 60 ? "border-emerald-500/40 bg-emerald-500/5" :
                    plan.confidence != null && plan.confidence < 40 ? "border-red-500/40 bg-red-500/5" :
                    plan.confidence != null ? "border-amber-500/40 bg-amber-500/5" :
                    plan.source === "stop_loss" ? "border-red-500/40 bg-red-500/5" :
                    plan.source === "take_profit" ? "border-green-500/40 bg-green-500/5" :
                    "border-border bg-card/50"
                  }`}>
                    {/* Row 1: Grade + Stock + Price + Score */}
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className={`shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded tabular-nums ${
                          plan.confidence != null && plan.confidence >= 60 ? "bg-emerald-500/15 text-emerald-500" :
                          plan.confidence != null && plan.confidence >= 40 ? "bg-amber-500/15 text-amber-500" :
                          plan.confidence != null ? "bg-red-500/15 text-red-500" :
                          plan.source === "stop_loss" ? "bg-red-500/15 text-red-500" :
                          plan.source === "take_profit" ? "bg-green-500/15 text-green-500" :
                          plan.source === "beta" ? "bg-blue-500/15 text-blue-500" :
                          plan.direction === "buy" ? "bg-emerald-500/15 text-emerald-500" :
                          "bg-red-500/15 text-red-500"
                        }`}>
                          {plan.confidence != null ? `${plan.confidence.toFixed(0)}%` :
                           plan.source === "stop_loss" ? "止损" :
                           plan.source === "take_profit" ? "止盈" :
                           plan.source === "max_hold" ? "超期" :
                           plan.source === "beta" ? "Beta" :
                           plan.direction === "buy" ? "买入" : "卖出"}
                        </span>
                        <span className="font-mono font-bold text-sm">{plan.stock_code}</span>
                        <span className="text-sm truncate">{plan.stock_name || "—"}</span>
                        {plan.today_close != null && (
                          <span className="flex items-center gap-1 text-xs shrink-0">
                            <span className="font-medium">¥{plan.today_close.toFixed(2)}</span>
                            <span className={plan.today_change_pct != null && plan.today_change_pct >= 0 ? "text-red-500" : "text-green-500"}>
                              {plan.today_change_pct != null ? `${plan.today_change_pct >= 0 ? "+" : ""}${plan.today_change_pct.toFixed(2)}%` : ""}
                            </span>
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {plan.combined_score != null && (
                          <span className="text-xs font-bold tabular-nums" style={{
                            color: plan.combined_score >= 30 ? "var(--chart-2, #22c55e)" :
                                   plan.combined_score >= 15 ? "var(--chart-4, #eab308)" :
                                   "var(--muted-foreground)"
                          }}>
                            {plan.combined_score.toFixed(1)}
                          </span>
                        )}
                        <span className="text-[10px] text-muted-foreground">{plan.plan_date}</span>
                        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground/50 transition-transform group-open:rotate-180" />
                      </div>
                    </div>

                    {/* Row 2: Strategy + Scores mini bar */}
                    <div className="mt-1.5 flex items-center gap-3 text-[11px] text-muted-foreground">
                      {plan.strategy_name && (
                        <span className="truncate max-w-[120px]" title={plan.strategy_name}>
                          {plan.strategy_name.replace(/.*\]\s*/, "").split("_").slice(0, 3).join("_")}
                        </span>
                      )}
                      {plan.alpha_score != null && (
                        <span className="tabular-nums">α{plan.alpha_score.toFixed(1)}</span>
                      )}
                      {plan.beta_score != null && (
                        <span className="tabular-nums">β{(plan.beta_score * 100).toFixed(0)}</span>
                      )}
                      {plan.gamma_score != null && (
                        <span className="tabular-nums" style={{
                          color: plan.gamma_score >= 60 ? "var(--chart-2, #22c55e)" :
                                 plan.gamma_score >= 30 ? "var(--chart-4, #eab308)" : "inherit"
                        }}>γ{plan.gamma_score.toFixed(1)}</span>
                      )}
                      {plan.phase && (
                        <span className={`px-1 py-0.5 rounded text-[10px] ${
                          plan.phase === "cold" ? "bg-sky-500/10 text-sky-500" :
                          plan.phase === "warm" ? "bg-amber-500/10 text-amber-500" :
                          "bg-emerald-500/10 text-emerald-500"
                        }`}>
                          {plan.phase === "cold" ? "冷启动" : plan.phase === "warm" ? "预热" : "成熟"}
                        </span>
                      )}
                      <span className="ml-auto tabular-nums">¥{plan.plan_price.toFixed(2)} × {plan.quantity}</span>
                    </div>
                  </summary>

                  {/* Expanded detail panel */}
                  <div className="border border-t-0 border-border rounded-b-lg px-3 pb-3 pt-2 bg-muted/20 space-y-2.5 text-xs">
                    {/* Score breakdown */}
                    {(plan.alpha_score != null || plan.beta_score != null) && (
                      <div className="grid grid-cols-4 gap-1.5">
                        <div className="rounded-md bg-background/60 p-1.5 text-center">
                          <div className="text-[10px] text-muted-foreground">Alpha</div>
                          <div className="font-bold tabular-nums text-sm">{plan.alpha_score != null ? plan.alpha_score.toFixed(1) : "—"}</div>
                        </div>
                        <div className="rounded-md bg-background/60 p-1.5 text-center">
                          <div className="text-[10px] text-muted-foreground">Beta</div>
                          <div className="font-bold tabular-nums text-sm">{plan.beta_score != null ? (plan.beta_score * 100).toFixed(0) : "—"}</div>
                        </div>
                        <div className="rounded-md bg-background/60 p-1.5 text-center">
                          <div className="text-[10px] text-muted-foreground">Gamma</div>
                          <div className="font-bold tabular-nums text-sm" style={{
                            color: plan.gamma_score != null && plan.gamma_score >= 60 ? "var(--chart-2, #22c55e)" :
                                   plan.gamma_score != null && plan.gamma_score >= 30 ? "var(--chart-4, #eab308)" :
                                   "inherit"
                          }}>{plan.gamma_score != null ? plan.gamma_score.toFixed(1) : "—"}</div>
                        </div>
                        <div className="rounded-md bg-background/60 p-1.5 text-center">
                          <div className="text-[10px] text-muted-foreground">综合</div>
                          <div className="font-bold tabular-nums text-sm" style={{
                            color: plan.combined_score != null && plan.combined_score >= 0.8 ? "var(--chart-2, #22c55e)" :
                                   plan.combined_score != null && plan.combined_score >= 0.5 ? "var(--chart-4, #eab308)" :
                                   "inherit"
                          }}>{plan.combined_score != null ? plan.combined_score.toFixed(2) : "—"}</div>
                        </div>
                      </div>
                    )}

                    {/* Exit config */}
                    {(plan.stop_loss_pct != null || plan.take_profit_pct != null || plan.max_hold_days != null) && (
                      <div className="flex gap-3 text-muted-foreground">
                        {plan.stop_loss_pct != null && (
                          <span>止损: <span className="text-red-500 font-medium">{plan.stop_loss_pct}%</span></span>
                        )}
                        {plan.take_profit_pct != null && (
                          <span>止盈: <span className="text-green-500 font-medium">{plan.take_profit_pct}%</span></span>
                        )}
                        {plan.max_hold_days != null && (
                          <span>MHD: <span className="text-foreground font-medium">{plan.max_hold_days}天</span></span>
                        )}
                      </div>
                    )}

                    {/* Buy conditions */}
                    {plan.buy_conditions && plan.buy_conditions.length > 0 && (
                      <div>
                        <div className="text-[10px] text-muted-foreground/70 mb-1">买入条件</div>
                        <div className="flex flex-wrap gap-1">
                          {plan.buy_conditions.map((c: Record<string, unknown>, i: number) => (
                            <span key={i} className="inline-flex items-center px-1.5 py-0.5 rounded bg-emerald-500/8 text-emerald-600 dark:text-emerald-400 text-[10px] font-mono">
                              {formatCondition(c)}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Sell conditions */}
                    {plan.sell_conditions && plan.sell_conditions.length > 0 && (
                      <div>
                        <div className="text-[10px] text-muted-foreground/70 mb-1">卖出条件</div>
                        <div className="flex flex-wrap gap-1">
                          {plan.sell_conditions.map((c: Record<string, unknown>, i: number) => (
                            <span key={i} className="inline-flex items-center px-1.5 py-0.5 rounded bg-red-500/8 text-red-600 dark:text-red-400 text-[10px] font-mono">
                              {formatCondition(c)}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Market data detail */}
                    {plan.today_close != null && (
                      <div className="flex gap-3 text-muted-foreground">
                        <span>现价: <span className="text-foreground font-medium">¥{plan.today_close.toFixed(2)}</span></span>
                        {plan.today_high != null && <span>最高: ¥{plan.today_high.toFixed(2)}</span>}
                        {plan.today_low != null && <span>最低: ¥{plan.today_low.toFixed(2)}</span>}
                        <span>计划价: <span className="text-foreground">¥{plan.plan_price.toFixed(2)}</span></span>
                        <span>金额: <span className="text-foreground">¥{(plan.plan_price * plan.quantity).toLocaleString()}</span></span>
                      </div>
                    )}

                    {/* Gamma details */}
                    {plan.gamma_score != null && (
                      <div>
                        <div className="text-[10px] text-muted-foreground/70 mb-1">缠论 (Gamma)</div>
                        <div className="grid grid-cols-3 gap-1.5">
                          <div className="rounded-md bg-background/60 p-1.5 text-center">
                            <div className="text-[10px] text-muted-foreground">日线强度</div>
                            <div className="font-bold tabular-nums text-xs">{plan.gamma_daily_strength != null ? plan.gamma_daily_strength.toFixed(1) : "—"}</div>
                          </div>
                          <div className="rounded-md bg-background/60 p-1.5 text-center">
                            <div className="text-[10px] text-muted-foreground">周线共振</div>
                            <div className="font-bold tabular-nums text-xs">{plan.gamma_weekly_resonance != null ? plan.gamma_weekly_resonance.toFixed(1) : "—"}</div>
                          </div>
                          <div className="rounded-md bg-background/60 p-1.5 text-center">
                            <div className="text-[10px] text-muted-foreground">结构健康</div>
                            <div className="font-bold tabular-nums text-xs">{plan.gamma_structure_health != null ? plan.gamma_structure_health.toFixed(1) : "—"}</div>
                          </div>
                        </div>
                        {(plan.gamma_daily_mmd || plan.gamma_weekly_mmd) && (
                          <div className="mt-1 flex gap-2 text-[10px]">
                            {plan.gamma_daily_mmd && (
                              <span className="px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-500 font-medium">
                                日{plan.gamma_daily_mmd}
                              </span>
                            )}
                            {plan.gamma_weekly_mmd && (
                              <span className="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-500 font-medium">
                                周{plan.gamma_weekly_mmd}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Strategy name (truncated) */}
                    {plan.strategy_name && (
                      <div className="text-[10px] text-muted-foreground truncate" title={plan.strategy_name}>
                        策略: {plan.strategy_name}
                      </div>
                    )}
                  </div>
                </details>
              ))}

              {/* Executed/Expired plans */}
              {filteredPlans.filter((p: BotTradePlanItem) => p.status !== "pending").length > 0 && (
                <details className="mt-4">
                  <summary className="text-sm text-muted-foreground cursor-pointer hover:text-foreground transition-colors">
                    历史计划 ({filteredPlans.filter((p: BotTradePlanItem) => p.status !== "pending").length})
                  </summary>
                  <div className="mt-2 space-y-1.5">
                    {filteredPlans.filter((p: BotTradePlanItem) => p.status !== "pending").map((plan: BotTradePlanItem) => (
                      <div key={plan.id} className="border border-border/50 rounded-lg p-2 opacity-60 hover:opacity-80 transition-opacity">
                        <div className="flex items-center justify-between text-sm">
                          <div className="flex items-center gap-2">
                            <span className={plan.direction === "buy" ? "text-emerald-500" : "text-red-500"}>
                              {plan.direction === "buy" ? "买" : "卖"}
                            </span>
                            <span className="font-mono">{plan.stock_code}</span>
                            <span className="text-muted-foreground text-xs">{plan.stock_name}</span>
                            {plan.combined_score != null && (
                              <span className="text-[10px] tabular-nums text-muted-foreground">
                                综合{plan.combined_score.toFixed(1)}
                              </span>
                            )}
                          </div>
                          <span className={`text-[10px] px-1.5 py-0.5 rounded ${plan.status === "executed" ? "bg-green-500/10 text-green-500" : "bg-muted text-muted-foreground"}`}>
                            {plan.status === "executed" ? "已执行" : "已过期"}
                          </span>
                        </div>
                        <div className="mt-1 flex gap-3 text-[11px] text-muted-foreground">
                          <span>¥{plan.plan_price.toFixed(2)}</span>
                          <span>{plan.quantity}股</span>
                          <span>{plan.plan_date}</span>
                          {plan.strategy_name && <span className="truncate max-w-[150px]">{plan.strategy_name}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </>
          )}
        </div>
      )}

      {/* Closed trades (reviews) */}
      {subTab === "closed" && (
        <div className="space-y-3">
          {(!filteredReviews || filteredReviews.length === 0) ? (
            <div className="text-center text-muted-foreground text-sm py-10">暂无已完结交易</div>
          ) : filteredReviews.map(r => (
            <div key={r.id} className="rounded-lg border border-border/50 bg-card/30 overflow-hidden">
              <button
                onClick={() => loadTimeline(r.stock_code)}
                className="w-full text-left p-3 hover:bg-accent/30 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-medium text-sm">{r.stock_name}</span>
                    <span className="text-xs text-muted-foreground ml-2">{r.stock_code}</span>
                    <span className={`ml-2 text-[10px] px-1.5 py-0.5 rounded ${r.pnl > 0 ? "bg-red-500/10 text-red-400" : "bg-green-500/10 text-green-400"}`}>
                      {r.pnl > 0 ? "盈利" : "亏损"}
                    </span>
                    {r.memory_synced && (
                      <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400">记忆已同步</span>
                    )}
                  </div>
                  <div className={`text-sm font-mono ${pnlColor(r.pnl)}`}>
                    {pnlSign(r.pnl)}¥{Math.abs(r.pnl).toLocaleString()} ({pnlSign(r.pnl_pct)}{r.pnl_pct.toFixed(1)}%)
                  </div>
                </div>
                <div className="flex gap-4 mt-1 text-[10px] text-muted-foreground">
                  <span>持有 {r.holding_days}天</span>
                  <span>{r.first_buy_date} → {r.last_sell_date}</span>
                </div>
              </button>

              {/* Expanded timeline + review */}
              {expandedCode === r.stock_code && timelines[r.stock_code] && (
                <div className="border-t border-border/30 p-3 space-y-3">
                  <div className="text-[10px] text-muted-foreground font-medium">交易记录</div>
                  {timelines[r.stock_code].trades.map((t: BotTradeItem) => (
                    <div key={t.id} className="flex items-start gap-2 text-xs">
                      <span className={`mt-0.5 ${t.action === "buy" ? "text-red-400" : t.action === "hold" ? "text-muted-foreground" : "text-green-400"}`}>
                        {t.action === "buy" ? "+" : t.action === "hold" ? "=" : "-"}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-muted-foreground">{t.trade_date}</span>
                          <span className="font-medium">
                            {t.action === "buy" ? "买入" : t.action === "sell" ? "卖出" : t.action === "reduce" ? "减仓" : "持有"}
                          </span>
                          {t.sell_reason && t.action !== "buy" && t.action !== "hold" && (
                            <span className={`text-[10px] px-1 py-0.5 rounded ${
                              t.sell_reason === "stop_loss" ? "bg-red-500/10 text-red-400" :
                              t.sell_reason === "take_profit" ? "bg-green-500/10 text-green-400" :
                              t.sell_reason === "max_hold" ? "bg-amber-500/10 text-amber-400" :
                              "bg-blue-500/10 text-blue-400"
                            }`}>
                              {t.sell_reason === "stop_loss" ? "止损" :
                               t.sell_reason === "take_profit" ? "止盈" :
                               t.sell_reason === "max_hold" ? "超期" : "AI"}
                            </span>
                          )}
                          {t.quantity > 0 && <span className="font-mono">{t.quantity}股 @¥{t.price.toFixed(2)}</span>}
                        </div>
                        {t.thinking && (
                          <div className="text-muted-foreground mt-0.5 line-clamp-2">{t.thinking}</div>
                        )}
                      </div>
                    </div>
                  ))}

                  {/* Review content */}
                  {r.review_thinking && (
                    <div className="mt-3 pt-3 border-t border-border/30">
                      <div className="text-[10px] text-muted-foreground font-medium mb-1">复盘分析</div>
                      <div className="text-xs text-muted-foreground whitespace-pre-line">{r.review_thinking}</div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {subTab === "diary" && (
        <div className="space-y-4">
          {/* Date picker */}
          <div className="flex items-center gap-2">
            <button onClick={() => {
              const d = new Date(diaryDate);
              d.setDate(d.getDate() - 1);
              setDiaryDate(d.toISOString().slice(0, 10));
            }} className="px-2 py-1 rounded hover:bg-muted text-muted-foreground">&lt;</button>
            <input type="date" value={diaryDate} onChange={e => setDiaryDate(e.target.value)}
              className="bg-background border border-border rounded px-2 py-1 text-sm" />
            <button onClick={() => {
              const d = new Date(diaryDate);
              d.setDate(d.getDate() + 1);
              setDiaryDate(d.toISOString().slice(0, 10));
            }} className="px-2 py-1 rounded hover:bg-muted text-muted-foreground">&gt;</button>
            <button onClick={() => setDiaryDate(new Date().toISOString().slice(0, 10))}
              className="text-xs text-muted-foreground hover:text-foreground">今天</button>
          </div>

          {!diary ? (
            <div className="text-center text-muted-foreground py-8">加载中...</div>
          ) : (
            <>
              {/* Refresh pipeline */}
              <div className="border border-border rounded-lg p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium">Do-Refresh 流程</span>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    diary.refresh.status === "succeeded" ? "bg-green-500/10 text-green-500" :
                    diary.refresh.status === "running" ? "bg-blue-500/10 text-blue-500" :
                    diary.refresh.status === "failed" ? "bg-red-500/10 text-red-500" :
                    "bg-muted text-muted-foreground"
                  }`}>
                    {diary.refresh.status === "succeeded" ? "已完成" :
                     diary.refresh.status === "running" ? "进行中" :
                     diary.refresh.status === "failed" ? "失败" : "未开始"}
                  </span>
                </div>
                {diary.refresh.duration_sec != null && (
                  <div className="text-[10px] text-muted-foreground mb-2">
                    耗时: {Math.round(diary.refresh.duration_sec / 60)}分钟
                  </div>
                )}
                <div className="space-y-1">
                  {diary.refresh.steps.map((step, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className="w-4 text-center shrink-0">
                        {step.status === "done" ? "\u2705" :
                         step.status === "running" ? "\uD83D\uDD04" :
                         step.status === "failed" ? "\u274C" : "\u23F3"}
                      </span>
                      <span className={`flex-1 ${step.status === "pending" ? "text-muted-foreground" : ""}`}>
                        {step.name}
                      </span>
                      {step.progress && (
                        <span className="text-muted-foreground font-mono text-[10px]">{step.progress}</span>
                      )}
                      {step.detail && step.status === "done" && (
                        <span className="text-muted-foreground text-[10px]">{step.detail}</span>
                      )}
                      {step.error && (
                        <span className="text-red-500 truncate max-w-[200px] text-[10px]" title={step.error}>{step.error}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Execution */}
              <div className="border border-border rounded-lg p-3">
                <div className="text-sm font-medium mb-2">今日交易执行</div>
                <div className="text-[10px] text-muted-foreground mb-1">
                  计划 {diary.execution.summary.executed}/{diary.execution.summary.plans_total} 执行
                  {diary.execution.summary.sells_tp + diary.execution.summary.sells_sl > 0 && (
                    <span> + {diary.execution.summary.sells_tp + diary.execution.summary.sells_sl} 退出监控</span>
                  )}
                </div>
                <div className="flex flex-wrap gap-2 text-xs mb-3">
                  <span className="px-2 py-1 rounded bg-emerald-500/10 text-emerald-500">买入 {diary.execution.summary.buys}</span>
                  {diary.execution.summary.sells_tp > 0 && <span className="px-2 py-1 rounded bg-green-500/10 text-green-500">止盈 {diary.execution.summary.sells_tp}</span>}
                  {diary.execution.summary.sells_sl > 0 && <span className="px-2 py-1 rounded bg-red-500/10 text-red-500">止损 {diary.execution.summary.sells_sl}</span>}
                  {diary.execution.summary.sells_mhd > 0 && <span className="px-2 py-1 rounded bg-amber-500/10 text-amber-500">超期 {diary.execution.summary.sells_mhd}</span>}
                  {(diary.execution.summary.sells_signal ?? 0) > 0 && <span className="px-2 py-1 rounded bg-blue-500/10 text-blue-500">信号 {diary.execution.summary.sells_signal}</span>}
                  {diary.execution.summary.sells_ai > 0 && <span className="px-2 py-1 rounded bg-purple-500/10 text-purple-500">AI {diary.execution.summary.sells_ai}</span>}
                  <span className="px-2 py-1 rounded bg-muted text-muted-foreground">过期 {diary.execution.summary.expired}</span>
                </div>

                {diary.execution.buy_list.length > 0 && (
                  <details open={diary.execution.buy_list.length <= 20}>
                    <summary className="text-xs text-muted-foreground cursor-pointer mb-1">买入明细 ({diary.execution.buy_list.length})</summary>
                    <div className="space-y-1.5 mt-1">
                      {diary.execution.buy_list.map((b, i) => (
                        <div key={i} className="text-xs border-l-2 border-emerald-500 pl-2">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-bold">{b.code}</span>
                            <span>{b.name}</span>
                            <span className="text-muted-foreground">¥{b.price}×{b.quantity.toLocaleString()}</span>
                            {b.combined != null && <span className="text-emerald-500 font-medium">{b.combined.toFixed(2)}</span>}
                          </div>
                          <div className="text-muted-foreground text-[10px]">
                            {b.strategy_name && <span>{b.strategy_name.split("_").slice(0, 3).join("_")} </span>}
                            {b.trigger && <span>| {b.trigger} </span>}
                            {b.alpha != null && <span>α{b.alpha.toFixed(0)} </span>}
                            {b.gamma != null && <span>γ{b.gamma.toFixed(1)}</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  </details>
                )}

                {diary.execution.sell_list.length > 0 && (
                  <details className="mt-2">
                    <summary className="text-xs text-muted-foreground cursor-pointer mb-1">卖出明细 ({diary.execution.sell_list.length})</summary>
                    <div className="space-y-1.5 mt-1">
                      {diary.execution.sell_list.map((s, i) => (
                        <div key={i} className="text-xs border-l-2 border-red-500 pl-2">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-bold">{s.code}</span>
                            <span>{s.name}</span>
                            <span className="text-muted-foreground">¥{s.price}×{s.quantity.toLocaleString()}</span>
                            <span className={`px-1 py-0.5 rounded text-[10px] ${
                              s.reason === "take_profit" ? "bg-green-500/10 text-green-500" :
                              s.reason === "stop_loss" ? "bg-red-500/10 text-red-500" :
                              "bg-muted text-muted-foreground"
                            }`}>{s.reason_label}</span>
                          </div>
                          {s.trigger && <div className="text-[10px] text-muted-foreground">{s.trigger}</div>}
                        </div>
                      ))}
                    </div>
                  </details>
                )}

                {diary.execution.expired_list.length > 0 && (
                  <details className="mt-2">
                    <summary className="text-xs text-muted-foreground cursor-pointer mb-1">过期未触发 ({diary.execution.expired_list.length})</summary>
                    <div className="space-y-1 mt-1">
                      {diary.execution.expired_list.slice(0, 50).map((e, i) => (
                        <div key={i} className="text-[10px] text-muted-foreground flex gap-2">
                          <span className="font-mono">{e.code}</span>
                          <span>{e.name}</span>
                          <span>{e.reason}</span>
                        </div>
                      ))}
                      {diary.execution.expired_list.length > 50 && (
                        <div className="text-[10px] text-muted-foreground">...还有{diary.execution.expired_list.length - 50}条</div>
                      )}
                    </div>
                  </details>
                )}
              </div>

              {/* Signals & Plans */}
              <div className="border border-border rounded-lg p-3">
                <div className="text-sm font-medium mb-2">信号 & 明日计划 ({diary.plans_created.for_date})</div>
                <div className="flex gap-3 text-xs mb-3 text-muted-foreground">
                  <span>信号: {diary.signals.generated} (买{diary.signals.buy_signals} 卖{diary.signals.sell_signals})</span>
                  <span>|</span>
                  <span>明日: {diary.plans_created.summary.buy}买 + {diary.plans_created.summary.sell_tp + diary.plans_created.summary.sell_sl + diary.plans_created.summary.sell_mhd + diary.plans_created.summary.sell_signal}卖</span>
                </div>

                {diary.plans_created.buy_list.length > 0 && (
                  <details open>
                    <summary className="text-xs text-muted-foreground cursor-pointer mb-1">买入计划 ({diary.plans_created.buy_list.length})</summary>
                    <div className="space-y-1.5 mt-1">
                      {diary.plans_created.buy_list.map((p, i) => (
                        <div key={i} className="text-xs border-l-2 border-emerald-500 pl-2">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-bold">{p.code}</span>
                            <span>{p.name}</span>
                            {p.plan_price && <span className="text-muted-foreground">@¥{p.plan_price.toFixed(2)}</span>}
                            {p.combined != null && <span className="text-emerald-500 font-medium">{p.combined.toFixed(2)}</span>}
                          </div>
                          <div className="text-[10px] text-muted-foreground">{p.reason}</div>
                          <div className="text-[10px] flex gap-2">
                            {p.alpha != null && <span>α{p.alpha.toFixed(0)}</span>}
                            {p.gamma != null && <span>γ{p.gamma.toFixed(1)}</span>}
                            {p.gamma_daily_mmd && (
                              <span className="px-1 py-0.5 rounded bg-violet-500/10 text-violet-500">日{p.gamma_daily_mmd}</span>
                            )}
                            {p.gamma_weekly_mmd && (
                              <span className="px-1 py-0.5 rounded bg-blue-500/10 text-blue-500">周{p.gamma_weekly_mmd}</span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </details>
                )}

                {diary.plans_created.sell_list.length > 0 && (
                  <details className="mt-2">
                    <summary className="text-xs text-muted-foreground cursor-pointer mb-1">卖出计划 ({diary.plans_created.sell_list.length})</summary>
                    <div className="space-y-1 mt-1">
                      {diary.plans_created.sell_list.slice(0, 50).map((s, i) => (
                        <div key={i} className="text-[10px] text-muted-foreground flex gap-2">
                          <span className="font-mono">{s.code}</span>
                          <span>{s.name}</span>
                          <span className={`px-1 py-0.5 rounded ${
                            s.source === "take_profit" ? "bg-green-500/10 text-green-500" :
                            s.source === "stop_loss" ? "bg-red-500/10 text-red-500" :
                            s.source === "max_hold" ? "bg-amber-500/10 text-amber-500" :
                            "bg-muted"
                          }`}>{s.source_label}</span>
                          <span>{s.reason}</span>
                        </div>
                      ))}
                      {diary.plans_created.sell_list.length > 50 && (
                        <div className="text-[10px] text-muted-foreground">...还有{diary.plans_created.sell_list.length - 50}条</div>
                      )}
                    </div>
                  </details>
                )}
              </div>

              {/* Portfolio snapshot */}
              {diary.portfolio_snapshot && (
                <div className="border border-border rounded-lg p-3">
                  <div className="text-sm font-medium mb-1">持仓快照</div>
                  <div className="flex gap-4 text-xs text-muted-foreground">
                    <span>持仓 <span className="text-foreground font-medium">{diary.portfolio_snapshot.total_holdings}</span> 只</span>
                    <span>投入 <span className="text-foreground font-medium">¥{(diary.portfolio_snapshot.total_invested / 10000).toFixed(0)}万</span></span>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────

// ── AnalysisProgress ─────────────────────────────────

function AnalysisProgress({
  progress,
  errorMessage,
  onRetry,
}: {
  progress: string;
  errorMessage: string;
  onRetry: () => void;
}) {
  if (errorMessage) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Card className="max-w-sm">
          <CardContent className="pt-6 text-center space-y-3">
            <div className="text-destructive text-sm">{errorMessage}</div>
            <Button variant="outline" size="sm" onClick={onRetry}>
              <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
              重试
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex-1 flex items-center justify-center">
      <Card className="max-w-sm">
        <CardContent className="pt-6 text-center space-y-3">
          <Loader2 className="h-8 w-8 animate-spin mx-auto text-chart-1" />
          <div className="space-y-1">
            <p className="text-sm font-medium">正在分析市场...</p>
            <p className="text-xs text-muted-foreground">{progress}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────

const LS_KEY_JOB = "analysis-job-id";
const LS_KEY_DATE = "analysis-report-date";

function saveAnalysisState(jobId: string, reportDate: string) {
  try {
    localStorage.setItem(LS_KEY_JOB, jobId);
    localStorage.setItem(LS_KEY_DATE, reportDate);
  } catch { /* quota / SSR */ }
}

function clearAnalysisState() {
  try {
    localStorage.removeItem(LS_KEY_JOB);
    localStorage.removeItem(LS_KEY_DATE);
  } catch { /* SSR */ }
}

function loadAnalysisState(): { jobId: string | null; reportDate: string } {
  try {
    return {
      jobId: localStorage.getItem(LS_KEY_JOB),
      reportDate: localStorage.getItem(LS_KEY_DATE) || "",
    };
  } catch {
    return { jobId: null, reportDate: "" };
  }
}

export default function AIPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [analysisJobId, setAnalysisJobId] = useState<string | null>(null);
  const [analysisReportDate, setAnalysisReportDate] = useState<string>("");
  const [mainTab, setMainTab] = useState<"analysis" | "trading">("analysis");
  // Mobile view: "reports" | "content" | "chat"
  const [mobileView, setMobileView] = useState<"reports" | "content" | "chat">("reports");
  // Tablet: show/hide chat overlay
  const [showChat, setShowChat] = useState(false);
  const queryClient = useQueryClient();

  const reportsQuery = useAIReports();
  const reportQuery = useAIReport(selectedId ?? 0);
  const datesQuery = useAIReportDates();
  const triggerMutation = useTriggerAnalysis();
  const pollQuery = useAnalysisPoll(analysisJobId);
  const { data: schedulerStatus } = useAISchedulerStatus();
  const syncMutation = useMutation({
    mutationFn: () => ai.triggerSync(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-scheduler-status"] }),
  });
  const betaAggregateMutation = useMutation({
    mutationFn: () => ai.betaAggregate(),
  });

  // Restore analysis state from localStorage on mount
  useEffect(() => {
    const saved = loadAnalysisState();
    if (saved.jobId) {
      setAnalysisJobId(saved.jobId);
      setAnalysisReportDate(saved.reportDate);
    }
  }, []);

  // Auto-select first report
  useEffect(() => {
    if (!selectedId && !analysisJobId && reportsQuery.data && reportsQuery.data.length > 0) {
      setSelectedId(reportsQuery.data[0].id);
    }
  }, [selectedId, analysisJobId, reportsQuery.data]);

  // Handle analysis completion or error
  useEffect(() => {
    if (!analysisJobId) return;

    // If poll query itself errors (404 — job expired from server memory), clear state
    if (pollQuery.isError) {
      setAnalysisJobId(null);
      setAnalysisReportDate("");
      clearAnalysisState();
      return;
    }

    if (!pollQuery.data) return;
    const { status, reportId } = pollQuery.data;

    if (status === "completed") {
      queryClient.invalidateQueries({ queryKey: ["ai-reports"] });
      queryClient.invalidateQueries({ queryKey: ["ai-report-dates"] });
      if (reportId) {
        setSelectedId(reportId);
      }
      setAnalysisJobId(null);
      setAnalysisReportDate("");
      clearAnalysisState();
    }
    // error status from poll data is shown in UI; user clicks retry to clear
  }, [pollQuery.data, pollQuery.isError, analysisJobId, analysisReportDate, queryClient]);

  const handleTrigger = useCallback(
    (date?: string) => {
      triggerMutation.mutate(date, {
        onSuccess: (data) => {
          setAnalysisJobId(data.jobId);
          setAnalysisReportDate(data.reportDate);
          saveAnalysisState(data.jobId, data.reportDate);
        },
      });
    },
    [triggerMutation],
  );

  const handleRetry = useCallback(() => {
    setAnalysisJobId(null);
    setAnalysisReportDate("");
    clearAnalysisState();
    handleTrigger();
  }, [handleTrigger]);

  const isAnalyzing = !!analysisJobId;
  const reports = reportsQuery.data ?? [];
  const report = reportQuery.data;

  // ── Shared sub-components ──

  const reportListContent = (
    <>
      {/* Scheduler status */}
      {schedulerStatus && (
        <div className="mx-3 mt-2 mb-1 rounded-lg border border-border/40 bg-muted/30 px-3 py-2 text-[11px] space-y-1.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              {schedulerStatus.running ? (
                <CircleCheck className="h-3 w-3 text-green-500" />
              ) : (
                <CircleX className="h-3 w-3 text-red-500" />
              )}
              <span className={schedulerStatus.running ? "text-green-500" : "text-red-500"}>
                {schedulerStatus.running ? "数据同步运行中" : "数据同步已停止"}
              </span>
            </div>
            {schedulerStatus.is_refreshing ? (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 text-amber-500 border-amber-500/30">
                <Loader2 className="h-2.5 w-2.5 animate-spin mr-1" />
                {schedulerStatus.sync_step || "同步中"}
              </Badge>
            ) : (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => betaAggregateMutation.mutate()}
                  disabled={betaAggregateMutation.isPending}
                  className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
                >
                  <Zap className={`h-3 w-3 ${betaAggregateMutation.isPending ? "animate-spin" : ""}`} />
                  {betaAggregateMutation.isSuccess
                    ? `Beta聚合 (${betaAggregateMutation.data?.insights_updated ?? 0})`
                    : "Beta聚合"}
                </button>
                <button
                  onClick={() => syncMutation.mutate()}
                  disabled={syncMutation.isPending}
                  className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
                >
                  <RefreshCw className={`h-3 w-3 ${syncMutation.isPending ? "animate-spin" : ""}`} />
                  立即同步
                </button>
              </div>
            )}
          </div>
          {schedulerStatus.is_refreshing && schedulerStatus.sync_total > 0 && (
            <div className="space-y-0.5">
              <div className="flex items-center justify-between text-muted-foreground">
                <span>{schedulerStatus.sync_step}</span>
                <span>{schedulerStatus.sync_done}/{schedulerStatus.sync_total} ({Math.round(schedulerStatus.sync_done / schedulerStatus.sync_total * 100)}%)</span>
              </div>
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full bg-amber-500 transition-all duration-500"
                  style={{ width: `${Math.round(schedulerStatus.sync_done / schedulerStatus.sync_total * 100)}%` }}
                />
              </div>
            </div>
          )}
          <div className="flex items-center gap-3 text-muted-foreground">
            <div className="flex items-center gap-1">
              <Calendar className="h-3 w-3" />
              <span>最新数据: {schedulerStatus.latest_data_date || "—"}</span>
            </div>
            <div className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              <span>下次同步: {schedulerStatus.next_run_time?.slice(5) || "—"}</span>
            </div>
          </div>
        </div>
      )}
      <div className="py-1">
        {reportsQuery.isLoading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}
        {reports.map((r: AIReportListItem) => (
          <button
            key={r.id}
            onClick={() => {
              setSelectedId(r.id);
              setMobileView("content");
              if (isAnalyzing) {
                setAnalysisJobId(null);
                clearAnalysisState();
              }
            }}
            className={`w-full text-left px-3 py-2 text-sm transition-colors hover:bg-accent/50 ${
              selectedId === r.id && !isAnalyzing
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground"
            }`}
          >
            <div className="flex items-center gap-2">
              <Calendar className="h-3.5 w-3.5 shrink-0" />
              <span className="font-mono text-xs">{r.report_date}</span>
            </div>
            <div className="flex items-center gap-1.5 mt-1">
              {regimeBadge(r.market_regime)}
              <span className="text-xs truncate">{r.report_type}</span>
            </div>
            <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
              {r.summary}
            </p>
          </button>
        ))}
        {!reportsQuery.isLoading && reports.length === 0 && (
          <div className="text-center py-8 text-xs text-muted-foreground">
            <p>暂无报告</p>
            <p className="mt-1">点击上方按钮触发分析</p>
          </div>
        )}
      </div>
    </>
  );

  const mainTabBar = (
    <div className="flex border-b border-border/30 px-4">
      <button
        onClick={() => setMainTab("analysis")}
        className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-[1px] ${
          mainTab === "analysis"
            ? "border-primary text-primary"
            : "border-transparent text-muted-foreground hover:text-foreground"
        }`}
      >
        市场分析
      </button>
      <button
        onClick={() => setMainTab("trading")}
        className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-[1px] ${
          mainTab === "trading"
            ? "border-primary text-primary"
            : "border-transparent text-muted-foreground hover:text-foreground"
        }`}
      >
        AI交易
      </button>
    </div>
  );

  const centerContent = (
    <>
      {mainTab === "analysis" ? (
        <>
          {isAnalyzing ? (
            <AnalysisProgress
              progress={pollQuery.data?.progress || "正在准备分析..."}
              errorMessage={pollQuery.data?.status === "error" ? (pollQuery.data.errorMessage || "分析失败") : ""}
              onRetry={handleRetry}
            />
          ) : reportQuery.isLoading ? (
            <div className="flex-1 flex items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : reportQuery.isError && selectedId ? (
            <div className="flex-1 flex items-center justify-center text-muted-foreground">
              <div className="text-center space-y-2">
                <p className="text-sm">报告加载失败</p>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={isAnalyzing}
                  onClick={() => handleTrigger()}
                >
                  <Sparkles className="h-3.5 w-3.5 mr-1.5" />
                  生成新报告
                </Button>
              </div>
            </div>
          ) : (
            <ReportViewer report={report} />
          )}
        </>
      ) : (
        <ScrollArea className="flex-1">
          <BotTradingPanel />
        </ScrollArea>
      )}
    </>
  );

  // ── Mobile layout (<768px) ──
  // Tab bar at bottom, full-screen panels
  const mobileLayout = (
    <div className="flex flex-col h-[calc(100vh-3rem)] lg:hidden">
      {/* Top bar */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/40 shrink-0">
        {mobileView === "content" ? (
          <>
            <button
              onClick={() => setMobileView("reports")}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
            >
              <ChevronDown className="h-3 w-3 rotate-90" />
              返回
            </button>
            <div className="flex gap-2">
              <button
                onClick={() => setMainTab("analysis")}
                className={`text-xs font-medium px-2 py-1 rounded-md transition-colors ${
                  mainTab === "analysis" ? "bg-primary/10 text-primary" : "text-muted-foreground"
                }`}
              >
                市场分析
              </button>
              <button
                onClick={() => setMainTab("trading")}
                className={`text-xs font-medium px-2 py-1 rounded-md transition-colors ${
                  mainTab === "trading" ? "bg-primary/10 text-primary" : "text-muted-foreground"
                }`}
              >
                AI交易
              </button>
            </div>
            <button
              onClick={() => setMobileView("chat")}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              <MessageSquare className="h-4 w-4" />
            </button>
          </>
        ) : mobileView === "chat" ? (
          <>
            <button
              onClick={() => setMobileView("reports")}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
            >
              <ChevronDown className="h-3 w-3 rotate-90" />
              返回
            </button>
            <span className="text-sm font-medium">AI 对话</span>
            <div className="w-6" />
          </>
        ) : (
          <>
            <div className="flex items-center gap-2 text-sm font-medium">
              <Sparkles className="h-4 w-4 text-chart-1" />
              分析报告
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                disabled={isAnalyzing || triggerMutation.isPending}
                onClick={() => handleTrigger()}
              >
                {isAnalyzing || triggerMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
              </Button>
              <button
                onClick={() => setMobileView("chat")}
                className="text-muted-foreground hover:text-foreground"
              >
                <MessageSquare className="h-4 w-4" />
              </button>
            </div>
          </>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        {mobileView === "reports" && (
          <ScrollArea className="flex-1">
            {reportListContent}
          </ScrollArea>
        )}
        {mobileView === "content" && (
          <div className="flex-1 overflow-y-auto">{centerContent}</div>
        )}
        {mobileView === "chat" && <ChatWidget />}
      </div>

      {/* Bottom tab bar */}
      <div className="flex border-t border-border/40 bg-background shrink-0">
        {([
          { key: "reports" as const, label: "报告", icon: Sparkles },
          { key: "content" as const, label: "分析", icon: Brain },
          { key: "chat" as const, label: "对话", icon: MessageSquare },
        ]).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setMobileView(key)}
            className={`flex-1 flex flex-col items-center gap-0.5 py-2 text-[10px] transition-colors ${
              mobileView === key
                ? "text-primary"
                : "text-muted-foreground"
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>
    </div>
  );

  // ── Desktop layout (>=1024px) ──
  const desktopLayout = (
    <div className="hidden lg:flex h-[calc(100vh-3rem)]">
      {/* Left panel — Report list */}
      <div className="w-56 shrink-0 border-r border-border/40 flex flex-col">
        <div className="flex items-center justify-between px-3 py-2 border-b border-border/40">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Sparkles className="h-4 w-4 text-chart-1" />
            分析报告
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            disabled={isAnalyzing || triggerMutation.isPending}
            onClick={() => handleTrigger()}
            title="触发新分析"
          >
            {isAnalyzing || triggerMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>
        <ScrollArea className="flex-1">
          {reportListContent}
        </ScrollArea>
      </div>

      {/* Center panel */}
      <div className="flex-1 flex flex-col min-w-0">
        {mainTabBar}
        {centerContent}
      </div>

      {/* Right panel — Chat */}
      <div className="w-80 shrink-0 border-l border-border/40">
        <ChatWidget />
      </div>
    </div>
  );

  return (
    <>
      {mobileLayout}
      {desktopLayout}
    </>
  );
}
