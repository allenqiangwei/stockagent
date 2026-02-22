"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { Badge } from "@/components/ui/badge";
import { useStrategies, useBacktestRuns, useBacktestDetail } from "@/hooks/use-queries";
import { backtest as backtestApi } from "@/lib/api";
import { FlaskConical, Play, Loader2 } from "lucide-react";
import { EquityCurveChart } from "@/components/charts/equity-curve-chart";
import type { BacktestResult } from "@/types";

const SELL_REASON_LABEL: Record<string, string> = {
  strategy_exit: "策略卖出",
  stop_loss: "止损",
  take_profit: "止盈",
  max_hold: "持有到期",
  end_of_backtest: "回测结束",
};

function sellReasonLabel(reason: string) {
  return SELL_REASON_LABEL[reason] || reason;
}

function dateStr(d: Date) {
  return d.toISOString().slice(0, 10);
}

export default function BacktestPage() {
  const { data: strats } = useStrategies();
  const [stratId, setStratId] = useState<string>("");
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setMonth(d.getMonth() - 6);
    return dateStr(d);
  });
  const [endDate, setEndDate] = useState(() => dateStr(new Date()));
  const [capital, setCapital] = useState(10000);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [selectedRun, setSelectedRun] = useState<number>(0);

  const { data: runs, refetch: refetchRuns } = useBacktestRuns(
    stratId ? Number(stratId) : undefined
  );
  const { data: runDetail } = useBacktestDetail(selectedRun);

  const activeResult = result ?? runDetail;

  async function handleRun() {
    if (!stratId) return;
    setRunning(true);
    setResult(null);
    try {
      const res = await backtestApi.runSync({
        strategy_id: Number(stratId),
        start_date: startDate,
        end_date: endDate,
        capital_per_trade: capital,
      });
      setResult(res);
      refetchRuns();
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="p-3 sm:p-4 space-y-3 sm:space-y-4">
      <div className="flex items-center gap-2 text-base sm:text-lg font-semibold">
        <FlaskConical className="h-5 w-5" />
        策略回测
      </div>

      {/* Parameters */}
      <Card>
        <CardContent className="pt-4 pb-4 px-4">
          <div className="flex flex-wrap items-end gap-2 sm:gap-3">
            <div className="space-y-1 w-full sm:w-auto">
              <label className="text-xs text-muted-foreground">策略</label>
              <Select value={stratId} onValueChange={setStratId}>
                <SelectTrigger className="w-full sm:w-48 h-8 text-sm">
                  <SelectValue placeholder="选择策略" />
                </SelectTrigger>
                <SelectContent>
                  {strats?.map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">开始日期</label>
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="h-8 w-36 text-sm"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">结束日期</label>
              <Input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="h-8 w-36 text-sm"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">快速选择</label>
              <div className="flex gap-1">
                {[1, 2, 3, 5].map((y) => (
                  <Button
                    key={y}
                    size="sm"
                    variant="outline"
                    className="h-8 px-2.5 text-xs"
                    onClick={() => {
                      const end = new Date();
                      const start = new Date();
                      start.setFullYear(start.getFullYear() - y);
                      setStartDate(dateStr(start));
                      setEndDate(dateStr(end));
                    }}
                  >
                    {y}年
                  </Button>
                ))}
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">
                {strats?.find((s) => String(s.id) === stratId)?.portfolio_config
                  ? "初始资金"
                  : "单笔金额"}
              </label>
              <Input
                type="number"
                value={capital}
                onChange={(e) => setCapital(Number(e.target.value))}
                className="h-8 w-28 text-sm"
              />
            </div>
            <Button
              size="sm"
              onClick={handleRun}
              disabled={running || !stratId}
            >
              {running ? (
                <Loader2 className="h-4 w-4 animate-spin mr-1" />
              ) : (
                <Play className="h-4 w-4 mr-1" />
              )}
              运行回测
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid md:grid-cols-3 gap-4">
        {/* History runs */}
        <Card className="md:col-span-1">
          <CardHeader className="pb-2 px-4 pt-4">
            <CardTitle className="text-sm">回测历史</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {!runs?.length ? (
              <div className="text-sm text-muted-foreground py-4 text-center">
                暂无记录
              </div>
            ) : (
              <div className="space-y-1 max-h-80 overflow-y-auto">
                {runs.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => {
                      setSelectedRun(r.id);
                      setResult(null);
                    }}
                    className={`w-full text-left rounded px-2 py-1.5 text-sm transition-colors ${
                      selectedRun === r.id && !result
                        ? "bg-accent"
                        : "hover:bg-accent/50"
                    }`}
                  >
                    <div className="font-medium flex items-center gap-1.5">
                      {r.strategy_name}
                      {r.backtest_mode === "portfolio" && (
                        <Badge variant="outline" className="text-[9px] px-1 py-0">
                          组合
                        </Badge>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {r.start_date} ~ {r.end_date}
                    </div>
                    <div className="text-xs mt-0.5">
                      胜率 {r.win_rate.toFixed(1)}% · 收益{" "}
                      <span
                        className={
                          r.total_return_pct >= 0
                            ? "text-red-400"
                            : "text-green-400"
                        }
                      >
                        {r.total_return_pct >= 0 ? "+" : ""}
                        {r.total_return_pct.toFixed(1)}%
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Result detail */}
        <Card className="md:col-span-2">
          <CardHeader className="pb-2 px-4 pt-4">
            <CardTitle className="text-sm">回测结果</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {!activeResult ? (
              <div className="text-sm text-muted-foreground py-8 text-center">
                选择一条回测记录或运行新回测
              </div>
            ) : (
              <div className="space-y-4">
                {/* Metrics */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className="rounded-md border p-2">
                    <div className="text-xs text-muted-foreground">总交易</div>
                    <div className="text-xl font-bold font-mono">
                      {activeResult.total_trades}
                    </div>
                  </div>
                  <div className="rounded-md border p-2">
                    <div className="text-xs text-muted-foreground">胜率</div>
                    <div className="text-xl font-bold font-mono">
                      {activeResult.win_rate.toFixed(1)}%
                    </div>
                  </div>
                  <div className="rounded-md border p-2">
                    <div className="text-xs text-muted-foreground">累计收益</div>
                    <div
                      className={`text-xl font-bold font-mono ${
                        activeResult.total_return_pct >= 0
                          ? "text-red-400"
                          : "text-green-400"
                      }`}
                    >
                      {activeResult.total_return_pct >= 0 ? "+" : ""}
                      {activeResult.total_return_pct.toFixed(2)}%
                    </div>
                  </div>
                  <div className="rounded-md border p-2">
                    <div className="text-xs text-muted-foreground">最大回撤</div>
                    <div className="text-xl font-bold font-mono text-green-400">
                      {activeResult.max_drawdown_pct.toFixed(2)}%
                    </div>
                  </div>
                </div>

                {/* Portfolio mode advanced metrics */}
                {activeResult.cagr_pct != null && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div className="rounded-md border p-2">
                      <div className="text-xs text-muted-foreground">CAGR</div>
                      <div
                        className={`text-xl font-bold font-mono ${
                          activeResult.cagr_pct >= 0
                            ? "text-red-400"
                            : "text-green-400"
                        }`}
                      >
                        {activeResult.cagr_pct >= 0 ? "+" : ""}
                        {activeResult.cagr_pct.toFixed(2)}%
                      </div>
                    </div>
                    <div className="rounded-md border p-2">
                      <div className="text-xs text-muted-foreground">Sharpe</div>
                      <div className="text-xl font-bold font-mono">
                        {(activeResult.sharpe_ratio ?? 0).toFixed(2)}
                      </div>
                    </div>
                    <div className="rounded-md border p-2">
                      <div className="text-xs text-muted-foreground">Calmar</div>
                      <div className="text-xl font-bold font-mono">
                        {(activeResult.calmar_ratio ?? 0).toFixed(2)}
                      </div>
                    </div>
                    <div className="rounded-md border p-2">
                      <div className="text-xs text-muted-foreground">盈亏比</div>
                      <div className="text-xl font-bold font-mono">
                        {(activeResult.profit_loss_ratio ?? 0).toFixed(2)}
                      </div>
                    </div>
                  </div>
                )}

                {/* Additional stats */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-sm">
                  <div>
                    <span className="text-muted-foreground">盈利/亏损: </span>
                    <span className="font-mono">
                      {activeResult.win_trades}/{activeResult.lose_trades}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">平均持有: </span>
                    <span className="font-mono">
                      {activeResult.avg_hold_days.toFixed(1)}天
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">平均收益: </span>
                    <span className="font-mono">
                      {activeResult.avg_pnl_pct.toFixed(2)}%
                    </span>
                  </div>
                </div>

                {/* Sell reason stats */}
                {activeResult.sell_reason_stats &&
                  Object.keys(activeResult.sell_reason_stats).length > 0 && (
                    <div>
                      <div className="text-xs text-muted-foreground mb-1">
                        卖出原因分布
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(activeResult.sell_reason_stats).map(
                          ([reason, count]) => (
                            <Badge key={reason} variant="outline">
                              {sellReasonLabel(reason)}: {count}
                            </Badge>
                          )
                        )}
                      </div>
                    </div>
                  )}

                {/* Equity curve */}
                {activeResult.equity_curve?.length > 0 && (
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">
                      收益曲线
                    </div>
                    <EquityCurveChart data={activeResult.equity_curve} />
                  </div>
                )}

                {/* Trades table */}
                {activeResult.trades?.length > 0 && (
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">
                      交易明细
                    </div>
                    <div className="max-h-64 overflow-auto">
                      <Table className="min-w-[640px]">
                        <TableHeader>
                          <TableRow>
                            <TableHead>代码</TableHead>
                            <TableHead>买入日期</TableHead>
                            <TableHead>买入价</TableHead>
                            <TableHead>卖出日期</TableHead>
                            <TableHead>卖出价</TableHead>
                            <TableHead>收益率</TableHead>
                            <TableHead>持有天数</TableHead>
                            <TableHead>卖出原因</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {activeResult.trades.map((t, i) => (
                            <TableRow key={i}>
                              <TableCell className="font-mono">
                                {t.stock_code}
                              </TableCell>
                              <TableCell>{t.buy_date}</TableCell>
                              <TableCell className="font-mono">
                                {t.buy_price.toFixed(2)}
                              </TableCell>
                              <TableCell>{t.sell_date}</TableCell>
                              <TableCell className="font-mono">
                                {t.sell_price.toFixed(2)}
                              </TableCell>
                              <TableCell
                                className={`font-mono ${
                                  t.pnl_pct >= 0
                                    ? "text-red-400"
                                    : "text-green-400"
                                }`}
                              >
                                {t.pnl_pct >= 0 ? "+" : ""}
                                {t.pnl_pct.toFixed(2)}%
                              </TableCell>
                              <TableCell className="font-mono">
                                {t.hold_days}
                              </TableCell>
                              <TableCell className="text-xs">
                                {sellReasonLabel(t.sell_reason)}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
