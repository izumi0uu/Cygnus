"""
OAuth 2.1 Service — client registration, auth code lifecycle, token exchange.

Implements Authorization Code + PKCE (RFC 7636) flow for Claude Desktop MCP.
Access tokens issued are the existing ark_... MCP tokens — no new token format.
"""

import hashlib
import secrets
import uuid
from base64 import urlsafe_b64decode
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.oauth_models import OAuthAuthCode, OAuthClient
from app.services.mcp_auth_service import MCPAuthService


class OAuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -------------------------------------------------------------------------
    # Client management
    # -------------------------------------------------------------------------

    async def register_client(self, name: str, redirect_uris: list[str]) -> OAuthClient:
        """Register a new OAuth client (called by Claude Desktop on first connect)."""
        client = OAuthClient(
            client_id=OAuthClient.generate_client_id(),
            name=name or "Unknown Client",
            redirect_uris=redirect_uris,
        )
        self.db.add(client)
        await self.db.flush()
        return client

    async def get_client(self, client_id: str) -> Optional[OAuthClient]:
        result = await self.db.execute(
            select(OAuthClient).where(OAuthClient.client_id == client_id)
        )
        return result.scalar_one_or_none()

    # -------------------------------------------------------------------------
    # Authorization code
    # -------------------------------------------------------------------------

    async def create_auth_code(
        self,
        client_id: str,
        employee_id: uuid.UUID,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
        scope: Optional[str] = None,
    ) -> str:
        code = secrets.token_urlsafe(32)
        auth_code = OAuthAuthCode(
            code=code,
            client_id=client_id,
            employee_id=employee_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        self.db.add(auth_code)
        await self.db.flush()
        return code

    # -------------------------------------------------------------------------
    # Token exchange
    # -------------------------------------------------------------------------

    async def exchange_code(
        self,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> str:
        """
        Exchange an auth code + PKCE verifier for an MCP access token.
        Returns the ark_... token string.
        """
        result = await self.db.execute(
            select(OAuthAuthCode).where(
                OAuthAuthCode.code == code,
                OAuthAuthCode.client_id == client_id,
                OAuthAuthCode.used.is_(False),
            )
        )
        auth_code = result.scalar_one_or_none()

        if not auth_code:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")

        if datetime.now(timezone.utc) > auth_code.expires_at:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")

        if auth_code.redirect_uri != redirect_uri:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")

        if not self._verify_pkce(code_verifier, auth_code.code_challenge, auth_code.code_challenge_method):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")

        # Mark code as used (one-time)
        await self.db.execute(
            update(OAuthAuthCode)
            .where(OAuthAuthCode.id == auth_code.id)
            .values(used=True)
        )

        # Issue (or reuse) the employee's MCP token
        mcp_service = MCPAuthService(self.db)
        token = await mcp_service.generate_token(auth_code.employee_id)
        await self.db.commit()
        return token

    # -------------------------------------------------------------------------
    # PKCE verification
    # -------------------------------------------------------------------------

    @staticmethod
    def _verify_pkce(verifier: str, challenge: str, method: str) -> bool:
        if method != "S256":
            return False
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        # urlsafe base64 without padding
        computed = (
            __import__("base64")
            .urlsafe_b64encode(digest)
            .rstrip(b"=")
            .decode("ascii")
        )
        return computed == challenge
