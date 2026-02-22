# Market Page: Indicator System + Watchlist Button Design

## Overview

Upgrade the market page to support professional indicator display with TradingView-style multi-pane layout, overlay indicators on the main chart, and a watchlist add/remove button.

## Indicator Classification

**Overlay (on main K-line chart, shared price axis):**
- MA: MA5, MA10, MA20, MA60, MA120, MA250
- EMA: EMA12, EMA26, EMA50

**Independent Pane (each indicator gets its own resizable panel):**
- MACD (12,26,9): histogram + DIF/DEA lines
- RSI (14): 0-100 range, 30/70 reference lines
- KDJ (9,3,3): K/D/J three lines, 0-100 range
- ADX (14): +DI/-DI/ADX three lines
- OBV: cumulative volume line
- ATR (14): volatility

VOL remains as an overlay histogram on the main chart (existing behavior).

## Header Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ 000001 平安银行 ★  │  MA  EMA  MACD  RSI  KDJ  ADX  │  日K 周K 月K │
└──────────────────────────────────────────────────────────────────┘
```

- **Watchlist button (★)**: Solid yellow = in watchlist, hollow gray = not. Click to toggle.
- **Indicator labels**: Click disabled indicator to enable (default params). Click enabled indicator to open params Popover. Popover has "remove" button to disable.
- **Default enabled**: MA + MACD

## Indicator Params Popover

| Indicator | Popover Content |
|-----------|----------------|
| MA | Checkboxes: MA5 MA10 MA20 MA60 MA120 MA250 |
| EMA | Checkboxes: EMA12 EMA26 EMA50 |
| RSI | Period input (default 14) |
| MACD | Fast/Slow/Signal inputs (default 12/26/9) |
| KDJ | N/M1/M2 inputs (default 9/3/3) |
| ADX | Period input (default 14) |

Changes apply immediately (no confirm button).

## Chart Panel Architecture

Vertical ResizablePanelGroup in the center area:

```
┌────────────────────────────────┐
│  Main chart (K-line+MA+VOL)    │  flex-1
├──────── drag handle ───────────┤
│  MACD pane (default 100px)     │  resizable
├──────── drag handle ───────────┤
│  RSI pane (default 100px)      │  resizable
└────────────────────────────────┘
```

- Panels are dynamic: enable RSI = add panel, disable = remove
- Time axis sync across all chart instances via `subscribeVisibleLogicalRangeChange`
- Only bottom-most panel shows time axis labels

## Data Flow

1. Store holds `indicators` state (enabled/params per indicator)
2. Enabled indicators → build API query string (e.g. "MA,RSI,MACD")
3. Single `useIndicators()` call returns all data
4. Frontend splits by column prefix (MA_, RSI_, MACD_, etc.)
5. Overlay data → KlineChart `overlays` prop
6. Pane data → individual IndicatorChart instances

## Zustand State

```ts
indicators: {
  MA:   { enabled: true, params: { periods: [5, 10, 20, 60] } },
  EMA:  { enabled: false, params: { periods: [12, 26] } },
  RSI:  { enabled: false, params: { period: 14 } },
  MACD: { enabled: true, params: { fast: 12, slow: 26, signal: 9 } },
  KDJ:  { enabled: false, params: { n: 9, m1: 3, m2: 3 } },
  ADX:  { enabled: false, params: { period: 14 } },
  OBV:  { enabled: false, params: {} },
  ATR:  { enabled: false, params: { period: 14 } },
}
```

## File Changes

| File | Action | Content |
|------|--------|---------|
| `web/src/lib/store.ts` | Modify | Add indicators state + actions |
| `web/src/lib/indicator-meta.ts` | New | INDICATOR_META constants + splitIndicatorData() |
| `web/src/app/market/page.tsx` | Modify | Header watchlist+indicators, vertical pane layout |
| `web/src/components/charts/kline-chart.tsx` | Modify | Add overlays prop for MA/EMA lines |
| `web/src/components/charts/indicator-chart.tsx` | Modify | Single-indicator pane mode, time sync |
| `web/src/components/market/indicator-toolbar.tsx` | New | Indicator labels + param Popovers |
| `web/src/components/market/watchlist-button.tsx` | New | Star toggle button |

Backend: zero changes.
