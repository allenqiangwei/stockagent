"""Label building and XGBoost model training."""

from enum import IntEnum
from typing import Optional
import os

import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split


class SignalLabel(IntEnum):
    """5-class labels for supervised learning.

    Labels based on forward N-day returns:
    - STRONG_SELL (0): Return < -5%
    - WEAK_SELL (1): Return -5% to -2%
    - HOLD (2): Return -2% to +2%
    - WEAK_BUY (3): Return +2% to +5%
    - STRONG_BUY (4): Return > +5%
    """
    STRONG_SELL = 0
    WEAK_SELL = 1
    HOLD = 2
    WEAK_BUY = 3
    STRONG_BUY = 4


class LabelBuilder:
    """Creates labels from forward returns for supervised learning.

    Labels are based on N-day forward returns:
    - STRONG_BUY: return > strong_buy_threshold
    - WEAK_BUY: weak_buy_threshold < return <= strong_buy_threshold
    - HOLD: weak_sell_threshold < return <= weak_buy_threshold
    - WEAK_SELL: strong_sell_threshold < return <= weak_sell_threshold
    - STRONG_SELL: return <= strong_sell_threshold

    Usage:
        builder = LabelBuilder()
        labels = builder.create_labels(df, forward_days=5)
    """

    def __init__(
        self,
        strong_buy_threshold: float = 5.0,
        weak_buy_threshold: float = 2.0,
        weak_sell_threshold: float = -2.0,
        strong_sell_threshold: float = -5.0
    ):
        """Initialize label builder.

        Args:
            strong_buy_threshold: Min return % for STRONG_BUY (default: 5%)
            weak_buy_threshold: Min return % for WEAK_BUY (default: 2%)
            weak_sell_threshold: Max return % for WEAK_SELL (default: -2%)
            strong_sell_threshold: Max return % for STRONG_SELL (default: -5%)
        """
        self.strong_buy_threshold = strong_buy_threshold
        self.weak_buy_threshold = weak_buy_threshold
        self.weak_sell_threshold = weak_sell_threshold
        self.strong_sell_threshold = strong_sell_threshold

    def calculate_forward_returns(
        self,
        df: pd.DataFrame,
        forward_days: int = 5
    ) -> pd.Series:
        """Calculate forward N-day returns.

        Args:
            df: DataFrame with 'close' column
            forward_days: Number of days forward to calculate return

        Returns:
            Series of forward returns in percentage
        """
        close = df["close"]
        future_close = close.shift(-forward_days)
        forward_return = (future_close - close) / close * 100
        return forward_return

    def create_labels(
        self,
        df: pd.DataFrame,
        forward_days: int = 5
    ) -> pd.Series:
        """Create classification labels from forward returns.

        Args:
            df: DataFrame with 'close' column
            forward_days: Number of days forward for return calculation

        Returns:
            Series of SignalLabel values (0-4), NaN for last forward_days rows
        """
        forward_returns = self.calculate_forward_returns(df, forward_days)

        labels = pd.Series(index=df.index, dtype=float)

        labels[forward_returns > self.strong_buy_threshold] = SignalLabel.STRONG_BUY
        labels[
            (forward_returns > self.weak_buy_threshold) &
            (forward_returns <= self.strong_buy_threshold)
        ] = SignalLabel.WEAK_BUY
        labels[
            (forward_returns > self.weak_sell_threshold) &
            (forward_returns <= self.weak_buy_threshold)
        ] = SignalLabel.HOLD
        labels[
            (forward_returns > self.strong_sell_threshold) &
            (forward_returns <= self.weak_sell_threshold)
        ] = SignalLabel.WEAK_SELL
        labels[forward_returns <= self.strong_sell_threshold] = SignalLabel.STRONG_SELL

        return labels


class XGBoostTrainer:
    """XGBoost model for 5-class signal prediction.

    Trains a multi-class classifier to predict signal strength
    from technical indicator features.

    Output is converted to a 0-100 score based on class probabilities:
    - score = sum(class_prob * class_value * 25)

    Usage:
        trainer = XGBoostTrainer()
        trainer.train(X_train, y_train)
        scores = trainer.predict(X_test)
        trainer.save("models/xgb_model.json")
    """

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 5,
        learning_rate: float = 0.1,
        random_state: int = 42
    ):
        """Initialize XGBoost trainer.

        Args:
            n_estimators: Number of boosting rounds (default: 100)
            max_depth: Max tree depth (default: 5)
            learning_rate: Learning rate (default: 0.1)
            random_state: Random seed for reproducibility
        """
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.random_state = random_state
        self.model: Optional[xgb.XGBClassifier] = None
        self.feature_names: Optional[list[str]] = None

    def train(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        eval_size: float = 0.2
    ) -> dict:
        """Train the XGBoost model.

        Args:
            X: Feature DataFrame
            y: Label Series (SignalLabel values 0-4)
            eval_size: Fraction of data for validation (default: 0.2)

        Returns:
            Dict with training metrics
        """
        self.feature_names = list(X.columns)

        # Split for evaluation
        X_train, X_eval, y_train, y_eval = train_test_split(
            X, y,
            test_size=eval_size,
            random_state=self.random_state,
            stratify=y
        )

        # Initialize model
        self.model = xgb.XGBClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            random_state=self.random_state,
            objective="multi:softprob",
            num_class=5,
            eval_metric="mlogloss"
        )

        # Train with early stopping
        self.model.fit(
            X_train, y_train,
            eval_set=[(X_eval, y_eval)],
            verbose=False
        )

        # Calculate metrics
        train_score = self.model.score(X_train, y_train)
        eval_score = self.model.score(X_eval, y_eval)

        return {
            "train_accuracy": train_score,
            "eval_accuracy": eval_score,
            "n_samples": len(X),
            "n_features": len(self.feature_names)
        }

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict scores (0-100) for samples.

        Converts class probabilities to a weighted score:
        score = sum(prob[i] * i * 25) for i in 0..4

        This maps:
        - Pure STRONG_SELL -> 0
        - Pure STRONG_BUY -> 100
        - Uncertain/mixed -> 50

        Args:
            X: Feature DataFrame

        Returns:
            Array of scores in [0, 100] range
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")

        probas = self.model.predict_proba(X)

        # Weighted sum: class 0 -> 0, class 4 -> 100
        class_weights = np.array([0, 25, 50, 75, 100])
        scores = np.dot(probas, class_weights)

        return scores

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Predict class probabilities.

        Args:
            X: Feature DataFrame

        Returns:
            Array of shape (n_samples, 5) with class probabilities
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")

        return self.model.predict_proba(X)

    def get_feature_importance(self) -> dict[str, float]:
        """Get feature importance scores.

        Returns:
            Dict mapping feature name to importance score
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")

        importance = self.model.feature_importances_
        return dict(zip(self.feature_names, importance))

    def save(self, path: str) -> None:
        """Save model to file.

        Args:
            path: Path to save model (should end with .json)
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")

        # Ensure directory exists
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        self.model.save_model(path)

    def load(self, path: str) -> None:
        """Load model from file.

        Args:
            path: Path to model file
        """
        self.model = xgb.XGBClassifier()
        self.model.load_model(path)
