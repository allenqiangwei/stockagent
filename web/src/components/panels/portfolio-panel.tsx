"use client";

import { usePortfolio, useRemovePortfolio } from "@/hooks/use-queries";
import { useAppStore } from "@/lib/store";
import { ScrollArea } from "@/components/ui/scroll-area";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

function formatMoney(v: number | null | undefined) {
  if (v == null) return "--";
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + "万";
  return v.toFixed(2);
}

export function PortfolioPanel() {
  const currentStock = useAppStore((s) => s.currentStock);
  const setCurrentStock = useAppStore((s) => s.setCurrentStock);
  const { data: portfolio } = usePortfolio();
  const removePortfolio = useRemovePortfolio();

  const totalMarketValue = portfolio?.reduce((sum, p) => sum + (p.market_value ?? 0), 0) ?? 0;
  const totalPnl = portfolio?.reduce((sum, p) => sum + (p.pnl ?? 0), 0) ?? 0;
  const totalCost = portfolio?.reduce((sum, p) => sum + p.avg_cost * p.quantity, 0) ?? 0;
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
  const hasPnl = portfolio && portfolio.length > 0 && portfolio.some((p) => p.pnl != null);

  return (
    <div className="flex flex-col h-full p-2 gap-2">
      <div className="text-xs font-medium text-muted-foreground px-1">持仓</div>

      {/* Summary */}
      {hasPnl && (
        <div className="flex items-center justify-between px-2 py-1.5 rounded bg-muted/30 text-xs">
          <div>
            <span className="text-muted-foreground">总市值 </span>
            <span className="font-mono">{formatMoney(totalMarketValue)}</span>
          </div>
          <div>
            <span className="text-muted-foreground">盈亏 </span>
            <span
              className={cn(
                "font-mono",
                totalPnl >= 0 ? "text-red-400" : "text-green-400"
              )}
            >
              {totalPnl >= 0 ? "+" : ""}
              {formatMoney(totalPnl)} ({totalPnlPct >= 0 ? "+" : ""}
              {totalPnlPct.toFixed(2)}%)
            </span>
          </div>
        </div>
      )}

      <ScrollArea className="flex-1">
        <div className="space-y-0.5">
          {(!portfolio || portfolio.length === 0) && (
            <div className="py-8 text-center text-xs text-muted-foreground">
              暂无持仓
            </div>
          )}
          {portfolio?.map((p) => {
            const pnlPct = p.pnl_pct ?? null;
            const isUp = pnlPct !== null && pnlPct >= 0;
            const pnlColor =
              pnlPct === null
                ? "text-muted-foreground"
                : isUp
                  ? "text-red-400"
                  : "text-green-400";

            const changePct = p.change_pct ?? null;
            const dayUp = changePct !== null && changePct >= 0;
            const dayColor =
              changePct === null
                ? "text-muted-foreground"
                : dayUp
                  ? "text-red-400"
                  : "text-green-400";

            return (
              <div
                key={p.stock_code}
                onClick={() => setCurrentStock(p.stock_code, p.stock_name)}
                className={cn(
                  "flex items-center justify-between rounded px-2 py-1.5 text-sm cursor-pointer transition-colors group",
                  p.stock_code === currentStock
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-accent/50"
                )}
              >
                <div className="min-w-0 shrink-0">
                  <div className="text-xs truncate">{p.stock_name}</div>
                  <div className="font-mono text-[10px] text-muted-foreground">
                    {p.stock_code}
                  </div>
                  <div className="text-[10px] text-muted-foreground">
                    {p.quantity}股 × {p.avg_cost.toFixed(2)}
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="text-right">
                    {p.close != null ? (
                      <>
                        <div className={cn("font-mono text-xs", dayColor)}>
                          {p.close.toFixed(2)}
                        </div>
                        <div className={cn("font-mono text-[10px]", pnlColor)}>
                          {pnlPct !== null
                            ? `${isUp ? "+" : ""}${pnlPct.toFixed(2)}%`
                            : "--"}
                        </div>
                        {p.pnl != null && (
                          <div className={cn("font-mono text-[10px]", pnlColor)}>
                            {p.pnl >= 0 ? "+" : ""}
                            {formatMoney(p.pnl)}
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="text-[10px] text-muted-foreground">--</div>
                    )}
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      removePortfolio.mutate(p.stock_code);
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
