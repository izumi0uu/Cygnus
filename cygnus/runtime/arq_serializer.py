"""
Versioned, deterministic, allowlisted serializer for ARQ jobs and results.

Replaces arq's default pickle-based ``job_serializer``/``job_deserializer`` so
a crafted or malicious queue payload can never execute code inside the worker:
only the closed grammar below is accepted, and every payload is bounded by
size, container item count, and nesting depth before arq ever sees it.

Format
------
Every payload starts with a fixed header: ``b"cygq" <version byte>`` followed
by a type-tagged tree. The version byte lets future formats ship without ever
silently mis-decoding older payloads.

Value tags:

    NIL, FALSE, TRUE, INT, STR, BYTES, LIST, TUPLE, MAP, EXC

Integers use zigzag varints, lengths and counts use unsigned varints, map keys
must be ``str`` and are emitted in sorted order so equal payloads always encode
to identical bytes (deterministic, useful for comparing queued jobs). The
``EXC`` tag stores an exception class name plus its ``args`` tuple (falling
back to ``str(exc)`` when the args are not encodable) so failed-job results
survive the round trip exactly without ever calling ``pickle``; decoding
reconstructs only allowlisted exception classes (unknown names degrade to
``Exception``).

Anything outside the allowlist (``datetime``, sets, arbitrary objects, raw
pickle bytes, ...) is rejected at encode time with ``QueueSerializationError``
or at decode time with ``QueueDeserializationError`` — never executed.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

MAGIC = b"cygq"
VERSION = 1
HEADER_LEN = len(MAGIC) + 1

MAX_SERIALIZED_BYTES = 4 * 1024 * 1024
MAX_DEPTH = 64
MAX_CONTAINER_ITEMS = 100_000
#: A varint may span at most 512 bytes (4096 bits) — far beyond any payload
#: value arq produces, but wide enough to match the arbitrary-precision ints
#: the encoder accepts. Payload size is the ultimate bound.
_MAX_VARINT_SHIFT = 4096

# Value type tags
_NIL = 0x00
_FALSE = 0x01
_TRUE = 0x02
_INT = 0x03
_STR = 0x04
_BYTES = 0x05
_LIST = 0x06
_TUPLE = 0x07
_MAP = 0x08
_EXC = 0x09


class QueueSerializationError(RuntimeError):
    """An object cannot be encoded into the safe queue format."""


class QueueDeserializationError(RuntimeError):
    """A payload is not a valid, allowlisted queue payload."""


#: Exception classes safe to reconstruct from a decoded ``EXC`` record.
#: Unknown names always degrade to ``Exception``; nothing user-defined is ever
#: instantiated from queue bytes.
_SAFE_EXCEPTION_CLASSES: dict[str, type[BaseException]] = {
    "RuntimeError": RuntimeError,
    "ValueError": ValueError,
    "KeyError": KeyError,
    "TypeError": TypeError,
    "LookupError": LookupError,
    "TimeoutError": TimeoutError,
    "OSError": OSError,
    #: ``type(exc).__name__`` is ``"CancelledError"``; the dotted form is kept
    #: so both spellings reconstruct the same (safe) class.
    "CancelledError": asyncio.CancelledError,
    "asyncio.CancelledError": asyncio.CancelledError,
}
_FALLBACK_EXCEPTION = Exception


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def dumps(obj: Any) -> bytes:
    """Serialize *obj* into the versioned, allowlisted queue format.

    Raises ``QueueSerializationError`` for any payload that is not a closed
    set of primitives or that exceeds the size/depth/item bounds.
    """
    buf = bytearray(MAGIC + bytes([VERSION]))
    _encode(obj, buf, 0)
    if len(buf) > MAX_SERIALIZED_BYTES:
        raise QueueSerializationError(
            f"payload of {len(buf)} bytes exceeds {MAX_SERIALIZED_BYTES} byte limit"
        )
    return bytes(buf)


def _encode(obj: Any, buf: bytearray, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise QueueSerializationError(f"payload nests deeper than {MAX_DEPTH} levels")
    if obj is None:
        buf.append(_NIL)
    elif isinstance(obj, bool):
        buf.append(_TRUE if obj else _FALSE)
    elif isinstance(obj, int):
        buf.append(_INT)
        _encode_zigzag(buf, obj)
    elif isinstance(obj, str):
        encoded = obj.encode("utf-8")
        buf.append(_STR)
        _encode_uint(buf, len(encoded))
        buf.extend(encoded)
    elif isinstance(obj, (bytes, bytearray)):
        buf.append(_BYTES)
        _encode_uint(buf, len(obj))
        buf.extend(obj)
    elif isinstance(obj, tuple):
        _encode_sequence(buf, _TUPLE, obj, depth)
    elif isinstance(obj, list):
        _encode_sequence(buf, _LIST, obj, depth)
    elif isinstance(obj, dict):
        if len(obj) > MAX_CONTAINER_ITEMS:
            raise QueueSerializationError(
                f"map with {len(obj)} items exceeds {MAX_CONTAINER_ITEMS} item limit"
            )
        if not all(isinstance(key, str) for key in obj):
            raise QueueSerializationError("map keys must be str")
        buf.append(_MAP)
        _encode_uint(buf, len(obj))
        for key in sorted(obj):
            _encode(key, buf, depth + 1)
            _encode(obj[key], buf, depth + 1)
    elif isinstance(obj, BaseException):
        buf.append(_EXC)
        _encode(type(obj).__name__, buf, depth + 1)
        # Store ``args`` so exact round trips survive (e.g. ``KeyError("k")``
        # keeps ``args == ("k",)``); fall back to ``str(exc)`` only when the
        # args themselves are not encodable, so a job failure can always be
        # queued without ever calling pickle.
        try:
            _encode(obj.args, buf, depth + 1)
        except QueueSerializationError:
            _encode(str(obj), buf, depth + 1)
    else:
        raise QueueSerializationError(
            f"unsupported payload type {type(obj).__name__!r}; "
            "only allowlisted primitives may be queued"
        )


def _encode_sequence(buf: bytearray, tag: int, items: tuple | list, depth: int) -> None:
    if len(items) > MAX_CONTAINER_ITEMS:
        raise QueueSerializationError(
            f"sequence with {len(items)} items exceeds {MAX_CONTAINER_ITEMS} item limit"
        )
    buf.append(tag)
    _encode_uint(buf, len(items))
    for item in items:
        _encode(item, buf, depth + 1)


def _encode_uint(buf: bytearray, value: int) -> None:
    """Unsigned base-128 varint, little-endian, high bit = continuation."""
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            buf.append(byte | 0x80)
        else:
            buf.append(byte)
            return


def _encode_zigzag(buf: bytearray, value: int) -> None:
    """Signed integer as a zigzag varint (deterministic, compact)."""
    if value >= 0:
        _encode_uint(buf, value << 1)
    else:
        _encode_uint(buf, (-value << 1) - 1)


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def loads(data: Any) -> Any:
    """Decode a queue payload, rejecting anything outside the allowlist.

    Raises ``QueueDeserializationError`` for missing/bad headers, unknown
    versions, oversize or over-deep payloads, unknown tags, malformed values,
    or trailing garbage. A payload this function accepts is guaranteed to
    contain only allowlisted primitive values.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise QueueDeserializationError("payload must be bytes")
    data = bytes(data)
    if len(data) < HEADER_LEN:
        raise QueueDeserializationError("payload shorter than header")
    if data[: len(MAGIC)] != MAGIC:
        raise QueueDeserializationError("payload missing cygnus queue magic header")
    if data[len(MAGIC)] != VERSION:
        raise QueueDeserializationError(
            f"unsupported queue payload version {data[len(MAGIC)]!r}"
        )
    if len(data) > MAX_SERIALIZED_BYTES:
        raise QueueDeserializationError(
            f"payload of {len(data)} bytes exceeds {MAX_SERIALIZED_BYTES} byte limit"
        )
    value, pos = _decode(data, HEADER_LEN, len(data), 0)
    if pos != len(data):
        raise QueueDeserializationError("trailing bytes after payload")
    return value


def _decode(data: bytes, pos: int, end: int, depth: int) -> tuple[Any, int]:
    if depth > MAX_DEPTH:
        raise QueueDeserializationError(f"payload nests deeper than {MAX_DEPTH} levels")
    if pos >= end:
        raise QueueDeserializationError("truncated payload")
    tag = data[pos]
    pos += 1

    if tag == _NIL:
        return None, pos
    if tag == _FALSE:
        return False, pos
    if tag == _TRUE:
        return True, pos
    if tag == _INT:
        return _decode_zigzag(data, pos, end)
    if tag == _STR:
        length, pos = _decode_uint(data, pos, end)
        if length > end - pos:
            raise QueueDeserializationError("truncated string")
        try:
            return data[pos : pos + length].decode("utf-8"), pos + length
        except UnicodeDecodeError as exc:
            raise QueueDeserializationError("string is not valid utf-8") from exc
    if tag == _BYTES:
        length, pos = _decode_uint(data, pos, end)
        if length > end - pos:
            raise QueueDeserializationError("truncated bytes")
        return data[pos : pos + length], pos + length
    if tag in (_LIST, _TUPLE):
        count, pos = _decode_uint(data, pos, end)
        if count > MAX_CONTAINER_ITEMS:
            raise QueueDeserializationError(
                f"container with {count} items exceeds {MAX_CONTAINER_ITEMS} item limit"
            )
        items = []
        for _ in range(count):
            item, pos = _decode(data, pos, end, depth + 1)
            items.append(item)
        return (tuple(items) if tag == _TUPLE else items), pos
    if tag == _MAP:
        count, pos = _decode_uint(data, pos, end)
        if count > MAX_CONTAINER_ITEMS:
            raise QueueDeserializationError(
                f"map with {count} items exceeds {MAX_CONTAINER_ITEMS} item limit"
            )
        mapping = {}
        for _ in range(count):
            key, pos = _decode(data, pos, end, depth + 1)
            if not isinstance(key, str):
                raise QueueDeserializationError("map key is not a string")
            value, pos = _decode(data, pos, end, depth + 1)
            mapping[key] = value
        return mapping, pos
    if tag == _EXC:
        name, pos = _decode(data, pos, end, depth + 1)
        args, pos = _decode(data, pos, end, depth + 1)
        if not isinstance(name, str):
            raise QueueDeserializationError("malformed exception record")
        cls = _SAFE_EXCEPTION_CLASSES.get(name, _FALLBACK_EXCEPTION)
        # New records store the exception ``args`` tuple; legacy/fallback
        # records store ``str(exc)``. Either way only allowlisted primitives
        # are ever fed to the reconstructed exception.
        if isinstance(args, tuple):
            try:
                return cls(*args), pos
            except Exception:
                return _FALLBACK_EXCEPTION(*args), pos
        if isinstance(args, str):
            try:
                return cls(args), pos
            except Exception:
                return _FALLBACK_EXCEPTION(args), pos
        raise QueueDeserializationError("malformed exception record")
    raise QueueDeserializationError(f"unknown payload tag 0x{tag:02x}")


def _decode_uint(data: bytes, pos: int, end: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= end:
            raise QueueDeserializationError("truncated varint")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > _MAX_VARINT_SHIFT:
            raise QueueDeserializationError("varint exceeds allowed length")


def _decode_zigzag(data: bytes, pos: int, end: int) -> tuple[int, int]:
    value, pos = _decode_uint(data, pos, end)
    if value & 1:
        return -(value >> 1) - 1, pos
    return value >> 1, pos


#: arq-compatible serializer entry points (see ``arq.jobs.Serializer`` and
#: ``arq.jobs.Deserializer``).
Serializer = Callable[[dict[str, Any]], bytes]
Deserializer = Callable[[bytes], dict[str, Any]]

__all__ = [
    "MAGIC",
    "VERSION",
    "HEADER_LEN",
    "MAX_SERIALIZED_BYTES",
    "MAX_DEPTH",
    "MAX_CONTAINER_ITEMS",
    "QueueSerializationError",
    "QueueDeserializationError",
    "dumps",
    "loads",
]
