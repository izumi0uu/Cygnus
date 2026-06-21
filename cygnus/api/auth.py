from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cygnus.api.config import settings


@dataclass
class User:
    id: str
    name: str
    email: str
    password_hash: str
    role: str = "admin"
    is_active: bool = True


@dataclass
class InMemoryUserStore:
    _users: dict[str, User] = field(default_factory=dict)

    def add(self, user: User) -> None:
        self._users[user.email.lower()] = user

    def find_by_email(self, email: str) -> Optional[User]:
        return self._users.get(email.lower())

    def find_by_id(self, user_id: str) -> Optional[User]:
        for user in self._users.values():
            if user.id == user_id:
                return user
        return None


store = InMemoryUserStore()


def seed_default_admin() -> None:
    if not settings.seed_default_admin:
        return
    if settings.default_admin_email is None or settings.default_admin_password is None:
        raise RuntimeError("default admin seed requested without credentials")
    if store.find_by_email(settings.default_admin_email) is not None:
        return
    store.add(
        User(
            id=str(uuid.uuid4()),
            name="Support Lead",
            email=settings.default_admin_email,
            password_hash=hash_password(settings.default_admin_password),
            role="admin",
        )
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "name": user.name,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


def authenticate_user(email: str, password: str) -> Optional[User]:
    user = store.find_by_email(email)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "department_ids": [],
        "department_names": [],
        "permissions": [],
        "workspace_memberships": [],
    }


security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    user = store.find_by_id(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
