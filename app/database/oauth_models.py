"""
OAuth 2.1 models — clients and authorization codes.

Used by the OAuth flow that allows Claude Desktop to connect to the MCP server
without manually configuring Bearer tokens in claude_desktop_config.json.
"""

import secrets
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models import Base


class OAuthClient(Base):
    """A registered OAuth client (e.g. Claude Desktop)."""
    __tablename__ = "oauth_clients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    redirect_uris: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    @classmethod
    def generate_client_id(cls) -> str:
        return f"client_{secrets.token_urlsafe(16)}"


class OAuthAuthCode(Base):
    """A short-lived authorization code issued during the OAuth flow."""
    __tablename__ = "oauth_auth_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("oauth_clients.client_id", ondelete="CASCADE")
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE")
    )
    redirect_uri: Mapped[str] = mapped_column(String(2000))
    code_challenge: Mapped[str] = mapped_column(String(128))
    code_challenge_method: Mapped[str] = mapped_column(String(10), default="S256")
    scope: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)
