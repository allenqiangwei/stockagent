"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useLabExperiments,
  useLabExperiment,
  useDeleteExperiment,
  usePromoteStrategy,
  useBacktestDetail,
} from "@/hooks/use-queries";
import { EquityCurveChart } from "@/components/charts/equity-curve-chart";
import type { LabExperimentListItem, LabExperimentStrategy } from "@/types";
import {
  Loader2,
  Trash2,
  ChevronDown,
  ChevronUp,
  Trophy,
  ArrowUpFromLine,
  TrendingUp,
} from "lucide-react";

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

const SELL_REASON_LABEL: Record<string, string> = {
  strategy_exit: "策略卖出",
  stop_loss: "止损",
  take_profit: "止盈",
  max_hold: "持有到期",
  end_of_backtest: "回测结束",
};

// ── Regime styles ────────────────────────────────
const REGIME_STYLE: Record<string, { label: string; cls: string }> = {
  trending_bull: { label: "趋势上涨", cls: "text-emerald-500" },
  trending_bear: { label: "趋势下跌", cls: "text-red-500" },
  ranging: { label: "震荡整理", cls: "text-zinc-400" },
  volatile: { label: "高波动", cls: "text-amber-500" },
  unknown: { label: "未知", cls: "text-zinc-500" },
};

// ── Main component ──────────────────────────────
export function ExperimentList() {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useLabExperiments(page);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const deleteExp = useDeleteExperiment();

  if (isLoading) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin inline mr-2" />
        加载中...
      </div>
    );
  }

  if (!data?.items?.length) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        暂无实验记录
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        {data.items.map((exp) => (
          <ExperimentRow
            key={exp.id}
            exp={exp}
            expanded={expandedId === exp.id}
            onToggle={() =>
              setExpandedId(expandedId === exp.id ? null : exp.id)
            }
            onDelete={() => {
              if (confirm("确定删除该实验及所有相关数据？")) {
                deleteExp.mutate(exp.id, {
                  onSuccess: () => {
                    if (expandedId === exp.id) setExpandedId(null);
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
    </div>
  );
}

// ── Experiment row ───────────────────────────────
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
              <span className="text-xs text-muted-foreground shrink-0">
                {exp.created_at}
              </span>
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

// ── Experiment detail ────────────────────────────
function ExperimentDetail({ experimentId }: { experimentId: number }) {
  const { data, isLoading } = useLabExperiment(experimentId);
  const promote = usePromoteStrategy();

  if (isLoading) {
    return (
      <div className="p-4 text-sm text-muted-foreground">加载策略详情...</div>
    );
  }

  if (!data?.strategies?.length) {
    return <div className="p-4 text-sm text-muted-foreground">无策略数据</div>;
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

// ── Strategy row ─────────────────────────────────
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
            {rank <= 3 && (
              <Trophy
                className={`h-3.5 w-3.5 ${
                  rank === 1
                    ? "text-amber-500"
                    : rank === 2
                    ? "text-zinc-400"
                    : "text-amber-700"
                }`}
              />
            )}
            <span className="text-sm">{rank}</span>
          </div>
        </TableCell>
        <TableCell>
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-medium">{s.name}</span>
            {s.promoted && (
              <Badge className="text-[10px] bg-emerald-600 text-white">
                已推广
              </Badge>
            )}
          </div>
        </TableCell>
        <TableCell className="text-right font-mono text-sm">
          {s.status === "done" ? s.score.toFixed(2) : "—"}
        </TableCell>
        <TableCell
          className={`text-right font-mono text-sm ${
            s.total_return_pct >= 0 ? "text-emerald-500" : "text-red-500"
          }`}
        >
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
                onClick={(e) => {
                  e.stopPropagation();
                  onPromote();
                }}
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

// ── Strategy detail panel ────────────────────────
function StrategyDetailPanel({
  strategy: s,
}: {
  strategy: LabExperimentStrategy;
}) {
  const { data: btDetail, isLoading } = useBacktestDetail(
    s.backtest_run_id ?? 0
  );
  const [showTrades, setShowTrades] = useState(false);

  return (
    <div className="bg-muted/10 border-t border-border p-4 space-y-4">
      <div className="text-sm text-muted-foreground">{s.description}</div>
      {s.error_message && (
        <div className="text-red-400 text-xs">错误: {s.error_message}</div>
      )}

      {s.status === "done" && (
        <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
          <MetricCard label="评分" value={s.score.toFixed(2)} />
          <MetricCard
            label="总收益"
            value={`${s.total_return_pct >= 0 ? "+" : ""}${s.total_return_pct.toFixed(1)}%`}
            cls={s.total_return_pct >= 0 ? "text-emerald-500" : "text-red-500"}
          />
          <MetricCard
            label="最大回撤"
            value={`${s.max_drawdown_pct.toFixed(1)}%`}
            cls="text-red-400"
          />
          <MetricCard label="胜率" value={`${s.win_rate.toFixed(1)}%`} />
          <MetricCard label="交易数" value={String(s.total_trades)} />
          <MetricCard
            label="平均持仓"
            value={`${s.avg_hold_days.toFixed(1)}天`}
          />
        </div>
      )}

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

          {btDetail?.sell_reason_stats &&
            Object.keys(btDetail.sell_reason_stats).length > 0 && (
              <div className="mt-3">
                <div className="text-xs text-muted-foreground mb-1">
                  卖出原因分布
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(btDetail.sell_reason_stats).map(
                    ([reason, count]) => (
                      <Badge key={reason} variant="outline" className="text-xs">
                        {SELL_REASON_LABEL[reason] || reason}: {count}
                      </Badge>
                    )
                  )}
                </div>
              </div>
            )}

          {s.regime_stats && Object.keys(s.regime_stats).length > 0 && (
            <RegimeStatsTable regimeStats={s.regime_stats} />
          )}

          {btDetail?.trades?.length ? (
            <div className="mt-3">
              <Button
                size="sm"
                variant="outline"
                className="text-xs h-7"
                onClick={() => setShowTrades(!showTrades)}
              >
                {showTrades ? "收起" : "展开"} 交易明细 ({btDetail.trades.length}{" "}
                笔)
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
                          <TableCell className="font-mono text-xs">
                            {t.stock_code}
                          </TableCell>
                          <TableCell className="text-xs">
                            {t.buy_date}
                          </TableCell>
                          <TableCell className="font-mono text-xs">
                            {t.buy_price.toFixed(2)}
                          </TableCell>
                          <TableCell className="text-xs">
                            {t.sell_date}
                          </TableCell>
                          <TableCell className="font-mono text-xs">
                            {t.sell_price.toFixed(2)}
                          </TableCell>
                          <TableCell
                            className={`font-mono text-xs ${
                              t.pnl_pct >= 0
                                ? "text-emerald-500"
                                : "text-red-500"
                            }`}
                          >
                            {t.pnl_pct >= 0 ? "+" : ""}
                            {t.pnl_pct.toFixed(2)}%
                          </TableCell>
                          <TableCell className="font-mono text-xs">
                            {t.hold_days}
                          </TableCell>
                          <TableCell className="text-xs">
                            {SELL_REASON_LABEL[t.sell_reason] || t.sell_reason}
                          </TableCell>
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

      <div className="flex gap-3 text-xs">
        <span className="text-muted-foreground">
          止损:{" "}
          <span className="font-mono text-red-400">
            {s.exit_config.stop_loss_pct}%
          </span>
        </span>
        <span className="text-muted-foreground">
          止盈:{" "}
          <span className="font-mono text-emerald-500">
            +{s.exit_config.take_profit_pct}%
          </span>
        </span>
        <span className="text-muted-foreground">
          最大持仓:{" "}
          <span className="font-mono">{s.exit_config.max_hold_days}天</span>
        </span>
      </div>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────
function MetricCard({
  label,
  value,
  cls,
}: {
  label: string;
  value: string;
  cls?: string;
}) {
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

function RegimeStatsTable({
  regimeStats,
}: {
  regimeStats: Record<
    string,
    {
      trades: number;
      wins: number;
      win_rate: number;
      avg_pnl: number;
      total_pnl: number;
    }
  >;
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
                    <span className={`text-xs font-medium ${style.cls}`}>
                      {style.label}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {data.trades}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {data.win_rate.toFixed(1)}%
                  </TableCell>
                  <TableCell
                    className={`text-right font-mono text-xs ${
                      data.avg_pnl >= 0 ? "text-emerald-500" : "text-red-500"
                    }`}
                  >
                    {data.avg_pnl >= 0 ? "+" : ""}
                    {data.avg_pnl.toFixed(2)}%
                  </TableCell>
                  <TableCell
                    className={`text-right font-mono text-xs ${
                      data.total_pnl >= 0 ? "text-emerald-500" : "text-red-500"
                    }`}
                  >
                    {data.total_pnl >= 0 ? "+" : ""}
                    {data.total_pnl.toFixed(1)}%
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
