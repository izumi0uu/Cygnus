"""Public-network URL validation and bounded retrieval for source ingestion."""

from __future__ import annotations

import asyncio
import inspect
import ipaddress
import socket
from collections.abc import AsyncIterable, AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpcore
import httpx


_MAX_REDIRECTS = 5
_STREAM_CHUNK_BYTES = 64 * 1024


class SourceURLValidationError(ValueError):
    """Raised when a source URL is not safe to persist or fetch."""


class SourceURLPayloadTooLarge(ValueError):
    """Raised when a streamed URL response exceeds its configured byte limit."""


@dataclass(frozen=True, slots=True)
class ValidatedSourceURL:
    url: str
    host: str
    port: int
    addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceURLResponse:
    url: str
    content_type: str | None
    payload: bytes


@dataclass(frozen=True, slots=True)
class _FetchedHop:
    status_code: int
    headers: httpx.Headers
    payload: bytes


def _is_public_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False

    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        parsed = parsed.ipv4_mapped

    return bool(
        parsed.is_global
        and not parsed.is_loopback
        and not parsed.is_private
        and not parsed.is_link_local
        and not parsed.is_multicast
        and not parsed.is_unspecified
        and not parsed.is_reserved
    )


async def _resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        records = await asyncio.get_running_loop().getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise SourceURLValidationError("Source URL host could not be resolved") from exc

    addresses: list[str] = []
    for record in records:
        address = record[4][0]
        if isinstance(address, str) and address not in addresses:
            addresses.append(address)
    if not addresses:
        raise SourceURLValidationError("Source URL host did not resolve to an address")
    if any(not _is_public_address(address) for address in addresses):
        raise SourceURLValidationError("Source URL resolves to a non-public address")
    return tuple(addresses)


def _normalized_url(parts, host: str) -> str:
    host_component = f"[{host}]" if ":" in host else host
    if parts.port is not None:
        host_component = f"{host_component}:{parts.port}"
    return urlunsplit(
        (parts.scheme.lower(), host_component, parts.path or "/", parts.query, "")
    )


async def validate_source_url(value: str) -> ValidatedSourceURL:
    """Normalize and resolve a public HTTP(S) source URL."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise SourceURLValidationError(
            "Source URL must be non-empty and have no surrounding whitespace"
        )
    if any(ord(char) < 0x20 for char in value):
        raise SourceURLValidationError("Source URL contains control characters")

    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise SourceURLValidationError("Source URL is invalid") from exc

    if parts.scheme.lower() not in {"http", "https"}:
        raise SourceURLValidationError("Source URL must use http or https")
    if parts.username is not None or parts.password is not None:
        raise SourceURLValidationError("Source URL credentials are not allowed")
    if not host or "%" in host:
        raise SourceURLValidationError("Source URL must include a valid host")

    try:
        normalized_host = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise SourceURLValidationError("Source URL host is invalid") from exc
    if not normalized_host:
        raise SourceURLValidationError("Source URL must include a valid host")

    resolved_port = port or (443 if parts.scheme.lower() == "https" else 80)
    addresses = await _resolve_public_addresses(normalized_host, resolved_port)
    return ValidatedSourceURL(
        url=_normalized_url(parts, normalized_host),
        host=normalized_host,
        port=resolved_port,
        addresses=addresses,
    )


class _PinnedAsyncNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect only to the addresses validated for one source URL hop."""

    def __init__(self, target: ValidatedSourceURL) -> None:
        self._target = target
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        if host.rstrip(".").lower() != self._target.host or port != self._target.port:
            raise httpcore.ConnectError("Pinned source connection origin mismatch")

        if not self._target.addresses:
            raise httpcore.ConnectError(
                "Pinned source target has no approved addresses"
            )
        if any(not _is_public_address(address) for address in self._target.addresses):
            raise httpcore.ConnectError(
                "Pinned source target includes a non-public address"
            )

        last_error: Exception | None = None
        for address in self._target.addresses:
            try:
                # This is the actual connection boundary: never hand the hostname
                # back to the network backend, which could perform a rebinding DNS
                # lookup after validation.
                return await self._backend.connect_tcp(
                    host=address,
                    port=port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise httpcore.ConnectError(
            "Unable to connect to the resolved source host"
        ) from last_error

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix sockets are not permitted for source URLs")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream: Iterable[bytes] | AsyncIterable[bytes]) -> None:
        self._stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        if isinstance(self._stream, AsyncIterable):
            async for chunk in self._stream:
                yield chunk
        else:
            for chunk in self._stream:
                yield chunk

    async def aclose(self) -> None:
        aclose = getattr(self._stream, "aclose", None)
        if callable(aclose):
            result = aclose()
            if inspect.isawaitable(result):
                await result


class _PinnedAsyncHTTPTransport(httpx.AsyncBaseTransport):
    """HTTPX transport that retains the URL hostname for Host/SNI but pins TCP."""

    def __init__(self, target: ValidatedSourceURL) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            network_backend=_PinnedAsyncNetworkBackend(target),
            max_connections=1,
            max_keepalive_connections=0,
            http2=False,
            retries=0,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._pool.handle_async_request(
            httpcore.Request(
                method=request.method,
                url=httpcore.URL(
                    scheme=request.url.raw_scheme,
                    host=request.url.raw_host,
                    port=request.url.port,
                    target=request.url.raw_path,
                ),
                headers=request.headers.raw,
                content=request.stream,
                extensions=request.extensions,
            )
        )
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_ResponseStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


async def _read_bounded_response(response: httpx.Response, max_bytes: int) -> bytes:
    declared_length = response.headers.get("content-length")
    if declared_length is not None:
        try:
            declared = int(declared_length)
        except (TypeError, ValueError):
            declared = None
        if declared is not None and declared > max_bytes:
            raise SourceURLPayloadTooLarge("Source URL response exceeds the byte limit")

    payload = bytearray()
    async for chunk in response.aiter_bytes(_STREAM_CHUNK_BYTES):
        if len(payload) + len(chunk) > max_bytes:
            raise SourceURLPayloadTooLarge("Source URL response exceeds the byte limit")
        payload.extend(chunk)
    return bytes(payload)


async def _fetch_one_hop(
    target: ValidatedSourceURL, max_bytes: int, timeout_seconds: float
) -> _FetchedHop:
    transport = _PinnedAsyncHTTPTransport(target)
    async with httpx.AsyncClient(
        transport=transport,
        follow_redirects=False,
        timeout=httpx.Timeout(timeout_seconds),
        trust_env=False,
    ) as client:
        async with client.stream(
            "GET", target.url, headers={"Accept": "*/*"}
        ) as response:
            if response.is_redirect:
                return _FetchedHop(response.status_code, response.headers, b"")
            response.raise_for_status()
            return _FetchedHop(
                response.status_code,
                response.headers,
                await _read_bounded_response(response, max_bytes),
            )


async def fetch_public_source_url(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float = 30.0,
) -> SourceURLResponse:
    """Fetch through explicit redirects, validating and pinning every destination.

    Egress allow policy: only ``http``/``https`` destinations whose DNS resolves
    exclusively to globally routable, non-reserved public addresses are fetched;
    private, loopback, link-local, multicast, CGNAT, and documentation ranges are
    refused before any connection is attempted. Every redirect hop is re-validated
    and re-pinned, so a redirect to an internal address is refused. Each hop
    streams its body through a byte budget of ``max_bytes`` (applied to the
    decoded payload, so decompression bombs are bounded too) and a per-hop
    ``timeout_seconds`` deadline.
    """
    if not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a positive number")

    current_url = url
    visited: set[str] = set()
    for _ in range(_MAX_REDIRECTS + 1):
        target = await validate_source_url(current_url)
        if target.url in visited:
            raise SourceURLValidationError("Source URL redirect loop detected")
        visited.add(target.url)

        fetched = await _fetch_one_hop(target, max_bytes, timeout_seconds)
        if 300 <= fetched.status_code < 400:
            location = fetched.headers.get("location")
            if not location:
                raise SourceURLValidationError(
                    "Source URL redirect is missing a location"
                )
            current_url = urljoin(target.url, location)
            continue

        return SourceURLResponse(
            url=target.url,
            content_type=fetched.headers.get("content-type"),
            payload=fetched.payload,
        )

    raise SourceURLValidationError("Source URL exceeded the redirect limit")
