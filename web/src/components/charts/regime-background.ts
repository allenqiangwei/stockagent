/**
 * RegimeBackgroundPrimitive — lightweight-charts v5 ISeriesPrimitive
 *
 * Draws semi-transparent colored rectangles behind the candlestick chart,
 * one per regime week. Colors follow A-share convention (red=bull, green=bear).
 */

import type {
  ISeriesPrimitive,
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  SeriesAttachedParameter,
  Time,
} from "lightweight-charts";
import type { CanvasRenderingTarget2D } from "fancy-canvas";

export interface RegimeZone {
  start: Time;
  end: Time;
  regime: string;
  confidence: number;
}

/** A-share color mapping: red=bull, green=bear */
const REGIME_COLORS: Record<string, string> = {
  trending_bull: "239, 68, 68",   // red
  trending_bear: "34, 197, 94",   // green
  ranging: "234, 179, 8",         // yellow
  volatile: "168, 85, 247",       // purple
};

const BASE_ALPHA = 0.18;

class RegimePaneRenderer implements IPrimitivePaneRenderer {
  private _zones: RegimeZone[] = [];
  private _timeToCoord: ((t: Time) => number | null) | null = null;
  private _chartHeight = 0;

  update(
    zones: RegimeZone[],
    timeToCoord: (t: Time) => number | null,
    chartHeight: number,
  ) {
    this._zones = zones;
    this._timeToCoord = timeToCoord;
    this._chartHeight = chartHeight;
  }

  draw(target: CanvasRenderingTarget2D) {
    // Not used — we draw in drawBackground
  }

  drawBackground(target: CanvasRenderingTarget2D) {
    if (!this._timeToCoord || this._zones.length === 0) return;

    const timeToCoord = this._timeToCoord;
    const zones = this._zones;
    const chartHeight = this._chartHeight;

    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      const h = chartHeight || mediaSize.height;
      for (const zone of zones) {
        const x1 = timeToCoord(zone.start);
        const x2 = timeToCoord(zone.end);
        if (x1 === null || x2 === null) continue;

        const rgb = REGIME_COLORS[zone.regime] ?? "128, 128, 128";
        const alpha = BASE_ALPHA * Math.max(0.3, zone.confidence);
        ctx.fillStyle = `rgba(${rgb}, ${alpha})`;
        ctx.fillRect(
          Math.min(x1, x2),
          0,
          Math.abs(x2 - x1) + 1,
          h,
        );
      }
    });
  }
}

class RegimePaneView implements IPrimitivePaneView {
  private _renderer = new RegimePaneRenderer();
  private _source: RegimeBackgroundPrimitive;

  constructor(source: RegimeBackgroundPrimitive) {
    this._source = source;
  }

  update() {
    const chart = this._source.chart;
    if (!chart) return;

    const timeScale = chart.timeScale();
    this._renderer.update(
      this._source.zones,
      (t: Time) => timeScale.timeToCoordinate(t),
      chart.chartElement().clientHeight,
    );
  }

  renderer(): IPrimitivePaneRenderer {
    return this._renderer;
  }
}

export class RegimeBackgroundPrimitive implements ISeriesPrimitive<Time> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  chart: any = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private _series: any = null;
  private _paneView: RegimePaneView;
  private _requestUpdate?: () => void;
  zones: RegimeZone[] = [];

  constructor() {
    this._paneView = new RegimePaneView(this);
  }

  attached(param: SeriesAttachedParameter<Time>) {
    this.chart = param.chart;
    this._series = param.series;
    this._requestUpdate = param.requestUpdate;
  }

  detached() {
    this.chart = null;
    this._series = null;
    this._requestUpdate = undefined;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this._paneView];
  }

  updateAllViews() {
    this._paneView.update();
  }

  setData(zones: RegimeZone[]) {
    this.zones = zones;
    if (this._requestUpdate) {
      this._requestUpdate();
    }
  }
}
