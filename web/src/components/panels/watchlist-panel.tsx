"use client";

import { useWatchlist, useRemoveWatchlist } from "@/hooks/use-queries";
import { useAppStore } from "@/lib/store";
import { StockSearch } from "./stock-search";
import { ScrollArea } from "@/components/ui/scroll-area";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export function WatchlistPanel() {
  const currentStock = useAppStore((s) => s.currentStock);
  const setCurrentStock = useAppStore((s) => s.setCurrentStock);
  const { data: watchlist } = useWatchlist();
  const removeWatchlist = useRemoveWatchlist();

  return (
    <div className="flex flex-col h-full p-2 gap-2">
      <div className="text-xs font-medium text-muted-foreground px-1">自选</div>
      <StockSearch />
      <ScrollArea className="flex-1">
        <div className="space-y-0.5">
          {watchlist?.map((w) => {
            const changePct = w.change_pct ?? null;
            const isUp = changePct !== null && changePct >= 0;
            const priceColor =
              changePct === null
                ? "text-muted-foreground"
                : isUp
                  ? "text-red-400"
                  : "text-green-400";

            return (
              <div
                key={w.stock_code}
                onClick={() => setCurrentStock(w.stock_code, w.stock_name)}
                className={cn(
                  "flex items-center justify-between rounded px-2 py-1.5 text-sm cursor-pointer transition-colors group",
                  w.stock_code === currentStock
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-accent/50"
                )}
              >
                <div className="min-w-0 shrink-0">
                  <div className="text-xs truncate">{w.stock_name}</div>
                  <div className="font-mono text-[10px] text-muted-foreground">
                    {w.stock_code}
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  {w.close != null ? (
                    <div className="text-right">
                      <div className={cn("font-mono text-xs", priceColor)}>
                        {w.close.toFixed(2)}
                      </div>
                      <div className={cn("font-mono text-[10px]", priceColor)}>
                        {changePct !== null
                          ? `${isUp ? "+" : ""}${changePct.toFixed(2)}%`
                          : "--"}
                      </div>
                    </div>
                  ) : (
                    <div className="text-[10px] text-muted-foreground">--</div>
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      removeWatchlist.mutate(w.stock_code);
                    }}
                    className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity ml-0.5"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </ScrollArea>
    </div>
  );
}
