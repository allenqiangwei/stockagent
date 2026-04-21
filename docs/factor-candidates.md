# Beta 因子候选列表

> 基于学术研究（Barra CNE5/6、Fama-French、WorldQuant 101 Alphas）和 A 股实证经验整理。
> 标注了每个因子在本系统中的数据可用性。

## 当前已有因子 (14个)

| # | 因子 | 类别 | 状态 |
|---|------|------|------|
| 1 | alpha_score | 信号 | ✓ 使用中 |
| 2 | day_of_week | 日历 | ✓ 使用中 |
| 3 | stock_return_5d | 动量 | ✓ 使用中 |
| 4 | stock_volatility_20d | 波动率 | ✓ 使用中 |
| 5 | volume_ratio_5d | 量能 | ✓ 使用中 |
| 6 | index_return_5d | 大盘 | ✓ 使用中 |
| 7 | index_return_20d | 大盘 | ✓ 使用中 |
| 8 | sector_heat_score | 情绪 | ✓ 使用中 |
| 9 | regime_encoded | 宏观 | ✓ 使用中 |
| 10 | strategy_family_encoded | 信号 | ✓ 使用中 |
| 11 | gamma_score | 缠论 | ✓ 使用中 |
| 12 | daily_mmd_type_encoded | 缠论 | ✓ 使用中 |
| 13 | daily_mmd_age | 缠论 | ✓ 使用中 |
| 14 | weekly_resonance | 缠论 | ✓ 使用中 |

---

## 新增候选因子

### 一、价量因子 (Price-Volume)

数据来源: `daily_prices` (6M行) + `stock_daily` (3.9M行)

| # | 因子名 | 英文 | 计算方式 | 数据可用 |
|---|--------|------|----------|----------|
| 15 | 5日动量 | momentum_5d | (close - close_5d_ago) / close_5d_ago | ✓ daily_prices |
| 16 | 20日动量 | momentum_20d | (close - close_20d_ago) / close_20d_ago | ✓ daily_prices |
| 17 | 隔夜收益率 | overnight_return | (open_today - close_yesterday) / close_yesterday | ✓ daily_prices |
| 18 | 日内收益率 | intraday_return | (close - open) / open | ✓ daily_prices |
| 19 | 上影线比率 | upper_shadow_ratio | (high - max(open,close)) / (high - low) | ✓ daily_prices |
| 20 | 下影线比率 | lower_shadow_ratio | (min(open,close) - low) / (high - low) | ✓ daily_prices |
| 21 | 振幅 | amplitude | (high - low) / close | ✓ daily_prices |
| 22 | 5日振幅标准差 | amplitude_std_5d | std(amplitude, 5) | ✓ daily_prices |
| 23 | 量价相关性 | price_volume_corr_20d | corr(close_return, volume, 20) | ✓ daily_prices |
| 24 | 成交额集中度 | amount_concentration | max(amount_5d) / sum(amount_5d) | ✓ daily_prices |
| 25 | 大单比例(近似) | big_order_proxy | amount / volume — 均价越高说明大单越多 | ✓ daily_prices |
| 26 | 换手率变化 | turnover_change_5d | turnover_today / avg(turnover, 5d) | ✓ daily_basic |
| 27 | 量比 | volume_ratio_intraday | volume_today / avg(volume, 5d) | ✓ daily_prices |
| 28 | 高低价位比 | high_low_ratio_20d | (20d_high - close) / (20d_high - 20d_low) | ✓ daily_prices |
| 29 | 收盘价位置 | close_position_20d | (close - 20d_low) / (20d_high - 20d_low) | ✓ daily_prices |
| 30 | 连涨/连跌天数 | consecutive_direction | 连续涨/跌的天数(正/负) | ✓ daily_prices |

### 二、波动率因子 (Volatility)

| # | 因子名 | 英文 | 计算方式 | 数据可用 |
|---|--------|------|----------|----------|
| 31 | 5日波动率 | volatility_5d | std(daily_return, 5) | ✓ daily_prices |
| 32 | 波动率变化 | volatility_change | vol_5d / vol_20d | ✓ daily_prices |
| 33 | 已实现偏度 | realized_skewness_20d | skew(daily_return, 20) | ✓ daily_prices |
| 34 | 已实现峰度 | realized_kurtosis_20d | kurtosis(daily_return, 20) | ✓ daily_prices |
| 35 | 下行波动率 | downside_volatility_20d | std(negative_returns_only, 20) | ✓ daily_prices |
| 36 | 最大回撤(20日) | max_drawdown_20d | 20日内最大回撤 | ✓ daily_prices |
| 37 | Parkinson波动率 | parkinson_vol | sqrt(1/4ln2 * mean(ln(H/L)^2)) | ✓ daily_prices |
| 38 | 特质波动率 | idio_volatility | 残差波动率(回归掉市场因子后) | ✓ 需要计算 |

### 三、估值因子 (Valuation / Value)

数据来源: `daily_basic` (21K行)

| # | 因子名 | 英文 | 计算方式 | 数据可用 |
|---|--------|------|----------|----------|
| 39 | PE (已有但未入模) | pe_ratio | 市盈率 | ✓ daily_basic.pe |
| 40 | PB (已有但未入模) | pb_ratio | 市净率 | ✓ daily_basic.pb |
| 41 | 总市值 | market_cap | 总市值 | ✓ daily_basic.total_mv |
| 42 | 流通市值 | circ_market_cap | 流通市值 | ✓ daily_basic.circ_mv |
| 43 | 市值对数 | log_market_cap | ln(total_mv) — Barra Size因子 | ✓ daily_basic |
| 44 | EP (盈利收益率) | earnings_yield | 1/PE — Barra Earnings Yield | ✓ daily_basic |
| 45 | BP (账面价值比) | book_to_price | 1/PB — Barra Book-to-Price | ✓ daily_basic |
| 46 | 换手率(已有但记分卡用) | turnover_rate | 换手率 | ✓ daily_basic |

### 四、动量/反转因子 (Momentum/Reversal)

| # | 因子名 | 英文 | 计算方式 | 数据可用 |
|---|--------|------|----------|----------|
| 47 | 1日反转 | reversal_1d | -1 * return_1d | ✓ daily_prices |
| 48 | 中期动量(剔除近月) | momentum_12m_skip1m | ret_252d - ret_21d (Barra Momentum) | ✓ daily_prices |
| 49 | 短期反转 | short_term_reversal_5d | -1 * return_5d | ✓ daily_prices |
| 50 | 加权动量 | weighted_momentum_20d | sum(ret_i * (21-i)/210, i=1..20) — 近日权重高 | ✓ daily_prices |
| 51 | 相对强弱(vs大盘) | relative_strength_20d | stock_ret_20d - index_ret_20d | ✓ daily_prices + index_daily |
| 52 | 行业内相对强弱 | industry_relative_momentum | stock_ret - industry_avg_ret | ✓ 需关联stocks.industry |

### 五、流动性因子 (Liquidity)

| # | 因子名 | 英文 | 计算方式 | 数据可用 |
|---|--------|------|----------|----------|
| 53 | Amihud非流动性 | amihud_illiquidity | avg(|return| / amount, 20d) | ✓ daily_prices |
| 54 | 零交易天数 | zero_trade_days_20d | count(volume==0, 20d) / 20 | ✓ daily_prices |
| 55 | 换手率波动 | turnover_volatility_20d | std(turnover_rate, 20) | ✓ daily_basic |
| 56 | 平均换手率 | avg_turnover_20d | mean(turnover_rate, 20) | ✓ daily_basic |
| 57 | 成交额对数 | log_amount_20d | ln(mean(amount, 20)) | ✓ daily_prices |

### 六、市场环境因子 (Market / Macro)

数据来源: `market_regimes` (166行), `index_daily` (3.7K行)

| # | 因子名 | 英文 | 计算方式 | 数据可用 |
|---|--------|------|----------|----------|
| 58 | 大盘波动率 | index_volatility_20d | std(index_return, 20) | ✓ index_daily |
| 59 | 市场宽度 | market_breadth | 上涨家数 / 全市场 (from market_regimes.breadth) | ✓ market_regimes |
| 60 | 市场趋势强度 | trend_strength | market_regimes.trend_strength | ✓ market_regimes |
| 61 | 市场波动率 | market_volatility | market_regimes.volatility | ✓ market_regimes |
| 62 | 大盘周收益 | index_return_weekly | market_regimes.index_return_pct | ✓ market_regimes |

### 七、情绪因子 (Sentiment)

数据来源: `news_sentiment_results` (258行), `news_events` (11K行), `news_stock_links` (14K行)

| # | 因子名 | 英文 | 计算方式 | 数据可用 |
|---|--------|------|----------|----------|
| 63 | 个股新闻数量(3日) | news_count_3d | count(news_stock_links, 3d) | ✓ news_stock_links |
| 64 | 个股新闻影响方向 | news_impact_direction | avg(impact_direction) from news_events | ✓ news_events |
| 65 | 个股负面事件数 | negative_event_count | count(impact_direction < 0, 7d) | ✓ news_events |
| 66 | 板块情绪趋势 | sector_heat_trend | sector_heat.trend encoded (rising=1, flat=0, falling=-1) | ✓ sector_heat |
| 67 | 市场情绪 | market_sentiment | news_sentiment_results.market_sentiment | ✓ news_sentiment_results |
| 68 | 情绪置信度 | sentiment_confidence | news_sentiment_results.confidence | ✓ news_sentiment_results |

### 八、Barra 风险因子 (Barra CNE5/6 Style Factors)

可从现有数据计算的 Barra 标准因子:

| # | 因子名 | Barra名 | 计算方式 | 数据可用 |
|---|--------|---------|----------|----------|
| 69 | Beta | BETA | regress(stock_ret ~ market_ret, 252d).beta | ✓ daily_prices + index_daily |
| 70 | 对数市值 | SIZE | ln(market_cap) | ✓ daily_basic |
| 71 | 非线性市值 | NLSIZE | SIZE^3 残差(orthogonalized) | ✓ daily_basic |
| 72 | 账面市值比 | BTOP | 1 / PB | ✓ daily_basic |
| 73 | 动量(剔除近月) | MOMENTUM | cumret(2m..12m ago) | ✓ daily_prices |
| 74 | 残差波动率 | RESVOL | std(residual from CAPM, 252d) | ✓ 需要计算 |
| 75 | 流动性 | LIQUIDITY | log(avg turnover 1m/3m/12m) | ✓ daily_basic |
| 76 | 杠杆 | LEVERAGE | (long_term_debt + short_term_debt) / equity | ✗ 需财报 |
| 77 | 盈利收益率 | EARNYILD | E/P = 1/PE | ✓ daily_basic |
| 78 | 成长性 | GROWTH | 营收/利润增长率 | ✗ 需财报 |

### 九、质量/基本面因子 (Quality / Fundamental)

当前系统**没有财报数据表**，以下因子需要接入 TuShare/AkShare 财报接口:

| # | 因子名 | 英文 | 计算方式 | 数据可用 |
|---|--------|------|----------|----------|
| 79 | ROE | return_on_equity | 净利润 / 净资产 | ✗ 需财报 |
| 80 | ROA | return_on_assets | 净利润 / 总资产 | ✗ 需财报 |
| 81 | ROIC | return_on_invested_capital | NOPAT / 投入资本 | ✗ 需财报 |
| 82 | 毛利率 | gross_margin | (营收-成本) / 营收 | ✗ 需财报 |
| 83 | 净利率 | net_margin | 净利润 / 营收 | ✗ 需财报 |
| 84 | 资产负债率 | debt_to_assets | 总负债 / 总资产 | ✗ 需财报 |
| 85 | 流动比率 | current_ratio | 流动资产 / 流动负债 | ✗ 需财报 |
| 86 | 营收增长率 | revenue_growth_yoy | 营收同比增长 | ✗ 需财报 |
| 87 | 净利润增长率 | profit_growth_yoy | 净利润同比增长 | ✗ 需财报 |
| 88 | 资产周转率 | asset_turnover | 营收 / 总资产 | ✗ 需财报 |
| 89 | 应计利润率 | accruals_ratio | (净利润 - 经营现金流) / 总资产 | ✗ 需财报 |
| 90 | 经营现金流/净利润 | cash_conversion | 经营现金流 / 净利润 | ✗ 需财报 |
| 91 | 总资产增长率 | asset_growth | 总资产同比变化 — Fama-French Investment因子 | ✗ 需财报 |
| 92 | 股息率 | dividend_yield | 每股股息 / 股价 | ✗ 需财报 |

### 十、筹码/微观结构因子 (Microstructure)

| # | 因子名 | 英文 | 计算方式 | 数据可用 |
|---|--------|------|----------|----------|
| 93 | 筹码集中度 | chip_concentration | 获利比例变化率 | △ 需额外计算 |
| 94 | 主力成本偏离 | cost_deviation | close / avg_cost(筹码加权均价) | △ 需额外计算 |
| 95 | 股价相对52周高点 | pct_from_52w_high | close / max(close, 252d) - 1 | ✓ daily_prices |
| 96 | 股价相对52周低点 | pct_from_52w_low | close / min(close, 252d) - 1 | ✓ daily_prices |

### 十一、日历/时间因子 (Calendar)

| # | 因子名 | 英文 | 计算方式 | 数据可用 |
|---|--------|------|----------|----------|
| 97 | 月份 | month_of_year | 1-12 (A股1月效应、年报季效应) | ✓ 日期计算 |
| 98 | 是否月末周 | is_month_end_week | 月末5个交易日=1 | ✓ trading_calendar |
| 99 | 距上次涨停天数 | days_since_limit_up | 从最近涨停日起算 | ✓ daily_prices |
| 100 | 距IPO天数(对数) | log_days_since_ipo | ln(today - list_date) | ✓ stocks.list_date |

### 十二、概念/板块因子 (Sector / Concept)

数据来源: `stock_concepts` (169K行)

| # | 因子名 | 英文 | 计算方式 | 数据可用 |
|---|--------|------|----------|----------|
| 101 | 概念板块数量 | concept_count | count(concepts per stock) | ✓ stock_concepts |
| 102 | 热门概念命中数 | hot_concept_hits | count(stock concepts ∩ trending concepts) | ✓ stock_concepts + sector_heat |

---

## 优先级建议

### P0 — 立即可用（只需从现有表计算，无需新数据源）

从 `daily_prices` + `daily_basic` + `index_daily` 直接计算：

| 因子 | 理由 |
|------|------|
| pe_ratio (#39) | 已在 daily_basic，只需加入模型 |
| pb_ratio (#40) | 同上 |
| log_market_cap (#43) | Barra SIZE，最经典风险因子之一 |
| momentum_20d (#16) | 动量是最稳定的 alpha 因子 |
| amihud_illiquidity (#53) | A股流动性因子有效性最强 |
| price_volume_corr_20d (#23) | 量价背离是经典信号 |
| close_position_20d (#29) | 近20日价格位置 |
| max_drawdown_20d (#36) | 风险度量 |
| relative_strength_20d (#51) | 相对大盘强弱 |
| pct_from_52w_high (#95) | 锚定效应 |
| index_volatility_20d (#58) | 大盘风险环境 |
| market_breadth (#59) | 已在 market_regimes 表 |
| news_count_3d (#63) | 已在 news_stock_links 表 |
| month_of_year (#97) | 简单日历因子 |

### P1 — 短期可加（需少量额外计算）

| 因子 | 所需工作 |
|------|----------|
| beta (#69) | 252日回归，较重但一次计算 |
| realized_skewness (#33) | 20日偏度 |
| downside_volatility (#35) | 只取负收益的标准差 |
| overnight_return (#17) | open vs prev_close |
| consecutive_direction (#30) | 简单状态计数 |

### P2 — 需新数据源（需接入财报接口）

所有质量/基本面因子 (#79-#92) 需要 TuShare `fina_indicator` 或 AkShare 财报接口。
建议先接入 `fina_indicator` 表获取 ROE、毛利率、资产负债率等核心指标。

---

## 参考来源

- [Barra CNE5 Model (MSCI)](https://www.msci.com/www/fact-sheet/barra-china-equity-model-cne5-/0161591697)
- [Barra CNE6 Factor Introduction](https://studylib.net/doc/27664066/cne6-barra-china-a-total-market-equity-model-for-long-ter...)
- [WorldQuant 101 Formulaic Alphas](https://docs.dolphindb.com/en/Tutorials/wq101alpha.html)
- [中金价量因子手册](https://finance.sina.cn/2022-08-10/detail-imizirav7498837.d.html)
- [因子的定义和分类 (证券时报)](https://www.stcn.com/article/detail/1286680.html)
- [2024有效选股因子 (知乎)](https://zhuanlan.zhihu.com/p/680683619)
- [Alpha Factor Library (ML for Trading)](https://stefan-jansen.github.io/machine-learning-for-trading/24_alpha_factor_library/)
- [Taming the Factor Zoo (AQR)](https://www.aqr.com/-/media/AQR/Documents/AQR-Insight-Award/2018/Taming-the-Factor-Zoo.pdf)
- [Factor Zoo (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4605976)
