"""Focused portal JWT session-revocation contracts for CYG-128."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
import jwt
import pytest
from sqlalchemy import DefaultClause, Table, delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.sql.expression import Select, Update

from cygnus.runtime.config import settings
from cygnus.runtime.database.models import Employee, EmployeeDepartment
from cygnus.runtime.routers import auth as auth_router
from cygnus.runtime.routers import rbac as rbac_router
from cygnus.runtime.services.auth_service import (
    JWT_ALGORITHM,
    advance_employee_session_version,
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    verify_password,
)


class _Result:
    def __init__(self, scalar: object = None, rows: list[object] | None = None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[object]:
        return self._rows


class _PortalSessionDatabase:
    """Small statement-aware double for focused router and dependency tests."""

    def __init__(self, employee: Employee):
        self.employee = employee
        self.select_count = 0
        self.update_statements: list[Update] = []
        self._update_lock = asyncio.Lock()

    async def execute(self, statement: object) -> _Result:
        if isinstance(statement, Update):
            self.update_statements.append(statement)
            compact_sql = "".join(str(statement.compile()).split())
            assert "session_version=(employees.session_version+" in compact_sql
            params = statement.compile().params

            # Yield before the simulated database write so concurrent callers
            # exercise the column-relative increment rather than serial task order.
            await asyncio.sleep(0)
            async with self._update_lock:
                expected_hash = params.get("password_hash_1")
                if (
                    expected_hash is not None
                    and self.employee.password_hash != expected_hash
                ):
                    return _Result()
                self.employee.session_version += 1
                replacement_hash = params.get("password_hash")
                if replacement_hash is not None:
                    self.employee.password_hash = str(replacement_hash)
                return _Result(self.employee.session_version)

        if isinstance(statement, Select):
            descriptions = statement.column_descriptions
            entity = descriptions[0].get("entity") if descriptions else None
            if entity is Employee:
                self.select_count += 1
                return _Result(self.employee)
            if entity is EmployeeDepartment:
                return _Result(rows=[])
            return _Result(rows=[])

        raise AssertionError(f"unexpected statement: {statement!r}")

    async def get(self, model: type[object], key: object) -> object | None:
        if model is Employee and key == self.employee.id:
            return self.employee
        return None

    async def flush(self) -> None:
        return None

    async def delete(self, _row: object) -> None:
        return None

    def add(self, _row: object) -> None:
        return None


def _employee(*, session_version: int = 0, password: str = "old-password") -> Employee:
    employee_id = uuid.uuid4()
    return Employee(
        id=employee_id,
        name="Portal employee",
        email=f"portal-{employee_id}@example.test",
        password_hash=hash_password(password),
        session_version=session_version,
        role="employee",
        global_role="viewer",
        is_active=True,
    )


def _token(employee: Employee) -> str:
    return create_access_token(
        employee_id=str(employee.id),
        role=employee.role,
        name=employee.name,
        session_version=employee.session_version,
    )


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def _assert_unauthorized(token: str, db: _PortalSessionDatabase) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(_credentials(token), db)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 401


def _request() -> Any:
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/login",
            "headers": [],
            "query_string": b"",
            "client": ("192.0.2.10", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def test_password_change_revokes_stolen_token() -> None:
    async def exercise() -> None:
        employee = _employee()
        db = _PortalSessionDatabase(employee)
        stolen_token = _token(employee)

        response = await auth_router.change_password(
            auth_router.ChangePasswordRequest(
                current_password="old-password",
                new_password="new-password",
            ),
            employee,
            db,  # type: ignore[arg-type]
        )

        assert response == {"message": "Password changed successfully"}
        assert employee.session_version == 1
        assert employee.password_hash is not None
        assert verify_password("new-password", employee.password_hash)
        await _assert_unauthorized(stolen_token, db)

    asyncio.run(exercise())


def test_admin_password_reset_revokes_stolen_token() -> None:
    async def exercise() -> None:
        employee = _employee()
        db = _PortalSessionDatabase(employee)
        stolen_token = _token(employee)
        admin = SimpleNamespace(
            id=uuid.uuid4(),
            role="admin",
            global_role="admin",
        )

        with patch.object(rbac_router, "log_audit", new=AsyncMock()):
            response = await rbac_router.update_employee(
                str(employee.id),
                rbac_router.EmployeeCreate(
                    name=employee.name,
                    email=employee.email,
                    password="administrator-reset",
                    role=employee.role,
                    global_role=employee.global_role,
                    department_ids=[],
                ),
                db,  # type: ignore[arg-type]
                admin,  # type: ignore[arg-type]
            )

        assert response == {"id": str(employee.id), "name": employee.name}
        assert employee.session_version == 1
        assert employee.password_hash is not None
        assert verify_password("administrator-reset", employee.password_hash)
        await _assert_unauthorized(stolen_token, db)

    asyncio.run(exercise())


def test_successful_logout_revokes_stolen_token() -> None:
    async def exercise() -> None:
        employee = _employee()
        db = _PortalSessionDatabase(employee)
        stolen_token = _token(employee)

        response = await auth_router.logout(employee, db)  # type: ignore[arg-type]

        assert response == {"message": "Logged out successfully"}
        assert employee.session_version == 1
        await _assert_unauthorized(stolen_token, db)

    asyncio.run(exercise())


def test_fresh_login_token_carries_current_version_and_authenticates() -> None:
    async def exercise() -> None:
        employee = _employee(session_version=7)
        db = _PortalSessionDatabase(employee)
        authenticate = AsyncMock(return_value=employee)

        with patch.object(
            auth_router,
            "authenticate_employee_with_rate_limit",
            new=authenticate,
        ):
            response = await auth_router.login(
                auth_router.LoginRequest(
                    email=employee.email,
                    password="old-password",
                ),
                _request(),
                db,  # type: ignore[arg-type]
            )

        payload = decode_access_token(response.access_token)
        assert payload is not None
        assert payload["session_version"] == 7
        authenticated = await get_current_user(
            _credentials(response.access_token),
            db,  # type: ignore[arg-type]
        )
        assert authenticated is employee

    asyncio.run(exercise())


def test_token_without_session_version_is_rejected_after_employee_load() -> None:
    async def exercise() -> None:
        employee = _employee()
        db = _PortalSessionDatabase(employee)
        legacy_token = jwt.encode(
            {
                "sub": str(employee.id),
                "role": employee.role,
                "name": employee.name,
                "iat": datetime.now(timezone.utc),
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            settings.secret_key,
            algorithm=JWT_ALGORITHM,
        )

        await _assert_unauthorized(legacy_token, db)
        assert db.select_count == 1

    asyncio.run(exercise())


def test_deactivated_employee_token_remains_rejected() -> None:
    async def exercise() -> None:
        employee = _employee(session_version=3)
        token = _token(employee)
        employee.is_active = False
        db = _PortalSessionDatabase(employee)

        await _assert_unauthorized(token, db)

    asyncio.run(exercise())


def test_concurrent_revocations_use_column_relative_increments() -> None:
    async def exercise() -> None:
        employee = _employee()
        db = _PortalSessionDatabase(employee)

        versions = await asyncio.gather(
            *(
                advance_employee_session_version(db, employee.id)  # type: ignore[arg-type]
                for _ in range(8)
            )
        )

        resolved_versions = [version for version in versions if version is not None]
        assert len(resolved_versions) == 8
        assert sorted(resolved_versions) == list(range(1, 9))
        assert employee.session_version == 8
        assert len(db.update_statements) == 8

    asyncio.run(exercise())


def test_employee_session_version_is_non_nullable_and_server_defaulted() -> None:
    table = Employee.__table__
    assert isinstance(table, Table)
    column = table.c.session_version
    assert column.nullable is False
    assert isinstance(column.server_default, DefaultClause)
    assert str(column.server_default.arg) == "0"
    assert "ck_employees_session_version_nonnegative" in {
        constraint.name for constraint in table.constraints
    }


_INTEGRATION_DATABASE_URL = os.getenv("CYGNUS_GOVERNANCE_TEST_DATABASE_URL")


@unittest.skipUnless(
    _INTEGRATION_DATABASE_URL,
    "CYGNUS_GOVERNANCE_TEST_DATABASE_URL is not configured",
)
class PortalSessionRevocationPostgresTests(unittest.TestCase):
    def test_concurrent_revocations_cannot_lose_increments(self) -> None:
        asyncio.run(self._exercise_concurrent_revocations())

    async def _exercise_concurrent_revocations(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")

        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        employee_id = uuid.uuid4()
        try:
            async with sessions() as session:
                session.add(
                    Employee(
                        id=employee_id,
                        name="Concurrent portal revocations",
                        email=f"portal-concurrency-{employee_id}@example.test",
                        password_hash=hash_password("concurrent-password"),
                        session_version=0,
                        role="employee",
                        global_role="viewer",
                        is_active=True,
                    )
                )
                await session.commit()

            async def revoke_once() -> int | None:
                async with sessions() as session:
                    version = await advance_employee_session_version(
                        session,
                        employee_id,
                    )
                    await session.commit()
                    return version

            versions = await asyncio.gather(*(revoke_once() for _ in range(8)))
            resolved_versions = [version for version in versions if version is not None]
            self.assertEqual(len(resolved_versions), 8)
            self.assertEqual(sorted(resolved_versions), list(range(1, 9)))

            async with sessions() as session:
                persisted_version = (
                    await session.execute(
                        select(Employee.session_version).where(
                            Employee.id == employee_id
                        )
                    )
                ).scalar_one()
                self.assertEqual(persisted_version, 8)
        finally:
            async with sessions() as session:
                await session.execute(
                    delete(Employee).where(Employee.id == employee_id)
                )
                await session.commit()
            await engine.dispose()
