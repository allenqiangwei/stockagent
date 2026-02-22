"use client";

import { useState, useMemo, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useNewsLatest, useNewsStats, useSentimentLatest, useTriggerSentimentAnalysis } from "@/hooks/use-queries";
import {
  Newspaper,
  TrendingUp,
  TrendingDown,
  Minus,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Loader2,
  Database,
  Clock,
  FileText,
  Brain,
  RefreshCw,
} from "lucide-react";
import type { NewsItem } from "@/types";

// ── Sentiment helpers ────────────────────────────
function sentimentLabel(score: number) {
  if (score > 58) return "positive";
  if (score < 42) return "negative";
  return "neutral";
}

function sentimentBadge(score: number) {
  const s = sentimentLabel(score);
  if (s === "positive")
    return <Badge className="bg-green-600/20 text-green-400 border-green-600/30">{score.toFixed(0)} 正面</Badge>;
  if (s === "negative")
    return <Badge className="bg-red-600/20 text-red-400 border-red-600/30">{score.toFixed(0)} 负面</Badge>;
  return <Badge className="bg-yellow-600/20 text-yellow-400 border-yellow-600/30">{score.toFixed(0)} 中性</Badge>;
}

const SOURCE_LABELS: Record<string, string> = {
  cls: "财联社",
  eastmoney: "东方财富",
  sina: "新浪财经",
};

const PAGE_SIZE = 20;

// ── Main component ───────────────────────────────
export default function NewsPage() {
  const { data, isLoading, error } = useNewsLatest();
  const { data: stats } = useNewsStats();
  const { data: sentiment } = useSentimentLatest();
  const triggerMutation = useTriggerSentimentAnalysis();

  // Countdown to next fetch
  const [countdown, setCountdown] = useState("");
  useEffect(() => {
    if (!data?.next_fetch_timestamp) return;
    const tick = () => {
      const remaining = Math.max(0, data.next_fetch_timestamp - Date.now() / 1000);
      if (remaining <= 0) { setCountdown("刷新中..."); return; }
      const m = Math.floor(remaining / 60);
      const s = Math.floor(remaining % 60);
      setCountdown(`${m}分${s.toString().padStart(2, "0")}秒`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [data?.next_fetch_timestamp]);

  // Filters
  const [sourceFilter, setSourceFilter] = useState("all");
  const [sentimentFilter, setSentimentFilter] = useState("all");
  const [sortBy, setSortBy] = useState<"time" | "sentiment">("time");
  const [page, setPage] = useState(1);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  // Reset page when filters change
  const setSourceAndReset = (v: string) => { setSourceFilter(v); setPage(1); setExpandedIdx(null); };
  const setSentimentAndReset = (v: string) => { setSentimentFilter(v); setPage(1); setExpandedIdx(null); };
  const setSortAndReset = (v: string) => { setSortBy(v as "time" | "sentiment"); setPage(1); };

  // Filtered + sorted list
  const filtered = useMemo(() => {
    if (!data?.news_list) return [];
    let list = data.news_list;
    if (sourceFilter !== "all") list = list.filter((n) => n.source === sourceFilter);
    if (sentimentFilter === "positive") list = list.filter((n) => n.sentiment_score > 58);
    else if (sentimentFilter === "negative") list = list.filter((n) => n.sentiment_score < 42);
    else if (sentimentFilter === "neutral") list = list.filter((n) => n.sentiment_score >= 42 && n.sentiment_score <= 58);

    const sorted = [...list];
    if (sortBy === "time") sorted.sort((a, b) => b.publish_time.localeCompare(a.publish_time));
    else sorted.sort((a, b) => b.sentiment_score - a.sentiment_score);
    return sorted;
  }, [data?.news_list, sourceFilter, sentimentFilter, sortBy]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageItems = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[60vh] gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" /> 加载中...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-[60vh] text-destructive">
        加载失败: {(error as Error).message}
      </div>
    );
  }

  const d = data!;
  const empty = d.total_count === 0;

  return (
    <div className="space-y-4 sm:space-y-6 p-3 sm:p-6 max-w-6xl mx-auto">
      {/* ── Header ─────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Newspaper className="h-5 sm:h-6 w-5 sm:w-6 text-chart-1" />
          <h1 className="text-lg sm:text-xl font-semibold">财经资讯</h1>
        </div>
        {d.fetch_time && (
          <span className="text-xs text-muted-foreground">
            更新于 {d.fetch_time}
          </span>
        )}
      </div>

      {/* ── AI Market Sentiment Card ──────────────── */}
      <Card className={`${
        (sentiment?.market_sentiment ?? 0) > 30 ? "bg-green-600/10" :
        (sentiment?.market_sentiment ?? 0) < -30 ? "bg-red-600/10" : "bg-yellow-600/10"
      } border-0 mb-4`}>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Brain className="h-5 w-5 text-purple-400" />
              <span className="text-sm font-medium text-muted-foreground">AI 市场情绪分析</span>
            </div>
            <div className="flex items-center gap-2">
              {sentiment?.analysis_time && (
                <span className="text-xs text-muted-foreground">
                  {sentiment.period_type === "pre_market" ? "盘前" : sentiment.period_type === "post_close" ? "收盘后" : "手动"} · {sentiment.analysis_time}
                </span>
              )}
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2"
                onClick={() => triggerMutation.mutate()}
                disabled={triggerMutation.isPending}
              >
                <RefreshCw className={`h-3.5 w-3.5 ${triggerMutation.isPending ? "animate-spin" : ""}`} />
              </Button>
            </div>
          </div>

          {sentiment?.has_data ? (
            <div className="space-y-3">
              <div className="flex items-baseline gap-3">
                <span className={`text-3xl font-bold ${
                  sentiment.market_sentiment > 30 ? "text-green-400" :
                  sentiment.market_sentiment < -30 ? "text-red-400" : "text-yellow-400"
                }`}>
                  {sentiment.market_sentiment > 0 ? "+" : ""}{sentiment.market_sentiment.toFixed(0)}
                </span>
                <span className={`text-sm ${
                  sentiment.market_sentiment > 30 ? "text-green-400" :
                  sentiment.market_sentiment < -30 ? "text-red-400" : "text-yellow-400"
                }`}>
                  {sentiment.market_sentiment > 60 ? "强烈乐观" :
                   sentiment.market_sentiment > 30 ? "偏乐观" :
                   sentiment.market_sentiment < -60 ? "强烈悲观" :
                   sentiment.market_sentiment < -30 ? "偏悲观" : "中性"}
                </span>
                <span className="text-xs text-muted-foreground">
                  信心 {sentiment.confidence.toFixed(0)}% · {sentiment.news_count} 条新闻
                </span>
              </div>

              {sentiment.key_summary && (
                <p className="text-sm text-muted-foreground">{sentiment.key_summary}</p>
              )}

              {sentiment.event_tags.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {sentiment.event_tags.map((tag: string, i: number) => (
                    <Badge key={i} variant="secondary" className="text-xs">{tag}</Badge>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">暂无分析数据，点击刷新按钮手动触发</p>
          )}
        </CardContent>
      </Card>

      {/* ── Info bar ──────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        {stats && (
          <span className="inline-flex items-center gap-1">
            <Database className="h-3.5 w-3.5" />
            数据库总计 {stats.total_archived} 条
          </span>
        )}
        {d.fetch_time && (
          <span className="inline-flex items-center gap-1">
            <FileText className="h-3.5 w-3.5" />
            本次获取 {d.total_count} 条
          </span>
        )}
        {countdown && (
          <span className="inline-flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" />
            下次自动获取: {countdown}
          </span>
        )}
        {stats?.by_date && stats.by_date.length > 0 && (
          <span className="inline-flex items-center gap-1 ml-auto">
            今日入库 {stats.by_date[0].count} 条
          </span>
        )}
      </div>

      {empty ? (
        <Card>
          <CardContent className="flex items-center justify-center h-40 text-muted-foreground">
            暂无新闻数据，后台服务正在抓取中...
          </CardContent>
        </Card>
      ) : (
        <>
          {/* ── Sentiment overview cards ────────────── */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <SentimentCard
              title="整体情绪"
              value={d.overall_sentiment}
              icon={d.overall_sentiment > 58 ? TrendingUp : d.overall_sentiment < 42 ? TrendingDown : Minus}
              color={d.overall_sentiment > 58 ? "text-green-400" : d.overall_sentiment < 42 ? "text-red-400" : "text-yellow-400"}
            />
            <SentimentCard title="正面" value={d.positive_count} suffix="条" icon={TrendingUp} color="text-green-400" />
            <SentimentCard title="负面" value={d.negative_count} suffix="条" icon={TrendingDown} color="text-red-400" />
            <SentimentCard title="中性" value={d.neutral_count} suffix="条" icon={Minus} color="text-yellow-400" />
          </div>

          {/* ── Hot keywords ───────────────────────── */}
          {d.keyword_counts.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium">热门关键词</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {d.keyword_counts.map(([kw, count]) => (
                  <Badge key={kw} variant="secondary" className="text-xs">
                    {kw} ({count})
                  </Badge>
                ))}
              </CardContent>
            </Card>
          )}

          {/* ── Filters ────────────────────────────── */}
          <div className="flex flex-wrap items-center gap-3">
            <Select value={sourceFilter} onValueChange={setSourceAndReset}>
              <SelectTrigger className="w-[130px] h-8 text-xs">
                <SelectValue placeholder="来源" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部来源</SelectItem>
                <SelectItem value="cls">财联社</SelectItem>
                <SelectItem value="eastmoney">东方财富</SelectItem>
                <SelectItem value="sina">新浪财经</SelectItem>
              </SelectContent>
            </Select>

            <Select value={sentimentFilter} onValueChange={setSentimentAndReset}>
              <SelectTrigger className="w-[130px] h-8 text-xs">
                <SelectValue placeholder="情绪" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部情绪</SelectItem>
                <SelectItem value="positive">正面</SelectItem>
                <SelectItem value="negative">负面</SelectItem>
                <SelectItem value="neutral">中性</SelectItem>
              </SelectContent>
            </Select>

            <Select value={sortBy} onValueChange={setSortAndReset}>
              <SelectTrigger className="w-[130px] h-8 text-xs">
                <SelectValue placeholder="排序" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="time">按时间</SelectItem>
                <SelectItem value="sentiment">按情绪</SelectItem>
              </SelectContent>
            </Select>

            <span className="text-xs text-muted-foreground ml-auto">
              共 {filtered.length} 条
            </span>
          </div>

          {/* ── News list ──────────────────────────── */}
          <div className="space-y-2">
            {pageItems.map((item, i) => {
              const globalIdx = (page - 1) * PAGE_SIZE + i;
              const isOpen = expandedIdx === globalIdx;
              return (
                <NewsCard
                  key={globalIdx}
                  item={item}
                  isOpen={isOpen}
                  onToggle={() => setExpandedIdx(isOpen ? null : globalIdx)}
                />
              );
            })}
          </div>

          {/* ── Pagination ─────────────────────────── */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                上一页
              </Button>
              <span className="text-sm text-muted-foreground">
                {page} / {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                下一页
              </Button>
            </div>
          )}

          {/* ── Source stats ───────────────────────── */}
          {Object.keys(d.source_stats).length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {Object.entries(d.source_stats).map(([src, stats]) => (
                <Card key={src}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium">{SOURCE_LABELS[src] ?? src}</CardTitle>
                  </CardHeader>
                  <CardContent className="flex items-center justify-between">
                    <span className="text-2xl font-bold">{stats.count}</span>
                    {sentimentBadge(stats.avg_sentiment)}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Sub-components ───────────────────────────────

function SentimentCard({
  title,
  value,
  suffix,
  icon: Icon,
  color,
}: {
  title: string;
  value: number;
  suffix?: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 pt-4">
        <Icon className={`h-5 w-5 ${color}`} />
        <div>
          <p className="text-xs text-muted-foreground">{title}</p>
          <p className="text-xl font-bold">
            {typeof value === "number" && !suffix ? value.toFixed(1) : value}
            {suffix && <span className="text-sm font-normal text-muted-foreground ml-1">{suffix}</span>}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function NewsCard({
  item,
  isOpen,
  onToggle,
}: {
  item: NewsItem;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <Card
      className="cursor-pointer transition-colors hover:bg-accent/30"
      onClick={onToggle}
    >
      <CardContent className="py-3 px-4 space-y-2">
        {/* Title row */}
        <div className="flex items-start gap-2">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium leading-snug">{item.title}</p>
          </div>
          <div className="flex items-center gap-1 sm:gap-2 shrink-0">
            <Badge variant="outline" className="text-[10px] hidden sm:inline-flex">
              {SOURCE_LABELS[item.source] ?? item.source}
            </Badge>
            {sentimentBadge(item.sentiment_score)}
            {isOpen ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </div>
        </div>

        {/* Time */}
        <p className="text-xs text-muted-foreground">{item.publish_time}</p>

        {/* Expanded detail */}
        {isOpen && (
          <div className="space-y-2 pt-2 border-t border-border/50">
            {item.content && (
              <p className="text-sm text-muted-foreground leading-relaxed">
                {item.content.length > 300
                  ? item.content.slice(0, 300) + "..."
                  : item.content}
              </p>
            )}
            {item.keywords && (
              <div className="flex flex-wrap gap-1">
                {item.keywords.split(",").map((kw) => (
                  <Badge key={kw.trim()} variant="secondary" className="text-[10px]">
                    {kw.trim()}
                  </Badge>
                ))}
              </div>
            )}
            {item.url && (
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-chart-1 hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                <ExternalLink className="h-3 w-3" />
                查看原文
              </a>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
