"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineSeries,
  HistogramSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
  type Time,
} from "lightweight-charts";
import type { PaneData } from "@/lib/indicator-meta";
import type { TimeRange } from "./kline-chart";

interface IndicatorChartProps {
  pane: PaneData;
  /** Whether to show the time axis labels (only bottom pane should) */
  showTimeAxis?: boolean;
  /** Called with time-based range when user scrolls/zooms */
  onVisibleTimeRangeChange?: (range: TimeRange | null) => void;
  /** Called when chart is ready to accept external range sync */
  onSyncReady?: (syncFn: (range: TimeRange) => void) => void;
  /** Initial time range to apply after first data load (from main chart) */
  initialTimeRange?: TimeRange | null;
}

export function IndicatorChart({
  pane,
  showTimeAxis = true,
  onVisibleTimeRangeChange,
  onSyncReady,
  initialTimeRange,
}: IndicatorChartProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesMapRef = useRef<Map<string, ISeriesApi<SeriesType>>>(new Map());
  const prevDataKeyRef = useRef("");
  const isSyncingRef = useRef(false);
  const isFirstDataRef = useRef(true);
  const disposedRef = useRef(false);
  const visibleRangeCallbackRef = useRef(onVisibleTimeRangeChange);
  visibleRangeCallbackRef.current = onVisibleTimeRangeChange;
  const onSyncReadyRef = useRef(onSyncReady);
  onSyncReadyRef.current = onSyncReady;
  const initialTimeRangeRef = useRef(initialTimeRange);
  initialTimeRangeRef.current = initialTimeRange;

  // ── Create chart (once per mount) ──
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
        fontSize: 10,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.1)" },
      timeScale: {
        borderColor: "rgba(255,255,255,0.1)",
        timeVisible: false,
        visible: showTimeAxis,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
    });

    disposedRef.current = false;

    // Emit time-based range changes for cross-chart sync
    chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
      if (disposedRef.current) return;
      if (!isSyncingRef.current && visibleRangeCallbackRef.current) {
        const timeRange = chart.timeScale().getVisibleRange();
        visibleRangeCallbackRef.current(timeRange);
      }
    });

    chartRef.current = chart;
    prevDataKeyRef.current = "";
    isFirstDataRef.current = true;

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
      seriesMapRef.current.clear();
    };
  }, [showTimeAxis]);

  // ── Update data ──
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !pane.series.length) return;

    const dataKey = pane.series.map((s) => `${s.key}:${s.data.length}`).join("|");
    if (dataKey === prevDataKeyRef.current) return;
    prevDataKeyRef.current = dataKey;

    const currentKeys = new Set(pane.series.map((s) => s.key));

    // Remove old series
    for (const [key, series] of seriesMapRef.current) {
      if (!currentKeys.has(key)) {
        chart.removeSeries(series);
        seriesMapRef.current.delete(key);
      }
    }

    // Add or update series
    for (const s of pane.series) {
      let series = seriesMapRef.current.get(s.key);
      if (!series) {
        if (s.type === "histogram") {
          series = chart.addSeries(HistogramSeries, {
            color: s.color,
            priceLineVisible: false,
            lastValueVisible: false,
            title: s.displayName,
          });
        } else {
          series = chart.addSeries(LineSeries, {
            color: s.color,
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: true,
            title: s.displayName,
          });
        }
        seriesMapRef.current.set(s.key, series);
      }
      series.setData(
        s.data.map((d) => ({
          time: d.time as Time,
          value: d.value,
          ...(s.type === "histogram" ? { color: d.value >= 0 ? "#ef4444" : "#22c55e" } : {}),
        }))
      );
    }

    // Reference lines (drawn as invisible price lines)
    if (pane.meta.referenceLines) {
      const firstLineSeries = Array.from(seriesMapRef.current.values())[0];
      if (firstLineSeries) {
        for (const level of pane.meta.referenceLines) {
          firstLineSeries.createPriceLine({
            price: level,
            color: "rgba(255,255,255,0.15)",
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: false,
          });
        }
      }
    }

    // On first data load, apply initial time range from main chart.
    // Must defer to next frame — chart needs time to process setData() before setVisibleRange works.
    if (isFirstDataRef.current && initialTimeRangeRef.current) {
      const range = initialTimeRangeRef.current;
      isSyncingRef.current = true;
      requestAnimationFrame(() => {
        if (disposedRef.current) return;
        try {
          chart.timeScale().setVisibleRange(range);
        } catch { /* ignore */ }
        requestAnimationFrame(() => { isSyncingRef.current = false; });
      });
    } else if (isFirstDataRef.current) {
      chart.timeScale().fitContent();
    }
    isFirstDataRef.current = false;
  }, [pane]);

  return (
    <div ref={wrapperRef} className="w-full h-full overflow-hidden">
      <div ref={chartContainerRef} />
    </div>
  );
}
