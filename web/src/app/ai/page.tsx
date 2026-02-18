"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
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
} from "lucide-react";
import {
  useAIReports,
  useAIReport,
  useAIReportDates,
  useAIChatSend,
  useAIChatPoll,
  useTriggerAnalysis,
  useAnalysisPoll,
} from "@/hooks/use-queries";
import type { AIReport, AIReportListItem } from "@/types";

// ── helpers ────────────────────────────────────────────

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
  const queryClient = useQueryClient();

  const reportsQuery = useAIReports();
  const reportQuery = useAIReport(selectedId ?? 0);
  const datesQuery = useAIReportDates();
  const triggerMutation = useTriggerAnalysis();
  const pollQuery = useAnalysisPoll(analysisJobId);

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

  return (
    <div className="flex h-[calc(100vh-3rem)]">
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
        </ScrollArea>
      </div>

      {/* Center panel — Report viewer / Analysis progress */}
      <div className="flex-1 flex flex-col min-w-0">
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
      </div>

      {/* Right panel — Chat */}
      <div className="w-80 shrink-0 border-l border-border/40">
        <ChatWidget />
      </div>
    </div>
  );
}
