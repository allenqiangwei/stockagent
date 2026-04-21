"use client";

const SELL_REASON_LABEL: Record<string, string> = {
  strategy_exit: "策略卖出",
  stop_loss: "止损",
  take_profit: "止盈",
  max_hold: "持有到期",
  end_of_backtest: "回测结束",
};

const BAR_COLORS = [
  "bg-emerald-500",
  "bg-blue-500",
  "bg-amber-500",
  "bg-red-500",
  "bg-purple-500",
  "bg-cyan-500",
];

interface ExitReasonChartProps {
  data: Record<string, number>;
}

export function ExitReasonChart({ data }: ExitReasonChartProps) {
  const entries = Object.entries(data).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) return null;

  const total = entries.reduce((s, [, v]) => s + v, 0);
  const maxVal = entries[0][1];

  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground mb-2">退出原因分布</div>
      {entries.map(([reason, count], i) => {
        const pct = total > 0 ? ((count / total) * 100).toFixed(1) : "0";
        const barWidth = maxVal > 0 ? (count / maxVal) * 100 : 0;
        return (
          <div key={reason} className="flex items-center gap-2 text-xs">
            <span className="w-16 text-right text-muted-foreground shrink-0 truncate">
              {SELL_REASON_LABEL[reason] || reason}
            </span>
            <div className="flex-1 h-5 bg-muted/30 rounded overflow-hidden">
              <div
                className={`h-full rounded ${BAR_COLORS[i % BAR_COLORS.length]} transition-all duration-500`}
                style={{ width: `${barWidth}%` }}
              />
            </div>
            <span className="w-16 text-muted-foreground shrink-0">
              {count} ({pct}%)
            </span>
          </div>
        );
      })}
    </div>
  );
}
