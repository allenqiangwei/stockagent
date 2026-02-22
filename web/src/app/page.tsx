"use client";

import { useWatchlist, useTodaySignals, useBacktestRuns } from "@/hooks/use-queries";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useAppStore } from "@/lib/store";
import { useRouter } from "next/navigation";
import { LayoutDashboard, TrendingUp, Zap, FlaskConical } from "lucide-react";

function signalColor(level: number) {
  if (level >= 4) return "text-red-400";
  if (level >= 3) return "text-yellow-400";
  return "text-muted-foreground";
}

export default function DashboardPage() {
  const router = useRouter();
  const setCurrentStock = useAppStore((s) => s.setCurrentStock);
  const { data: watchlist } = useWatchlist();
  const { data: todaySignals } = useTodaySignals();
  const { data: runs } = useBacktestRuns();

  const recentRuns = runs?.slice(0, 5) ?? [];
  const topSignals = todaySignals?.items?.slice(0, 10) ?? [];

  return (
    <div className="p-3 sm:p-4 space-y-3 sm:space-y-4">
      <div className="flex items-center gap-2 text-base sm:text-lg font-semibold">
        <LayoutDashboard className="h-5 w-5" />
        仪表盘
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card>
          <CardContent className="pt-4 pb-3 px-4">
            <div className="text-xs text-muted-foreground">自选股</div>
            <div className="text-2xl font-bold mt-1">{watchlist?.length ?? 0}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3 px-4">
            <div className="text-xs text-muted-foreground">今日信号</div>
            <div className="text-2xl font-bold mt-1">{todaySignals?.total ?? 0}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3 px-4">
            <div className="text-xs text-muted-foreground">强烈买入</div>
            <div className="text-2xl font-bold mt-1 text-red-400">
              {topSignals.filter((s) => s.signal_level >= 4).length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3 px-4">
            <div className="text-xs text-muted-foreground">回测次数</div>
            <div className="text-2xl font-bold mt-1">{runs?.length ?? 0}</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        {/* Watchlist */}
        <Card>
          <CardHeader className="pb-2 px-4 pt-4">
            <CardTitle className="text-sm flex items-center gap-1.5">
              <TrendingUp className="h-4 w-4" />
              自选列表
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {!watchlist?.length ? (
              <div className="text-sm text-muted-foreground py-4 text-center">
                暂无自选股，前往行情页添加
              </div>
            ) : (
              <div className="space-y-1">
                {watchlist.map((w) => (
                  <button
                    key={w.stock_code}
                    onClick={() => {
                      setCurrentStock(w.stock_code, w.stock_name);
                      router.push("/market");
                    }}
                    className="flex items-center justify-between w-full rounded px-2 py-1.5 text-sm hover:bg-accent/50 transition-colors"
                  >
                    <span className="font-mono">{w.stock_code}</span>
                    <span className="text-muted-foreground">{w.stock_name}</span>
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Today signals */}
        <Card>
          <CardHeader className="pb-2 px-4 pt-4">
            <CardTitle className="text-sm flex items-center gap-1.5">
              <Zap className="h-4 w-4" />
              今日信号 {todaySignals?.trade_date ? `(${todaySignals.trade_date})` : ""}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {!topSignals.length ? (
              <div className="text-sm text-muted-foreground py-4 text-center">
                暂无信号数据
              </div>
            ) : (
              <div className="space-y-1">
                {topSignals.map((s) => (
                  <div
                    key={s.stock_code}
                    className="flex items-center justify-between rounded px-2 py-1.5 text-sm"
                  >
                    <span className="font-mono">{s.stock_code}</span>
                    <Badge variant="outline" className={signalColor(s.signal_level)}>
                      {s.signal_level_name} ({s.final_score.toFixed(0)})
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent backtest runs */}
      <Card>
        <CardHeader className="pb-2 px-4 pt-4">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <FlaskConical className="h-4 w-4" />
            最近回测
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          {!recentRuns.length ? (
            <div className="text-sm text-muted-foreground py-4 text-center">
              暂无回测记录
            </div>
          ) : (
            <div className="space-y-1">
              {recentRuns.map((r) => (
                <div
                  key={r.id}
                  className="flex items-center justify-between rounded px-2 py-1.5 text-sm"
                >
                  <span>{r.strategy_name}</span>
                  <div className="flex items-center gap-3 text-xs">
                    <span>
                      胜率{" "}
                      <span className="font-mono">{(r.win_rate * 100).toFixed(1)}%</span>
                    </span>
                    <span
                      className={
                        r.total_return_pct >= 0 ? "text-red-400" : "text-green-400"
                      }
                    >
                      收益 {r.total_return_pct >= 0 ? "+" : ""}
                      {r.total_return_pct.toFixed(1)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
