"""Confidence score model persistence."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Integer, Float, DateTime
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ConfidenceModel(Base):
    """Persisted Logistic Regression model for trade confidence scoring.

    Model params (coef, intercept, scaler_mean, scaler_scale) are stored as
    JSON — no binary serialization needed.
    """

    __tablename__ = "confidence_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    model_params: Mapped[dict] = mapped_column(JSON)  # {coef, intercept, scaler_mean, scaler_scale}
    feature_names: Mapped[list] = mapped_column(JSON)
    auc_score: Mapped[float] = mapped_column(Float, default=0.5)
    brier_score: Mapped[float] = mapped_column(Float, default=0.25)
    training_samples: Mapped[int] = mapped_column(Integer, default=0)
    positive_rate: Mapped[float] = mapped_column(Float, default=0.5)
    calibration_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
