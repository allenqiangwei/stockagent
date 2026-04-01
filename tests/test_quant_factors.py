"""Tests for the 8 P0 quantitative factor groups (26 sub-fields).

Each factor is tested for:
- Correct column naming
- Correct output shape
- Value sanity (non-all-NaN, expected ranges)
- Division-by-zero safety
"""

import numpy as np
import pandas as pd
import pytest

from api.services.indicator_registry import (
    EXTENDED_INDICATORS,
    _COMPUTE_FUNCTIONS,
    compute_extended_indicator,
    get_extended_field_group,
    resolve_extended_column,
)


def _make_df(n: int = 60, seed: int = 42) -> pd.DataFrame:
    """Create a realistic OHLCV DataFrame for testing."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2025-01-01", periods=n)
    close = 10.0 + np.cumsum(rng.randn(n) * 0.3)
    close = np.maximum(close, 1.0)  # keep positive
    high = close + rng.uniform(0.1, 0.5, n)
    low = close - rng.uniform(0.1, 0.5, n)
    low = np.maximum(low, 0.5)
    opn = low + (high - low) * rng.uniform(0.2, 0.8, n)
    volume = rng.randint(100_000, 1_000_000, n).astype(float)
    amount = volume * close * rng.uniform(0.9, 1.1, n)
    return pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close,
         "volume": volume, "amount": amount},
        index=dates,
    )


# ── Registry metadata tests ──────────────────────────────

QUANT_FACTORS = ["MOM", "REALVOL", "KBAR", "PVOL", "LIQ", "PPOS", "RSTR", "AMPVOL"]


@pytest.mark.parametrize("group", QUANT_FACTORS)
def test_extended_indicators_entry(group):
    """Each factor must be in EXTENDED_INDICATORS with required keys."""
    assert group in EXTENDED_INDICATORS
    meta = EXTENDED_INDICATORS[group]
    assert "label" in meta
    assert "sub_fields" in meta
    assert "params" in meta
    assert len(meta["sub_fields"]) > 0


@pytest.mark.parametrize("group", QUANT_FACTORS)
def test_compute_function_registered(group):
    """Each factor must have a compute function in _COMPUTE_FUNCTIONS."""
    assert group in _COMPUTE_FUNCTIONS


@pytest.mark.parametrize("group", QUANT_FACTORS)
def test_get_extended_field_group(group):
    """All sub_fields must resolve back to their group."""
    meta = EXTENDED_INDICATORS[group]
    for sub_field, _ in meta["sub_fields"]:
        assert get_extended_field_group(sub_field) == group


# ── MOM ──────────────────────────────────────────────────

class TestMOM:
    def test_columns_and_shape(self):
        df = _make_df()
        result = compute_extended_indicator(df, "MOM", {"period": 10})
        assert "MOM_10" in result.columns
        assert len(result) == len(df)

    def test_default_params(self):
        df = _make_df()
        result = compute_extended_indicator(df, "MOM")
        assert "MOM_20" in result.columns

    def test_values_sane(self):
        df = _make_df()
        result = compute_extended_indicator(df, "MOM", {"period": 5})
        vals = result["MOM_5"].dropna()
        assert len(vals) > 0
        # MOM is percentage change, should not be all zeros
        assert not (vals == 0).all()

    def test_first_n_rows_nan(self):
        df = _make_df()
        result = compute_extended_indicator(df, "MOM", {"period": 10})
        assert result["MOM_10"].iloc[:10].isna().all()

    def test_resolve_column(self):
        col = resolve_extended_column("MOM", {"period": 15})
        assert col == "MOM_15"


# ── REALVOL ──────────────────────────────────────────────

class TestREALVOL:
    def test_columns_and_shape(self):
        df = _make_df()
        result = compute_extended_indicator(df, "REALVOL", {"period": 10})
        expected_cols = {"REALVOL_10", "REALVOL_skew_10", "REALVOL_kurt_10",
                         "REALVOL_downside_10"}
        assert expected_cols == set(result.columns)
        assert len(result) == len(df)

    def test_values_sane(self):
        df = _make_df()
        result = compute_extended_indicator(df, "REALVOL", {"period": 10})
        vol = result["REALVOL_10"].dropna()
        assert len(vol) > 0
        assert (vol >= 0).all()  # volatility is non-negative

    def test_downside_vol_nonneg(self):
        df = _make_df()
        result = compute_extended_indicator(df, "REALVOL", {"period": 10})
        ds = result["REALVOL_downside_10"].dropna()
        assert len(ds) > 0
        assert (ds >= 0).all()

    def test_resolve_column(self):
        col = resolve_extended_column("REALVOL_skew", {"period": 20})
        assert col == "REALVOL_skew_20"


# ── KBAR ─────────────────────────────────────────────────

class TestKBAR:
    def test_columns_and_shape(self):
        df = _make_df()
        result = compute_extended_indicator(df, "KBAR")
        expected_cols = {"KBAR_upper_shadow", "KBAR_lower_shadow",
                         "KBAR_body_ratio", "KBAR_amplitude",
                         "KBAR_overnight_ret", "KBAR_intraday_ret"}
        assert expected_cols == set(result.columns)
        assert len(result) == len(df)

    def test_no_param_suffix(self):
        """KBAR has no params, so columns should not have numeric suffixes."""
        df = _make_df()
        result = compute_extended_indicator(df, "KBAR")
        for col in result.columns:
            # No _N suffix expected
            assert col in {"KBAR_upper_shadow", "KBAR_lower_shadow",
                           "KBAR_body_ratio", "KBAR_amplitude",
                           "KBAR_overnight_ret", "KBAR_intraday_ret"}

    def test_shadow_ratios_bounded(self):
        df = _make_df()
        result = compute_extended_indicator(df, "KBAR")
        for col in ["KBAR_upper_shadow", "KBAR_lower_shadow", "KBAR_body_ratio"]:
            vals = result[col].dropna()
            assert (vals >= 0).all()
            assert (vals <= 1.0001).all()  # floating point tolerance

    def test_shadow_plus_body_equals_one(self):
        """upper_shadow + lower_shadow + body_ratio should sum to ~1."""
        df = _make_df()
        result = compute_extended_indicator(df, "KBAR")
        total = (result["KBAR_upper_shadow"] + result["KBAR_lower_shadow"]
                 + result["KBAR_body_ratio"]).dropna()
        np.testing.assert_allclose(total.values, 1.0, atol=1e-10)

    def test_overnight_ret_first_nan(self):
        df = _make_df()
        result = compute_extended_indicator(df, "KBAR")
        assert pd.isna(result["KBAR_overnight_ret"].iloc[0])

    def test_resolve_column(self):
        col = resolve_extended_column("KBAR_amplitude")
        assert col == "KBAR_amplitude"


# ── PVOL ─────────────────────────────────────────────────

class TestPVOL:
    def test_columns_and_shape(self):
        df = _make_df()
        result = compute_extended_indicator(df, "PVOL", {"period": 10})
        expected_cols = {"PVOL_corr_10", "PVOL_amount_conc_10", "PVOL_vwap_bias_10"}
        assert expected_cols == set(result.columns)
        assert len(result) == len(df)

    def test_corr_bounded(self):
        df = _make_df()
        result = compute_extended_indicator(df, "PVOL", {"period": 10})
        corr = result["PVOL_corr_10"].dropna()
        assert (corr >= -1.001).all()
        assert (corr <= 1.001).all()

    def test_amount_conc_bounded(self):
        df = _make_df()
        result = compute_extended_indicator(df, "PVOL", {"period": 10})
        conc = result["PVOL_amount_conc_10"].dropna()
        assert (conc >= 0).all()
        assert (conc <= 1.001).all()

    def test_resolve_column(self):
        col = resolve_extended_column("PVOL_vwap_bias", {"period": 20})
        assert col == "PVOL_vwap_bias_20"


# ── LIQ ──────────────────────────────────────────────────

class TestLIQ:
    def test_columns_and_shape(self):
        df = _make_df()
        result = compute_extended_indicator(df, "LIQ", {"period": 10})
        expected_cols = {"LIQ_amihud_10", "LIQ_turnover_vol_10", "LIQ_log_amount_10"}
        assert expected_cols == set(result.columns)
        assert len(result) == len(df)

    def test_amihud_nonneg(self):
        df = _make_df()
        result = compute_extended_indicator(df, "LIQ", {"period": 10})
        amihud = result["LIQ_amihud_10"].dropna()
        assert (amihud >= 0).all()

    def test_log_amount_nonneg(self):
        df = _make_df()
        result = compute_extended_indicator(df, "LIQ", {"period": 10})
        log_amt = result["LIQ_log_amount_10"].dropna()
        assert (log_amt >= 0).all()

    def test_resolve_column(self):
        col = resolve_extended_column("LIQ_amihud", {"period": 20})
        assert col == "LIQ_amihud_20"


# ── PPOS ─────────────────────────────────────────────────

class TestPPOS:
    def test_columns_and_shape(self):
        df = _make_df()
        result = compute_extended_indicator(df, "PPOS", {"period": 10})
        expected_cols = {"PPOS_close_pos_10", "PPOS_high_dist_10",
                         "PPOS_low_dist_10", "PPOS_drawdown_10",
                         "PPOS_consec_dir_10"}
        assert expected_cols == set(result.columns)
        assert len(result) == len(df)

    def test_close_pos_bounded(self):
        df = _make_df()
        result = compute_extended_indicator(df, "PPOS", {"period": 10})
        cp = result["PPOS_close_pos_10"].dropna()
        assert (cp >= -0.001).all()
        assert (cp <= 1.001).all()

    def test_high_dist_nonpositive(self):
        df = _make_df()
        result = compute_extended_indicator(df, "PPOS", {"period": 10})
        hd = result["PPOS_high_dist_10"].dropna()
        assert (hd <= 0.001).all()  # close <= rolling high

    def test_drawdown_nonpositive(self):
        df = _make_df()
        result = compute_extended_indicator(df, "PPOS", {"period": 10})
        dd = result["PPOS_drawdown_10"].dropna()
        assert (dd <= 0.001).all()

    def test_consec_dir_integer_like(self):
        df = _make_df()
        result = compute_extended_indicator(df, "PPOS", {"period": 10})
        cd = result["PPOS_consec_dir_10"].dropna()
        np.testing.assert_array_equal(cd.values, cd.values.astype(int))

    def test_resolve_column(self):
        col = resolve_extended_column("PPOS_drawdown", {"period": 20})
        assert col == "PPOS_drawdown_20"


# ── RSTR ─────────────────────────────────────────────────

class TestRSTR:
    def test_columns_and_shape(self):
        df = _make_df()
        result = compute_extended_indicator(df, "RSTR", {"period": 10})
        expected_cols = {"RSTR_10", "RSTR_weighted_10"}
        assert expected_cols == set(result.columns)
        assert len(result) == len(df)

    def test_values_sane(self):
        df = _make_df()
        result = compute_extended_indicator(df, "RSTR", {"period": 10})
        rstr = result["RSTR_10"].dropna()
        assert len(rstr) > 0

    def test_weighted_has_values(self):
        df = _make_df()
        result = compute_extended_indicator(df, "RSTR", {"period": 10})
        w = result["RSTR_weighted_10"].dropna()
        assert len(w) > 0

    def test_resolve_column(self):
        col = resolve_extended_column("RSTR_weighted", {"period": 20})
        assert col == "RSTR_weighted_20"


# ── AMPVOL ───────────────────────────────────────────────

class TestAMPVOL:
    def test_columns_and_shape(self):
        df = _make_df()
        result = compute_extended_indicator(df, "AMPVOL", {"period": 5})
        expected_cols = {"AMPVOL_std_5", "AMPVOL_parkinson_5"}
        assert expected_cols == set(result.columns)
        assert len(result) == len(df)

    def test_values_nonneg(self):
        df = _make_df()
        result = compute_extended_indicator(df, "AMPVOL", {"period": 5})
        for col in result.columns:
            vals = result[col].dropna()
            assert (vals >= 0).all()

    def test_resolve_column(self):
        col = resolve_extended_column("AMPVOL_parkinson", {"period": 5})
        assert col == "AMPVOL_parkinson_5"


# ── Division-by-zero safety ──────────────────────────────

class TestDivisionByZero:
    """Factors must not raise on degenerate data (zero prices/volume)."""

    def _make_zero_df(self) -> pd.DataFrame:
        """Create a DataFrame with some zero values."""
        df = _make_df(n=30)
        df.iloc[5, df.columns.get_loc("volume")] = 0
        df.iloc[6, df.columns.get_loc("amount")] = 0
        return df

    @pytest.mark.parametrize("group", QUANT_FACTORS)
    def test_no_raise_on_zero(self, group):
        """Compute should not raise on zero-containing data."""
        df = self._make_zero_df()
        # Should not raise
        result = compute_extended_indicator(df, group)
        assert len(result) == len(df)


# ── FIELD_RANGES integration ─────────────────────────────

class TestFieldRanges:
    """Verify all quantitative factor sub-fields have FIELD_RANGES entries."""

    def test_all_fields_have_ranges(self):
        from src.signals.rule_engine import FIELD_RANGES
        for group in QUANT_FACTORS:
            meta = EXTENDED_INDICATORS[group]
            for sub_field, _ in meta["sub_fields"]:
                assert sub_field in FIELD_RANGES, (
                    f"Missing FIELD_RANGES entry for {sub_field}"
                )

    def test_field_range_lookup(self):
        """Parametrized column names should resolve via prefix matching."""
        from src.signals.rule_engine import _get_field_range
        # Parametrized fields
        assert _get_field_range("MOM_20") == (-100, 500)
        assert _get_field_range("REALVOL_10") == (0, 30)
        assert _get_field_range("REALVOL_skew_10") == (-5, 5)
        assert _get_field_range("PVOL_corr_20") == (-1, 1)
        assert _get_field_range("LIQ_amihud_20") == (0, 100)
        assert _get_field_range("PPOS_close_pos_20") == (0, 1)
        assert _get_field_range("RSTR_weighted_20") == (-10, 10)
        assert _get_field_range("AMPVOL_parkinson_5") == (0, 20)
        # Non-parametrized
        assert _get_field_range("KBAR_upper_shadow") == (0, 1)
        assert _get_field_range("KBAR_amplitude") == (0, 0.3)


# ── Integration tests: backtest pipeline ────────────────

def test_factors_in_backtest_conditions():
    """Verify new factors can be used in buy_conditions and evaluated."""
    from src.signals.rule_engine import evaluate_conditions, collect_indicator_params
    from src.indicators.indicator_calculator import IndicatorConfig, IndicatorCalculator

    df = _make_df(60)

    buy_conditions = [
        {"field": "MOM", "operator": ">", "compare_type": "value",
         "compare_value": 0, "params": {"period": 5}},
        {"field": "PPOS_close_pos", "operator": "<", "compare_type": "value",
         "compare_value": 0.5, "params": {"period": 20}},
        {"field": "REALVOL", "operator": "<", "compare_type": "value",
         "compare_value": 5, "params": {"period": 20}},
    ]

    collected = collect_indicator_params(buy_conditions)
    config = IndicatorConfig.from_collected_params(collected)
    calculator = IndicatorCalculator(config)
    indicators = calculator.calculate_all(df)
    df_full = pd.concat([df, indicators], axis=1)

    assert "MOM_5" in df_full.columns
    assert "PPOS_close_pos_20" in df_full.columns
    assert "REALVOL_20" in df_full.columns

    triggered, labels = evaluate_conditions(buy_conditions, df_full, mode="AND")
    assert isinstance(triggered, bool)


def test_factors_vectorize():
    """Verify new factors work with vectorized signal generation."""
    from src.signals.rule_engine import collect_indicator_params
    from src.indicators.indicator_calculator import IndicatorConfig, IndicatorCalculator
    from src.backtest.vectorized_signals import vectorize_conditions

    df = _make_df(60)

    conditions = [
        {"field": "MOM", "operator": ">", "compare_type": "value",
         "compare_value": 0, "params": {"period": 20}},
    ]

    collected = collect_indicator_params(conditions)
    config = IndicatorConfig.from_collected_params(collected)
    calculator = IndicatorCalculator(config)
    indicators = calculator.calculate_all(df)
    df_full = pd.concat([df, indicators], axis=1)

    signals = vectorize_conditions(conditions, df_full, mode="AND")
    assert len(signals) == len(df_full)
    assert signals.dtype == bool


def test_all_new_fields_registered():
    """Verify all 26 new sub-fields appear in get_all_fields()."""
    from api.services.indicator_registry import get_all_fields
    fields = get_all_fields()
    new_factors = [
        "MOM", "REALVOL", "REALVOL_skew", "REALVOL_kurt", "REALVOL_downside",
        "KBAR_upper_shadow", "KBAR_lower_shadow", "KBAR_body_ratio",
        "KBAR_amplitude", "KBAR_overnight_ret", "KBAR_intraday_ret",
        "PVOL_corr", "PVOL_amount_conc", "PVOL_vwap_bias",
        "LIQ_amihud", "LIQ_turnover_vol", "LIQ_log_amount",
        "PPOS_close_pos", "PPOS_high_dist", "PPOS_low_dist",
        "PPOS_drawdown", "PPOS_consec_dir",
        "RSTR", "RSTR_weighted",
        "AMPVOL_std", "AMPVOL_parkinson",
    ]
    missing = [f for f in new_factors if f not in fields]
    assert not missing, f"Missing fields: {missing}"
