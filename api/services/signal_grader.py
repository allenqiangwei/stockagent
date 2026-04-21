"""Signal quality grader — dynamically labels trade plans based on historical outcomes.

Computes bin-level win rates from completed bot_trade_reviews, then grades
new plans by looking up their (α, γ) bin. Recalibrates daily after do_refresh.

The grading is purely data-driven: no hardcoded rules, adapts as more trades complete.
"""

import logging
import threading
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Bin definitions ──────────────────────────────────────

ALPHA_BINS = [0, 50, 60, 70, 80, 90, 101]       # 5 bins
GAMMA_BINS = [0, 20, 40, 60, 80, 101]            # 5 bins + "no gamma"
COMBINED_BINS = [0, 0.3, 0.4, 0.5, 0.6, 0.7, 1.01]

# Grade thresholds (on win rate)
GRADE_GREEN = 55.0   # 🟢 win rate >= 55%
GRADE_YELLOW = 40.0  # 🟡 40-55%
# Below 40% = 🔴


def _bin_index(value: float, bins: list[float]) -> int:
    """Find which bin a value falls into. Returns bin index (0-based)."""
    for i in range(len(bins) - 1):
        if value < bins[i + 1]:
            return i
    return len(bins) - 2


# ── Calibration data (recalculated daily) ────────────────

class _CalibrationData:
    """Thread-safe container for bin-level statistics."""

    def __init__(self):
        self.lock = threading.Lock()
        # Key: (alpha_bin, gamma_bin) → {"n": int, "win_rate": float, "avg_pnl": float}
        self.bins: dict[tuple[int, int], dict] = {}
        # Key: combined_bin → same
        self.combined_bins: dict[int, dict] = {}
        self.total_trades: int = 0
        self.overall_win_rate: float = 0.0
        self.calibrated: bool = False

    def get(self, alpha_bin: int, gamma_bin: int) -> Optional[dict]:
        with self.lock:
            return self.bins.get((alpha_bin, gamma_bin))

    def get_combined(self, combined_bin: int) -> Optional[dict]:
        with self.lock:
            return self.combined_bins.get(combined_bin)


_calibration = _CalibrationData()


# ── Calibration (called daily after do_refresh) ──────────

def calibrate(db: Session) -> dict:
    """Recalibrate signal grades from all completed trade reviews.

    Joins bot_trade_plans → bot_trade_reviews to get (α, β, γ, combined) → pnl
    for every completed trade, then computes per-bin win rates.

    Returns summary stats.
    """
    from sqlalchemy import text

    rows = db.execute(text("""
        SELECT p.alpha_score, p.beta_score, p.gamma_score, p.combined_score,
               r.pnl_pct
        FROM bot_trade_plans p
        JOIN bot_trade_reviews r
            ON r.stock_code = p.stock_code
            AND r.strategy_id = p.strategy_id
            AND r.first_buy_date = p.plan_date
        WHERE p.status = 'executed' AND p.direction = 'buy'
            AND p.alpha_score IS NOT NULL
    """)).fetchall()

    if not rows:
        logger.info("Signal grader: no completed trades to calibrate from")
        return {"status": "no_data"}

    # Build numpy arrays
    alpha = np.array([r[0] for r in rows])
    gamma = np.array([r[2] if r[2] is not None else -1 for r in rows])
    combined = np.array([r[3] for r in rows])
    pnl = np.array([r[4] for r in rows])
    wins = pnl > 0

    # Compute bin stats: (alpha_bin, gamma_bin) → {n, win_rate, avg_pnl}
    new_bins: dict[tuple[int, int], dict] = {}

    for a_idx in range(len(ALPHA_BINS) - 1):
        a_lo, a_hi = ALPHA_BINS[a_idx], ALPHA_BINS[a_idx + 1]

        for g_idx in range(len(GAMMA_BINS) - 1):
            g_lo, g_hi = GAMMA_BINS[g_idx], GAMMA_BINS[g_idx + 1]
            mask = (alpha >= a_lo) & (alpha < a_hi) & (gamma >= g_lo) & (gamma < g_hi)
            n = int(mask.sum())
            if n > 0:
                new_bins[(a_idx, g_idx)] = {
                    "n": n,
                    "win_rate": float(wins[mask].mean() * 100),
                    "avg_pnl": float(pnl[mask].mean()),
                }

        # "no gamma" bin (gamma_bin = -1)
        mask = (alpha >= a_lo) & (alpha < a_hi) & (gamma < 0)
        n = int(mask.sum())
        if n > 0:
            new_bins[(a_idx, -1)] = {
                "n": n,
                "win_rate": float(wins[mask].mean() * 100),
                "avg_pnl": float(pnl[mask].mean()),
            }

    # Combined bins
    new_combined: dict[int, dict] = {}
    for c_idx in range(len(COMBINED_BINS) - 1):
        c_lo, c_hi = COMBINED_BINS[c_idx], COMBINED_BINS[c_idx + 1]
        mask = (combined >= c_lo) & (combined < c_hi)
        n = int(mask.sum())
        if n > 0:
            new_combined[c_idx] = {
                "n": n,
                "win_rate": float(wins[mask].mean() * 100),
                "avg_pnl": float(pnl[mask].mean()),
            }

    # Update global calibration atomically
    with _calibration.lock:
        _calibration.bins = new_bins
        _calibration.combined_bins = new_combined
        _calibration.total_trades = len(rows)
        _calibration.overall_win_rate = float(wins.mean() * 100)
        _calibration.calibrated = True

    logger.info(
        "Signal grader calibrated: %d trades, %d bins, overall wr=%.1f%%",
        len(rows), len(new_bins), _calibration.overall_win_rate,
    )

    return {
        "status": "calibrated",
        "total_trades": len(rows),
        "overall_win_rate": round(_calibration.overall_win_rate, 1),
        "bins": len(new_bins),
    }


# ── Grading (called at plan creation time) ───────────────

def grade_signal(
    alpha: float,
    gamma: Optional[float],
    combined: float,
) -> dict:
    """Grade a signal based on calibrated bin statistics.

    Returns:
        {
            "grade": "green" | "yellow" | "red" | "unknown",
            "label": "🟢推荐" | "🟡中性" | "🔴避坑" | "⚪未知",
            "win_rate": float | None,
            "avg_pnl": float | None,
            "sample_size": int,
            "source": "alpha_gamma" | "combined" | "uncalibrated",
        }
    """
    if not _calibration.calibrated:
        return {
            "grade": "unknown", "label": "⚪未知",
            "win_rate": None, "avg_pnl": None,
            "sample_size": 0, "source": "uncalibrated",
        }

    # Primary: look up (alpha_bin, gamma_bin)
    a_idx = _bin_index(alpha, ALPHA_BINS)
    if gamma is not None and gamma >= 0:
        g_idx = _bin_index(gamma, GAMMA_BINS)
    else:
        g_idx = -1

    stats = _calibration.get(a_idx, g_idx)

    # Fallback to combined_score bin if primary has < 10 samples
    if not stats or stats["n"] < 10:
        c_idx = _bin_index(combined, COMBINED_BINS)
        c_stats = _calibration.get_combined(c_idx)
        if c_stats and c_stats["n"] >= 10:
            stats = c_stats
            source = "combined"
        elif stats:
            source = "alpha_gamma"  # small sample but use it
        else:
            return {
                "grade": "unknown", "label": "⚪未知",
                "win_rate": None, "avg_pnl": None,
                "sample_size": 0, "source": "no_bin_data",
            }
    else:
        source = "alpha_gamma"

    wr = stats["win_rate"]
    if wr >= GRADE_GREEN:
        grade, label = "green", "🟢推荐"
    elif wr >= GRADE_YELLOW:
        grade, label = "yellow", "🟡中性"
    else:
        grade, label = "red", "🔴避坑"

    return {
        "grade": grade,
        "label": label,
        "win_rate": round(wr, 1),
        "avg_pnl": round(stats["avg_pnl"], 2),
        "sample_size": stats["n"],
        "source": source,
    }


# ── API: get current calibration stats ───────────────────

def get_calibration_report() -> dict:
    """Return full calibration report for API/dashboard."""
    if not _calibration.calibrated:
        return {"calibrated": False}

    with _calibration.lock:
        bins_report = []
        for (a_idx, g_idx), stats in sorted(_calibration.bins.items()):
            a_lo = ALPHA_BINS[a_idx] if a_idx >= 0 else 0
            a_hi = ALPHA_BINS[a_idx + 1] if a_idx + 1 < len(ALPHA_BINS) else 101
            if g_idx >= 0:
                g_lo = GAMMA_BINS[g_idx]
                g_hi = GAMMA_BINS[g_idx + 1] if g_idx + 1 < len(GAMMA_BINS) else 101
                g_label = f"γ[{g_lo},{g_hi})"
            else:
                g_label = "无γ"

            wr = stats["win_rate"]
            if wr >= GRADE_GREEN:
                grade = "🟢"
            elif wr >= GRADE_YELLOW:
                grade = "🟡"
            else:
                grade = "🔴"

            bins_report.append({
                "alpha": f"α[{a_lo},{a_hi})",
                "gamma": g_label,
                "n": stats["n"],
                "win_rate": round(wr, 1),
                "avg_pnl": round(stats["avg_pnl"], 2),
                "grade": grade,
            })

        return {
            "calibrated": True,
            "total_trades": _calibration.total_trades,
            "overall_win_rate": round(_calibration.overall_win_rate, 1),
            "bins": bins_report,
        }
