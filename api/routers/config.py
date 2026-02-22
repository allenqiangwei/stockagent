"""Config router — read/update application settings via config.yaml."""

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter

from api.config import get_settings

router = APIRouter(prefix="/api/config", tags=["config"])

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "config.yaml"


def _read_yaml() -> dict:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _write_yaml(data: dict):
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _mask_token(token: str) -> str:
    """Mask token for display: show first 6 and last 4 chars."""
    if not token or len(token) <= 10:
        return "***" if token else ""
    return f"{token[:6]}****{token[-4:]}"


@router.get("")
def get_config():
    """Return current config with masked token."""
    raw = _read_yaml()
    ds = raw.get("data_sources", {})
    ts_cfg = ds.get("tushare", {})
    sig = raw.get("signals", {})
    risk = raw.get("risk_control", {})

    dk = raw.get("deepseek", {})
    ai_lab = raw.get("ai_lab", {})

    return {
        "data_sources": {
            "realtime_quotes": ds.get("realtime_quotes", "tushare"),
            "historical_daily": ds.get("historical_daily", "tushare"),
            "index_data": ds.get("index_data", "tushare"),
            "sector_data": ds.get("sector_data", "tushare"),
            "money_flow": ds.get("money_flow", "tushare"),
            "stock_list": ds.get("stock_list", "tushare"),
            "fallback_enabled": ds.get("fallback_enabled", True),
            "tushare_token_masked": _mask_token(ts_cfg.get("token", "")),
            "tushare_rate_limit": ts_cfg.get("rate_limit", 190),
        },
        "signals": {
            "auto_refresh_hour": sig.get("auto_refresh_hour", 19),
            "auto_refresh_minute": sig.get("auto_refresh_minute", 0),
        },
        "risk_control": {
            "fixed_stop_pct": risk.get("fixed_stop_pct", 0.05),
            "atr_multiplier": risk.get("atr_multiplier", 2.0),
            "max_position_pct": risk.get("max_position_pct", 0.25),
            "target_total_pct": risk.get("target_total_pct", 0.6),
            "max_stocks": risk.get("max_stocks", 10),
        },
        "deepseek": {
            "api_key_masked": _mask_token(dk.get("api_key", "")),
            "base_url": dk.get("base_url", "https://api.deepseek.com/v1"),
            "model": dk.get("model", "deepseek-chat"),
        },
        "ai_lab": {
            "weight_return": ai_lab.get("weight_return", 0.30),
            "weight_drawdown": ai_lab.get("weight_drawdown", 0.25),
            "weight_sharpe": ai_lab.get("weight_sharpe", 0.25),
            "weight_plr": ai_lab.get("weight_plr", 0.20),
        },
    }


@router.put("")
def update_config(body: dict[str, Any]):
    """Partially update config.yaml and reload settings.

    Accepts optional keys: data_sources, signals, risk_control.
    tushare_token is write-only — only written when non-empty.
    """
    raw = _read_yaml()

    # ── Data sources ──────────────────────────────
    if "data_sources" in body:
        incoming_ds = body["data_sources"]
        ds = raw.setdefault("data_sources", {})

        for key in (
            "realtime_quotes", "historical_daily", "index_data",
            "sector_data", "money_flow", "stock_list", "fallback_enabled",
        ):
            if key in incoming_ds:
                ds[key] = incoming_ds[key]

        # TuShare sub-config
        ts_cfg = ds.setdefault("tushare", {})
        new_token = incoming_ds.get("tushare_token", "")
        if new_token:
            ts_cfg["token"] = new_token
        if "tushare_rate_limit" in incoming_ds:
            ts_cfg["rate_limit"] = incoming_ds["tushare_rate_limit"]

    # ── Signals ───────────────────────────────────
    if "signals" in body:
        incoming_sig = body["signals"]
        sig = raw.setdefault("signals", {})
        for key in ("auto_refresh_hour", "auto_refresh_minute"):
            if key in incoming_sig:
                sig[key] = incoming_sig[key]

    # ── Risk control ──────────────────────────────
    if "risk_control" in body:
        incoming_risk = body["risk_control"]
        risk = raw.setdefault("risk_control", {})
        for key in (
            "fixed_stop_pct", "atr_multiplier",
            "max_position_pct", "target_total_pct", "max_stocks",
        ):
            if key in incoming_risk:
                risk[key] = incoming_risk[key]

    # ── AI Lab ────────────────────────────────────
    if "ai_lab" in body:
        incoming_lab = body["ai_lab"]
        lab = raw.setdefault("ai_lab", {})
        for key in ("weight_return", "weight_drawdown", "weight_sharpe", "weight_plr"):
            if key in incoming_lab:
                lab[key] = incoming_lab[key]

    # ── DeepSeek ─────────────────────────────────
    if "deepseek" in body:
        incoming_dk = body["deepseek"]
        dk = raw.setdefault("deepseek", {})
        new_api_key = incoming_dk.get("api_key", "")
        if new_api_key:
            dk["api_key"] = new_api_key
        for key in ("base_url", "model"):
            if key in incoming_dk:
                dk[key] = incoming_dk[key]

    # Write back
    _write_yaml(raw)

    # Clear cached Settings so next request reads fresh config
    get_settings.cache_clear()

    # Update signal scheduler if schedule changed
    if "signals" in body:
        try:
            from api.services.signal_scheduler import get_signal_scheduler
            sched = get_signal_scheduler()
            sig = raw.get("signals", {})
            sched.refresh_hour = sig.get("auto_refresh_hour", 19)
            sched.refresh_minute = sig.get("auto_refresh_minute", 0)
        except Exception:
            pass

    return {"status": "ok"}
