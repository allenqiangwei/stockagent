"use client";

import { useState } from "react";
import { useQuote, useRelatedNews, usePortfolio, useAddPortfolio } from "@/hooks/use-queries";
import { useAppStore } from "@/lib/store";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { ExternalLink, Briefcase } from "lucide-react";
import type { NewsItem } from "@/types";

function formatNum(n: number | null | undefined) {
  if (n == null) return "--";
  return n.toFixed(2);
}

function formatVol(v: number | null | undefined) {
  if (v == null) return "--";
  if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
  if (v >= 1e4) return (v / 1e4).toFixed(0) + "万";
  return v.toFixed(0);
}

function sentimentColor(score: number | null): string {
  if (score == null) return "bg-yellow-500";
  if (score > 58) return "bg-red-500";
  if (score < 42) return "bg-green-500";
  return "bg-yellow-500";
}

function sentimentLabel(score: number | null): { text: string; cls: string } {
  if (score == null) return { text: "中性", cls: "text-yellow-500" };
  if (score > 58) return { text: "积极", cls: "text-red-400" };
  if (score < 42) return { text: "消极", cls: "text-green-400" };
  return { text: "中性", cls: "text-yellow-500" };
}

function formatTime(publishTime: string): string {
  if (!publishTime) return "";
  const d = new Date(publishTime);
  if (isNaN(d.getTime())) return publishTime.slice(0, 16);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 60) return `${diffMin}分钟前`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}小时前`;
  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 7) return `${diffDay}天前`;
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function formatFullTime(publishTime: string): string {
  if (!publishTime) return "";
  const d = new Date(publishTime);
  if (isNaN(d.getTime())) return publishTime;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function NewsRow({
  item,
  onClick,
}: {
  item: NewsItem;
  onClick: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className="block px-1 py-1.5 rounded hover:bg-muted/50 transition-colors cursor-pointer"
    >
      <div className="flex items-start gap-1.5">
        <span
          className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${sentimentColor(item.sentiment_score)}`}
        />
        <span className="text-xs leading-snug line-clamp-2">{item.title}</span>
      </div>
      <div className="flex items-center gap-2 mt-0.5 ml-3">
        <span className="text-[10px] text-muted-foreground">
          {item.source}
        </span>
        <span className="text-[10px] text-muted-foreground">
          {formatTime(item.publish_time)}
        </span>
      </div>
    </div>
  );
}

function NewsDetailDialog({
  item,
  open,
  onOpenChange,
}: {
  item: NewsItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  if (!item) return null;
  const sentiment = sentimentLabel(item.sentiment_score);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-sm leading-snug pr-6">
            {item.title}
          </DialogTitle>
        </DialogHeader>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>{item.source}</span>
          <span>{formatFullTime(item.publish_time)}</span>
          <span className={sentiment.cls}>
            情绪: {sentiment.text}
            {item.sentiment_score != null && ` (${item.sentiment_score.toFixed(0)})`}
          </span>
        </div>
        <ScrollArea className="flex-1 min-h-0 mt-2">
          <p className="text-sm leading-relaxed whitespace-pre-wrap">
            {item.content || "暂无正文内容"}
          </p>
        </ScrollArea>
        {item.url && (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 mt-2"
          >
            <ExternalLink className="h-3 w-3" />
            查看原文
          </a>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function QuotePanel() {
  const code = useAppStore((s) => s.currentStock);
  const name = useAppStore((s) => s.currentStockName);
  const { data: q, isLoading } = useQuote(code);
  const { data: related } = useRelatedNews(code);
  const { data: portfolio } = usePortfolio();
  const addPortfolio = useAddPortfolio();
  const [selectedNews, setSelectedNews] = useState<NewsItem | null>(null);
  const [portfolioOpen, setPortfolioOpen] = useState(false);
  const [pQty, setPQty] = useState("100");
  const [pCost, setPCost] = useState("");
  const existingHolding = portfolio?.find((p) => p.stock_code === code);

  if (isLoading) {
    return (
      <div className="p-3 text-sm text-muted-foreground">加载行情中...</div>
    );
  }
  if (!q) return null;

  const changePct = q.change_pct ?? 0;
  const isUp = changePct >= 0;
  const color = isUp ? "text-red-400" : "text-green-400";

  const newsList = related?.news ?? [];
  const industry = related?.industry ?? "";
  const concepts = related?.concepts ?? [];

  return (
    <div className="flex flex-col h-full">
      {/* Quote section */}
      <div className="p-3 space-y-3 shrink-0">
        <div>
          <div className="text-xs text-muted-foreground">{code}</div>
          <div className="text-lg font-semibold">{name}</div>
          <div className={`text-2xl font-bold font-mono ${color}`}>
            {formatNum(q.close)}
          </div>
          <div className={`text-sm font-mono ${color}`}>
            {isUp ? "+" : ""}
            {changePct.toFixed(2)}%
          </div>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <div className="flex justify-between">
            <span className="text-muted-foreground">开盘</span>
            <span className="font-mono">{formatNum(q.open)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">最高</span>
            <span className="font-mono text-red-400">{formatNum(q.high)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">最低</span>
            <span className="font-mono text-green-400">{formatNum(q.low)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">成交量</span>
            <span className="font-mono">{formatVol(q.volume)}</span>
          </div>
        </div>
        {/* Portfolio button */}
        <div className="pt-1">
          {existingHolding ? (
            <Button variant="outline" size="sm" className="w-full text-xs h-7" disabled>
              <Briefcase className="h-3 w-3 mr-1" />
              已持仓 {existingHolding.quantity}股
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              className="w-full text-xs h-7"
              onClick={() => {
                setPCost(q?.close?.toFixed(2) ?? "");
                setPQty("100");
                setPortfolioOpen(true);
              }}
            >
              <Briefcase className="h-3 w-3 mr-1" />
              加入持仓
            </Button>
          )}
        </div>
      </div>

      <Separator />

      {/* Add to portfolio dialog */}
      <Dialog open={portfolioOpen} onOpenChange={setPortfolioOpen}>
        <DialogContent className="max-w-xs">
          <DialogHeader>
            <DialogTitle className="text-sm">加入持仓 — {name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">数量（股）</span>
              <Input
                type="number"
                value={pQty}
                onChange={(e) => setPQty(e.target.value)}
                className="h-8 text-sm"
                min={1}
              />
            </div>
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">均价（元）</span>
              <Input
                type="number"
                value={pCost}
                onChange={(e) => setPCost(e.target.value)}
                className="h-8 text-sm"
                step="0.01"
                min={0}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              size="sm"
              className="text-xs"
              disabled={!pQty || !pCost || addPortfolio.isPending}
              onClick={() => {
                const qty = parseInt(pQty, 10);
                const cost = parseFloat(pCost);
                if (qty > 0 && cost > 0) {
                  addPortfolio.mutate(
                    { code, quantity: qty, avgCost: cost, name },
                    { onSuccess: () => setPortfolioOpen(false) }
                  );
                }
              }}
            >
              {addPortfolio.isPending ? "提交中..." : "确认"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Related news section */}
      <div className="px-3 pt-2 pb-1 shrink-0 space-y-1">
        <span className="text-xs font-medium">相关资讯</span>
        {(industry || concepts.length > 0) && (
          <div className="flex flex-wrap gap-1">
            {industry && (
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                {industry}
              </Badge>
            )}
            {concepts.map((c) => (
              <Badge key={c} variant="outline" className="text-[10px] px-1.5 py-0">
                {c}
              </Badge>
            ))}
          </div>
        )}
      </div>

      <ScrollArea className="flex-1 min-h-0 px-2 pb-2">
        {newsList.length === 0 ? (
          <div className="py-4 text-center text-xs text-muted-foreground">
            暂无相关资讯
          </div>
        ) : (
          <div className="space-y-0.5">
            {newsList.map((item, i) => (
              <NewsRow
                key={i}
                item={item}
                onClick={() => setSelectedNews(item)}
              />
            ))}
          </div>
        )}
      </ScrollArea>

      <NewsDetailDialog
        item={selectedNews}
        open={selectedNews !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedNews(null);
        }}
      />
    </div>
  );
}
