"use client";

import { Badge } from "@/components/ui/badge";
import { Trophy } from "lucide-react";
import type { SignalItem } from "@/types";

function ScoreBar({ count, quality, simplicity, total }: {
  count: number;
  quality: number;
  simplicity: number;
  total: number;
}) {
  if (total <= 0) return null;
  const pctC = (count / 100) * 100;
  const pctQ = (quality / 100) * 100;
  const pctS = (simplicity / 100) * 100;

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden flex">
        <div className="h-full bg-blue-500" style={{ width: `${pctC}%` }} title={`数量 ${count}`} />
        <div className="h-full bg-violet-500" style={{ width: `${pctQ}%` }} title={`质量 ${quality}`} />
        <div className="h-full bg-orange-500" style={{ width: `${pctS}%` }} title={`简洁性 ${simplicity}`} />
      </div>
      <span className="text-xs text-muted-foreground tabular-nums w-7 text-right">{total}</span>
    </div>
  );
}

function GammaScoreBar({ daily, weekly, health, total }: {
  daily: number;
  weekly: number;
  health: number;
  total: number;
}) {
  if (total <= 0) return null;
  const pctD = (daily / 100) * 100;
  const pctW = (weekly / 100) * 100;
  const pctH = (health / 100) * 100;

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden flex">
        <div className="h-full bg-emerald-500" style={{ width: `${pctD}%` }} title={`日线 ${daily}`} />
        <div className="h-full bg-cyan-500" style={{ width: `${pctW}%` }} title={`周线 ${weekly}`} />
        <div className="h-full bg-yellow-500" style={{ width: `${pctH}%` }} title={`结构 ${health}`} />
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
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-blue-500" />数量</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-violet-500" />质量</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-orange-500" />简洁性</span>
          <span className="mx-1 text-border">|</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-emerald-500" />日线</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-cyan-500" />周线</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-yellow-500" />结构</span>
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
              count={s.count_score}
              quality={s.quality_score}
              simplicity={s.simplicity_score}
              total={s.alpha_score}
            />

            <GammaScoreBar
              daily={s.gamma_daily_strength}
              weekly={s.gamma_weekly_resonance}
              health={s.gamma_structure_health}
              total={s.gamma_score}
            />

            {s.gamma_daily_mmd && (
              <div className="mt-1 flex items-center gap-1.5">
                <Badge className="px-1 py-0 text-[10px] leading-4 bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 hover:bg-emerald-500/20">
                  {s.gamma_daily_mmd}
                </Badge>
                {s.gamma_weekly_mmd && (
                  <Badge className="px-1 py-0 text-[10px] leading-4 bg-cyan-500/20 text-cyan-400 border border-cyan-500/40 hover:bg-cyan-500/20">
                    周{s.gamma_weekly_mmd.split(":")[1]}
                  </Badge>
                )}
                <span className="text-[10px] text-muted-foreground ml-auto">
                  综合 {(s.combined_score * 100).toFixed(0)}
                </span>
              </div>
            )}

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
