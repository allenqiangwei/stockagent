"use client";

import { useState, useMemo, useCallback, useEffect, useRef, Fragment } from "react";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAppStore, type IndicatorKey } from "@/lib/store";
import { useKline, useIndicators } from "@/hooks/use-queries";
import { KlineChart, type TimeRange } from "@/components/charts/kline-chart";
import { IndicatorChart } from "@/components/charts/indicator-chart";
import { WatchlistPanel } from "@/components/panels/watchlist-panel";
import { PortfolioPanel } from "@/components/panels/portfolio-panel";
import { QuotePanel } from "@/components/panels/quote-panel";
import { WatchlistButton } from "@/components/market/watchlist-button";
import { IndicatorToolbar } from "@/components/market/indicator-toolbar";
import { buildIndicatorQuery, splitIndicatorData, INDICATOR_META } from "@/lib/indicator-meta";
import type { Time } from "lightweight-charts";

function dateStr(d: Date) {
  return d.toISOString().slice(0, 10);
}

// Data range tiers per period (years)
const LOAD_RANGES: Record<string, number[]> = {
  daily: [1.5, 10],
  weekly: [6, 25],
  monthly: [25, 25],
};

// ── Mobile view selector ──────────────────────────
type MobileView = "chart" | "watchlist" | "portfolio" | "quote";

// ── Left panel tab selector ─────────────────────
type LeftTab = "watchlist" | "portfolio";

// ── Hook: responsive breakpoint ───────────────────
function useIsMobile() {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mql = window.matchMedia("(max-width: 767px)");
    setIsMobile(mql.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);
  return isMobile;
}

export default function MarketPage() {
  const code = useAppStore((s) => s.currentStock);
  const name = useAppStore((s) => s.currentStockName);
  const period = useAppStore((s) => s.chartPeriod);
  const setPeriod = useAppStore((s) => s.setChartPeriod);
  const indicators = useAppStore((s) => s.indicators);

  const [loadLevel, setLoadLevel] = useState(0);
  const [mobileView, setMobileView] = useState<MobileView>("chart");
  const [leftTab, setLeftTab] = useState<LeftTab>("watchlist");
  const isMobile = useIsMobile();

  // Reset load level when period changes
  useEffect(() => {
    setLoadLevel(0);
  }, [period]);

  const end = useMemo(() => dateStr(new Date()), []);
  const start = useMemo(() => {
    const d = new Date();
    const years = (LOAD_RANGES[period] ?? LOAD_RANGES.daily)[Math.min(loadLevel, 1)];
    d.setFullYear(d.getFullYear() - Math.floor(years));
    if (years % 1 > 0) {
      d.setMonth(d.getMonth() - Math.round((years % 1) * 12));
    }
    return dateStr(d);
  }, [period, loadLevel]);

  // Build indicator query from store
  const indicatorQuery = useMemo(() => buildIndicatorQuery(indicators), [indicators]);

  const { data: kline, isLoading: klineLoading } = useKline(code, start, end, period);
  const { data: indicatorData } = useIndicators(code, indicatorQuery, start, end);

  // Split indicator data into overlays and panes
  const { overlays, panes } = useMemo(
    () => splitIndicatorData(indicatorData?.data ?? [], indicators),
    [indicatorData, indicators]
  );

  // Enabled pane indicators (for dynamic panel rendering)
  const enabledPanes = useMemo(
    () =>
      (Object.keys(indicators) as IndicatorKey[]).filter(
        (k) => indicators[k].enabled && INDICATOR_META[k].type === "pane"
      ),
    [indicators]
  );

  const handleLoadMore = useCallback(() => {
    setLoadLevel((prev) => Math.min(prev + 1, 1));
  }, []);

  const chartReady = kline?.bars?.length && kline.period === period && kline.stock_code === code;

  // Compute initial time range from bar data (matches KlineChart's defaultBars=255)
  const defaultBars = 255;
  const initialTimeRange = useMemo<TimeRange | null>(() => {
    if (!kline?.bars?.length) return null;
    const bars = kline.bars;
    const total = bars.length;
    const fromIdx = total > defaultBars ? total - defaultBars : 0;
    return {
      from: bars[fromIdx].date as Time,
      to: bars[total - 1].date as Time,
    } as TimeRange;
  }, [kline?.bars]);

  // ── Time axis sync via callbacks (time-based) ──
  const mainSyncFnRef = useRef<((range: TimeRange) => void) | null>(null);
  const paneSyncFnsRef = useRef<Map<string, (range: TimeRange) => void>>(new Map());
  const lastMainTimeRangeRef = useRef<TimeRange | null>(null);

  const handleMainSyncReady = useCallback((syncFn: (range: TimeRange) => void) => {
    mainSyncFnRef.current = syncFn;
  }, []);

  const handlePaneSyncReady = useCallback((indKey: string, syncFn: (range: TimeRange) => void) => {
    paneSyncFnsRef.current.set(indKey, syncFn);
  }, []);

  const handleVisibleTimeRangeChange = useCallback((range: TimeRange | null) => {
    if (!range) return;
    lastMainTimeRangeRef.current = range;
    paneSyncFnsRef.current.forEach((syncFn) => syncFn(range));
  }, []);

  const handlePaneTimeRangeChange = useCallback((range: TimeRange | null) => {
    if (!range) return;
    if (mainSyncFnRef.current) mainSyncFnRef.current(range);
    paneSyncFnsRef.current.forEach((syncFn) => syncFn(range));
  }, []);

  useEffect(() => {
    if (!panes.length) return;
    const timer = setTimeout(() => {
      const range = lastMainTimeRangeRef.current ?? initialTimeRange;
      if (!range) return;
      paneSyncFnsRef.current.forEach((syncFn) => syncFn(range));
    }, 200);
    return () => clearTimeout(timer);
  }, [panes, initialTimeRange]);

  // ── Header bar (shared between mobile/desktop) ──
  const headerBar = (
    <div className="flex items-center justify-between px-2 sm:px-3 py-1.5 border-b border-border/40 gap-1 sm:gap-2 min-w-0">
      <div className="flex items-center gap-1 sm:gap-2 shrink-0 min-w-0">
        <span className="font-mono text-xs sm:text-sm truncate">{code}</span>
        <span className="text-xs sm:text-sm text-muted-foreground truncate hidden xs:inline">{name}</span>
        <WatchlistButton />
      </div>
      <div className="flex-1 flex justify-center overflow-x-auto min-w-0 hidden sm:flex">
        <IndicatorToolbar />
      </div>
      <Tabs value={period} onValueChange={(v) => setPeriod(v as typeof period)} className="shrink-0">
        <TabsList className="h-7">
          <TabsTrigger value="daily" className="text-xs px-2 h-6">日K</TabsTrigger>
          <TabsTrigger value="weekly" className="text-xs px-2 h-6">周K</TabsTrigger>
          <TabsTrigger value="monthly" className="text-xs px-2 h-6">月K</TabsTrigger>
        </TabsList>
      </Tabs>
    </div>
  );

  // ── Chart content (shared) ──
  const chartContent = (
    <div className="flex-1 min-h-0">
      {enabledPanes.length > 0 ? (
        <ResizablePanelGroup orientation="vertical">
          <ResizablePanel defaultSize="65%" minSize="30%">
            <div className="relative w-full h-full">
              <div className="absolute inset-0">
                {!chartReady && klineLoading ? (
                  <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
                    加载K线数据中...
                  </div>
                ) : chartReady ? (
                  <KlineChart
                    key={`${code}-${period}`}
                    bars={kline.bars}
                    signals={kline.signals}
                    overlays={overlays}
                    onLoadMore={loadLevel < 1 ? handleLoadMore : undefined}
                    onVisibleTimeRangeChange={handleVisibleTimeRangeChange}
                    onSyncReady={handleMainSyncReady}
                    defaultBars={255}
                  />
                ) : (
                  <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
                    无数据
                  </div>
                )}
              </div>
            </div>
          </ResizablePanel>

          {enabledPanes.map((indKey, idx) => {
            const paneData = panes.find((p) => p.indicatorKey === indKey);
            const isLast = idx === enabledPanes.length - 1;
            return (
              <Fragment key={indKey}>
                <ResizableHandle />
                <ResizablePanel defaultSize="17%" minSize="8%">
                  <div className="relative w-full h-full border-t border-border/40">
                    <div className="absolute inset-0">
                      <div className="absolute top-0.5 left-1 z-10 text-[10px] text-muted-foreground/60">
                        {INDICATOR_META[indKey].label}
                      </div>
                      {paneData ? (
                        <IndicatorChart
                          key={`${code}-${period}-${indKey}`}
                          pane={paneData}
                          showTimeAxis={isLast}
                          onVisibleTimeRangeChange={handlePaneTimeRangeChange}
                          onSyncReady={(fn) => handlePaneSyncReady(indKey, fn)}
                          initialTimeRange={lastMainTimeRangeRef.current ?? initialTimeRange}
                        />
                      ) : (
                        <div className="flex items-center justify-center h-full text-xs text-muted-foreground">
                          {INDICATOR_META[indKey].label} 加载中...
                        </div>
                      )}
                    </div>
                  </div>
                </ResizablePanel>
              </Fragment>
            );
          })}
        </ResizablePanelGroup>
      ) : (
        <div className="relative w-full h-full">
          <div className="absolute inset-0">
            {!chartReady && klineLoading ? (
              <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
                加载K线数据中...
              </div>
            ) : chartReady ? (
              <KlineChart
                key={`${code}-${period}`}
                bars={kline.bars}
                signals={kline.signals}
                overlays={overlays}
                onLoadMore={loadLevel < 1 ? handleLoadMore : undefined}
                defaultBars={255}
              />
            ) : (
              <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
                无数据
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );

  // ── Mobile layout ──────────────────────────────
  if (isMobile) {
    return (
      <div className="h-[calc(100vh-3rem)] flex flex-col">
        {/* Mobile view tabs */}
        <div className="flex border-b border-border/40 shrink-0">
          {(
            [
              { key: "chart", label: "K线" },
              { key: "watchlist", label: "自选" },
              { key: "portfolio", label: "持仓" },
              { key: "quote", label: "详情" },
            ] as const
          ).map((tab) => (
            <button
              key={tab.key}
              onClick={() => setMobileView(tab.key)}
              className={`flex-1 py-2 text-xs text-center transition-colors ${
                mobileView === tab.key
                  ? "text-foreground font-medium border-b-2 border-primary"
                  : "text-muted-foreground"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Mobile content */}
        {mobileView === "chart" && (
          <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
            {headerBar}
            {/* Indicator toolbar below header on mobile */}
            <div className="px-2 py-1 border-b border-border/40 overflow-x-auto sm:hidden">
              <IndicatorToolbar />
            </div>
            {chartContent}
          </div>
        )}

        {mobileView === "watchlist" && (
          <div className="flex-1 min-h-0 overflow-y-auto">
            <WatchlistPanel />
          </div>
        )}

        {mobileView === "portfolio" && (
          <div className="flex-1 min-h-0 overflow-y-auto">
            <PortfolioPanel />
          </div>
        )}

        {mobileView === "quote" && (
          <div className="flex-1 min-h-0 overflow-y-auto">
            <QuotePanel />
          </div>
        )}
      </div>
    );
  }

  // ── Desktop layout (md+) ──────────────────────
  return (
    <div className="h-[calc(100vh-3rem)]">
      <ResizablePanelGroup orientation="horizontal">
        {/* Left: Watchlist / Portfolio */}
        <ResizablePanel defaultSize="15%" minSize="10%" maxSize="25%">
          <div className="flex flex-col h-full">
            <div className="flex border-b border-border/40 shrink-0">
              {(
                [
                  { key: "watchlist", label: "自选" },
                  { key: "portfolio", label: "持仓" },
                ] as const
              ).map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setLeftTab(tab.key)}
                  className={`flex-1 py-1.5 text-xs text-center transition-colors ${
                    leftTab === tab.key
                      ? "text-foreground font-medium border-b-2 border-primary"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="flex-1 min-h-0">
              {leftTab === "watchlist" ? <WatchlistPanel /> : <PortfolioPanel />}
            </div>
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* Center: Charts */}
        <ResizablePanel defaultSize="65%" minSize="40%">
          <div className="flex flex-col h-full overflow-hidden">
            {headerBar}
            {chartContent}
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* Right: Quote info */}
        <ResizablePanel defaultSize="20%" minSize="15%" maxSize="30%">
          <QuotePanel />
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
