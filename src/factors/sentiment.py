"""Sentiment factors: NEWS_SENTIMENT."""

import numpy as np
import pandas as pd

from .registry import register_factor


@register_factor(
    name="NEWS_SENTIMENT",
    label="新闻情绪",
    sub_fields=[
        ("NEWS_SENTIMENT_3D", "3日新闻情绪"),
        ("NEWS_SENTIMENT_7D", "7日新闻情绪"),
    ],
    params={},
    field_ranges={
        "NEWS_SENTIMENT_3D": (-1.0, 1.0),
        "NEWS_SENTIMENT_7D": (-1.0, 1.0),
    },
    category="sentiment",
)
def compute_news_sentiment(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    return pd.DataFrame({
        "NEWS_SENTIMENT_3D": pd.Series(np.nan, index=df.index),
        "NEWS_SENTIMENT_7D": pd.Series(np.nan, index=df.index),
    })
