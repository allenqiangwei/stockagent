"use client";

import { Card, CardContent } from "@/components/ui/card";
import { usePoolStatus } from "@/hooks/use-queries";
import {
  Layers,
  GitBranch,
  BarChart3,
  Target,
  TrendingUp,
  Loader2,
} from "lucide-react";

interface KpiCardProps {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  sub?: string;
}

function KpiCard({ icon, label, value, sub }: KpiCardProps) {
  return (
    <Card className="flex-1 min-w-[140px]">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
          {icon}
          {label}
        </div>
        <div className="text-2xl font-bold tracking-tight">{value}</div>
        {sub && <div className="text-xs text-muted-foreground mt-0.5">{sub}</div>}
      </CardContent>
    </Card>
  );
}

export function PoolOverview() {
  const { data: pool, isLoading } = usePoolStatus();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        加载策略池...
      </div>
    );
  }

  if (!pool) return null;

  const families = pool.families_summary ?? [];
  const bestReturn = families.length > 0
    ? Math.max(...families.map((f) => {
        // champion_score is score, not return — derive best return from the data we have
        // families_summary doesn't include return directly, so we show champion_score
        return f.champion_score;
      }))
    : 0;

  const avgScore = families.length > 0
    ? families.reduce((sum, f) => sum + f.avg_score, 0) / families.length
    : 0;

  return (
    <div className="flex flex-wrap gap-3">
      <KpiCard
        icon={<Layers className="h-4 w-4" />}
        label="活跃策略"
        value={pool.active_strategies.toLocaleString()}
      />
      <KpiCard
        icon={<GitBranch className="h-4 w-4" />}
        label="策略家族"
        value={pool.family_count}
      />
      <KpiCard
        icon={<BarChart3 className="h-4 w-4" />}
        label="市场覆盖"
        value={Object.keys(pool.regime_coverage || {}).length}
        sub="个市场阶段"
      />
      <KpiCard
        icon={<Target className="h-4 w-4" />}
        label="池平均 Score"
        value={avgScore.toFixed(4)}
      />
      <KpiCard
        icon={<TrendingUp className="h-4 w-4" />}
        label="最佳 Champion"
        value={bestReturn.toFixed(4)}
        sub={`信号精简 ${pool.signal_eval_reduction}`}
      />
    </div>
  );
}
