"""Analyze trades where confidence >= 60% but lost money.

Joins:
1. bot_trade_plans (confidence, alpha_score, gamma_score, stock_code, stock_name, plan_date)
2. bot_trade_reviews (pnl_pct, holding_days, exit_reason, stock_code)
3. market_regimes (trend_strength, volatility, market_regime) on plan_date within week_start/week_end

Filter: confidence >= 60 AND pnl_pct <= 0

Print each failure with all details + summary statistics.
"""

import sys
import os
from datetime import datetime, timedelta
from collections import Counter, defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.models.base import SessionLocal
from api.models.bot_trading import BotTradePlan, BotTradeReview
from api.models.market_regime import MarketRegimeLabel
from sqlalchemy import text


def main():
    session = SessionLocal()

    try:
        # First, print overall statistics about data
        print("=" * 150)
        print("DATASET OVERVIEW")
        print("=" * 150)

        overview = session.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM bot_trade_plans) as total_plans,
                (SELECT COUNT(*) FROM bot_trade_plans WHERE confidence IS NOT NULL) as plans_with_conf,
                (SELECT COUNT(*) FROM bot_trade_plans WHERE confidence >= 60) as high_conf_plans,
                (SELECT COUNT(*) FROM bot_trade_reviews) as total_reviews,
                (SELECT COUNT(*) FROM bot_trade_reviews WHERE pnl_pct <= 0) as losing_reviews
        """)).fetchone()

        print(f"BotTradePlan:")
        print(f"  Total plans: {overview[0]}")
        print(f"  Plans with confidence score: {overview[1]}")
        print(f"  Plans with confidence >= 60%: {overview[2]}")
        print(f"\nBotTradeReview:")
        print(f"  Total reviews: {overview[3]}")
        print(f"  Losing/breaking-even reviews (pnl <= 0): {overview[4]}")

        # Query: DISTINCT ON (br.id) to avoid duplicates
        # Join BotTradePlan to BotTradeReview on:
        #   - stock_code match
        #   - bp.created_at within 7 days before br.created_at (broader window)
        # Then join MarketRegimes on plan_date within week_start/week_end
        query = text("""
            SELECT DISTINCT ON (br.id)
                br.id as review_id,
                br.stock_code,
                br.stock_name,
                bp.plan_date,
                bp.confidence,
                bp.alpha_score,
                bp.gamma_score,
                br.pnl_pct,
                br.holding_days,
                br.exit_reason,
                br.first_buy_date,
                br.last_sell_date,
                mr.regime,
                mr.trend_strength,
                mr.volatility,
                ABS(EXTRACT(DAY FROM (br.created_at - bp.created_at))) as days_between
            FROM bot_trade_reviews br
            LEFT JOIN bot_trade_plans bp ON (
                bp.stock_code = br.stock_code
                AND bp.created_at >= br.created_at - interval '7 days'
                AND bp.created_at <= br.created_at
                AND bp.direction = 'buy'
                AND bp.status IN ('executed', 'pending')
            )
            LEFT JOIN market_regimes mr ON (
                TO_DATE(bp.plan_date, 'YYYY-MM-DD')::date >= mr.week_start
                AND TO_DATE(bp.plan_date, 'YYYY-MM-DD')::date <= mr.week_end
            )
            WHERE br.pnl_pct IS NOT NULL
                AND br.pnl_pct <= 0
                AND bp.confidence IS NOT NULL
                AND bp.confidence >= 60.0
            ORDER BY br.id, days_between ASC
            LIMIT 1000
        """)

        results = session.execute(query).fetchall()

        print("\n" + "=" * 150)
        print("TRADES WITH CONFIDENCE >= 60% AND pnl_pct <= 0")
        print("=" * 150)

        if not results:
            print("\n** EXCELLENT NEWS: No trades found with confidence >= 60% and pnl_pct <= 0 **\n")

            # Now show what high-confidence trades DID occur
            high_conf_results = session.execute(text("""
                SELECT DISTINCT ON (br.id)
                    br.id as review_id,
                    br.stock_code,
                    br.stock_name,
                    bp.plan_date,
                    bp.confidence,
                    br.pnl_pct,
                    br.holding_days,
                    br.exit_reason
                FROM bot_trade_reviews br
                LEFT JOIN bot_trade_plans bp ON (
                    bp.stock_code = br.stock_code
                    AND bp.created_at >= br.created_at - interval '7 days'
                    AND bp.created_at <= br.created_at
                    AND bp.direction = 'buy'
                )
                WHERE bp.confidence IS NOT NULL
                    AND bp.confidence >= 60.0
                ORDER BY br.id, ABS(EXTRACT(DAY FROM (br.created_at - bp.created_at))) ASC
                LIMIT 100
            """)).fetchall()

            print(f"\nTotal high-confidence (>=60%) executed trades: {len(high_conf_results)}")
            print(f"Displayed: {min(20, len(high_conf_results))} of {len(high_conf_results)}\n")
            print(f"{'Review':<8} {'Stock':<8} {'PlanDate':<12} {'Conf%':<7} {'PnL%':<8} {'Days':<6} {'Exit':<20}")
            print("-" * 70)

            for row in high_conf_results[:20]:
                review_id, stock_code, stock_name, plan_date, confidence, pnl_pct, holding_days, exit_reason = row
                conf_str = f"{confidence:.1f}" if confidence else "N/A"
                pnl_str = f"{pnl_pct:.2f}%" if pnl_pct else "N/A"
                exit_str = (exit_reason or "N/A")[:20]
                print(f"{review_id:<8} {stock_code:<8} {plan_date or 'N/A':<12} {conf_str:<7} {pnl_str:<8} {holding_days or 0:<6} {exit_str:<20}")

            # Detailed analysis of all high-confidence trades
            print("\n" + "=" * 150)
            print("PERFORMANCE ANALYSIS OF HIGH-CONFIDENCE (>=60%) TRADES")
            print("=" * 150)

            stats = session.execute(text("""
                SELECT
                    COUNT(*) as total_trades,
                    COUNT(*) FILTER (WHERE pnl_pct > 0) as winning_trades,
                    COUNT(*) FILTER (WHERE pnl_pct = 0) as breakeven_trades,
                    COUNT(*) FILTER (WHERE pnl_pct < 0) as losing_trades,
                    ROUND(AVG(confidence)::numeric, 2) as avg_confidence,
                    ROUND(MIN(confidence)::numeric, 2) as min_confidence,
                    ROUND(MAX(confidence)::numeric, 2) as max_confidence,
                    ROUND(AVG(pnl_pct)::numeric, 2) as avg_pnl_pct,
                    ROUND(MIN(pnl_pct)::numeric, 2) as min_pnl_pct,
                    ROUND(MAX(pnl_pct)::numeric, 2) as max_pnl_pct,
                    ROUND(AVG(holding_days)::numeric, 1) as avg_holding_days
                FROM bot_trade_reviews br
                LEFT JOIN bot_trade_plans bp ON (
                    bp.stock_code = br.stock_code
                    AND bp.created_at >= br.created_at - interval '7 days'
                    AND bp.created_at <= br.created_at
                    AND bp.direction = 'buy'
                )
                WHERE bp.confidence IS NOT NULL
                    AND bp.confidence >= 60.0
            """)).fetchone()

            total, wins, breaks, losses, avg_conf, min_conf, max_conf, avg_pnl, min_pnl, max_pnl, avg_days = stats

            print(f"\nTrade Counts:")
            print(f"  Total: {total}")
            print(f"  Winning (PnL > 0): {wins} ({wins*100//total if total else 0}%)")
            print(f"  Break-even (PnL = 0): {breaks} ({breaks*100//total if total else 0}%)")
            print(f"  Losing (PnL < 0): {losses} ({losses*100//total if total else 0}%)")

            print(f"\nConfidence Score:")
            print(f"  Avg: {avg_conf}%")
            print(f"  Range: {min_conf}% - {max_conf}%")

            print(f"\nP&L Distribution:")
            print(f"  Avg P&L: {avg_pnl}%")
            print(f"  Range: {min_pnl}% to {max_pnl}%")

            print(f"\nHolding Duration:")
            print(f"  Avg days: {avg_days}")

            # Show by confidence bands
            print(f"\nPerformance by Confidence Band:")
            band_stats = session.execute(text("""
                SELECT
                    CASE
                        WHEN bp.confidence >= 90 THEN '90%+'
                        WHEN bp.confidence >= 80 THEN '80-89%'
                        WHEN bp.confidence >= 70 THEN '70-79%'
                        WHEN bp.confidence >= 60 THEN '60-69%'
                        ELSE '<60%'
                    END as conf_band,
                    COUNT(*) as count,
                    COUNT(*) FILTER (WHERE br.pnl_pct > 0) as wins,
                    ROUND(AVG(br.pnl_pct)::numeric, 2) as avg_pnl
                FROM bot_trade_reviews br
                LEFT JOIN bot_trade_plans bp ON (
                    bp.stock_code = br.stock_code
                    AND bp.created_at >= br.created_at - interval '7 days'
                    AND bp.created_at <= br.created_at
                    AND bp.direction = 'buy'
                )
                WHERE bp.confidence IS NOT NULL
                    AND bp.confidence >= 60.0
                GROUP BY conf_band
                ORDER BY conf_band DESC
            """)).fetchall()

            for band, count, wins_in_band, avg_pnl_band in band_stats:
                wr = (wins_in_band * 100 // count) if count else 0
                print(f"  {band}: {count} trades, {wins_in_band} wins ({wr}%), avg P&L={avg_pnl_band}%")

            # Show by exit reason
            print(f"\nExit Reasons for High-Confidence Trades:")
            exit_stats = session.execute(text("""
                SELECT
                    br.exit_reason,
                    COUNT(*) as count,
                    COUNT(*) FILTER (WHERE br.pnl_pct > 0) as wins,
                    ROUND(AVG(br.pnl_pct)::numeric, 2) as avg_pnl
                FROM bot_trade_reviews br
                LEFT JOIN bot_trade_plans bp ON (
                    bp.stock_code = br.stock_code
                    AND bp.created_at >= br.created_at - interval '7 days'
                    AND bp.created_at <= br.created_at
                    AND bp.direction = 'buy'
                )
                WHERE bp.confidence IS NOT NULL
                    AND bp.confidence >= 60.0
                GROUP BY br.exit_reason
                ORDER BY count DESC
            """)).fetchall()

            for exit_reason, count, wins_in_reason, avg_pnl_reason in exit_stats:
                wr = (wins_in_reason * 100 // count) if count else 0
                reason_str = (exit_reason or "N/A")
                print(f"  {reason_str}: {count} trades, {wins_in_reason} wins ({wr}%), avg P&L={avg_pnl_reason}%")

            # Confidence metric validation: show aggregate performance by confidence bands
            print(f"\n" + "=" * 150)
            print("CONFIDENCE METRIC VALIDATION: Performance Across All Confidence Levels")
            print("=" * 150)

            val_stats = session.execute(text("""
                WITH stats AS (
                    SELECT
                        CASE
                            WHEN bp.confidence IS NULL THEN 'NULL'
                            WHEN bp.confidence < 20 THEN '<20%'
                            WHEN bp.confidence < 40 THEN '20-40%'
                            WHEN bp.confidence < 60 THEN '40-60%'
                            WHEN bp.confidence < 80 THEN '60-80%'
                            ELSE '80%+'
                        END as conf_band,
                        COUNT(*) as count,
                        COUNT(*) FILTER (WHERE br.pnl_pct > 0) as wins,
                        ROUND(AVG(br.pnl_pct)::numeric, 2) as avg_pnl,
                        ROUND(((COUNT(*) FILTER (WHERE br.pnl_pct > 0))::numeric / COUNT(*) * 100)::numeric, 1) as win_rate
                    FROM bot_trade_reviews br
                    LEFT JOIN bot_trade_plans bp ON (
                        bp.stock_code = br.stock_code
                        AND bp.created_at >= br.created_at - interval '7 days'
                        AND bp.created_at <= br.created_at
                        AND bp.direction = 'buy'
                    )
                    GROUP BY CASE
                        WHEN bp.confidence IS NULL THEN 'NULL'
                        WHEN bp.confidence < 20 THEN '<20%'
                        WHEN bp.confidence < 40 THEN '20-40%'
                        WHEN bp.confidence < 60 THEN '40-60%'
                        WHEN bp.confidence < 80 THEN '60-80%'
                        ELSE '80%+'
                    END
                )
                SELECT conf_band, count, wins, avg_pnl, win_rate FROM stats
                ORDER BY
                    CASE conf_band
                        WHEN 'NULL' THEN 0
                        WHEN '<20%' THEN 1
                        WHEN '20-40%' THEN 2
                        WHEN '40-60%' THEN 3
                        WHEN '60-80%' THEN 4
                        ELSE 5
                    END
            """)).fetchall()

            print(f"\n{'Confidence Band':<20} {'Count':<10} {'Wins':<10} {'Win Rate':<15} {'Avg P&L':<12}")
            print("-" * 70)
            for conf_band, count, wins, avg_pnl, win_rate in val_stats:
                print(f"{conf_band:<20} {count:<10} {wins:<10} {win_rate:.1f}%{'':<9} {avg_pnl}%")

            return

        print(f"Found {len(results)} confidence failures\n")
        print("=" * 150)

        # Collect statistics
        exit_reasons = []
        regimes = []
        confidence_levels = []
        alpha_scores = []
        gamma_scores = []
        pnl_pcts = []
        holding_days_list = []
        regime_changed_counts = defaultdict(int)

        # Print header
        print(f"{'Review':<8} {'Stock':<8} {'PlanDate':<12} {'Conf%':<7} {'Alpha':<8} {'Gamma':<8} "
              f"{'PnL%':<8} {'Days':<6} {'Exit':<20} {'Regime':<18} {'TrendStr':<10} {'Vol':<10}")
        print("=" * 150)

        for row in results:
            review_id, stock_code, stock_name, plan_date, confidence, alpha_score, gamma_score, \
                pnl_pct, holding_days, exit_reason, first_buy_date, last_sell_date, \
                regime, trend_strength, volatility, days_between = row

            # Collect stats
            if confidence:
                confidence_levels.append(confidence)
            if alpha_score:
                alpha_scores.append(alpha_score)
            if gamma_score:
                gamma_scores.append(gamma_score)
            if pnl_pct:
                pnl_pcts.append(pnl_pct)
            if holding_days:
                holding_days_list.append(holding_days)
            if exit_reason:
                exit_reasons.append(exit_reason)
            if regime:
                regimes.append(regime)

            # Format output
            exit_reason_str = (exit_reason or "N/A")[:20]
            regime_str = (regime or "N/A")[:18]
            conf_str = f"{confidence:.1f}" if confidence else "N/A"
            alpha_str = f"{alpha_score:.3f}" if alpha_score else "N/A"
            gamma_str = f"{gamma_score:.3f}" if gamma_score else "N/A"
            pnl_str = f"{pnl_pct:.2f}%"
            trend_str = f"{trend_strength:.3f}" if trend_strength else "N/A"
            vol_str = f"{volatility:.3f}" if volatility else "N/A"

            print(f"{review_id:<8} {stock_code:<8} {plan_date or 'N/A':<12} {conf_str:<7} {alpha_str:<8} "
                  f"{gamma_str:<8} {pnl_str:<8} {holding_days or 0:<6} {exit_reason_str:<20} "
                  f"{regime_str:<18} {trend_str:<10} {vol_str:<10}")

        print("=" * 150)
        print("\n" + "=" * 80)
        print("SUMMARY STATISTICS")
        print("=" * 80)

        if confidence_levels:
            print(f"\nConfidence Levels (N={len(confidence_levels)}):")
            print(f"  Min: {min(confidence_levels):.1f}%")
            print(f"  Max: {max(confidence_levels):.1f}%")
            print(f"  Avg: {sum(confidence_levels) / len(confidence_levels):.1f}%")

        if pnl_pcts:
            print(f"\nP&L % (N={len(pnl_pcts)}):")
            print(f"  Min: {min(pnl_pcts):.2f}%")
            print(f"  Max: {max(pnl_pcts):.2f}%")
            print(f"  Avg: {sum(pnl_pcts) / len(pnl_pcts):.2f}%")

        if alpha_scores:
            print(f"\nAlpha Scores (N={len(alpha_scores)}):")
            print(f"  Min: {min(alpha_scores):.3f}")
            print(f"  Max: {max(alpha_scores):.3f}")
            print(f"  Avg: {sum(alpha_scores) / len(alpha_scores):.3f}")

        if gamma_scores:
            print(f"\nGamma Scores (N={len(gamma_scores)}):")
            print(f"  Min: {min(gamma_scores):.3f}")
            print(f"  Max: {max(gamma_scores):.3f}")
            print(f"  Avg: {sum(gamma_scores) / len(gamma_scores):.3f}")

        if holding_days_list:
            print(f"\nHolding Days (N={len(holding_days_list)}):")
            print(f"  Min: {min(holding_days_list)}")
            print(f"  Max: {max(holding_days_list)}")
            print(f"  Avg: {sum(holding_days_list) / len(holding_days_list):.1f}")

        if exit_reasons:
            print(f"\nExit Reasons (N={len(exit_reasons)}):")
            reason_counts = Counter(exit_reasons)
            for reason, count in reason_counts.most_common(10):
                pct = (count / len(exit_reasons)) * 100
                print(f"  {reason}: {count} ({pct:.1f}%)")

        if regimes:
            print(f"\nMarket Regimes (N={len(regimes)}):")
            regime_counts = Counter(regimes)
            for regime, count in regime_counts.most_common(10):
                pct = (count / len(regimes)) * 100
                print(f"  {regime}: {count} ({pct:.1f}%)")

        # Analyze correlation: low confidence_levels with bad exit_reason?
        if confidence_levels and exit_reasons:
            print(f"\n\nANALYSIS: Confidence Ranges vs Exit Reasons")
            print("-" * 80)

            conf_ranges = {
                "60-70%": [r for r, c in zip(exit_reasons, confidence_levels) if 60 <= c < 70],
                "70-80%": [r for r, c in zip(exit_reasons, confidence_levels) if 70 <= c < 80],
                "80-90%": [r for r, c in zip(exit_reasons, confidence_levels) if 80 <= c < 90],
                "90%+": [r for r, c in zip(exit_reasons, confidence_levels) if c >= 90],
            }

            for conf_range, reasons in conf_ranges.items():
                if reasons:
                    reason_dist = Counter(reasons)
                    print(f"\n{conf_range} (N={len(reasons)}):")
                    for reason, count in reason_dist.most_common(5):
                        pct = (count / len(reasons)) * 100
                        print(f"    {reason}: {pct:.1f}%")

    finally:
        session.close()


if __name__ == "__main__":
    main()
