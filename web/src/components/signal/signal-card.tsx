"use client";

import { Badge } from "@/components/ui/badge";
import type { SignalItem } from "@/types";

const ACTION_STYLES: Record<string, { label: string; cls: string }> = {
  buy: {
    label: "买入",
    cls: "bg-emerald-600 text-white hover:bg-emerald-600",
  },
  sell: {
    label: "卖出",
    cls: "bg-red-600 text-white hover:bg-red-600",
  },
  hold: {
    label: "持有",
    cls: "bg-zinc-600 text-zinc-300 hover:bg-zinc-600",
  },
};

const CARD_BORDER: Record<string, string> = {
  buy: "border-emerald-600/30",
  sell: "border-red-600/30",
  hold: "border-border",
};

export function SignalCard({
  signal,
  onClick,
}: {
  signal: SignalItem;
  onClick?: () => void;
}) {
  const action = signal.action || "hold";
  const style = ACTION_STYLES[action] ?? ACTION_STYLES.hold;
  const border = CARD_BORDER[action] ?? CARD_BORDER.hold;
  const strategies = signal.reasons || [];

  return (
    <div
      onClick={onClick}
      className={`rounded-lg border ${border} bg-card p-3 cursor-pointer transition-colors hover:bg-accent/50`}
    >
      {/* Top row: code + name | action badge */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="font-mono text-sm text-muted-foreground">
            {signal.stock_code}
          </span>
          {signal.stock_name && (
            <span className="ml-1.5 text-sm font-medium truncate">
              {signal.stock_name}
            </span>
          )}
        </div>
        <Badge className={`shrink-0 text-xs ${style.cls}`}>
          {style.label}
        </Badge>
      </div>

      {/* Bottom: date + matched strategies */}
      <div className="mt-2 flex items-center gap-2 text-xs">
        <span className="text-muted-foreground shrink-0">
          {signal.trade_date}
        </span>
        {strategies.length > 0 && (
          <span className="truncate text-muted-foreground">
            {strategies.join(" · ")}
          </span>
        )}
      </div>
    </div>
  );
}
