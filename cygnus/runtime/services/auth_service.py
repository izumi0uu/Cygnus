"""
Auth Service — JWT-based authentication for Admin Portal and Employee Portal.

Ownership:
- employee authentication, JWT session issuance, and request-scoped auth dependencies live here
- permission resolution may call into ``permission_engine``, but auth/session ownership remains in the runtime shell

Handles:
  - Password hashing (bcrypt)
  - JWT token generation and verification
  - Login / logout (stateless JWT)
  - Role-based access (admin vs employee)
  - Scoped permission checks (v2: resource:action:scope format)
"""

import hashlib
import ipaddress
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cygnus.runtime.config import settings
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee, EmployeeDepartment

# JWT config
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

security = HTTPBearer(auto_error=False)

VALID_SYSTEM_ROLES = frozenset({"admin", "employee"})
VALID_GLOBAL_ROLES = frozenset({"viewer", "contributor", "knowledge_manager", "admin"})


class LoginRateLimitExceeded(Exception):
    """Raised when the shared Redis login-attempt budget is exhausted."""


class LoginRateLimitUnavailable(Exception):
    """Raised when login abuse protection cannot use its shared Redis store."""


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password using bcrypt without exposing malformed hashes."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (TypeError, ValueError):
        return False


# Keep unknown-account attempts on the same bcrypt work factor as known accounts.
_DUMMY_PASSWORD_HASH = hash_password("cygnus-invalid-login-password")


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------


def create_access_token(employee_id: str, role: str, name: str) -> str:
    """Create a signed JWT token."""
    payload = {
        "sub": employee_id,
        "role": role,
        "name": name,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token. Returns payload or None."""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ---------------------------------------------------------------------------
# Client IP resolution (forwarded headers, fail-closed)
# ---------------------------------------------------------------------------


def _peer_is_trusted_proxy(peer: str, trusted_entries: list[str]) -> bool:
    """True when the direct peer is in the configured trusted proxy list.

    Supports literal IPs and CIDR ranges (e.g. '172.16.0.0/12'). Unparseable
    entries are ignored, and any failure returns False (fail closed).
    """
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for entry in trusted_entries:
        try:
            if "/" in entry:
                if peer_ip in ipaddress.ip_network(entry, strict=False):
                    return True
            elif peer_ip == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def get_client_ip(request: Request) -> str:
    """Resolve the caller's IP for abuse budgets behind a trusted proxy.

    Fail-closed behavior:
    - forwarded headers are only honored when the immediate peer is listed in
      TRUSTED_PROXY_IPS (or a CIDR covering it);
    - when trusted, the rightmost X-Forwarded-For entry is used — that is the
      address the trusted proxy appended, so client-supplied spoofed entries
      can never win;
    - otherwise the direct socket peer is returned unchanged.
    """
    peer = request.client.host if request.client is not None else "unknown"
    trusted_entries = [
        entry.strip()
        for entry in settings.trusted_proxy_ips.split(",")
        if entry.strip()
    ]
    if not _peer_is_trusted_proxy(peer, trusted_entries):
        return peer

    forwarded_for = request.headers.get("x-forwarded-for", "")
    entries = [entry.strip() for entry in forwarded_for.split(",") if entry.strip()]
    if entries:
        return entries[-1]
    return peer


# ---------------------------------------------------------------------------
# Login / authenticate
# ---------------------------------------------------------------------------


async def authenticate_employee(
    db: AsyncSession, email: str, password: str
) -> Optional[Employee]:
    """
    Verify email + password. Returns Employee or None.
    """
    stmt = (
        select(Employee)
        .where(Employee.email == email, Employee.is_active.is_(True))
        .options(
            selectinload(Employee.employee_departments).selectinload(
                EmployeeDepartment.department
            ),
        )
    )
    result = await db.execute(stmt)
    employee = result.scalar_one_or_none()

    if not employee or not employee.password_hash:
        _ = verify_password(password, _DUMMY_PASSWORD_HASH)
        return None
    if not verify_password(password, employee.password_hash):
        return None
    return employee


# ---------------------------------------------------------------------------
# Shared Redis login abuse protection
# ---------------------------------------------------------------------------

_LOGIN_ATTEMPT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
if count > tonumber(ARGV[2]) then
    return 0
end
return 1
"""


@dataclass(frozen=True)
class LoginAttemptLimiter:
    """Atomically consume bounded login budgets from the shared Redis store."""

    redis: Any
    max_attempts: int
    window_seconds: int

    @staticmethod
    def _key(kind: str, value: str) -> str:
        digest = hashlib.sha256(value.strip().casefold().encode("utf-8")).hexdigest()
        return f"cygnus:auth:login:{kind}:{digest}"

    def _keys(self, email: str, client_ip: str) -> tuple[str, str]:
        return (
            self._key("email", email),
            self._key("ip", client_ip or "unknown"),
        )

    async def consume(self, *, email: str, client_ip: str) -> bool:
        """Record this attempt before credential lookup and return its allowance."""
        try:
            for key in self._keys(email, client_ip):
                allowed = await self.redis.eval(
                    _LOGIN_ATTEMPT_SCRIPT,
                    1,
                    key,
                    self.window_seconds,
                    self.max_attempts,
                )
                if int(allowed) != 1:
                    return False
        except Exception as exc:
            raise LoginRateLimitUnavailable() from exc
        return True

    async def clear(self, *, email: str, client_ip: str) -> None:
        """Clear the shared budgets only after successful authentication."""
        try:
            await self.redis.delete(*self._keys(email, client_ip))
        except Exception as exc:
            raise LoginRateLimitUnavailable() from exc


async def get_login_attempt_limiter() -> LoginAttemptLimiter:
    """Resolve the API/worker Redis pool used for login abuse protection."""
    resolved_settings = settings
    try:
        from cygnus.runtime.worker import get_arq_pool

        redis = await get_arq_pool()
    except Exception as exc:
        raise LoginRateLimitUnavailable() from exc
    return LoginAttemptLimiter(
        redis=redis,
        max_attempts=resolved_settings.login_rate_limit_attempts,
        window_seconds=resolved_settings.login_rate_limit_window_seconds,
    )


async def authenticate_employee_with_rate_limit(
    db: AsyncSession,
    email: str,
    password: str,
    *,
    client_ip: str,
) -> Optional[Employee]:
    """Authenticate only after consuming a shared, bounded login-attempt budget."""
    limiter = await get_login_attempt_limiter()
    if not await limiter.consume(email=email, client_ip=client_ip):
        raise LoginRateLimitExceeded()

    employee = await authenticate_employee(db, email, password)
    if employee is not None:
        await limiter.clear(email=email, client_ip=client_ip)
    return employee


# ---------------------------------------------------------------------------
# Employee privilege-boundary checks
# ---------------------------------------------------------------------------


def validate_employee_role_assignment(role: str, global_role: str) -> None:
    """Reject unknown roles at the administrative assignment boundary."""
    if role not in VALID_SYSTEM_ROLES:
        raise HTTPException(400, "Role must be 'admin' or 'employee'")
    if global_role not in VALID_GLOBAL_ROLES:
        raise HTTPException(
            400,
            "Global role must be one of: viewer, contributor, knowledge_manager, admin",
        )


def enforce_employee_management_boundary(
    current_user: Employee,
    *,
    role: str | None = None,
    global_role: str | None = None,
) -> None:
    """Require a system admin for employee mutations and privileged assignments."""
    if getattr(current_user, "role", None) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    if role is not None or global_role is not None:
        if role is None or global_role is None:
            raise ValueError("Role assignments must include both role fields")
        validate_employee_role_assignment(role, global_role)


def is_privileged_employee(employee: Employee) -> bool:
    """Return whether an employee holds either form of administrative authority."""
    return employee.role == "admin" or employee.global_role == "admin"


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Employee:
    """
    FastAPI dependency — extracts and validates JWT from Authorization header.
    Returns the authenticated Employee.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    result = await db.execute(
        select(Employee)
        .options(
            selectinload(Employee.employee_departments).selectinload(
                EmployeeDepartment.department
            ),
        )
        .where(Employee.id == uuid.UUID(payload["sub"]))
    )
    employee = result.scalar_one_or_none()
    if not employee or not employee.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found or deactivated",
        )

    # Ensure default global_role is populated
    if not getattr(employee, "global_role", None):
        employee.global_role = "viewer"

    return employee


async def require_employee_management_admin(
    current_user: Employee = Depends(get_current_user),
) -> Employee:
    """Require a system administrator for employee-management mutations."""
    enforce_employee_management_boundary(current_user)
    return current_user


async def require_admin(
    current_user: Employee = Depends(get_current_user),
) -> Employee:
    """
    FastAPI dependency — requires admin role.
    Use on admin-only endpoints.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def require_permission(permission: str):
    """
    FastAPI dependency factory — checks a specific permission on the employee's custom role.
    Admins bypass all permission checks.

    Supports both new scoped format (doc:read:own_dept) and org permissions (org:settings:read).

    For scoped resource permissions (doc/wiki), this only checks that the user
    has SOME variant (own_dept or all). Actual scope filtering (which documents
    they can see) is handled by the permission engine at query time.

    Usage: Depends(require_permission("doc:read"))  — checks for doc:read:own_dept OR doc:read:all
           Depends(require_permission("org:settings:read"))  — exact match
    """

    async def _check(current_user: Employee = Depends(get_current_user)) -> Employee:
        if current_user.role == "admin":
            return current_user

        from cygnus.runtime.services.permission_engine import (
            _get_user_permissions,
            has_any_permission,
        )

        effective = _get_user_permissions(current_user)

        # Check exact match first (for org: permissions)
        if permission in effective:
            return current_user

        # Check as resource:action (matches either :own_dept or :all)
        parts = permission.split(":")
        if len(parts) == 2:
            resource, action = parts
            if has_any_permission(list(effective), resource, action):
                return current_user
        elif len(parts) == 3:
            # Exact scoped permission check
            if permission in effective:
                return current_user
            # Also check if user has the :all version when :own_dept is required
            resource, action, scope = parts
            if scope == "own_dept" and f"{resource}:{action}:all" in effective:
                return current_user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission required: {permission}",
        )

    return Depends(_check)
