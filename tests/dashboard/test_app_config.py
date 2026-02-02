"""Tests for dashboard app configuration and utilities."""

import pytest
from src.dashboard.app_config import (
    AppConfig,
    PageConfig,
    init_session_state,
    get_page_config
)


class TestAppConfig:
    """Tests for AppConfig dataclass."""

    def test_app_config_defaults(self):
        """Test default app configuration."""
        config = AppConfig()
        assert config.app_title == "A股量化交易系统"
        assert config.page_icon == "📈"
        assert config.layout == "wide"

    def test_app_config_custom(self):
        """Test custom app configuration."""
        config = AppConfig(
            app_title="Custom Title",
            layout="centered"
        )
        assert config.app_title == "Custom Title"
        assert config.layout == "centered"


class TestPageConfig:
    """Tests for PageConfig dataclass."""

    def test_page_config_creation(self):
        """Test page config can be created."""
        config = PageConfig(
            name="市场概览",
            icon="🏠",
            path="pages/market_overview"
        )
        assert config.name == "市场概览"
        assert config.icon == "🏠"


class TestSessionState:
    """Tests for session state utilities."""

    def test_init_session_state_returns_dict(self):
        """Test init_session_state returns default values."""
        # This function should work without Streamlit
        defaults = init_session_state()

        assert "authenticated" in defaults
        assert "user_role" in defaults
        assert "current_page" in defaults
        assert defaults["authenticated"] is False

    def test_init_session_state_default_page(self):
        """Test default page is market overview."""
        defaults = init_session_state()
        assert defaults["current_page"] == "市场概览"


class TestGetPageConfig:
    """Tests for get_page_config function."""

    def test_get_page_config_returns_list(self):
        """Test page configs are returned as list."""
        pages = get_page_config()

        assert isinstance(pages, list)
        assert len(pages) >= 2  # At least market overview and signals

    def test_page_configs_have_required_fields(self):
        """Test all page configs have required fields."""
        pages = get_page_config()

        for page in pages:
            assert hasattr(page, "name")
            assert hasattr(page, "icon")
            assert hasattr(page, "path")

    def test_market_overview_is_first_page(self):
        """Test market overview is the first page."""
        pages = get_page_config()
        assert pages[0].name == "市场概览"

