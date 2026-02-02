"""Authentication system for dashboard."""

import hashlib
import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class UserRole(Enum):
    """User role enumeration."""
    ADMIN = "admin"
    READONLY = "readonly"

    @property
    def can_modify(self) -> bool:
        """Check if role can modify settings."""
        return self == UserRole.ADMIN


@dataclass
class User:
    """User account representation.

    Attributes:
        username: Unique username
        password_hash: Hashed password
        role: User role
        display_name: Optional display name
    """
    username: str
    password_hash: str
    role: UserRole
    display_name: Optional[str] = None

    def __post_init__(self):
        if self.display_name is None:
            self.display_name = self.username


def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Hash a password using SHA-256 with salt.

    Args:
        password: Plain text password
        salt: Optional salt (generated if not provided)

    Returns:
        Salted hash string in format: salt$hash
    """
    if salt is None:
        salt = secrets.token_hex(16)

    salted = f"{salt}{password}"
    hash_value = hashlib.sha256(salted.encode()).hexdigest()

    return f"{salt}${hash_value}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash.

    Args:
        password: Plain text password to verify
        password_hash: Stored hash in format: salt$hash

    Returns:
        True if password matches
    """
    try:
        salt, _ = password_hash.split("$", 1)
        return hash_password(password, salt) == password_hash
    except ValueError:
        return False


class AuthManager:
    """Manages user authentication and authorization.

    Provides user management, password verification, and role-based
    access control for the dashboard application.

    Usage:
        auth = AuthManager()
        user = auth.authenticate("admin", "password")
        if user and auth.check_permission(user, ["admin"]):
            # Allow access
    """

    def __init__(self):
        """Initialize auth manager with default users."""
        self._users: dict[str, User] = {}
        self._setup_default_users()

    def _setup_default_users(self):
        """Create default admin and viewer accounts."""
        # Default admin account
        self._users["admin"] = User(
            username="admin",
            password_hash=hash_password("admin123"),
            role=UserRole.ADMIN,
            display_name="管理员"
        )

        # Default viewer account
        self._users["viewer"] = User(
            username="viewer",
            password_hash=hash_password("viewer123"),
            role=UserRole.READONLY,
            display_name="观察者"
        )

    def authenticate(
        self,
        username: str,
        password: str
    ) -> Optional[User]:
        """Authenticate user credentials.

        Args:
            username: Username to authenticate
            password: Password to verify

        Returns:
            User object if authenticated, None otherwise
        """
        user = self._users.get(username)
        if user is None:
            return None

        if verify_password(password, user.password_hash):
            return user

        return None

    def get_user(self, username: str) -> Optional[User]:
        """Get user by username.

        Args:
            username: Username to lookup

        Returns:
            User object if found, None otherwise
        """
        return self._users.get(username)

    def get_all_users(self) -> list[User]:
        """Get all registered users.

        Returns:
            List of all User objects
        """
        return list(self._users.values())

    def add_user(
        self,
        username: str,
        password: str,
        role: UserRole,
        display_name: Optional[str] = None
    ) -> bool:
        """Add a new user.

        Args:
            username: Unique username
            password: Plain text password
            role: User role
            display_name: Optional display name

        Returns:
            True if user added successfully
        """
        if username in self._users:
            return False

        self._users[username] = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            display_name=display_name
        )

        return True

    def remove_user(self, username: str) -> bool:
        """Remove a user.

        Args:
            username: Username to remove

        Returns:
            True if user removed successfully
        """
        if username not in self._users:
            return False

        del self._users[username]
        return True

    def change_password(
        self,
        username: str,
        old_password: str,
        new_password: str
    ) -> bool:
        """Change user password.

        Args:
            username: Username to change password for
            old_password: Current password
            new_password: New password

        Returns:
            True if password changed successfully
        """
        user = self._users.get(username)
        if user is None:
            return False

        if not verify_password(old_password, user.password_hash):
            return False

        # Update password
        self._users[username] = User(
            username=user.username,
            password_hash=hash_password(new_password),
            role=user.role,
            display_name=user.display_name
        )

        return True

    def check_permission(
        self,
        user: Optional[User],
        allowed_roles: list[str]
    ) -> bool:
        """Check if user has permission based on role.

        Args:
            user: User to check
            allowed_roles: List of role values that have access

        Returns:
            True if user's role is in allowed_roles
        """
        if user is None:
            return False

        return user.role.value in allowed_roles

