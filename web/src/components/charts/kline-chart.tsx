"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  createSeriesMarkers,
  ColorType,
  CrosshairMode,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
  type Time,
  type LogicalRange,
} from "lightweight-charts";
import type { KlineBar } from "@/types";
import type { OverlayLine } from "@/lib/indicator-meta";

/** Time-based visible range for cross-chart sync */
export type TimeRange = { from: Time; to: Time };

interface KlineChartProps {
  bars: KlineBar[];
  signals?: { date: string; action: string; strategy_name: string }[];
  overlays?: OverlayLine[];
  onLoadMore?: () => void;
  /** Called with the time-based visible range when user scrolls/zooms */
  onVisibleTimeRangeChange?: (range: TimeRange | null) => void;
  /** Called when chart is ready to accept external range sync */
  onSyncReady?: (syncFn: (range: TimeRange) => void) => void;
  defaultBars?: number;
}

export function KlineChart({
  bars,
  signals = [],
  overlays = [],
  onLoadMore,
  onVisibleTimeRangeChange,
  onSyncReady,
  defaultBars = 255,
}: KlineChartProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const candleRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const volumeRef = useRef<any>(null);
  const overlaySeriesRef = useRef<Map<string, ISeriesApi<SeriesType>>>(new Map());
  const isFirstDataRef = useRef(true);
  const loadMoreRef = useRef(onLoadMore);
  loadMoreRef.current = onLoadMore;
  const visibleRangeCallbackRef = useRef(onVisibleTimeRangeChange);
  visibleRangeCallbackRef.current = onVisibleTimeRangeChange;
  const onSyncReadyRef = useRef(onSyncReady);
  onSyncReadyRef.current = onSyncReady;
  const prevDataKeyRef = useRef("");
  const prevOverlayKeyRef = useRef("");
  const isSyncingRef = useRef(false);
  const disposedRef = useRef(false);

  // ── Create chart structure (once per mount) ──
  useEffect(() => {
    if (!chartContainerRef.current || !wrapperRef.current) return;

    const { clientWidth: w, clientHeight: h } = wrapperRef.current;
    if (w === 0 || h === 0) return;

    const chart = createChart(chartContainerRef.current, {
      width: w,
      height: h,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#9ca3af",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.1)",
        scaleMargins: { top: 0.1, bottom: 0.25 },
      },
      timeScale: {
        borderColor: "rgba(255,255,255,0.1)",
        timeVisible: false,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
    });

    // A-share convention: red=up, green=down
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#ef4444",
      downColor: "#22c55e",
      borderUpColor: "#ef4444",
      borderDownColor: "#22c55e",
      wickUpColor: "#ef4444",
      wickDownColor: "#22c55e",
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    disposedRef.current = false;

    // Lazy loading + time sync (use logical range for load detection, time range for sync)
    const mountTime = Date.now();
    chart.timeScale().subscribeVisibleLogicalRangeChange((range: LogicalRange | null) => {
      if (disposedRef.current) return;
      // Gate loadMore by 1500ms to avoid triggering during initial render
      if (range && range.from < 20 && loadMoreRef.current && Date.now() - mountTime > 1500) {
        loadMoreRef.current();
      }
      // Emit time-based range for cross-chart sync
      if (!isSyncingRef.current && visibleRangeCallbackRef.current) {
        const timeRange = chart.timeScale().getVisibleRange();
        visibleRangeCallbackRef.current(timeRange);
      }
    });

    chartRef.current = chart;
    candleRef.current = candleSeries;
    volumeRef.current = volumeSeries;
    isFirstDataRef.current = true;
    prevDataKeyRef.current = "";
    prevOverlayKeyRef.current = "";

    // Register sync function with parent (time-based)
    if (onSyncReadyRef.current) {
      onSyncReadyRef.current((range: TimeRange) => {
        if (disposedRef.current) return;
        try {
          isSyncingRef.current = true;
          chart.timeScale().setVisibleRange(range);
        } catch {
          // Chart may not have data yet — ignore
        } finally {
          requestAnimationFrame(() => { isSyncingRef.current = false; });
        }
      });
    }

    // Manual resize via ResizeObserver
    const wrapper = wrapperRef.current;
    const ro = new ResizeObserver(() => {
      if (disposedRef.current) return;
      const nw = wrapper?.clientWidth ?? 0;
      const nh = wrapper?.clientHeight ?? 0;
      if (nw > 0 && nh > 0) chart.resize(nw, nh);
    });
    ro.observe(wrapper);

    return () => {
      disposedRef.current = true;
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      overlaySeriesRef.current.clear();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Update candlestick/volume data ──
  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    const volume = volumeRef.current;
    if (!chart || !candle || !volume || !bars.length) return;

    const dataKey = `${bars.length}:${bars[0].date}:${bars[bars.length - 1].date}`;
    if (dataKey === prevDataKeyRef.current) return;
    prevDataKeyRef.current = dataKey;

    const prevTimeRange = !isFirstDataRef.current
      ? chart.timeScale().getVisibleRange()
      : null;

    const candleData = bars.map((b) => ({
      time: b.date as Time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    candle.setData(candleData);

    const volumeData = bars.map((b) => ({
      time: b.date as Time,
      value: b.volume,
      color:
        b.close >= b.open
          ? "rgba(239,68,68,0.3)"
          : "rgba(34,197,94,0.3)",
    }));
    volume.setData(volumeData);

    if (signals.length > 0) {
      createSeriesMarkers(
        candle,
        signals.map((s) => ({
          time: s.date as Time,
          position:
            s.action === "buy"
              ? ("belowBar" as const)
              : ("aboveBar" as const),
          color: s.action === "buy" ? "#ef4444" : "#22c55e",
          shape:
            s.action === "buy"
              ? ("arrowUp" as const)
              : ("arrowDown" as const),
          text: `${s.action === "buy" ? "B" : "S"} ${s.strategy_name}`,
        }))
      );
    }

    if (isFirstDataRef.current) {
      const total = candleData.length;
      if (defaultBars && total > defaultBars) {
        chart
          .timeScale()
          .setVisibleLogicalRange({ from: total - defaultBars, to: total - 1 } as LogicalRange);
      } else {
        chart.timeScale().fitContent();
      }
      isFirstDataRef.current = false;
    } else if (prevTimeRange) {
      chart.timeScale().setVisibleRange(prevTimeRange);
    }
  }, [bars, signals, defaultBars]);

  // ── Update overlay lines (MA, EMA) ──
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    // Build a key to detect changes
    const overlayKey = overlays.map((o) => `${o.key}:${o.data.length}`).join("|");
    if (overlayKey === prevOverlayKeyRef.current) return;
    prevOverlayKeyRef.current = overlayKey;

    const currentKeys = new Set(overlays.map((o) => o.key));

    // Remove series that are no longer needed
    for (const [key, series] of overlaySeriesRef.current) {
      if (!currentKeys.has(key)) {
        chart.removeSeries(series);
        overlaySeriesRef.current.delete(key);
      }
    }

    // Add or update series
    for (const overlay of overlays) {
      let series = overlaySeriesRef.current.get(overlay.key);
      if (!series) {
        series = chart.addSeries(LineSeries, {
          color: overlay.color,
          lineWidth: 1,
          lineStyle: overlay.lineStyle === 2 ? LineStyle.Dashed : LineStyle.Solid,
          crosshairMarkerVisible: false,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        overlaySeriesRef.current.set(overlay.key, series);
      }
      series.setData(
        overlay.data.map((d) => ({ time: d.time as Time, value: d.value }))
      );
    }
  }, [overlays]);

  return (
    <div ref={wrapperRef} className="relative w-full h-full overflow-hidden">
      <div ref={chartContainerRef} />
      {/* Overlay indicator legend */}
      {overlays.length > 0 && (
        <div className="absolute top-1 left-1 z-10 flex flex-wrap gap-x-3 gap-y-0.5 pointer-events-none">
          {overlays.map((o) => (
            <span
              key={o.key}
              className="text-[11px] font-medium leading-tight"
              style={{ color: o.color }}
            >
              {o.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
