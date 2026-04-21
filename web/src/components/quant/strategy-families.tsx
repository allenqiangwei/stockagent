"use client";

import { useState, useRef, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useFamilies,
  useFamilyStrategies,
  useBacktestRuns,
  useBacktestDetail,
  useStrategy,
} from "@/hooks/use-queries";
import { EquityCurve } from "@/components/quant/equity-curve";
import { ExitReasonChart } from "@/components/quant/exit-reason-chart";
import type { FamilySummary } from "@/types";
import {
  ChevronDown,
  ChevronRight,
  Trophy,
  Loader2,
  Layers,
  X,
} from "lucide-react";

type SortKey = "avg_score" | "champion_score" | "active_count";

// ── Family role badge ────────────────────────────
function RoleBadge({ role }: { role?: string | null }) {
  if (role === "champion") {
    return (
      <Badge className="px-1 py-0 text-[10px] leading-4 bg-yellow-500/20 text-yellow-400 border border-yellow-500/40 hover:bg-yellow-500/20">
        <Trophy className="h-3 w-3 mr-0.5" />
        冠军
      </Badge>
    );
  }
  return null;
}

// ── Inline backtest detail for a selected strategy ──
function InlineBacktestDetail({
  strategyId,
  onClose,
}: {
  strategyId: number;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const { data: strategy } = useStrategy(strategyId);
  const { data: runs } = useBacktestRuns(strategyId);
  const latestRunId = runs?.[0]?.id ?? 0;
  const { data: bt, isLoading: btLoading } = useBacktestDetail(latestRunId);

  const bs = strategy?.backtest_summary;
  const name =
    strategy?.name?.replace(/^\[AI[^\]]*\]\s*/, "").replace(/^\[P\]/, "") ??
    `#${strategyId}`;
  const hasRunDetail = bt != null;
  const hasData = hasRunDetail || bs != null;

  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [strategyId]);

  return (
    <div ref={ref} className="border-t border-primary/30 bg-muted/10 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium text-sm truncate">{name}</div>
          {bt && (
            <div className="text-xs text-muted-foreground">
              {bt.start_date} ~ {bt.end_date}
            </div>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0 shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            onClose();
          }}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      {btLoading ? (
        <div className="flex items-center justify-center py-4 text-muted-foreground text-xs">
          <Loader2 className="h-4 w-4 animate-spin mr-2" />
          加载中...
        </div>
      ) : !hasData ? (
        <div className="py-4 text-center text-xs text-muted-foreground">
          无回测数据
        </div>
      ) : (
        <>
          {/* Metrics */}
          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-7 gap-1.5">
            {bs?.score != null && (
              <Metric label="评分" value={bs.score.toFixed(4)} />
            )}
            <Metric
              label="总收益"
              value={`${(bt?.total_return_pct ?? bs?.total_return_pct ?? 0).toFixed(1)}%`}
              cls={
                (bt?.total_return_pct ?? bs?.total_return_pct ?? 0) >= 0
                  ? "text-red-400"
                  : "text-green-400"
              }
            />
            <Metric
              label="最大回撤"
              value={`${(bt?.max_drawdown_pct ?? bs?.max_drawdown_pct ?? 0).toFixed(1)}%`}
              cls="text-red-400"
            />
            <Metric
              label="胜率"
              value={`${(bt?.win_rate ?? bs?.win_rate ?? 0).toFixed(1)}%`}
            />
            <Metric
              label="交易数"
              value={`${bt?.total_trades ?? bs?.total_trades ?? 0}`}
            />
            <Metric
              label="平均持仓"
              value={`${(bt?.avg_hold_days ?? bs?.avg_hold_days ?? 0).toFixed(1)}天`}
            />
            {bt?.sharpe_ratio != null && (
              <Metric label="Sharpe" value={bt.sharpe_ratio.toFixed(2)} />
            )}
          </div>

          {/* Equity Curve */}
          {bt?.equity_curve?.length ? (
            <EquityCurve data={bt.equity_curve} height={220} />
          ) : null}

          {/* Exit reasons */}
          {bt?.sell_reason_stats &&
            Object.keys(bt.sell_reason_stats).length > 0 && (
              <ExitReasonChart data={bt.sell_reason_stats} />
            )}

          {/* Exit config */}
          {strategy?.exit_config && (
            <div className="flex gap-3 text-xs text-muted-foreground">
              {strategy.exit_config.stop_loss_pct != null && (
                <span>
                  止损:{" "}
                  <span className="font-mono text-red-400">
                    {strategy.exit_config.stop_loss_pct}%
                  </span>
                </span>
              )}
              {strategy.exit_config.take_profit_pct != null && (
                <span>
                  止盈:{" "}
                  <span className="font-mono text-emerald-500">
                    +{strategy.exit_config.take_profit_pct}%
                  </span>
                </span>
              )}
              {strategy.exit_config.max_hold_days != null && (
                <span>
                  最大持仓:{" "}
                  <span className="font-mono">
                    {strategy.exit_config.max_hold_days}天
                  </span>
                </span>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  cls,
}: {
  label: string;
  value: string;
  cls?: string;
}) {
  return (
    <div className="rounded border border-border/50 bg-background/50 px-2 py-1">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className={`text-xs font-bold font-mono ${cls || ""}`}>{value}</div>
    </div>
  );
}

// ── Expanded family detail ───────────────────────
function FamilyDetail({ fingerprint }: { fingerprint: string }) {
  const { data: strats, isLoading } = useFamilyStrategies(fingerprint);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-3 px-4 text-muted-foreground text-xs">
        <Loader2 className="h-3 w-3 animate-spin" /> 加载策略...
      </div>
    );
  }

  if (!strats || strats.length === 0) {
    return (
      <div className="py-3 px-4 text-muted-foreground text-xs">无策略</div>
    );
  }

  return (
    <div className="px-2 pb-2">
      <Table>
        <TableHeader>
          <TableRow className="text-xs">
            <TableHead className="h-7">策略名</TableHead>
            <TableHead className="h-7 text-right">Score</TableHead>
            <TableHead className="h-7 text-right">收益%</TableHead>
            <TableHead className="h-7 text-right">回撤%</TableHead>
            <TableHead className="h-7 text-right">胜率%</TableHead>
            <TableHead className="h-7 text-right">交易数</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {strats.map((s) => {
            const bs = s.backtest_summary;
            const isSelected = selectedId === s.id;
            return (
              <TableRow
                key={s.id}
                className={`text-xs cursor-pointer transition-colors ${
                  isSelected
                    ? "bg-primary/10 hover:bg-primary/15"
                    : "hover:bg-accent/50"
                }`}
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedId(isSelected ? null : s.id);
                }}
              >
                <TableCell className="py-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-xs truncate max-w-[240px]">
                      {s.name.replace(/^\[AI[^\]]*\]\s*/, "").replace(/^\[P\]/, "")}
                    </span>
                    <RoleBadge role={s.family_role} />
                  </div>
                </TableCell>
                <TableCell className="py-1.5 text-right font-mono">
                  {bs?.score?.toFixed(4) ?? "—"}
                </TableCell>
                <TableCell className="py-1.5 text-right font-mono">
                  <span
                    className={
                      (bs?.total_return_pct ?? 0) > 0
                        ? "text-red-400"
                        : "text-green-400"
                    }
                  >
                    {bs?.total_return_pct?.toFixed(1) ?? "—"}
                  </span>
                </TableCell>
                <TableCell className="py-1.5 text-right font-mono">
                  {bs?.max_drawdown_pct?.toFixed(1) ?? "—"}
                </TableCell>
                <TableCell className="py-1.5 text-right font-mono">
                  {bs?.win_rate != null ? bs.win_rate.toFixed(1) : "—"}
                </TableCell>
                <TableCell className="py-1.5 text-right font-mono">
                  {bs?.total_trades ?? "—"}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      {/* Inline backtest detail — appears right below the table */}
      {selectedId && (
        <InlineBacktestDetail
          strategyId={selectedId}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}

// ── Family card (collapsible) ────────────────────
function FamilyCard({
  family,
  expanded,
  onToggle,
}: {
  family: FamilySummary;
  expanded: boolean;
  onToggle: () => void;
}) {
  const Chevron = expanded ? ChevronDown : ChevronRight;

  return (
    <Card className="overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-accent/30 transition-colors"
      >
        <Chevron className="h-4 w-4 text-muted-foreground shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm truncate">
              {family.representative_name}
            </span>
            <Badge variant="outline" className="text-[10px] px-1.5">
              {family.active_count} 条
            </Badge>
          </div>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground shrink-0">
          <span>
            avg{" "}
            <span className="text-foreground font-mono">
              {family.avg_score.toFixed(4)}
            </span>
          </span>
          <span>
            best{" "}
            <span className="text-foreground font-mono">
              {family.champion_score.toFixed(4)}
            </span>
          </span>
        </div>
      </button>
      {expanded && <FamilyDetail fingerprint={family.fingerprint} />}
    </Card>
  );
}

// ── Main component ───────────────────────────────
export function StrategyFamilies() {
  const { data: families, isLoading } = useFamilies();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [sortBy, setSortBy] = useState<SortKey>("champion_score");
  const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        加载家族...
      </div>
    );
  }

  if (!families || families.length === 0) {
    return (
      <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
        <Layers className="h-8 w-8" />
        <span>暂无策略家族</span>
      </div>
    );
  }

  const sorted = [...families].sort((a, b) => {
    let cmp = 0;
    if (sortBy === "active_count") cmp = a.active_count - b.active_count;
    else if (sortBy === "champion_score")
      cmp = a.champion_score - b.champion_score;
    else cmp = a.avg_score - b.avg_score;
    return sortDir === "desc" ? -cmp : cmp;
  });

  const toggle = (fp: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(fp)) next.delete(fp);
      else next.add(fp);
      return next;
    });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">
          {families.length} 个家族
        </span>
        <div className="flex items-center gap-2">
          <Select
            value={sortBy}
            onValueChange={(v) => {
              setSortBy(v as SortKey);
              setSortDir("desc");
            }}
          >
            <SelectTrigger className="w-36 h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="champion_score">按冠军分</SelectItem>
              <SelectItem value="avg_score">按平均分</SelectItem>
              <SelectItem value="active_count">按策略数</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0 text-xs"
            onClick={() =>
              setSortDir((d) => (d === "desc" ? "asc" : "desc"))
            }
            title={sortDir === "desc" ? "降序" : "升序"}
          >
            {sortDir === "desc" ? "↓" : "↑"}
          </Button>
        </div>
      </div>
      <div className="space-y-2">
        {sorted.map((f) => (
          <FamilyCard
            key={f.fingerprint}
            family={f}
            expanded={expanded.has(f.fingerprint)}
            onToggle={() => toggle(f.fingerprint)}
          />
        ))}
      </div>
    </div>
  );
}
