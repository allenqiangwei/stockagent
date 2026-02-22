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
  Clock,
  CircleCheck,
  CircleX,
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
} from "@/hooks/use-queries";
import { bot } from "@/lib/api";
import type { AIReport, AIReportListItem, BotTradeItem, BotStockTimeline, BotTradePlanItem } from "@/types";

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

// ── BotTradingPanel ─────────────────────────────────────

function BotTradingPanel() {
  const { data: summary } = useBotSummary();
  const { data: portfolio } = useBotPortfolio();
  const { data: reviews } = useBotReviews();
  const { data: plans } = useBotPlans();
  const [subTab, setSubTab] = useState<"holding" | "plans" | "closed">("holding");
  const [expandedCode, setExpandedCode] = useState<string | null>(null);
  const [timelines, setTimelines] = useState<Record<string, BotStockTimeline>>({});

  const loadTimeline = async (code: string) => {
    if (timelines[code]) {
      setExpandedCode(expandedCode === code ? null : code);
      return;
    }
    try {
      const data = await bot.timeline(code);
      setTimelines(prev => ({ ...prev, [code]: data }));
      setExpandedCode(code);
    } catch { setExpandedCode(code); }
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

      {/* Sub-tabs */}
      <div className="flex gap-1 border-b border-border/30 pb-0">
        {(["holding", "plans", "closed"] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setSubTab(tab)}
            className={`px-3 py-1.5 text-xs font-medium transition-colors border-b-2 -mb-[1px] ${
              subTab === tab
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab === "holding" ? `当前持仓 (${portfolio?.length || 0})` : tab === "plans" ? `计划 (${plans?.length || 0})` : `已完结 (${reviews?.length || 0})`}
          </button>
        ))}
      </div>

      {/* Holdings */}
      {subTab === "holding" && (
        <div className="space-y-3">
          {(!portfolio || portfolio.length === 0) ? (
            <div className="text-center text-muted-foreground text-sm py-10">暂无持仓</div>
          ) : portfolio.map(h => (
            <div key={h.stock_code} className="rounded-lg border border-border/50 bg-card/30 overflow-hidden">
              <button
                onClick={() => loadTimeline(h.stock_code)}
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
              </button>

              {/* Expanded timeline */}
              {expandedCode === h.stock_code && timelines[h.stock_code] && (
                <div className="border-t border-border/30 p-3 space-y-2">
                  <div className="text-[10px] text-muted-foreground font-medium">交易记录 ({timelines[h.stock_code].trades.length}笔)</div>
                  {timelines[h.stock_code].trades.map((t: BotTradeItem) => (
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
          ))}
        </div>
      )}

      {/* Plans */}
      {subTab === "plans" && (
        <div className="space-y-3">
          {!plans?.length ? (
            <p className="text-center text-muted-foreground py-8">暂无交易计划</p>
          ) : (
            <>
              {/* Pending plans */}
              {plans.filter((p: BotTradePlanItem) => p.status === "pending").map((plan: BotTradePlanItem) => (
                <div key={plan.id} className="border border-amber-300 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-700 rounded-lg p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${plan.direction === "buy" ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"}`}>
                        {plan.direction === "buy" ? "买入" : "卖出"}
                      </span>
                      <span className="font-mono font-bold">{plan.stock_code}</span>
                      <span className="text-muted-foreground text-sm">{plan.stock_name}</span>
                    </div>
                    <span className="text-xs text-amber-600 dark:text-amber-400 font-medium">待执行 {plan.plan_date}</span>
                  </div>
                  <div className="mt-2 flex gap-4 text-sm text-muted-foreground">
                    <span>目标价: <span className="text-foreground">¥{plan.plan_price.toFixed(2)}</span></span>
                    <span>数量: <span className="text-foreground">{plan.quantity}</span></span>
                    {plan.direction === "sell" && <span>比例: <span className="text-foreground">{plan.sell_pct}%</span></span>}
                  </div>
                  {plan.thinking && (
                    <p className="mt-2 text-xs text-muted-foreground line-clamp-2">{plan.thinking}</p>
                  )}
                </div>
              ))}

              {/* Executed/Expired plans */}
              {plans.filter((p: BotTradePlanItem) => p.status !== "pending").length > 0 && (
                <details className="mt-4">
                  <summary className="text-sm text-muted-foreground cursor-pointer">
                    历史计划 ({plans.filter((p: BotTradePlanItem) => p.status !== "pending").length})
                  </summary>
                  <div className="mt-2 space-y-2">
                    {plans.filter((p: BotTradePlanItem) => p.status !== "pending").map((plan: BotTradePlanItem) => (
                      <div key={plan.id} className="border border-border rounded-lg p-2 opacity-60">
                        <div className="flex items-center justify-between text-sm">
                          <div className="flex items-center gap-2">
                            <span className={plan.direction === "buy" ? "text-green-600" : "text-red-600"}>
                              {plan.direction === "buy" ? "买" : "卖"}
                            </span>
                            <span className="font-mono">{plan.stock_code}</span>
                            <span className="text-muted-foreground">{plan.stock_name}</span>
                          </div>
                          <span className={`text-xs px-1.5 py-0.5 rounded ${plan.status === "executed" ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" : "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400"}`}>
                            {plan.status === "executed" ? "已执行" : "已过期"}
                          </span>
                        </div>
                        <div className="mt-1 flex gap-3 text-xs text-muted-foreground">
                          <span>¥{plan.plan_price.toFixed(2)}</span>
                          <span>{plan.quantity}股</span>
                          <span>{plan.plan_date}</span>
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
          {(!reviews || reviews.length === 0) ? (
            <div className="text-center text-muted-foreground text-sm py-10">暂无已完结交易</div>
          ) : reviews.map(r => (
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
        <div className="mx-3 mt-2 mb-1 rounded-lg border border-border/40 bg-muted/30 px-3 py-2 text-[11px] space-y-1">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              {schedulerStatus.running ? (
                <CircleCheck className="h-3 w-3 text-green-500" />
              ) : (
                <CircleX className="h-3 w-3 text-red-500" />
              )}
              <span className={schedulerStatus.running ? "text-green-500" : "text-red-500"}>
                {schedulerStatus.running ? "自动分析运行中" : "自动分析已停止"}
              </span>
            </div>
            {schedulerStatus.is_refreshing && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 text-amber-500 border-amber-500/30">
                <Loader2 className="h-2.5 w-2.5 animate-spin mr-1" />
                分析中
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-3 text-muted-foreground">
            <div className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              <span>上次: {schedulerStatus.last_run_date || "—"}</span>
            </div>
            <div className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              <span>下次: {schedulerStatus.next_run_time?.slice(5) || "—"}</span>
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
