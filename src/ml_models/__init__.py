"""Machine learning models for signal enhancement.

Provides:
- FeatureEngineer: Creates ML features from indicators
- LabelBuilder: Creates 5-class labels from forward returns
- XGBoostTrainer: Trains and predicts using XGBoost
"""

from .feature_engineer import FeatureEngineer
from .model_trainer import LabelBuilder, XGBoostTrainer, SignalLabel

__all__ = [
    "FeatureEngineer",
    "LabelBuilder",
    "XGBoostTrainer",
    "SignalLabel",
]
