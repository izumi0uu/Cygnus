"""Deterministic fake internal delivery consumer (verification-only).

This harness is NOT a production fixture provider. It mirrors the internal
copilot delivery contract so receipt tests can deterministically prove the
signed request -> signed ack loop:

- verifies the outbound ``X-Cygnus-Signature: sha256=<hmac>`` over the exact
  request body; a bad signature gets ``401`` and never produces an ack
- computes the delivered digest as SHA-256 of the exact request body bytes
- returns a signed ack binding ``publication_id`` / ``surface_id`` /
  ``object_version`` / ``digest`` so the governed adapter can verify it

Real Production V1 acceptance still requires an external internal-copilot
endpoint; this fixture only proves the adapter contract deterministically.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, cast


class FakeConsumer:
    """Plain-ASGI fake of the internal delivery endpoint.

    ``fail_with`` makes every request fail with that HTTP status (bounded
    retry/dead-letter paths). ``tamper_ack`` returns a signed ack whose digest
    is wrong (drift denial). ``redirect_to`` issues a ``307`` to exercise
    DNS-per-redirect validation.
    """

    def __init__(
        self,
        secret: str,
        *,
        fail_with: int | None = None,
        tamper_ack: bool = False,
        redirect_to: str | None = None,
    ) -> None:
        if not secret:
            raise ValueError("fake consumer requires a non-empty secret")
        self.secret = secret
        self.fail_with = fail_with
        self.tamper_ack = tamper_ack
        self.redirect_to = redirect_to
        self.received_bodies: list[bytes] = []
        self.received_headers: list[dict[str, str]] = []

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._send_json(send, 404, {"error": "not an http request"})
            return
        method = cast(str, scope.get("method", "GET"))
        path = cast(str, scope.get("path", ""))
        if method != "POST" or path != "/api/internal/propagation-delivery":
            await self._send_json(send, 404, {"error": "not found"})
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        body = b""
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        self.received_bodies.append(body)
        self.received_headers.append(headers)

        if self.fail_with is not None:
            await self._send_json(send, self.fail_with, {"error": "synthetic failure"})
            return
        if self.redirect_to is not None and len(self.received_bodies) == 1:
            await send(
                {
                    "type": "http.response.start",
                    "status": 307,
                    "headers": [
                        (b"location", self.redirect_to.encode("latin-1")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        signature = headers.get("x-cygnus-signature", "")
        if not _verify_signature(body, signature, self.secret):
            await self._send_json(send, 401, {"error": "signature verification failed"})
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            await self._send_json(send, 400, {"error": "invalid delivery body"})
            return
        if not isinstance(payload, dict):
            await self._send_json(
                send, 400, {"error": "delivery body must be an object"}
            )
            return

        delivery_id = headers.get("x-cygnus-delivery-id", "")
        digest = "0" * 64 if self.tamper_ack else hashlib.sha256(body).hexdigest()
        version = payload.get("object_version")
        ack_payload = {
            "publication_id": headers.get("x-cygnus-publication-id"),
            "surface_id": headers.get("x-cygnus-surface"),
            "version": version,
            "digest": digest,
            "receipt_ref": f"fake-consumer:{delivery_id[:8]}",
            "acknowledged": True,
        }
        ack_body = json.dumps(
            ack_payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        ack_signature = _signature(ack_body, self.secret)
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (
                        b"x-cygnus-ack-signature",
                        f"sha256={ack_signature}".encode("latin-1"),
                    ),
                ],
            }
        )
        await send({"type": "http.response.body", "body": ack_body})

    async def _send_json(
        self, send: Any, status: int, payload: dict[str, object]
    ) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _verify_signature(body: bytes, header_value: str, secret: str) -> bool:
    if not header_value.startswith("sha256="):
        return False
    provided = header_value[len("sha256=") :].strip()
    return hmac.compare_digest(provided, _signature(body, secret))
