"use client";

import { useState, useMemo, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useIndexKline } from "@/hooks/use-queries";
import { marketOverview } from "@/lib/api";
import { IndexKlineChart } from "@/components/charts/index-kline-chart";
import { cn } from "@/lib/utils";
import { RefreshCw } from "lucide-react";
import type { RegimeWeek } from "@/types";

const INDEX_OPTIONS = [
  { code: "000001.SH", label: "上证指数" },
  { code: "399001.SZ", label: "深证成指" },
  { code: "399006.SZ", label: "创业板指" },
];

const TIME_RANGES = [
  { key: "1y", label: "1年", years: 1 },
  { key: "3y", label: "3年", years: 3 },
  { key: "5y", label: "5年", years: 5 },
] as const;

type TimeRangeKey = (typeof TIME_RANGES)[number]["key"];

function formatDate(d: Date) {
  return d.toISOString().slice(0, 10);
}

function computeDateRange(rangeKey: TimeRangeKey) {
  const now = new Date();
  const end = formatDate(now);
  const tr = TIME_RANGES.find((t) => t.key === rangeKey)!;
  const start = formatDate(
    new Date(now.getFullYear() - tr.years, now.getMonth(), now.getDate())
  );
  return { start, end };
}

const REGIME_LABELS: Record<string, { label: string; color: string; bgClass: string }> = {
  trending_bull: { label: "牛市趋势", color: "rgb(239, 68, 68)", bgClass: "bg-red-500/20" },
  trending_bear: { label: "熊市趋势", color: "rgb(34, 197, 94)", bgClass: "bg-green-500/20" },
  ranging: { label: "震荡盘整", color: "rgb(234, 179, 8)", bgClass: "bg-yellow-500/20" },
  volatile: { label: "高波动", color: "rgb(168, 85, 247)", bgClass: "bg-purple-500/20" },
};

function RegimeStats({ regimes }: { regimes: RegimeWeek[] }) {
  const stats = useMemo(() => {
    const map: Record<string, { weeks: number; totalReturn: number }> = {};
    for (const r of regimes) {
      if (!map[r.regime]) map[r.regime] = { weeks: 0, totalReturn: 0 };
      map[r.regime].weeks += 1;
      map[r.regime].totalReturn += r.index_return_pct;
    }
    const total = regimes.length;
    return Object.entries(map)
      .sort(([, a], [, b]) => b.weeks - a.weeks)
      .map(([regime, s]) => ({
        regime,
        ...s,
        pct: total > 0 ? ((s.weeks / total) * 100).toFixed(1) : "0",
      }));
  }, [regimes]);

  if (stats.length === 0) return null;

  return (
    <div className="border border-border/40 rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/40 bg-muted/30">
            <th className="text-left px-4 py-2 font-medium">阶段</th>
            <th className="text-right px-4 py-2 font-medium">周数</th>
            <th className="text-right px-4 py-2 font-medium">占比</th>
            <th className="text-right px-4 py-2 font-medium">累计涨跌幅</th>
          </tr>
        </thead>
        <tbody>
          {stats.map((s) => {
            const info = REGIME_LABELS[s.regime] ?? {
              label: s.regime,
              color: "#888",
              bgClass: "",
            };
            return (
              <tr key={s.regime} className="border-b border-border/20 last:border-0">
                <td className="px-4 py-2 flex items-center gap-2">
                  <span
                    className="inline-block w-2.5 h-2.5 rounded-sm"
                    style={{ backgroundColor: info.color }}
                  />
                  {info.label}
                </td>
                <td className="text-right px-4 py-2 tabular-nums">{s.weeks}</td>
                <td className="text-right px-4 py-2 tabular-nums">{s.pct}%</td>
                <td
                  className={cn(
                    "text-right px-4 py-2 tabular-nums font-medium",
                    s.totalReturn > 0 ? "text-red-500" : s.totalReturn < 0 ? "text-green-500" : ""
                  )}
                >
                  {s.totalReturn > 0 ? "+" : ""}
                  {s.totalReturn.toFixed(2)}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function MarketOverviewPage() {
  const [indexCode, setIndexCode] = useState("000001.SH");
  const [timeRange, setTimeRange] = useState<TimeRangeKey>("3y");
  const [refreshing, setRefreshing] = useState(false);
  const qc = useQueryClient();

  const { start, end } = useMemo(() => computeDateRange(timeRange), [timeRange]);

  const { data, isLoading, isFetching } = useIndexKline(indexCode, start, end);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      // Call API with refresh=true to force re-fetch + recompute
      await marketOverview.indexKline(indexCode, start, end, "daily", true);
      // Invalidate cache so useQuery picks up the new data
      await qc.invalidateQueries({ queryKey: ["index-kline"] });
    } catch {
      // ignore — user will see stale data
    } finally {
      setRefreshing(false);
    }
  }, [indexCode, start, end, qc]);

  const loading = refreshing || (isLoading && !data);

  return (
    <div className="flex flex-col gap-3 sm:gap-4 p-3 sm:p-4 h-[calc(100vh-3rem)]">
      {/* Toolbar */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        {/* Index selector */}
        <div className="flex gap-1">
          {INDEX_OPTIONS.map((idx) => (
            <button
              key={idx.code}
              onClick={() => setIndexCode(idx.code)}
              className={cn(
                "px-3 py-1.5 text-sm rounded-md transition-colors",
                indexCode === idx.code
                  ? "bg-accent text-accent-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
              )}
            >
              {idx.label}
            </button>
          ))}
        </div>
        {/* Time range + refresh */}
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {TIME_RANGES.map((tr) => (
              <button
                key={tr.key}
                onClick={() => setTimeRange(tr.key)}
                className={cn(
                  "px-3 py-1.5 text-sm rounded-md transition-colors",
                  timeRange === tr.key
                    ? "bg-accent text-accent-foreground font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                )}
              >
                {tr.label}
              </button>
            ))}
          </div>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md transition-colors",
              "text-muted-foreground hover:text-foreground hover:bg-accent/50",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
            title="刷新数据并重新计算市场阶段"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
            刷新数据
          </button>
        </div>
      </div>

      {/* Chart */}
      <div className="flex-1 min-h-0 border border-border/40 rounded-lg overflow-hidden bg-card relative">
        {loading ? (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            {refreshing ? "刷新中..." : "加载中..."}
          </div>
        ) : data && data.bars.length > 0 ? (
          <>
            {isFetching && (
              <div className="absolute top-2 right-2 z-10">
                <RefreshCw className="h-4 w-4 text-muted-foreground animate-spin" />
              </div>
            )}
            <IndexKlineChart bars={data.bars} regimes={data.regimes} />
          </>
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            暂无数据
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-3 sm:gap-4 text-xs sm:text-sm text-muted-foreground">
        {Object.entries(REGIME_LABELS).map(([key, info]) => (
          <div key={key} className="flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-3 rounded-sm"
              style={{ backgroundColor: info.color, opacity: 0.6 }}
            />
            <span>{info.label}</span>
          </div>
        ))}
      </div>

      {/* Stats table */}
      {data && data.regimes.length > 0 && <RegimeStats regimes={data.regimes} />}
    </div>
  );
}
