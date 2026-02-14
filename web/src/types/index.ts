export interface StockInfo {
  code: string;
  name: string;
  market: string;
  industry: string;
}

export interface KlineBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface KlineResponse {
  stock_code: string;
  stock_name: string;
  period: string;
  bars: KlineBar[];
  signals: { date: string; action: string; strategy_name: string }[];
}

export interface IndicatorPoint {
  date: string;
  values: Record<string, number | null>;
}

export interface QuoteResponse {
  stock_code: string;
  stock_name: string;
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  change_pct: number | null;
}

// ── Index / Market Overview ─────────────────────
export interface RegimeWeek {
  week_start: string;
  week_end: string;
  regime: string;
  confidence: number;
  trend_strength: number;
  volatility: number;
  index_return_pct: number;
}

export interface IndexKlineResponse {
  index_code: string;
  index_name: string;
  period: string;
  bars: KlineBar[];
  regimes: RegimeWeek[];
}

export interface WatchlistItem {
  stock_code: string;
  stock_name: string;
  sort_order: number;
  close: number | null;
  change_pct: number | null;
  date: string | null;
}

export interface RankFactor {
  type: "indicator" | "kline" | "basic";
  field: string;
  params?: Record<string, number>;
  direction: "asc" | "desc";
  weight: number;
}

export interface RankConfig {
  factors: RankFactor[];
}

export interface PortfolioConfig {
  initial_capital: number;
  max_positions: number;
  position_sizing: "equal_weight";
}

export interface Strategy {
  id: number;
  name: string;
  description: string;
  rules: Record<string, unknown>[];
  buy_conditions: Record<string, unknown>[];
  sell_conditions: Record<string, unknown>[];
  exit_config: {
    stop_loss_pct?: number;
    take_profit_pct?: number;
    max_hold_days?: number;
  };
  weight: number;
  enabled: boolean;
  rank_config?: RankConfig | null;
  portfolio_config?: PortfolioConfig | null;
}

export interface SignalItem {
  stock_code: string;
  stock_name: string;
  trade_date: string;
  final_score: number;
  signal_level: number;
  signal_level_name: string;
  action: "buy" | "sell" | "hold";
  reasons: string[];
}

export interface SignalMeta {
  last_generated_at: string | null;
  last_trade_date: string | null;
  signal_count: number;
  next_run_time: string | null;
  refresh_hour: number;
  refresh_minute: number;
}

export interface BacktestRun {
  id: number;
  strategy_name: string;
  start_date: string;
  end_date: string;
  total_trades: number;
  win_rate: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  created_at: string;
  backtest_mode?: string | null;
  cagr_pct?: number | null;
  sharpe_ratio?: number | null;
}

export interface BacktestResult {
  id: number;
  strategy_name: string;
  start_date: string;
  end_date: string;
  capital_per_trade: number;
  total_trades: number;
  win_trades: number;
  lose_trades: number;
  win_rate: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  avg_hold_days: number;
  avg_pnl_pct: number;
  equity_curve: { date: string; equity: number }[];
  sell_reason_stats: Record<string, number>;
  trades: TradeDetail[];
  // Portfolio mode fields
  backtest_mode?: string | null;
  initial_capital?: number | null;
  max_positions?: number | null;
  cagr_pct?: number | null;
  sharpe_ratio?: number | null;
  calmar_ratio?: number | null;
  profit_loss_ratio?: number | null;
  regime_stats?: Record<string, RegimeStatEntry> | null;
  index_return_pct?: number | null;
}

export interface TradeDetail {
  stock_code: string;
  strategy_name: string;
  buy_date: string;
  buy_price: number;
  sell_date: string;
  sell_price: number;
  sell_reason: string;
  pnl_pct: number;
  hold_days: number;
}

// ── App config (settings page) ──────────────────
export interface AppConfig {
  data_sources: {
    realtime_quotes: string;
    historical_daily: string;
    index_data: string;
    sector_data: string;
    money_flow: string;
    stock_list: string;
    fallback_enabled: boolean;
    tushare_token_masked: string;
    tushare_rate_limit: number;
  };
  signals: {
    auto_refresh_hour: number;
    auto_refresh_minute: number;
  };
  risk_control: {
    fixed_stop_pct: number;
    atr_multiplier: number;
    max_position_pct: number;
    target_total_pct: number;
    max_stocks: number;
  };
  deepseek: {
    api_key_masked: string;
    base_url: string;
    model: string;
  };
  ai_lab?: {
    weight_return: number;
    weight_drawdown: number;
    weight_sharpe: number;
    weight_plr: number;
  };
}

// ── Indicator metadata (for rule editor) ────────
export interface IndicatorParam {
  label: string;
  default: number;
  type: string;
}

export interface IndicatorGroup {
  label: string;
  sub_fields: [string, string][]; // [field_key, label]
  params: Record<string, IndicatorParam>;
}

export interface IndicatorGroupsResponse {
  groups: Record<string, IndicatorGroup>;
  operators: [string, string][]; // [op, label]
}

// Rule type used in strategy rules/conditions
export interface StrategyRule {
  field: string;
  operator: string;
  compare_type: "value" | "field";
  compare_value?: number;
  compare_field?: string;
  params?: Record<string, number>;
  compare_params?: Record<string, number>;
  score?: number;
  label?: string;
}

// ── News ─────────────────────────────────────────
export interface NewsItem {
  title: string;
  source: string; // "cls" | "eastmoney" | "sina"
  sentiment_score: number; // 0-100
  keywords: string;
  url: string;
  publish_time: string;
  content: string;
}

export interface SourceStats {
  count: number;
  avg_sentiment: number;
}

export interface NewsLatestResponse {
  fetch_time: string;
  fetch_timestamp: number;
  next_fetch_timestamp: number;
  interval_seconds: number;
  total_count: number;
  overall_sentiment: number;
  positive_count: number;
  negative_count: number;
  neutral_count: number;
  keyword_counts: [string, number][];
  source_stats: Record<string, SourceStats>;
  news_list: NewsItem[];
}

export interface NewsStatsResponse {
  total_archived: number;
  total: number;
  avg_sentiment: number;
  by_date: { fetch_date: string; count: number; avg_sentiment: number }[];
}

export interface SentimentLatestResponse {
  has_data: boolean;
  market_sentiment: number;
  confidence: number;
  event_tags: string[];
  key_summary: string;
  stock_mentions: { name: string; sentiment: number; reason: string }[];
  sector_impacts: { sector: string; impact: number; reason: string }[];
  analysis_time: string | null;
  period_type: string | null;
  news_count: number;
}

export interface SentimentHistoryItem {
  id: number;
  analysis_time: string | null;
  period_type: string;
  market_sentiment: number;
  confidence: number;
  event_tags: string[];
  key_summary: string;
  news_count: number;
}

export interface SentimentHistoryResponse {
  days: number;
  count: number;
  items: SentimentHistoryItem[];
}

export interface RelatedNewsResponse {
  stock_code: string;
  stock_name: string;
  industry: string;
  concepts: string[];
  news: NewsItem[];
}

// ── AI Lab ──────────────────────────────────────
export interface LabTemplate {
  id: number;
  name: string;
  category: string;
  description: string;
  is_builtin: boolean;
}

export interface LabExperimentStrategy {
  id: number;
  name: string;
  description: string;
  buy_conditions: Record<string, unknown>[];
  sell_conditions: Record<string, unknown>[];
  exit_config: { stop_loss_pct?: number; take_profit_pct?: number; max_hold_days?: number };
  status: string;
  error_message: string;
  total_trades: number;
  win_rate: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  avg_hold_days: number;
  avg_pnl_pct: number;
  score: number;
  backtest_run_id: number | null;
  regime_stats?: Record<string, RegimeStatEntry> | null;
  promoted: boolean;
  promoted_strategy_id: number | null;
}

export interface RegimeStatEntry {
  trades: number;
  wins: number;
  win_rate: number;
  avg_pnl: number;
  total_pnl: number;
}

export interface LabExperiment {
  id: number;
  theme: string;
  source_type: string;
  source_text: string;
  status: string;
  strategy_count: number;
  created_at: string;
  strategies: LabExperimentStrategy[];
}

export interface LabExperimentListItem {
  id: number;
  theme: string;
  source_type: string;
  status: string;
  strategy_count: number;
  best_score: number;
  best_name: string;
  created_at: string;
}
