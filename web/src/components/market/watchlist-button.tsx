"use client";

import { useWatchlist, useAddWatchlist, useRemoveWatchlist } from "@/hooks/use-queries";
import { useAppStore } from "@/lib/store";
import { Star } from "lucide-react";
import { cn } from "@/lib/utils";

export function WatchlistButton() {
  const code = useAppStore((s) => s.currentStock);
  const name = useAppStore((s) => s.currentStockName);
  const { data: watchlist } = useWatchlist();
  const addWatchlist = useAddWatchlist();
  const removeWatchlist = useRemoveWatchlist();

  const isInWatchlist = watchlist?.some((w) => w.stock_code === code) ?? false;

  const handleClick = () => {
    if (isInWatchlist) {
      removeWatchlist.mutate(code);
    } else {
      addWatchlist.mutate({ code, name });
    }
  };

  return (
    <button
      onClick={handleClick}
      className={cn(
        "p-0.5 transition-colors",
        isInWatchlist
          ? "text-yellow-400 hover:text-yellow-300"
          : "text-muted-foreground hover:text-yellow-400"
      )}
      title={isInWatchlist ? "移出自选" : "加入自选"}
    >
      <Star
        className="h-4 w-4"
        fill={isInWatchlist ? "currentColor" : "none"}
      />
    </button>
  );
}
