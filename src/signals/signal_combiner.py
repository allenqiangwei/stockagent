"""Signal combiner: rule-engine driven multi-strategy signal generation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any

import pandas as pd

from .base_signal import SignalLevel, score_to_signal_level
from .rule_engine import evaluate_rules, evaluate_conditions, collect_indicator_params
from .action_signal import ActionSignal, SignalAction, SellReason, ExitConfig


@dataclass
class CombinedSignal:
    """Combined signal from multiple strategies.

    Attributes:
        stock_code: Stock identifier
        stock_name: Stock name (e.g. 平安银行)
        trade_date: Date of the signal
        final_score: Weighted combined score (0-100)
        signal_level: Final signal classification
        swing_score: Score from first strategy (backward compat)
        trend_score: Score from second strategy (backward compat)
        ml_score: Score from ML model (optional)
        sentiment_score: Market sentiment score from news (optional)
        reasons: List of reasons from contributing strategies
        strategy_scores: Dict of strategy_name -> score (new)
    """
    stock_code: str
    trade_date: str
    final_score: float
    signal_level: SignalLevel
    swing_score: float
    trend_score: float
    ml_score: Optional[float]
    stock_name: str = ""
    sentiment_score: Optional[float] = None
    reasons: list[str] = field(default_factory=list)
    strategy_scores: dict = field(default_factory=dict)


def _load_strategies() -> List[Dict[str, Any]]:
    """从数据库加载所有启用的策略"""
    try:
        from src.data_storage.database import Database
        db_path = Path(__file__).parent.parent.parent / "data" / "stockagent.db"
        db = Database(str(db_path))
        db.init_tables()
        db.seed_default_indicators_and_strategies()
        strategies = db.get_all_strategies()
        return [s for s in strategies if s.get("enabled")]
    except Exception:
        return []


class SignalCombiner:
    """Combines signals from rule-based strategies with configurable weights.

    Strategies and their rules are loaded from the database.
    Each strategy's rules are evaluated by the rule engine,
    producing a score (0-100). Strategy scores are then
    weighted and combined with optional ML/sentiment scores.

    Usage:
        combiner = SignalCombiner()
        signal = combiner.combine(df, "000001", "2024-01-15")
    """

    def __init__(
        self,
        ml_weight: float = 0.25,
        sentiment_weight: float = 0.15
    ):
        self.ml_weight = ml_weight
        self.sentiment_weight = sentiment_weight
        self._strategies = _load_strategies()
        self._indicator_config = None

    def get_indicator_config(self):
        """获取所有策略规则所需的 IndicatorConfig。

        汇总所有启用策略的规则，提取需要计算的指标参数组合，
        返回可传给 IndicatorCalculator 的配置对象。
        """
        if self._indicator_config is not None:
            return self._indicator_config

        from src.indicators.indicator_calculator import IndicatorConfig

        all_rules = []
        for strategy in self._strategies:
            all_rules.extend(strategy.get("rules", []))
            all_rules.extend(strategy.get("buy_conditions", []))
            all_rules.extend(strategy.get("sell_conditions", []))

        if not all_rules:
            self._indicator_config = IndicatorConfig()
            return self._indicator_config

        collected = collect_indicator_params(all_rules)
        self._indicator_config = IndicatorConfig.from_collected_params(collected)
        return self._indicator_config

    def combine(
        self,
        df: pd.DataFrame,
        stock_code: str,
        trade_date: str,
        ml_score: Optional[float] = None,
        sentiment_score: Optional[float] = None,
        market_regime=None
    ) -> CombinedSignal:
        """Combine signals from all strategies.

        Args:
            df: DataFrame with OHLCV and indicator columns
            stock_code: Stock identifier
            trade_date: Date for the signal
            ml_score: Optional ML model score (0-100)
            sentiment_score: Optional market sentiment score (0-100)
            market_regime: Optional MarketRegime for adaptive weights

        Returns:
            CombinedSignal with weighted final score
        """
        # 用规则引擎评估每个策略
        strategy_results = []  # [(name, score, weight, reasons)]

        for strategy in self._strategies:
            rules = strategy.get("rules", [])
            weight = strategy.get("weight", 0.5)
            name = strategy.get("name", "未命名")

            score, reasons = evaluate_rules(rules, df)
            strategy_results.append((name, score, weight, reasons))

        # 收集策略得分和权重
        scores = []
        weights = []
        all_reasons = []
        strategy_scores = {}

        for name, score, weight, reasons in strategy_results:
            scores.append(score)
            weights.append(weight)
            strategy_scores[name] = score

            # 只收集有显著信号的原因
            if score > 60 or score < 40:
                for r in reasons:
                    all_reasons.append(f"[{name}] {r}")

        # 市场状态自适应（如果提供且有2个策略）
        if market_regime is not None and len(weights) >= 2:
            weights[0] = market_regime.swing_weight
            weights[1] = market_regime.trend_weight

        # ML/情绪得分
        if ml_score is not None:
            scores.append(ml_score)
            weights.append(self.ml_weight)

        if sentiment_score is not None:
            scores.append(sentiment_score)
            weights.append(self.sentiment_weight)
            if sentiment_score > 60:
                all_reasons.append(f"[情绪] 市场情绪偏多 ({sentiment_score:.0f})")
            elif sentiment_score < 40:
                all_reasons.append(f"[情绪] 市场情绪偏空 ({sentiment_score:.0f})")

        # 市场状态原因
        if market_regime is not None and len(weights) >= 2:
            all_reasons.append(
                f"[市场] {market_regime.regime_label} "
                f"(策略1 {weights[0]:.0%}/策略2 {weights[1]:.0%})"
            )

        # 归一化权重并计算最终得分
        if scores:
            total_weight = sum(weights)
            if total_weight > 0:
                final_score = sum(s * w / total_weight for s, w in zip(scores, weights))
            else:
                final_score = 50.0
        else:
            final_score = 50.0

        # 向后兼容：swing_score/trend_score 取前两个策略
        swing_score = strategy_results[0][1] if len(strategy_results) > 0 else 50.0
        trend_score = strategy_results[1][1] if len(strategy_results) > 1 else 50.0

        return CombinedSignal(
            stock_code=stock_code,
            trade_date=trade_date,
            final_score=final_score,
            signal_level=score_to_signal_level(final_score),
            swing_score=swing_score,
            trend_score=trend_score,
            ml_score=ml_score,
            sentiment_score=sentiment_score,
            reasons=all_reasons,
            strategy_scores=strategy_scores
        )

    def combine_batch(
        self,
        stock_data: dict[str, pd.DataFrame],
        trade_date: str,
        ml_scores: Optional[dict[str, float]] = None,
        sentiment_score: Optional[float] = None,
        market_regime=None
    ) -> list[CombinedSignal]:
        """Combine signals for multiple stocks."""
        ml_scores = ml_scores or {}
        results = []

        for stock_code, df in stock_data.items():
            ml_score = ml_scores.get(stock_code)
            signal = self.combine(
                df, stock_code, trade_date,
                ml_score=ml_score,
                sentiment_score=sentiment_score,
                market_regime=market_regime
            )
            results.append(signal)

        return results

    def generate_action_signals(
        self,
        df: pd.DataFrame,
        stock_code: str,
        trade_date: str,
        combined_signal: Optional[CombinedSignal] = None,
    ) -> List[ActionSignal]:
        """检查所有策略的买入/卖出触发条件，生成动作信号

        Args:
            df: DataFrame with OHLCV and indicator columns
            stock_code: Stock identifier
            trade_date: Date for the signal
            combined_signal: 已有的打分信号（用于填充 confidence_score）

        Returns:
            List of ActionSignal (可能为空、一个或多个)
        """
        action_signals = []
        confidence = combined_signal.final_score if combined_signal else 50.0

        for strategy in self._strategies:
            name = strategy.get("name", "未命名")

            # 检查买入条件 (AND 逻辑)
            buy_conds = strategy.get("buy_conditions", [])
            if buy_conds:
                triggered, labels = evaluate_conditions(buy_conds, df, mode="AND")
                if triggered:
                    # 读取策略级别的退出配置
                    exit_cfg_raw = strategy.get("exit_config", {})
                    exit_config = ExitConfig(
                        stop_loss_pct=exit_cfg_raw.get("stop_loss_pct"),
                        take_profit_pct=exit_cfg_raw.get("take_profit_pct"),
                        max_hold_days=exit_cfg_raw.get("max_hold_days"),
                    ) if exit_cfg_raw else None

                    action_signals.append(ActionSignal(
                        stock_code=stock_code,
                        trade_date=trade_date,
                        action=SignalAction.BUY,
                        strategy_name=name,
                        confidence_score=confidence,
                        exit_config=exit_config,
                        trigger_rules=labels,
                        reasons=[f"[{name}] {l}" for l in labels],
                    ))

            # 检查卖出条件 (OR 逻辑)
            sell_conds = strategy.get("sell_conditions", [])
            if sell_conds:
                triggered, labels = evaluate_conditions(sell_conds, df, mode="OR")
                if triggered:
                    action_signals.append(ActionSignal(
                        stock_code=stock_code,
                        trade_date=trade_date,
                        action=SignalAction.SELL,
                        strategy_name=name,
                        confidence_score=confidence,
                        sell_reason=SellReason.STRATEGY_EXIT,
                        trigger_rules=labels,
                        reasons=[f"[{name}] {l}" for l in labels],
                    ))

        return action_signals
