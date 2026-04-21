"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useExplorationRounds, useLabExperiment } from "@/hooks/use-queries";
import type { LabExperimentStrategy } from "@/types";
import { Loader2, ChevronDown, ChevronUp } from "lucide-react";

function SyncBadge({
  memory,
  pinecone,
}: {
  memory: boolean;
  pinecone: boolean;
}) {
  if (memory && pinecone)
    return (
      <Badge
        variant="outline"
        className="text-green-600 border-green-300 text-[10px]"
      >
        synced
      </Badge>
    );
  if (memory)
    return (
      <Badge
        variant="outline"
        className="text-yellow-600 border-yellow-300 text-[10px]"
      >
        partial
      </Badge>
    );
  return (
    <Badge
      variant="outline"
      className="text-red-600 border-red-300 text-[10px]"
    >
      not synced
    </Badge>
  );
}

function RoundExperimentList({ experimentIds }: { experimentIds: number[] }) {
  if (!experimentIds.length) {
    return <div className="text-xs text-muted-foreground">无关联实验</div>;
  }

  return (
    <div className="space-y-1.5">
      <h4 className="text-sm font-semibold">实验列表</h4>
      {experimentIds.map((eid) => (
        <RoundExperimentItem key={eid} experimentId={eid} />
      ))}
    </div>
  );
}

function RoundExperimentItem({ experimentId }: { experimentId: number }) {
  const { data, isLoading } = useLabExperiment(experimentId);

  if (isLoading) {
    return (
      <div className="text-xs text-muted-foreground py-1">
        #{experimentId} 加载中...
      </div>
    );
  }

  if (!data) {
    return (
      <div className="text-xs text-muted-foreground py-1">
        #{experimentId} 未找到
      </div>
    );
  }

  const promoted = data.strategies?.filter(
    (s: LabExperimentStrategy) => s.promoted
  ) ?? [];
  const bestStrategy = data.strategies
    ?.filter((s: LabExperimentStrategy) => s.status === "done")
    .sort((a: LabExperimentStrategy, b: LabExperimentStrategy) => b.score - a.score)[0];

  return (
    <div className="text-xs bg-muted/20 rounded px-3 py-2 space-y-1">
      <div className="flex items-center justify-between">
        <span className="font-medium truncate">
          #{data.id} {data.theme}
        </span>
        <span className="text-muted-foreground shrink-0 ml-2">
          {data.strategy_count} 策略
        </span>
      </div>
      {bestStrategy && (
        <div className="text-muted-foreground">
          最佳: {bestStrategy.name?.slice(0, 40)} (score={bestStrategy.score.toFixed(2)},
          ret={bestStrategy.total_return_pct.toFixed(1)}%)
        </div>
      )}
      {promoted.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {promoted.map((p: LabExperimentStrategy) => (
            <Badge
              key={p.id}
              className="text-[10px] bg-emerald-600/20 text-emerald-400 border-emerald-500/30"
            >
              ↑ {p.name?.slice(0, 30)} ({p.score.toFixed(2)})
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

export function ExplorationRounds() {
  const [page, setPage] = useState(1);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const { data, isLoading } = useExplorationRounds(page, 20);

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / 20);

  if (items.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        暂无探索记录
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {items.map((r) => (
        <Card
          key={r.id}
          className="cursor-pointer hover:bg-accent/30 transition-colors"
          onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}
        >
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold">R{r.round_number}</span>
                <Badge variant="secondary" className="text-xs">
                  {r.mode}
                </Badge>
                <span className="text-sm text-muted-foreground">
                  {r.started_at.slice(0, 16).replace("T", " ")} —{" "}
                  {r.finished_at.slice(11, 16)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <SyncBadge
                  memory={r.memory_synced}
                  pinecone={r.pinecone_synced}
                />
                {expandedId === r.id ? (
                  <ChevronUp className="h-4 w-4" />
                ) : (
                  <ChevronDown className="h-4 w-4" />
                )}
              </div>
            </div>

            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-sm">
              <span>
                实验 <b>{r.total_experiments}</b>个
              </span>
              <span>
                策略 <b>{r.total_strategies}</b>个
              </span>
              <span>
                盈利 <b>{r.profitable_count}</b> (
                {r.profitability_pct.toFixed(1)}%)
              </span>
              <span>
                StdA: <b>{r.std_a_count}</b>个
              </span>
              {r.promoted.length > 0 && (
                <span>
                  Promote: <b>{r.promoted.length}</b>个
                </span>
              )}
            </div>

            {r.best_strategy_name && (
              <div className="mt-1 text-sm text-muted-foreground">
                最佳: {r.best_strategy_name} —{" "}
                {r.best_strategy_score.toFixed(3)} / +
                {r.best_strategy_return.toFixed(1)}% /{" "}
                {r.best_strategy_dd.toFixed(1)}%
              </div>
            )}

            {expandedId === r.id && (
              <div
                className="mt-4 space-y-3 border-t pt-3"
                onClick={(e) => e.stopPropagation()}
              >
                {r.experiment_ids.length > 0 && (
                  <RoundExperimentList experimentIds={r.experiment_ids} />
                )}
                {r.insights.length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold mb-1">新洞察</h4>
                    <ul className="list-disc list-inside text-sm space-y-0.5">
                      {r.insights.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {r.promoted.length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold mb-1">Auto-Promote</h4>
                    <div className="flex flex-wrap gap-2">
                      {r.promoted.map(
                        (p: Record<string, unknown>, i: number) => (
                          <Badge key={i} variant="outline">
                            {p.name
                              ? `${p.name} ${p.label || ""} ${
                                  typeof p.score === "number"
                                    ? p.score.toFixed(2)
                                    : ""
                                }`
                              : p.families
                              ? `${p.count || 0}个: ${p.families}`
                              : JSON.stringify(p)}
                          </Badge>
                        )
                      )}
                    </div>
                  </div>
                )}
                {r.issues_resolved.length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold mb-1">问题修复</h4>
                    <ul className="list-disc list-inside text-sm space-y-0.5">
                      {r.issues_resolved.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {r.next_suggestions.length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold mb-1">下一步建议</h4>
                    <ul className="list-disc list-inside text-sm space-y-0.5">
                      {r.next_suggestions.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      ))}

      {totalPages > 1 && (
        <div className="flex justify-center gap-2 pt-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            上一页
          </Button>
          <span className="text-sm leading-8">
            {page} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => setPage(page + 1)}
          >
            下一页
          </Button>
        </div>
      )}
    </div>
  );
}
