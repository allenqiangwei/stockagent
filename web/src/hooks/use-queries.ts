"use client";

import { useQuery, useQueries, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { market, stocks, strategies, signals, backtest, news, appConfig, lab, marketOverview } from "@/lib/api";

// ── Market ───────────────────────────────────────
export function useKline(
  code: string,
  start: string,
  end: string,
  period = "daily"
) {
  return useQuery({
    queryKey: ["kline", code, period, start, end],
    queryFn: () => market.kline(code, start, end, period),
    enabled: !!code && !!start && !!end,
    placeholderData: keepPreviousData,
  });
}

export function useIndicators(
  code: string,
  indicators: string,
  start: string,
  end: string
) {
  return useQuery({
    queryKey: ["indicators", code, indicators, start, end],
    queryFn: () => market.indicators(code, indicators, start, end),
    enabled: !!code && !!indicators && !!start && !!end,
  });
}

export function useQuote(code: string) {
  return useQuery({
    queryKey: ["quote", code],
    queryFn: () => market.quote(code),
    enabled: !!code,
  });
}

export function useWatchlistQuotes(codes: string[]) {
  return useQueries({
    queries: codes.map((code) => ({
      queryKey: ["quote", code],
      queryFn: () => market.quote(code),
      staleTime: 60 * 1000,
    })),
  });
}

// ── Market Overview (index) ─────────────────────
export function useIndexKline(
  code: string,
  start: string,
  end: string,
  period = "daily"
) {
  return useQuery({
    queryKey: ["index-kline", code, period, start, end],
    queryFn: () => marketOverview.indexKline(code, start, end, period),
    enabled: !!code && !!start && !!end,
    placeholderData: keepPreviousData,
  });
}

// ── Stocks ───────────────────────────────────────
export function useStockSearch(keyword: string) {
  return useQuery({
    queryKey: ["stocks", keyword],
    queryFn: () => stocks.list(keyword, 1, 20),
    enabled: keyword.length >= 1,
  });
}

export function useWatchlist() {
  return useQuery({
    queryKey: ["watchlist"],
    queryFn: () => stocks.watchlist(),
  });
}

export function useAddWatchlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ code, name }: { code: string; name: string }) =>
      stocks.addWatchlist(code, name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });
}

export function useRemoveWatchlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => stocks.removeWatchlist(code),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });
}

// ── Strategies ───────────────────────────────────
export function useStrategies() {
  return useQuery({
    queryKey: ["strategies"],
    queryFn: () => strategies.list(),
  });
}

export function useStrategy(id: number) {
  return useQuery({
    queryKey: ["strategy", id],
    queryFn: () => strategies.get(id),
    enabled: id > 0,
  });
}

export function useIndicatorGroups() {
  return useQuery({
    queryKey: ["indicator-groups"],
    queryFn: () => strategies.indicatorGroups(),
    staleTime: Infinity,
  });
}

// ── Signals ──────────────────────────────────────
export function useSignalMeta() {
  return useQuery({
    queryKey: ["signals", "meta"],
    queryFn: () => signals.meta(),
    refetchInterval: 60 * 1000,
  });
}

export function useTodaySignals(date = "") {
  return useQuery({
    queryKey: ["signals", "today", date],
    queryFn: () => signals.today(date),
  });
}

export function useSignalHistory(page = 1, size = 50, action = "", date = "", strategy = "") {
  return useQuery({
    queryKey: ["signals", "history", page, size, action, date, strategy],
    queryFn: () => signals.history(page, size, action, date, strategy),
  });
}

export function useGenerateSignals() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { codes?: string[]; date?: string }) =>
      signals.generate(params.codes, params.date),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["signals"] }),
  });
}

// ── News ────────────────────────────────────────
export function useNewsLatest() {
  return useQuery({
    queryKey: ["news", "latest"],
    queryFn: () => news.latest(),
    refetchInterval: 5 * 60 * 1000, // refresh every 5 minutes
  });
}

export function useNewsStats() {
  return useQuery({
    queryKey: ["news", "stats"],
    queryFn: () => news.stats(),
    staleTime: 10 * 60 * 1000, // stats change slowly
  });
}

export function useRelatedNews(code: string) {
  return useQuery({
    queryKey: ["news", "related", code],
    queryFn: () => news.related(code),
    enabled: !!code,
    staleTime: 5 * 60 * 1000,
  });
}

export function useSentimentLatest() {
  return useQuery({
    queryKey: ["news", "sentiment", "latest"],
    queryFn: () => news.sentimentLatest(),
    refetchInterval: 5 * 60 * 1000,
  });
}

export function useSentimentHistory(days = 30) {
  return useQuery({
    queryKey: ["news", "sentiment", "history", days],
    queryFn: () => news.sentimentHistory(days),
    staleTime: 10 * 60 * 1000,
  });
}

export function useTriggerSentimentAnalysis() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => news.triggerAnalysis(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["news", "sentiment"] });
    },
  });
}

// ── Config ──────────────────────────────────────
export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: () => appConfig.get(),
    staleTime: 5 * 60_000,
  });
}

export function useUpdateConfig() {
  const qc = useQueryClient();
  return useMutation({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mutationFn: (data: Record<string, any>) => appConfig.update(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["config"] }),
  });
}

// ── Backtest ─────────────────────────────────────
export function useBacktestRuns(strategyId?: number) {
  return useQuery({
    queryKey: ["backtest", "runs", strategyId],
    queryFn: () => backtest.runs(strategyId),
  });
}

export function useBacktestDetail(runId: number) {
  return useQuery({
    queryKey: ["backtest", "detail", runId],
    queryFn: () => backtest.detail(runId),
    enabled: runId > 0,
  });
}

// ── AI Lab ──────────────────────────────────────
export function useLabTemplates() {
  return useQuery({
    queryKey: ["lab", "templates"],
    queryFn: () => lab.templates(),
  });
}

export function useLabExperiments(page = 1, size = 20) {
  return useQuery({
    queryKey: ["lab", "experiments", page, size],
    queryFn: () => lab.experiments(page, size),
  });
}

export function useLabExperiment(id: number) {
  return useQuery({
    queryKey: ["lab", "experiment", id],
    queryFn: () => lab.experiment(id),
    enabled: id > 0,
  });
}

export function useCreateTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; category?: string; description?: string }) =>
      lab.createTemplate(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lab", "templates"] }),
  });
}

export function useUpdateTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number; name?: string; category?: string; description?: string }) =>
      lab.updateTemplate(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lab", "templates"] }),
  });
}

export function useDeleteTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => lab.deleteTemplate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lab", "templates"] }),
  });
}

export function useDeleteExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => lab.deleteExperiment(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lab", "experiments"] }),
  });
}

export function usePromoteStrategy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => lab.promoteStrategy(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lab"] });
      qc.invalidateQueries({ queryKey: ["strategies"] });
    },
  });
}
