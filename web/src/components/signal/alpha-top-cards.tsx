"use client";

import { Badge } from "@/components/ui/badge";
import { Trophy } from "lucide-react";
import type { SignalItem } from "@/types";

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
            <div className="flex items-center gap-2 mb-1.5">
              <Badge className="shrink-0 px-1.5 py-0 text-[10px] leading-4 bg-amber-500/20 text-amber-400 border border-amber-500/40 hover:bg-amber-500/20">
                #{i + 1}
              </Badge>
              <span className="font-mono text-xs text-muted-foreground">{s.stock_code}</span>
              <span className="text-sm font-medium truncate">{s.stock_name || ""}</span>
            </div>

            <ScoreBar
              oversold={s.oversold_score}
              consensus={s.consensus_score}
              volumePrice={s.volume_price_score}
              total={s.alpha_score}
            />

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
