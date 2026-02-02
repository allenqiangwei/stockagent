"""Dashboard module for web interface."""

from .data_service import (
    DashboardDataService,
    MarketOverview,
    SignalSummary,
    PositionSummary,
    RiskStatusSummary
)
from .app_config import (
    AppConfig,
    PageConfig,
    get_app_config,
    get_page_config,
    init_session_state
)
from .auth import (
    AuthManager,
    User,
    UserRole,
    hash_password,
    verify_password
)

__all__ = [
    # Data Service
    "DashboardDataService",
    "MarketOverview",
    "SignalSummary",
    "PositionSummary",
    "RiskStatusSummary",
    # App Config
    "AppConfig",
    "PageConfig",
    "get_app_config",
    "get_page_config",
    "init_session_state",
    # Auth
    "AuthManager",
    "User",
    "UserRole",
    "hash_password",
    "verify_password",
]
