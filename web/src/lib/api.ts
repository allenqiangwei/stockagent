const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function put<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

// ── Market ────────────────────────────────────────────
import type {
  KlineResponse,
  IndicatorPoint,
  QuoteResponse,
  WatchlistItem,
  StockInfo,
  Strategy,
  SignalItem,
  SignalMeta,
  BacktestRun,
  BacktestResult,
  NewsLatestResponse,
  NewsStatsResponse,
  RelatedNewsResponse,
  SentimentLatestResponse,
  SentimentHistoryResponse,
  IndicatorGroupsResponse,
  AppConfig,
  LabTemplate,
  LabExperiment,
  LabExperimentListItem,
  IndexKlineResponse,
} from "@/types";

export const market = {
  kline: (code: string, start: string, end: string, period = "daily") =>
    request<KlineResponse>(
      `/market/kline/${code}?period=${period}&start=${start}&end=${end}`
    ),
  indicators: (code: string, indicators: string, start: string, end: string) =>
    request<{ stock_code: string; indicators: string[]; data: IndicatorPoint[] }>(
      `/market/indicators/${code}?indicators=${encodeURIComponent(indicators)}&start=${start}&end=${end}`
    ),
  quote: (code: string) => request<QuoteResponse>(`/market/quote/${code}`),
};

// ── Market Overview (index) ──────────────────────────
export const marketOverview = {
  indexKline: (code: string, start: string, end: string, period = "daily", refresh = false) =>
    request<IndexKlineResponse>(
      `/market/index-kline/${code}?period=${period}&start=${start}&end=${end}${refresh ? "&refresh=true" : ""}`
    ),
  indexList: () =>
    request<Record<string, { name: string }>>(`/market/index-list`),
};

// ── Stocks ────────────────────────────────────────────
export const stocks = {
  list: (keyword = "", page = 1, size = 50) =>
    request<{ total: number; items: StockInfo[] }>(
      `/stocks?keyword=${keyword}&page=${page}&size=${size}`
    ),
  sync: () => post<{ synced: number }>("/stocks/sync", {}),
  watchlist: () => request<WatchlistItem[]>("/stocks/watchlist"),
  addWatchlist: (code: string, name = "") =>
    post<WatchlistItem>("/stocks/watchlist", {
      stock_code: code,
      stock_name: name,
    }),
  removeWatchlist: (code: string) => del<{ removed: string }>(`/stocks/watchlist/${code}`),
};

// ── Strategies ────────────────────────────────────────
export const strategies = {
  list: () => request<Strategy[]>("/strategies"),
  get: (id: number) => request<Strategy>(`/strategies/${id}`),
  create: (data: Omit<Strategy, "id">) => post<Strategy>("/strategies", data),
  update: (id: number, data: Partial<Strategy>) =>
    put<Strategy>(`/strategies/${id}`, data),
  delete: (id: number) => del<{ deleted: number }>(`/strategies/${id}`),
  indicatorGroups: () =>
    request<IndicatorGroupsResponse>("/strategies/indicator-groups"),
};

// ── Signals ───────────────────────────────────────────
export const signals = {
  meta: () => request<SignalMeta>("/signals/meta"),
  today: (date = "") =>
    request<{ trade_date: string; total: number; items: SignalItem[] }>(
      `/signals/today?date=${date}`
    ),
  history: (page = 1, size = 50, action = "", date = "", strategy = "") =>
    request<{ total: number; items: SignalItem[] }>(
      `/signals/history?page=${page}&size=${size}&action=${action}&date=${date}&strategy=${strategy}`
    ),
  generate: (codes?: string[], date = "") =>
    post<{ trade_date: string; generated: number; items: SignalItem[] }>(
      `/signals/generate?date=${date}`,
      codes ?? null
    ),
  generateStream: (date = "") =>
    fetch(`${BASE}/signals/generate-stream?date=${date}`, { method: "POST" }),
};

// ── News ─────────────────────────────────────────
export const news = {
  latest: () => request<NewsLatestResponse>("/news/latest"),
  stats: () => request<NewsStatsResponse>("/news/stats"),
  related: (code: string) => request<RelatedNewsResponse>(`/news/related/${code}`),
  sentimentLatest: () => request<SentimentLatestResponse>("/news/sentiment/latest"),
  sentimentHistory: (days = 30) =>
    request<SentimentHistoryResponse>(`/news/sentiment/history?days=${days}`),
  triggerAnalysis: () => post<{ message: string; result: unknown }>("/news/sentiment/analyze", {}),
};

// ── Config ───────────────────────────────────────────
export const appConfig = {
  get: () => request<AppConfig>("/config"),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  update: (data: Record<string, any>) => put<{ status: string }>("/config", data),
};

// ── AI Lab ───────────────────────────────────────────
export const lab = {
  templates: () => request<LabTemplate[]>("/lab/templates"),
  createTemplate: (data: { name: string; category?: string; description?: string }) =>
    post<LabTemplate>("/lab/templates", data),
  updateTemplate: (id: number, data: { name?: string; category?: string; description?: string }) =>
    put<LabTemplate>(`/lab/templates/${id}`, data),
  deleteTemplate: (id: number) => del<{ deleted: number }>(`/lab/templates/${id}`),
  experiments: (page = 1, size = 20) =>
    request<{ total: number; items: LabExperimentListItem[] }>(
      `/lab/experiments?page=${page}&size=${size}`
    ),
  experiment: (id: number) => request<LabExperiment>(`/lab/experiments/${id}`),
  deleteExperiment: (id: number) => del<{ deleted: number }>(`/lab/experiments/${id}`),
  createExperimentSSE: (data: {
    theme: string;
    source_type: string;
    source_text: string;
    initial_capital?: number;
    max_positions?: number;
    max_position_pct?: number;
  }) =>
    fetch(`${BASE}/lab/experiments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  promoteStrategy: (id: number) =>
    post<{ message: string; strategy_id: number }>(`/lab/strategies/${id}/promote`, {}),
};

// ── Backtest ──────────────────────────────────────────
export const backtest = {
  runSync: (data: {
    strategy_id: number;
    start_date: string;
    end_date: string;
    capital_per_trade?: number;
    stock_codes?: string[];
    scope?: string;
  }) => post<BacktestResult>("/backtest/run/sync", data),
  runs: (strategyId?: number, limit = 50) =>
    request<BacktestRun[]>(
      `/backtest/runs?${strategyId ? `strategy_id=${strategyId}&` : ""}limit=${limit}`
    ),
  detail: (runId: number) => request<BacktestResult>(`/backtest/runs/${runId}`),
  runSSE: (data: {
    strategy_id: number;
    start_date: string;
    end_date: string;
    capital_per_trade?: number;
    stock_codes?: string[];
    scope?: string;
  }) => {
    return fetch(`${BASE}/backtest/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  },
};
