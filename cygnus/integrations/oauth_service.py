"""OAuth session adapter for Cygnus MCP clients.

Ownership:
- Claude/MCP-facing OAuth client registration, auth-code lifecycle, and token exchange live here
- this module is a session-facing integration adapter, not generic runtime service truth
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlsplit

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.integrations.mcp_auth import MCPAuthService
from cygnus.runtime.database.oauth_models import OAuthAuthCode, OAuthClient


MAX_REDIRECT_URIS_PER_CLIENT = 16
MAX_REDIRECT_URI_LENGTH = 2000


def validate_redirect_uris(redirect_uris: list[str]) -> None:
    """Reject redirect URIs that could enable open redirects or spoofing.

    Rules (fail closed):
    - exactly http(s) schemes;
    - absolute URIs with a host;
    - no fragment (a fragment is never sent to the server and breaks
      exact-match semantics);
    - no embedded userinfo credentials;
    - bounded count and length.
    """
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect_uris must be a non-empty list",
        )
    if len(redirect_uris) > MAX_REDIRECT_URIS_PER_CLIENT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"redirect_uris must contain at most {MAX_REDIRECT_URIS_PER_CLIENT} entries",
        )
    for uri in redirect_uris:
        if not isinstance(uri, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="redirect_uris entries must be strings",
            )
        if len(uri) > MAX_REDIRECT_URI_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="redirect_uri exceeds maximum length",
            )
        try:
            parsed = urlsplit(uri)
        except ValueError:
            parsed = None
        if (
            parsed is None
            or parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "redirect_uri must be an absolute http(s) URL without "
                    "fragment or userinfo"
                ),
            )


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

        The exchange is one-time: the code row is locked (FOR UPDATE) and
        marked used before the token is issued, so a concurrent second
        exchange cannot race the single-use guarantee. The code is additionally
        bound to the exact redirect_uri registered for the authorization
        request and to the S256 PKCE verifier.
        """
        result = await self.db.execute(
            select(OAuthAuthCode)
            .where(
                OAuthAuthCode.code == code,
                OAuthAuthCode.client_id == client_id,
                OAuthAuthCode.used.is_(False),
            )
            .with_for_update()
        )
        auth_code = result.scalar_one_or_none()

        if not auth_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant"
            )

        if datetime.now(timezone.utc) > auth_code.expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant"
            )

        if auth_code.redirect_uri != redirect_uri:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant"
            )

        if not self._verify_pkce(
            code_verifier, auth_code.code_challenge, auth_code.code_challenge_method
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant"
            )

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
            __import__("base64").urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        )
        return computed == challenge
