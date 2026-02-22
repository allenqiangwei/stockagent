"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  useSectorHeat,
  useNewsEvents,
  useTriggerNewsAnalysis,
  useNewsAnalysisPoll,
} from "@/hooks/use-queries";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Flame,
  BarChart3,
  Zap,
  Loader2,
} from "lucide-react";
import { useState } from "react";

const TREND_ICON: Record<string, React.ReactNode> = {
  rising: <TrendingUp className="h-4 w-4 text-emerald-500" />,
  falling: <TrendingDown className="h-4 w-4 text-red-500" />,
  flat: <Minus className="h-4 w-4 text-zinc-500" />,
};

const EVENT_TYPE_LABEL: Record<string, string> = {
  policy_positive: "政策利好",
  policy_negative: "政策利空",
  earnings_positive: "业绩利好",
  earnings_negative: "业绩利空",
  capital_flow: "资金面",
  industry_change: "行业变化",
  market_sentiment: "市场情绪",
  breaking_event: "突发事件",
  corporate_action: "公司治理",
  concept_hype: "概念炒作",
};

export default function SectorsPage() {
  const [analysisJobId, setAnalysisJobId] = useState<string | null>(null);

  const sectors = useSectorHeat();
  const events = useNewsEvents();
  const triggerNews = useTriggerNewsAnalysis();
  const poll = useNewsAnalysisPoll(analysisJobId);

  return (
    <div className="p-4 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Flame className="h-6 w-6 text-orange-500" />
          <h1 className="text-2xl font-bold">板块热度</h1>
        </div>
        <Button
          size="sm"
          onClick={() => {
            triggerNews.mutate(undefined, {
              onSuccess: (data) => setAnalysisJobId(data.job_id),
            });
          }}
          disabled={triggerNews.isPending || poll?.data?.status === "processing"}
        >
          {poll?.data?.status === "processing" ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin mr-1" />
              分析中...
            </>
          ) : (
            <>
              <Zap className="h-4 w-4 mr-1" />
              触发新闻分析
            </>
          )}
        </Button>
      </div>

      {/* Sector heat cards */}
      {(sectors.data?.sectors ?? []).length === 0 ? (
        <p className="text-zinc-500 text-center py-12">
          暂无板块数据，请先触发新闻分析
        </p>
      ) : (
        <div className="grid gap-3">
          {sectors.data?.sectors?.map((sec) => (
            <Card key={sec.id} className="bg-zinc-900 border-zinc-800">
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    {TREND_ICON[sec.trend] || TREND_ICON.flat}
                    <span className="font-bold">{sec.sector_name}</span>
                    <Badge variant="outline" className="text-xs">
                      {sec.sector_type === "concept" ? "概念" : "行业"}
                    </Badge>
                    {sec.news_count > 0 && (
                      <span className="text-xs text-zinc-500">
                        {sec.news_count}条新闻
                      </span>
                    )}
                  </div>
                  <span
                    className={`text-lg font-bold tabular-nums ${
                      sec.heat_score > 0
                        ? "text-emerald-500"
                        : sec.heat_score < 0
                        ? "text-red-500"
                        : "text-zinc-400"
                    }`}
                  >
                    {sec.heat_score > 0 ? "+" : ""}
                    {sec.heat_score}
                  </span>
                </div>

                {/* Heat bar */}
                <div className="h-2 bg-zinc-800 rounded-full overflow-hidden mb-2">
                  <div
                    className={`h-full rounded-full transition-all ${
                      sec.heat_score > 0 ? "bg-emerald-600" : "bg-red-600"
                    }`}
                    style={{
                      width: `${Math.min(Math.abs(sec.heat_score), 100)}%`,
                    }}
                  />
                </div>

                {sec.event_summary && (
                  <p className="text-sm text-zinc-400 mb-2">
                    {sec.event_summary}
                  </p>
                )}

                {sec.top_stocks?.length > 0 && (
                  <div className="flex gap-2 flex-wrap">
                    {sec.top_stocks.map((s) => (
                      <Badge
                        key={s.code}
                        variant="secondary"
                        className="text-xs"
                      >
                        {s.name} ({s.code})
                      </Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Recent events */}
      {(events.data?.events ?? []).length > 0 && (
        <div>
          <h2 className="text-xl font-bold mb-3 flex items-center gap-2">
            <BarChart3 className="h-5 w-5" />
            最近事件
          </h2>
          <div className="grid gap-2">
            {events.data?.events?.map((evt) => (
              <Card key={evt.id} className="bg-zinc-900 border-zinc-800">
                <CardContent className="p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge
                      className={`text-xs ${
                        evt.impact_direction === "positive"
                          ? "bg-emerald-900 text-emerald-300"
                          : evt.impact_direction === "negative"
                          ? "bg-red-900 text-red-300"
                          : "bg-zinc-800 text-zinc-400"
                      }`}
                    >
                      {EVENT_TYPE_LABEL[evt.event_type] || evt.event_type}
                    </Badge>
                    <Badge variant="outline" className="text-xs">
                      {evt.impact_level}
                    </Badge>
                    <span className="text-xs text-zinc-500 ml-auto">
                      {evt.created_at}
                    </span>
                  </div>
                  <p className="text-sm">{evt.summary}</p>
                  {evt.affected_sectors?.length > 0 && (
                    <div className="flex gap-1 mt-1 flex-wrap">
                      {evt.affected_sectors.map((s) => (
                        <Badge
                          key={s}
                          variant="outline"
                          className="text-xs text-zinc-500"
                        >
                          {s}
                        </Badge>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
