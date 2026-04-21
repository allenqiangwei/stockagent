"use client";

import { useState, useMemo } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useBacktestRuns, useBacktestDetail } from "@/hooks/use-queries";
import { EquityCurve } from "@/components/quant/equity-curve";
import { ExitReasonChart } from "@/components/quant/exit-reason-chart";
import type { BacktestRun, BacktestResult, TradeDetail } from "@/types";
import { Loader2, ArrowUpDown, BarChart3 } from "lucide-react";

const SELL_REASON_LABEL: Record<string, string> = {
  strategy_exit: "策略卖出",
  stop_loss: "止损",
  take_profit: "止盈",
  max_hold: "持有到期",
  end_of_backtest: "回测结束",
};

type TradeSortKey = "buy_date" | "pnl_pct" | "hold_days" | "sell_reason";
type SortDir = "asc" | "desc";

// ── Main component ──────────────────────────────
export function BacktestViewer() {
  const { data: runs, isLoading: runsLoading } = useBacktestRuns();
  const [selectedRunId, setSelectedRunId] = useState<number>(0);

  // Auto-select first run
  const runId = selectedRunId || (runs?.[0]?.id ?? 0);

  return (
    <div className="space-y-4">
      {/* Run selector */}
      <div className="flex items-center gap-3">
        <span className="text-sm text-muted-foreground shrink-0">选择回测:</span>
        {runsLoading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : runs && runs.length > 0 ? (
          <Select
            value={String(runId)}
            onValueChange={(v) => setSelectedRunId(Number(v))}
          >
            <SelectTrigger className="max-w-md h-8 text-xs">
              <SelectValue placeholder="选择回测记录" />
            </SelectTrigger>
            <SelectContent>
              {runs.map((r: BacktestRun) => (
                <SelectItem key={r.id} value={String(r.id)}>
                  <span className="font-mono">{r.strategy_name}</span>
                  <span className="text-muted-foreground ml-2">
                    {r.start_date}~{r.end_date} · ret{" "}
                    {r.total_return_pct?.toFixed(1)}%
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <span className="text-sm text-muted-foreground">暂无回测记录</span>
        )}
      </div>

      {/* Detail */}
      {runId > 0 && <BacktestDetail runId={runId} />}
    </div>
  );
}

// ── Backtest detail ─────────────────────────────
function BacktestDetail({ runId }: { runId: number }) {
  const { data: bt, isLoading } = useBacktestDetail(runId);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        加载回测详情...
      </div>
    );
  }

  if (!bt) return null;

  return (
    <div className="space-y-4">
      {/* Header */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <div className="font-medium text-sm">{bt.strategy_name}</div>
              <div className="text-xs text-muted-foreground">
                {bt.start_date} ~ {bt.end_date}
                {bt.backtest_mode && (
                  <Badge variant="secondary" className="ml-2 text-[10px]">
                    {bt.backtest_mode}
                  </Badge>
                )}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Equity Curve */}
      {bt.equity_curve?.length > 0 && (
        <Card>
          <CardContent className="p-4">
            <EquityCurve data={bt.equity_curve} height={300} />
          </CardContent>
        </Card>
      )}

      {/* Metrics */}
      <MetricsGrid bt={bt} />

      {/* Exit Reasons + Regime Stats side by side */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {bt.sell_reason_stats &&
          Object.keys(bt.sell_reason_stats).length > 0 && (
            <Card>
              <CardContent className="p-4">
                <ExitReasonChart data={bt.sell_reason_stats} />
              </CardContent>
            </Card>
          )}
        {bt.regime_stats && Object.keys(bt.regime_stats).length > 0 && (
          <Card>
            <CardContent className="p-4">
              <RegimeStats data={bt.regime_stats} />
            </CardContent>
          </Card>
        )}
      </div>

      {/* Trade list */}
      {bt.trades?.length > 0 && <TradeList trades={bt.trades} />}
    </div>
  );
}

// ── Metrics grid ─────────────────────────────────
function MetricsGrid({ bt }: { bt: BacktestResult }) {
  const metrics = [
    {
      label: "总收益",
      value: `${bt.total_return_pct >= 0 ? "+" : ""}${bt.total_return_pct.toFixed(1)}%`,
      cls: bt.total_return_pct >= 0 ? "text-red-400" : "text-green-400",
    },
    {
      label: "最大回撤",
      value: `${bt.max_drawdown_pct.toFixed(1)}%`,
      cls: "text-red-400",
    },
    {
      label: "胜率",
      value: `${bt.win_rate.toFixed(1)}%`,
    },
    {
      label: "交易数",
      value: `${bt.total_trades}`,
      sub: `赢 ${bt.win_trades} / 亏 ${bt.lose_trades}`,
    },
    {
      label: "平均持仓",
      value: `${bt.avg_hold_days.toFixed(1)} 天`,
    },
    {
      label: "平均收益",
      value: `${bt.avg_pnl_pct >= 0 ? "+" : ""}${bt.avg_pnl_pct.toFixed(2)}%`,
      cls: bt.avg_pnl_pct >= 0 ? "text-emerald-500" : "text-red-500",
    },
  ];

  // Optional advanced metrics
  if (bt.sharpe_ratio != null) {
    metrics.push({ label: "Sharpe", value: bt.sharpe_ratio.toFixed(2) });
  }
  if (bt.calmar_ratio != null) {
    metrics.push({ label: "Calmar", value: bt.calmar_ratio.toFixed(2) });
  }
  if (bt.cagr_pct != null) {
    metrics.push({ label: "CAGR", value: `${bt.cagr_pct.toFixed(1)}%` });
  }
  if (bt.profit_loss_ratio != null) {
    metrics.push({
      label: "盈亏比",
      value: bt.profit_loss_ratio.toFixed(2),
    });
  }
  if (bt.index_return_pct != null) {
    metrics.push({
      label: "超额收益",
      value: `${(bt.total_return_pct - bt.index_return_pct).toFixed(1)}%`,
      cls: "text-blue-400",
    });
  }

  return (
    <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-2">
      {metrics.map((m) => (
        <Card key={m.label}>
          <CardContent className="p-3">
            <div className="text-[10px] text-muted-foreground">{m.label}</div>
            <div className={`text-sm font-bold font-mono ${m.cls || ""}`}>
              {m.value}
            </div>
            {"sub" in m && m.sub && (
              <div className="text-[10px] text-muted-foreground">{m.sub}</div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ── Regime stats ─────────────────────────────────
const REGIME_STYLE: Record<string, { label: string; cls: string }> = {
  trending_bull: { label: "趋势上涨", cls: "text-emerald-500" },
  trending_bear: { label: "趋势下跌", cls: "text-red-500" },
  ranging: { label: "震荡整理", cls: "text-zinc-400" },
  volatile: { label: "高波动", cls: "text-amber-500" },
  unknown: { label: "未知", cls: "text-zinc-500" },
};

function RegimeStats({
  data,
}: {
  data: Record<
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
  const entries = Object.entries(data).filter(([k]) => k !== "unknown");
  if (!entries.length) return null;

  return (
    <div>
      <div className="text-xs text-muted-foreground mb-2">市场阶段分析</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs">阶段</TableHead>
            <TableHead className="text-xs text-right">交易</TableHead>
            <TableHead className="text-xs text-right">胜率</TableHead>
            <TableHead className="text-xs text-right">平均收益</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {entries.map(([regime, d]) => {
            const style = REGIME_STYLE[regime] ?? REGIME_STYLE.unknown;
            return (
              <TableRow key={regime}>
                <TableCell>
                  <span className={`text-xs font-medium ${style.cls}`}>
                    {style.label}
                  </span>
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {d.trades}
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {d.win_rate.toFixed(1)}%
                </TableCell>
                <TableCell
                  className={`text-right font-mono text-xs ${
                    d.avg_pnl >= 0 ? "text-emerald-500" : "text-red-500"
                  }`}
                >
                  {d.avg_pnl >= 0 ? "+" : ""}
                  {d.avg_pnl.toFixed(2)}%
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

// ── Sortable trade list ──────────────────────────
function TradeList({ trades }: { trades: TradeDetail[] }) {
  const [sortKey, setSortKey] = useState<TradeSortKey>("buy_date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [showAll, setShowAll] = useState(false);

  const sorted = useMemo(() => {
    const arr = [...trades];
    arr.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "buy_date":
          cmp = a.buy_date.localeCompare(b.buy_date);
          break;
        case "pnl_pct":
          cmp = a.pnl_pct - b.pnl_pct;
          break;
        case "hold_days":
          cmp = a.hold_days - b.hold_days;
          break;
        case "sell_reason":
          cmp = a.sell_reason.localeCompare(b.sell_reason);
          break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [trades, sortKey, sortDir]);

  const displayed = showAll ? sorted : sorted.slice(0, 50);

  const toggleSort = (key: TradeSortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const SortHeader = ({
    label,
    field,
    className,
  }: {
    label: string;
    field: TradeSortKey;
    className?: string;
  }) => (
    <TableHead
      className={`text-xs cursor-pointer hover:text-foreground ${className || ""}`}
      onClick={() => toggleSort(field)}
    >
      <div className="flex items-center gap-0.5">
        {label}
        {sortKey === field && (
          <ArrowUpDown className="h-3 w-3" />
        )}
      </div>
    </TableHead>
  );

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <BarChart3 className="h-3.5 w-3.5" />
            交易明细 ({trades.length} 笔)
          </div>
        </div>
        <div className="max-h-96 overflow-auto border rounded">
          <Table className="min-w-[700px]">
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">代码</TableHead>
                <SortHeader label="买入日期" field="buy_date" />
                <TableHead className="text-xs text-right">买入价</TableHead>
                <TableHead className="text-xs">卖出日期</TableHead>
                <TableHead className="text-xs text-right">卖出价</TableHead>
                <SortHeader
                  label="收益率"
                  field="pnl_pct"
                  className="text-right"
                />
                <SortHeader
                  label="持有天"
                  field="hold_days"
                  className="text-right"
                />
                <SortHeader label="卖出原因" field="sell_reason" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {displayed.map((t, i) => (
                <TableRow key={i}>
                  <TableCell className="font-mono text-xs">
                    {t.stock_code}
                  </TableCell>
                  <TableCell className="text-xs">{t.buy_date}</TableCell>
                  <TableCell className="font-mono text-xs text-right">
                    {t.buy_price.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-xs">{t.sell_date}</TableCell>
                  <TableCell className="font-mono text-xs text-right">
                    {t.sell_price.toFixed(2)}
                  </TableCell>
                  <TableCell
                    className={`font-mono text-xs text-right ${
                      t.pnl_pct >= 0 ? "text-emerald-500" : "text-red-500"
                    }`}
                  >
                    {t.pnl_pct >= 0 ? "+" : ""}
                    {t.pnl_pct.toFixed(2)}%
                  </TableCell>
                  <TableCell className="font-mono text-xs text-right">
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
        {trades.length > 50 && !showAll && (
          <Button
            size="sm"
            variant="outline"
            className="mt-2 text-xs"
            onClick={() => setShowAll(true)}
          >
            显示全部 {trades.length} 笔
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
