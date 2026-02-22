"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  AreaSeries,
  CrosshairMode,
  type IChartApi,
  type Time,
} from "lightweight-charts";

interface EquityCurveChartProps {
  data: { date: string; equity: number }[];
  height?: number;
}

export function EquityCurveChart({ data, height = 220 }: EquityCurveChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const disposedRef = useRef(false);

  useEffect(() => {
    disposedRef.current = false;
    const container = containerRef.current;
    if (!container) return;

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
      rightPriceScale: {
        borderVisible: false,
      },
      timeScale: {
        borderVisible: false,
        timeVisible: false,
      },
    });
    chartRef.current = chart;

    const series = chart.addSeries(AreaSeries, {
      lineColor: "#3b82f6",
      lineWidth: 2,
      topColor: "rgba(59,130,246,0.3)",
      bottomColor: "rgba(59,130,246,0.02)",
      crosshairMarkerRadius: 4,
      priceFormat: { type: "custom", formatter: (v: number) => v.toFixed(0) },
    });

    const chartData = data.map((p) => ({
      time: p.date as Time,
      value: p.equity,
    }));
    series.setData(chartData);

    if (chartData.length > 0) {
      chart.timeScale().fitContent();
    }

    // Resize observer
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
  }, [data, height]);

  return <div ref={containerRef} className="w-full" />;
}
