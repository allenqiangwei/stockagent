"""Dashboard application configuration and utilities."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AppConfig:
    """Application-level configuration.

    Attributes:
        app_title: Main application title
        page_icon: Emoji or image path for browser tab
        layout: Page layout (wide or centered)
        initial_sidebar_state: Sidebar state on load
    """
    app_title: str = "A股量化交易系统"
    page_icon: str = "📈"
    layout: str = "wide"
    initial_sidebar_state: str = "expanded"


@dataclass
class PageConfig:
    """Configuration for a dashboard page.

    Attributes:
        name: Display name for navigation
        icon: Emoji icon for menu
        path: Module path for the page
        requires_auth: Whether page requires login
        allowed_roles: List of roles that can access
    """
    name: str
    icon: str
    path: str
    requires_auth: bool = True
    allowed_roles: list[str] = field(default_factory=lambda: ["admin", "readonly"])


def init_session_state() -> dict:
    """Initialize default session state values.

    Returns:
        Dict with default session state keys and values
    """
    return {
        "authenticated": False,
        "user_role": None,
        "username": None,
        "current_page": "市场概览",
        "portfolio_value": 100000.0,
        "last_refresh": None,
    }


def get_page_config() -> list[PageConfig]:
    """Get configuration for all dashboard pages.

    Returns:
        List of PageConfig for navigation
    """
    return [
        PageConfig(
            name="市场概览",
            icon="🏠",
            path="pages.market_overview",
            requires_auth=True
        ),
        PageConfig(
            name="信号与持仓",
            icon="📊",
            path="pages.signals_positions",
            requires_auth=True
        ),
        PageConfig(
            name="风险状态",
            icon="⚠️",
            path="pages.risk_status",
            requires_auth=True
        ),
        PageConfig(
            name="系统设置",
            icon="⚙️",
            path="pages.settings",
            requires_auth=True,
            allowed_roles=["admin"]
        ),
    ]


def get_app_config() -> AppConfig:
    """Get application configuration.

    Returns:
        AppConfig instance with default or custom settings
    """
    return AppConfig()

