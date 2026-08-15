"""Provision one operator-owned OAuth client in an isolated candidate stack."""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid

from cygnus.integrations.oauth_service import OAuthService, validate_redirect_uris
from cygnus.runtime.database import get_async_session_factory


async def _provision(redirect_uri: str) -> str:
    if os.environ.get("CYGNUS_CERTIFICATION_MODE") != "1":
        raise RuntimeError("OAuth certification provisioning is isolated-stack only")
    validate_redirect_uris([redirect_uri])
    session_factory = get_async_session_factory()
    async with session_factory() as session:
        service = OAuthService(session)
        client = await service.register_client(
            f"Cygnus certification {uuid.uuid4().hex[:12]}", [redirect_uri]
        )
        await session.commit()
        return client.client_id


class Args(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.redirect_uri: str = ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--redirect-uri", required=True)
    args = parser.parse_args(namespace=Args())
    print(asyncio.run(_provision(args.redirect_uri)))


if __name__ == "__main__":
    main()
