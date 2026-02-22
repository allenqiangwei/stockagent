"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  CandlestickSeries,
  HistogramSeries,
  type IChartApi,
  type Time,
} from "lightweight-charts";
import type { KlineBar, RegimeWeek } from "@/types";
import { RegimeBackgroundPrimitive, type RegimeZone } from "./regime-background";

interface IndexKlineChartProps {
  bars: KlineBar[];
  regimes: RegimeWeek[];
}

export function IndexKlineChart({ bars, regimes }: IndexKlineChartProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const candleRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const volumeRef = useRef<any>(null);
  const primitiveRef = useRef<RegimeBackgroundPrimitive | null>(null);
  const disposedRef = useRef(false);
  const prevDataKeyRef = useRef("");

  // ── Create chart (once) ──
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

    // Attach regime background primitive to candle series
    const primitive = new RegimeBackgroundPrimitive();
    candleSeries.attachPrimitive(primitive);

    disposedRef.current = false;
    chartRef.current = chart;
    candleRef.current = candleSeries;
    volumeRef.current = volumeSeries;
    primitiveRef.current = primitive;
    prevDataKeyRef.current = "";

    // ResizeObserver for responsive sizing
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
      primitiveRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Update data ──
  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    const volume = volumeRef.current;
    if (!chart || !candle || !volume || !bars.length) return;

    const dataKey = `${bars.length}:${bars[0].date}:${bars[bars.length - 1].date}`;
    if (dataKey === prevDataKeyRef.current) return;
    prevDataKeyRef.current = dataKey;

    candle.setData(
      bars.map((b) => ({
        time: b.date as Time,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }))
    );

    volume.setData(
      bars.map((b) => ({
        time: b.date as Time,
        value: b.volume,
        color:
          b.close >= b.open
            ? "rgba(239,68,68,0.3)"
            : "rgba(34,197,94,0.3)",
      }))
    );

    // Show last ~255 bars by default
    const total = bars.length;
    if (total > 255) {
      chart.timeScale().setVisibleLogicalRange({
        from: total - 255,
        to: total - 1,
      } as import("lightweight-charts").LogicalRange);
    } else {
      chart.timeScale().fitContent();
    }
  }, [bars]);

  // ── Update regime zones ──
  useEffect(() => {
    const primitive = primitiveRef.current;
    if (!primitive) return;

    const zones: RegimeZone[] = regimes.map((r) => ({
      start: r.week_start as Time,
      end: r.week_end as Time,
      regime: r.regime,
      confidence: r.confidence,
    }));

    primitive.setData(zones);
  }, [regimes]);

  return (
    <div ref={wrapperRef} className="relative w-full h-full overflow-hidden">
      <div ref={chartContainerRef} />
    </div>
  );
}
