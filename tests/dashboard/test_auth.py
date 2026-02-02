"""Tests for dashboard authentication system."""

import pytest
import hashlib
from src.dashboard.auth import (
    AuthManager,
    User,
    hash_password,
    verify_password,
    UserRole
)


class TestUserRole:
    """Tests for UserRole enum."""

    def test_role_values(self):
        """Test role enum values."""
        assert UserRole.ADMIN.value == "admin"
        assert UserRole.READONLY.value == "readonly"

    def test_role_permissions(self):
        """Test role permission levels."""
        assert UserRole.ADMIN.can_modify
        assert not UserRole.READONLY.can_modify


class TestUser:
    """Tests for User dataclass."""

    def test_user_creation(self):
        """Test user can be created."""
        user = User(
            username="admin",
            password_hash="hash123",
            role=UserRole.ADMIN
        )
        assert user.username == "admin"
        assert user.role == UserRole.ADMIN

    def test_user_display_name(self):
        """Test user display name."""
        user = User(
            username="admin",
            password_hash="hash123",
            role=UserRole.ADMIN,
            display_name="管理员"
        )
        assert user.display_name == "管理员"


class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_hash_password_returns_string(self):
        """Test password hashing returns string."""
        hashed = hash_password("test123")
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_hash_password_different_for_different_inputs(self):
        """Test different passwords produce different hashes."""
        hash1 = hash_password("password1")
        hash2 = hash_password("password2")
        assert hash1 != hash2

    def test_verify_password_correct(self):
        """Test correct password verification."""
        password = "test123"
        hashed = hash_password(password)
        assert verify_password(password, hashed)

    def test_verify_password_incorrect(self):
        """Test incorrect password verification."""
        hashed = hash_password("test123")
        assert not verify_password("wrong", hashed)


class TestAuthManager:
    """Tests for AuthManager."""

    @pytest.fixture
    def auth_manager(self):
        """Create auth manager for testing."""
        return AuthManager()

    def test_manager_initialization(self, auth_manager):
        """Test manager initializes correctly."""
        assert auth_manager is not None

    def test_manager_has_default_users(self, auth_manager):
        """Test manager has default admin and viewer users."""
        users = auth_manager.get_all_users()
        usernames = [u.username for u in users]

        assert "admin" in usernames
        assert "viewer" in usernames

    def test_authenticate_valid_user(self, auth_manager):
        """Test authenticating valid user."""
        user = auth_manager.authenticate("admin", "admin123")

        assert user is not None
        assert user.username == "admin"
        assert user.role == UserRole.ADMIN

    def test_authenticate_invalid_password(self, auth_manager):
        """Test authenticating with wrong password."""
        user = auth_manager.authenticate("admin", "wrongpassword")
        assert user is None

    def test_authenticate_nonexistent_user(self, auth_manager):
        """Test authenticating nonexistent user."""
        user = auth_manager.authenticate("nonexistent", "password")
        assert user is None

    def test_get_user(self, auth_manager):
        """Test getting user by username."""
        user = auth_manager.get_user("admin")

        assert user is not None
        assert user.username == "admin"

    def test_get_nonexistent_user(self, auth_manager):
        """Test getting nonexistent user returns None."""
        user = auth_manager.get_user("nonexistent")
        assert user is None

    def test_add_user(self, auth_manager):
        """Test adding new user."""
        success = auth_manager.add_user(
            username="newuser",
            password="newpass123",
            role=UserRole.READONLY
        )

        assert success
        user = auth_manager.get_user("newuser")
        assert user is not None
        assert user.role == UserRole.READONLY

    def test_add_duplicate_user_fails(self, auth_manager):
        """Test adding duplicate username fails."""
        success = auth_manager.add_user(
            username="admin",
            password="newpass123",
            role=UserRole.READONLY
        )
        assert not success

    def test_change_password(self, auth_manager):
        """Test changing user password."""
        success = auth_manager.change_password(
            username="admin",
            old_password="admin123",
            new_password="newadmin123"
        )

        assert success

        # Old password should not work
        assert auth_manager.authenticate("admin", "admin123") is None

        # New password should work
        assert auth_manager.authenticate("admin", "newadmin123") is not None

    def test_change_password_wrong_old_password(self, auth_manager):
        """Test changing password with wrong old password fails."""
        success = auth_manager.change_password(
            username="admin",
            old_password="wrongpassword",
            new_password="newadmin123"
        )
        assert not success

    def test_check_permission(self, auth_manager):
        """Test checking user permissions."""
        admin = auth_manager.get_user("admin")
        viewer = auth_manager.get_user("viewer")

        # Admin can access admin pages
        assert auth_manager.check_permission(admin, ["admin"])

        # Viewer cannot access admin-only pages
        assert not auth_manager.check_permission(viewer, ["admin"])

        # Both can access readonly pages
        assert auth_manager.check_permission(admin, ["admin", "readonly"])
        assert auth_manager.check_permission(viewer, ["admin", "readonly"])

