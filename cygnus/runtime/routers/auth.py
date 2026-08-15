"""
Auth router — login, logout, profile, change password.

Two system roles:
  - admin: Full access (bypasses all permission checks)
  - employee: Access governed by custom_role scoped permissions
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import Employee
from cygnus.runtime.services.auth_service import (
    LoginRateLimitExceeded,
    LoginRateLimitUnavailable,
    advance_employee_session_version,
    authenticate_employee_with_rate_limit,
    create_access_token,
    get_client_ip,
    get_current_user,
    hash_password,
    verify_password,
)
from cygnus.runtime.services.permission_engine import get_effective_permissions

router = APIRouter()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str
    password: str


# Deprecated WorkspaceMembershipOut DTO


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ProfileResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    department_ids: list[str] = []
    department_names: list[str] = []
    is_active: bool
    has_mcp_token: bool
    permissions: list[str] = []
    workspace_memberships: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_workspace_memberships(db, employee_id) -> list:
    """Workspace memberships have been deprecated and removed."""
    return []


def _build_user_dict(
    employee: Employee,
    permissions: list[str],
    workspace_memberships: Optional[list] = None,
) -> dict:
    """Build user dict for login/me responses."""
    return {
        "id": str(employee.id),
        "name": employee.name,
        "email": employee.email,
        "role": employee.role,
        "department_ids": [
            str(ed.department_id) for ed in employee.employee_departments
        ],
        "department_names": [
            ed.department.name for ed in employee.employee_departments if ed.department
        ],
        "permissions": permissions,
        "workspace_memberships": workspace_memberships or [],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    req: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with a shared Redis-backed abuse budget."""
    client_ip = get_client_ip(request)
    try:
        employee = await authenticate_employee_with_rate_limit(
            db,
            req.email,
            req.password,
            client_ip=client_ip,
        )
    except LoginRateLimitExceeded:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    except LoginRateLimitUnavailable:
        raise HTTPException(
            status_code=503,
            detail="Authentication service temporarily unavailable",
        )

    if not employee:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(
        employee_id=str(employee.id),
        role=employee.role,
        name=employee.name,
        session_version=employee.session_version,
    )

    permissions = get_effective_permissions(employee)

    return LoginResponse(
        access_token=token,
        user=_build_user_dict(employee, permissions, []),
    )


@router.get("/auth/me", response_model=ProfileResponse)
async def get_profile(
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user profile. Validates the JWT is still valid."""
    permissions = get_effective_permissions(current_user)
    workspace_memberships = await _get_workspace_memberships(db, current_user.id)

    return ProfileResponse(
        id=str(current_user.id),
        name=current_user.name,
        email=current_user.email,
        role=current_user.role,
        department_ids=[
            str(ed.department_id) for ed in current_user.employee_departments
        ],
        department_names=[
            ed.department.name
            for ed in current_user.employee_departments
            if ed.department
        ],
        is_active=current_user.is_active,
        has_mcp_token=bool(current_user.mcp_token_hash),
        permissions=permissions,
        workspace_memberships=workspace_memberships,
    )


@router.post("/auth/logout")
async def logout(
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke every outstanding portal JWT for the authenticated employee."""
    session_version = await advance_employee_session_version(db, current_user.id)
    if session_version is None:
        raise HTTPException(
            status_code=401,
            detail="Account not found or deactivated",
        )
    return {"message": "Logged out successfully"}


@router.post("/auth/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the current user's password."""
    if not current_user.password_hash:
        raise HTTPException(400, "No password set. Contact admin.")

    if not verify_password(req.current_password, current_user.password_hash):
        raise HTTPException(401, "Current password is incorrect")

    if len(req.new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters")

    session_version = await advance_employee_session_version(
        db,
        current_user.id,
        password_hash=hash_password(req.new_password),
        expected_password_hash=current_user.password_hash,
    )
    if session_version is None:
        raise HTTPException(401, "Current password is incorrect")
    return {"message": "Password changed successfully"}


@router.get("/auth/status")
async def auth_status():
    """Check if auth is required (public endpoint for frontend)."""
    return {"auth_required": True}
