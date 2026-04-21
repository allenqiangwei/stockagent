"use client";

import { useEffect, useRef, useMemo } from "react";
import {
  createChart,
  ColorType,
  LineSeries,
  AreaSeries,
  CrosshairMode,
  type IChartApi,
  type Time,
} from "lightweight-charts";

interface EquityCurveProps {
  /** Strategy equity curve: [{date, equity}] */
  data: { date: string; equity: number }[];
  /** Optional benchmark index return data (normalized to same starting value) */
  benchmark?: { date: string; equity: number }[];
  height?: number;
}

export function EquityCurve({ data, benchmark, height = 280 }: EquityCurveProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const disposedRef = useRef(false);

  // Compute drawdown series from equity data
  const drawdownData = useMemo(() => {
    if (!data.length) return [];
    let peak = data[0].equity;
    return data.map((p) => {
      if (p.equity > peak) peak = p.equity;
      const dd = peak > 0 ? ((p.equity - peak) / peak) * 100 : 0;
      return { time: p.date as Time, value: dd };
    });
  }, [data]);

  useEffect(() => {
    disposedRef.current = false;
    const container = containerRef.current;
    if (!container || data.length === 0) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#9ca3af",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      crosshair: { mode: CrosshairMode.Magnet },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: false },
    });
    chartRef.current = chart;

    // Strategy equity line (blue)
    const strategySeries = chart.addSeries(LineSeries, {
      color: "#3b82f6",
      lineWidth: 2,
      priceFormat: { type: "custom", formatter: (v: number) => v.toFixed(0) },
      crosshairMarkerRadius: 4,
    });
    strategySeries.setData(
      data.map((p) => ({ time: p.date as Time, value: p.equity }))
    );

    // Benchmark line (gray, if provided)
    if (benchmark && benchmark.length > 0) {
      const bmSeries = chart.addSeries(LineSeries, {
        color: "#6b7280",
        lineWidth: 1,
        lineStyle: 2, // dashed
        priceFormat: { type: "custom", formatter: (v: number) => v.toFixed(0) },
        crosshairMarkerRadius: 3,
      });
      bmSeries.setData(
        benchmark.map((p) => ({ time: p.date as Time, value: p.equity }))
      );
    }

    // Drawdown area (red, on a second price scale)
    if (drawdownData.some((d) => d.value < -0.5)) {
      const ddSeries = chart.addSeries(AreaSeries, {
        lineColor: "rgba(239,68,68,0.5)",
        lineWidth: 1,
        topColor: "rgba(239,68,68,0.0)",
        bottomColor: "rgba(239,68,68,0.15)",
        priceScaleId: "drawdown",
        priceFormat: {
          type: "custom",
          formatter: (v: number) => `${v.toFixed(1)}%`,
        },
      });
      ddSeries.setData(drawdownData);
      chart.priceScale("drawdown").applyOptions({
        scaleMargins: { top: 0.7, bottom: 0 },
        borderVisible: false,
      });
    }

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (disposedRef.current || !container) return;
      chart.resize(container.clientWidth, height);
    });
    ro.observe(container);

    return () => {
      disposedRef.current = true;
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [data, benchmark, drawdownData, height]);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center text-sm text-muted-foreground" style={{ height }}>
        无资金曲线数据
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div ref={containerRef} className="w-full" />
      <div className="flex items-center gap-4 text-[10px] text-muted-foreground px-1">
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-0.5 bg-blue-500 rounded" /> 策略
        </span>
        {benchmark && benchmark.length > 0 && (
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-gray-500 rounded border-dashed" /> 基准
          </span>
        )}
        {drawdownData.some((d) => d.value < -0.5) && (
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-2 bg-red-500/20 rounded" /> 回撤
          </span>
        )}
      </div>
    </div>
  );
}
