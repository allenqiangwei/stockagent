# Alpha评分排名层 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an Alpha scoring/ranking layer on top of the existing rule-engine signal system so that when multiple stocks trigger buy signals, they are scored (0-100) and ranked, with only the Top 5 shown to the user.

**Architecture:** Scoring computation happens inside `SignalEngine._evaluate_stock()` — after buy signals are determined, a fixed-parameter indicator set (RSI_14, KDJ_9_3_3, MACD_12_26_9, MA_20) is computed and three sub-scores (oversold depth, multi-strategy consensus, volume-price) are calculated. Scores are persisted in existing unused DB columns (`final_score`, `swing_score`, `trend_score`). The API adds an `alpha_top` field to `/api/signals/today`. The frontend renders an Alpha Top 5 card row above the existing signal grid.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, pandas, Next.js 16, React 19, shadcn/ui, TanStack Query, Tailwind CSS

---

### Task 1: Backend — Add `_compute_alpha_score()` method

**Files:**
- Modify: `api/services/signal_engine.py:1-5` (imports), `:195-343` (_evaluate_stock + new method)

**Step 1: Add the `_compute_alpha_score` method**

Add this new method to the `SignalEngine` class, right before the `# ── Persistence` comment at line 345. Also add a module-level constant for the scoring IndicatorConfig.

At the top of the file (after the existing imports around line 20), add:

```python
import pandas as pd

# Fixed indicator params used for Alpha scoring (never changes per strategy)
_SCORING_CONFIG = IndicatorConfig(
    ma_periods=[20],
    ema_periods=[],
    rsi_periods=[14],
    macd_params_list=[(12, 26, 9)],
    kdj_params_list=[(9, 3, 3)],
    adx_periods=[],
    atr_periods=[],
    calc_obv=False,
)
```

Then add the method to the class (before `_save_signal`):

```python
def _compute_alpha_score(
    self,
    df: pd.DataFrame,
    buy_strategies: list[str],
    total_strategies: int,
) -> tuple[float, dict]:
    """Compute Alpha score for a stock that triggered buy signals.

    Args:
        df: Raw OHLCV DataFrame (will compute indicators with fixed params).
        buy_strategies: List of strategy names that triggered buy.
        total_strategies: Total number of enabled strategies.

    Returns:
        (total_score, {"oversold": x, "consensus": y, "volume_price": z})
    """
    scored_df = self.indicator_engine.compute(df, config=_SCORING_CONFIG)
    if scored_df is None or scored_df.empty or len(scored_df) < 2:
        return 0.0, {"oversold": 0.0, "consensus": 0.0, "volume_price": 0.0}

    latest = scored_df.iloc[-1]
    prev = scored_df.iloc[-2]

    # ── 1. Oversold depth (0-30) ──
    rsi_val = latest.get("RSI_14")
    rsi_score = max(0.0, (30 - (rsi_val or 50)) / 30 * 15) if rsi_val is not None and not pd.isna(rsi_val) else 0.0

    kdj_k = latest.get("KDJ_K_9_3_3")
    kdj_score = max(0.0, (20 - (kdj_k or 50)) / 20 * 10) if kdj_k is not None and not pd.isna(kdj_k) else 0.0

    macd_hist = latest.get("MACD_hist_12_26_9")
    macd_prev = prev.get("MACD_hist_12_26_9")
    macd_turning = 5.0 if (
        macd_hist is not None and macd_prev is not None
        and not pd.isna(macd_hist) and not pd.isna(macd_prev)
        and float(macd_hist) > float(macd_prev)
    ) else 0.0

    oversold = min(30.0, rsi_score + kdj_score + macd_turning)

    # ── 2. Multi-strategy consensus (0-40) ──
    consensus = (len(buy_strategies) / max(total_strategies, 1)) * 40.0

    # ── 3. Volume-price (0-30) ──
    vol = latest.get("volume")
    # Compute 5-day volume MA manually from the DataFrame
    vol_ma5 = scored_df["volume"].iloc[-5:].mean() if len(scored_df) >= 5 else None
    if vol is not None and vol_ma5 is not None and vol_ma5 > 0 and not pd.isna(vol):
        vol_ratio_score = min(15.0, max(0.0, (float(vol) / float(vol_ma5) - 1) * 10))
    else:
        vol_ratio_score = 0.0

    close = latest.get("close")
    ma20 = latest.get("MA_20")
    if close is not None and ma20 is not None and ma20 > 0 and not pd.isna(close) and not pd.isna(ma20):
        # Score higher when price is BELOW MA20 (near support)
        ma_deviation = (float(ma20) - float(close)) / float(ma20) * 100
        ma_score = min(15.0, max(0.0, ma_deviation * 3))
    else:
        ma_score = 0.0

    volume_price = min(30.0, vol_ratio_score + ma_score)

    total = round(oversold + consensus + volume_price, 1)
    breakdown = {
        "oversold": round(oversold, 1),
        "consensus": round(consensus, 1),
        "volume_price": round(volume_price, 1),
    }
    return total, breakdown
```

**Step 2: Modify `_evaluate_stock()` to call `_compute_alpha_score`**

In `_evaluate_stock()`, after the sentiment check (line 322-325), and before the deduplication block (line 327), add Alpha scoring for buy signals. The return dict (line 336-343) needs the new fields.

Replace the return block at lines 336-343 with:

```python
        # Alpha scoring — only for buy signals
        alpha_score = 0.0
        score_breakdown = {"oversold": 0.0, "consensus": 0.0, "volume_price": 0.0}
        if action == "buy":
            alpha_score, score_breakdown = self._compute_alpha_score(
                df, buy_strategies, len(strategies)
            )

        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "trade_date": trade_date,
            "action": action,
            "reasons": reasons,
            "sentiment_score": sentiment_score,
            "alpha_score": alpha_score,
            "score_breakdown": score_breakdown,
        }
```

**Step 3: Verify the backend starts**

Run: `cd /Users/allenqiang/stockagent && venv/bin/python -c "from api.services.signal_engine import SignalEngine; print('OK')"`

Expected: `OK`

**Step 4: Commit**

```bash
git add api/services/signal_engine.py
git commit -m "feat(alpha): add _compute_alpha_score to SignalEngine"
```

---

### Task 2: Backend — Update `_save_signal()` and `_signal_to_dict()`

**Files:**
- Modify: `api/services/signal_engine.py:347-378` (_save_signal), `:457-474` (_signal_to_dict)

**Step 1: Update `_save_signal` to persist alpha scores**

Currently `_save_signal` hardcodes `final_score=0.0`. Modify it to use the alpha_score from the signal dict, and store sub-scores in `swing_score` and `trend_score`.

Replace the `_save_signal` method (lines 347-377) with:

```python
    def _save_signal(self, sig: dict, trade_date: str):
        """Upsert signal to DB."""
        existing = (
            self.db.query(TradingSignal)
            .filter(
                TradingSignal.stock_code == sig["stock_code"],
                TradingSignal.trade_date == trade_date,
            )
            .first()
        )
        reasons_json = json.dumps(sig.get("reasons", []), ensure_ascii=False)
        action = sig.get("action", "hold")
        action_label = {"buy": "买入", "sell": "卖出"}.get(action, "持有")
        alpha = sig.get("alpha_score", 0.0)
        breakdown = sig.get("score_breakdown") or {}

        if existing:
            existing.final_score = alpha
            existing.swing_score = breakdown.get("oversold", 0.0)
            existing.trend_score = breakdown.get("volume_price", 0.0)
            existing.signal_level = {"buy": 4, "sell": 2}.get(action, 3)
            existing.signal_level_name = action_label
            existing.reasons = reasons_json
            existing.market_regime = action
        else:
            self.db.add(TradingSignal(
                stock_code=sig["stock_code"],
                trade_date=trade_date,
                final_score=alpha,
                swing_score=breakdown.get("oversold", 0.0),
                trend_score=breakdown.get("volume_price", 0.0),
                signal_level={"buy": 4, "sell": 2}.get(action, 3),
                signal_level_name=action_label,
                reasons=reasons_json,
                market_regime=action,
            ))
```

**Step 2: Update `_signal_to_dict` to include alpha fields in API output**

Replace `_signal_to_dict` (lines 457-474) with:

```python
    @staticmethod
    def _signal_to_dict(row: TradingSignal, stock_name: str = "") -> dict:
        reasons = row.reasons or "[]"
        try:
            reasons_list = json.loads(reasons)
        except (json.JSONDecodeError, TypeError):
            reasons_list = []

        alpha_score = row.final_score or 0.0
        oversold = row.swing_score or 0.0
        volume_price = row.trend_score or 0.0
        consensus = round(alpha_score - oversold - volume_price, 1)

        return {
            "stock_code": row.stock_code,
            "stock_name": stock_name,
            "trade_date": row.trade_date,
            "final_score": alpha_score,
            "alpha_score": alpha_score,
            "oversold_score": oversold,
            "consensus_score": max(0.0, consensus),
            "volume_price_score": volume_price,
            "signal_level": row.signal_level,
            "signal_level_name": row.signal_level_name,
            "action": row.market_regime or "hold",
            "reasons": reasons_list,
        }
```

**Step 3: Verify import works**

Run: `cd /Users/allenqiang/stockagent && venv/bin/python -c "from api.services.signal_engine import SignalEngine; print('OK')"`

Expected: `OK`

**Step 4: Commit**

```bash
git add api/services/signal_engine.py
git commit -m "feat(alpha): persist alpha scores in _save_signal, expose in _signal_to_dict"
```

---

### Task 3: Backend — Update `/api/signals/today` to return `alpha_top`

**Files:**
- Modify: `api/routers/signals.py:31-62`

**Step 1: Modify the `get_today_signals` endpoint**

Replace the route function (lines 31-62) with:

```python
@router.get("/today")
def get_today_signals(
    date: str = Query("", description="YYYY-MM-DD, default today"),
    db: Session = Depends(get_db),
):
    """Get signals for today (or a given date).

    If no date is specified and today has no signals yet,
    automatically falls back to the last date that has signals.

    Returns alpha_top: top 5 buy signals ranked by alpha_score.
    """
    engine = SignalEngine(db)
    explicit_date = bool(date)

    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    signals = engine.get_signals_by_date(date)

    # Auto-fallback: if caller didn't specify a date and today is empty,
    # show the most recent date that has signals.
    if not signals and not explicit_date:
        meta = engine.get_signal_meta()
        last_date = meta.get("last_trade_date")
        if last_date and last_date != date:
            date = last_date
            signals = engine.get_signals_by_date(date)

    # Alpha Top 5: buy signals sorted by alpha_score descending
    alpha_top = sorted(
        [s for s in signals if s.get("action") == "buy" and s.get("alpha_score", 0) > 0],
        key=lambda x: x.get("alpha_score", 0),
        reverse=True,
    )[:5]

    return {
        "trade_date": date,
        "total": len(signals),
        "items": signals,
        "alpha_top": alpha_top,
    }
```

**Step 2: Verify the API starts**

Run: `cd /Users/allenqiang/stockagent && NO_PROXY=localhost,127.0.0.1 venv/bin/python -c "from api.routers.signals import router; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add api/routers/signals.py
git commit -m "feat(alpha): add alpha_top to /api/signals/today response"
```

---

### Task 4: Frontend — Add `AlphaSignal` type and update API types

**Files:**
- Modify: `web/src/types/index.ts:120-138`
- Modify: `web/src/lib/api.ts:111-114`

**Step 1: Update `SignalItem` type to include alpha fields**

In `web/src/types/index.ts`, replace the `SignalItem` interface (lines 120-129) with:

```typescript
export interface SignalItem {
  stock_code: string;
  stock_name: string;
  trade_date: string;
  final_score: number;
  alpha_score: number;
  oversold_score: number;
  consensus_score: number;
  volume_price_score: number;
  signal_level: number;
  signal_level_name: string;
  action: "buy" | "sell" | "hold";
  reasons: string[];
}
```

**Step 2: Update the `signals.today` return type**

In `web/src/lib/api.ts`, replace lines 111-114 with:

```typescript
  today: (date = "") =>
    request<{ trade_date: string; total: number; items: SignalItem[]; alpha_top: SignalItem[] }>(
      `/signals/today?date=${date}`
    ),
```

**Step 3: Verify TypeScript compiles**

Run: `cd /Users/allenqiang/stockagent/web && npx tsc --noEmit`

Expected: No errors (existing code referencing `SignalItem` still works because all new fields are additive).

**Step 4: Commit**

```bash
git add web/src/types/index.ts web/src/lib/api.ts
git commit -m "feat(alpha): add alpha score fields to SignalItem type and API"
```

---

### Task 5: Frontend — Add AlphaTopCards component

**Files:**
- Create: `web/src/components/signal/alpha-top-cards.tsx`

**Step 1: Create the AlphaTopCards component**

```typescript
"use client";

import { Badge } from "@/components/ui/badge";
import { Trophy } from "lucide-react";
import type { SignalItem } from "@/types";

/** Segmented score bar: oversold (blue) + consensus (purple) + volume-price (orange) */
function ScoreBar({ oversold, consensus, volumePrice, total }: {
  oversold: number;
  consensus: number;
  volumePrice: number;
  total: number;
}) {
  if (total <= 0) return null;
  const pctO = (oversold / 100) * 100;
  const pctC = (consensus / 100) * 100;
  const pctV = (volumePrice / 100) * 100;

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden flex">
        <div className="h-full bg-blue-500" style={{ width: `${pctO}%` }} title={`超卖 ${oversold}`} />
        <div className="h-full bg-violet-500" style={{ width: `${pctC}%` }} title={`共识 ${consensus}`} />
        <div className="h-full bg-orange-500" style={{ width: `${pctV}%` }} title={`量价 ${volumePrice}`} />
      </div>
      <span className="text-xs text-muted-foreground tabular-nums w-7 text-right">{total}</span>
    </div>
  );
}

export function AlphaTopCards({
  items,
  onCardClick,
}: {
  items: SignalItem[];
  onCardClick?: (code: string, name: string) => void;
}) {
  if (!items || items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border p-4 text-center text-sm text-muted-foreground">
        今日无 Alpha 推荐
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Trophy className="h-4 w-4 text-amber-500" />
        Alpha Top {items.length}
        <div className="flex items-center gap-3 ml-auto text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-blue-500" />超卖</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-violet-500" />共识</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-orange-500" />量价</span>
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-2">
        {items.map((s, i) => (
          <div
            key={s.stock_code}
            onClick={() => onCardClick?.(s.stock_code, s.stock_name || "")}
            className="rounded-lg border border-amber-500/30 bg-card p-3 cursor-pointer transition-colors hover:bg-accent/50"
          >
            {/* Rank + stock info */}
            <div className="flex items-center gap-2 mb-1.5">
              <Badge className="shrink-0 px-1.5 py-0 text-[10px] leading-4 bg-amber-500/20 text-amber-400 border border-amber-500/40 hover:bg-amber-500/20">
                #{i + 1}
              </Badge>
              <span className="font-mono text-xs text-muted-foreground">{s.stock_code}</span>
              <span className="text-sm font-medium truncate">{s.stock_name || ""}</span>
            </div>

            {/* Score bar */}
            <ScoreBar
              oversold={s.oversold_score}
              consensus={s.consensus_score}
              volumePrice={s.volume_price_score}
              total={s.alpha_score}
            />

            {/* Matched strategies */}
            {s.reasons.length > 0 && (
              <div className="mt-1.5 text-xs text-muted-foreground truncate">
                {s.reasons.join(" · ")}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Step 2: Verify TypeScript compiles**

Run: `cd /Users/allenqiang/stockagent/web && npx tsc --noEmit`

Expected: No errors.

**Step 3: Commit**

```bash
git add web/src/components/signal/alpha-top-cards.tsx
git commit -m "feat(alpha): create AlphaTopCards component"
```

---

### Task 6: Frontend — Integrate AlphaTopCards into signals page

**Files:**
- Modify: `web/src/app/signals/page.tsx:1-5` (imports), `:398` (insert Alpha cards)

**Step 1: Add import**

At the top of `web/src/app/signals/page.tsx`, after the existing imports (around line 24 after the `SignalCard` import), add:

```typescript
import { AlphaTopCards } from "@/components/signal/alpha-top-cards";
```

**Step 2: Extract `alpha_top` from query data**

Inside the `SignalsPage` component (around line 127-128, after `const displaySignals = ...`), add:

```typescript
  const alphaTop = today?.alpha_top ?? [];
```

**Step 3: Insert AlphaTopCards into the "today" tab**

In the `TabsContent value="today"` section, right after the opening `<TabsContent value="today" className="space-y-3">` tag (line 398), before the action filter div (line 400), insert:

```typescript
          {/* Alpha Top 5 ranking */}
          <AlphaTopCards
            items={alphaTop}
            onCardClick={navigateToStock}
          />
```

**Step 4: Verify TypeScript compiles**

Run: `cd /Users/allenqiang/stockagent/web && npx tsc --noEmit`

Expected: No errors.

**Step 5: Commit**

```bash
git add web/src/app/signals/page.tsx
git commit -m "feat(alpha): integrate Alpha Top 5 cards into signals page"
```

---

### Task 7: End-to-end verification

**Step 1: Start the backend**

Run: `cd /Users/allenqiang/stockagent && NO_PROXY=localhost,127.0.0.1 venv/bin/uvicorn api.main:app --port 8050 --reload`

Verify it starts without import errors.

**Step 2: Test the API endpoint**

Run: `NO_PROXY=localhost,127.0.0.1 curl -s http://127.0.0.1:8050/api/signals/today | python3 -c "import json,sys; d=json.load(sys.stdin); print('alpha_top:', len(d.get('alpha_top',[])), 'items:', d.get('total',0)); [print(f'  #{i+1} {s[\"stock_code\"]} {s[\"stock_name\"]} alpha={s[\"alpha_score\"]}') for i,s in enumerate(d.get('alpha_top',[]))]"`

Expected: Shows `alpha_top` count and items (may be 0 if no signals exist yet; the key thing is the field exists and doesn't error).

**Step 3: Build the frontend**

Run: `cd /Users/allenqiang/stockagent/web && npx tsc --noEmit`

Expected: No errors.

**Step 4: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix(alpha): end-to-end verification fixes"
```
