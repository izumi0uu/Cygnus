"""CYG-129 regression tests: source ingestion boundary hardening.

Covers the acceptance surface:
  - SSRF: private/link-local/loopback/multicast URL destinations rejected
    before and after redirects, with pinned (DNS-rebinding-safe) fetch wiring.
  - Bounded retrieval: streaming byte budget + content-length fast-fail.
  - Archive limits: member count, compression ratio, aggregate uncompressed
    size, zip-slip path traversal (docx/xlsx/pptx paths).
  - XML limits: DOCTYPE/ENTITY rejection and nesting-depth cap.
  - Upload bound: oversized uploads (including preserve_verbatim) fail with
    413 before any lasting mutation; at-limit uploads flow through.
  - Object-level scope: every source read/mutation endpoint returns 404 for
    out-of-scope and missing sources (no ID enumeration), while in-scope and
    global sources remain readable.
"""

from __future__ import annotations

import asyncio
import io
import unittest
import uuid
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from fastapi.datastructures import UploadFile

from cygnus.runtime.config import settings
from cygnus.runtime.database.models import Source
from cygnus.runtime.routers import sources as sources_router
from cygnus.substrate import source_text, source_url


def _run(coro):
    return asyncio.run(coro)


def _make_zip(members: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            archive.writestr(name, data)
    return buffer.getvalue()


class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        pass


class _RecordingNetworkBackend:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def connect_tcp(self, **kwargs):
        self.calls.append(kwargs)
        return object()

    async def sleep(self, seconds: float) -> None:
        return None


class SourceURLValidationTests(unittest.TestCase):
    def test_rejects_non_public_destinations(self) -> None:
        private_targets = [
            "http://127.0.0.1/x",  # loopback
            "http://10.1.2.3/x",  # RFC1918 private
            "http://169.254.169.254/latest/meta-data",  # link-local metadata
            "http://224.0.0.1/x",  # multicast
            "http://[::1]/x",  # IPv6 loopback
            "http://[fc00::1]/x",  # IPv6 ULA
        ]
        for url in private_targets:
            with self.subTest(url=url):
                with self.assertRaises(source_url.SourceURLValidationError):
                    _run(source_url.validate_source_url(url))

    def test_rejects_non_http_schemes_and_credentials(self) -> None:
        for url in (
            "file:///etc/passwd",
            "ftp://example.com/x",
            "gopher://example.com/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(source_url.SourceURLValidationError):
                    _run(source_url.validate_source_url(url))
        with self.assertRaises(source_url.SourceURLValidationError):
            _run(source_url.validate_source_url("http://user:pass@example.com/x"))

    def test_accepts_public_destination(self) -> None:
        validated = _run(source_url.validate_source_url("http://93.184.216.34/path"))
        self.assertEqual(validated.host, "93.184.216.34")
        self.assertEqual(validated.url, "http://93.184.216.34/path")


class SourceURLFetchBoundTests(unittest.TestCase):
    def _public_target(self, url: str) -> source_url.ValidatedSourceURL:
        return source_url.ValidatedSourceURL(
            url=url, host="example.com", port=80, addresses=("93.184.216.34",)
        )

    def test_redirect_to_private_destination_is_rejected(self) -> None:
        hops = [
            source_url._FetchedHop(
                302, httpx.Headers({"location": "http://10.0.0.1/internal"}), b""
            )
        ]

        async def _validate(url: str):
            if url.startswith("http://10.0.0.1"):
                raise source_url.SourceURLValidationError(
                    "Source URL resolves to a non-public address"
                )
            return self._public_target(url)

        with (
            patch.object(source_url, "validate_source_url", side_effect=_validate),
            patch.object(source_url, "_fetch_one_hop", side_effect=hops),
        ):
            with self.assertRaises(source_url.SourceURLValidationError):
                _run(
                    source_url.fetch_public_source_url(
                        "http://example.com/start", max_bytes=1000
                    )
                )

    def test_redirect_loop_is_rejected(self) -> None:
        hops = [
            source_url._FetchedHop(
                302, httpx.Headers({"location": "http://example.com/b"}), b""
            ),
            source_url._FetchedHop(
                302, httpx.Headers({"location": "http://example.com/a"}), b""
            ),
        ]

        async def _validate(url: str):
            return self._public_target(url)

        with (
            patch.object(source_url, "validate_source_url", side_effect=_validate),
            patch.object(source_url, "_fetch_one_hop", side_effect=hops),
        ):
            with self.assertRaises(source_url.SourceURLValidationError):
                _run(
                    source_url.fetch_public_source_url(
                        "http://example.com/a", max_bytes=1000
                    )
                )

    def test_redirect_chain_limit_is_enforced(self) -> None:
        async def _validate(url: str):
            return self._public_target(url)

        redirect = source_url._FetchedHop(
            302, httpx.Headers({"location": "http://example.com/next"}), b""
        )
        hops = [redirect] * (source_url._MAX_REDIRECTS + 1)

        with (
            patch.object(source_url, "validate_source_url", side_effect=_validate),
            patch.object(source_url, "_fetch_one_hop", side_effect=hops),
        ):
            with self.assertRaises(source_url.SourceURLValidationError):
                _run(
                    source_url.fetch_public_source_url(
                        "http://example.com/start", max_bytes=1000
                    )
                )

    def test_normal_redirect_flow_returns_bounded_payload(self) -> None:
        hops = [
            source_url._FetchedHop(
                302, httpx.Headers({"location": "http://example.com/final"}), b""
            ),
            source_url._FetchedHop(
                200, httpx.Headers({"content-type": "text/plain"}), b"hello"
            ),
        ]

        async def _validate(url: str):
            return self._public_target(url)

        with (
            patch.object(source_url, "validate_source_url", side_effect=_validate),
            patch.object(source_url, "_fetch_one_hop", side_effect=hops),
        ):
            fetched = _run(
                source_url.fetch_public_source_url(
                    "http://example.com/start", max_bytes=1000
                )
            )

        self.assertEqual(fetched.url, "http://example.com/final")
        self.assertEqual(fetched.payload, b"hello")

    def test_streaming_byte_budget_is_enforced(self) -> None:
        response = httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            stream=_ChunkStream([b"x" * 1000] * 5),
        )
        with self.assertRaises(source_url.SourceURLPayloadTooLarge):
            _run(source_url._read_bounded_response(response, 2000))

    def test_content_length_fast_fail_is_enforced(self) -> None:
        response = httpx.Response(
            200,
            headers={"content-length": "99999"},
            stream=_ChunkStream([b"a"]),
        )
        with self.assertRaises(source_url.SourceURLPayloadTooLarge):
            _run(source_url._read_bounded_response(response, 1000))

    def test_within_budget_payload_is_returned(self) -> None:
        response = httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            stream=_ChunkStream([b"hello"]),
        )
        self.assertEqual(
            _run(source_url._read_bounded_response(response, 1000)), b"hello"
        )

    def test_connection_uses_validated_address_not_rebound_hostname(self) -> None:
        backend = _RecordingNetworkBackend()
        target = source_url.ValidatedSourceURL(
            url="http://example.com/source",
            host="example.com",
            port=80,
            addresses=("93.184.216.34",),
        )
        with patch.object(source_url.httpcore, "AnyIOBackend", return_value=backend):
            stream = _run(
                source_url._PinnedAsyncNetworkBackend(target).connect_tcp(
                    host="example.com",
                    port=80,
                )
            )

        self.assertIsNotNone(stream)
        self.assertEqual(
            backend.calls,
            [
                {
                    "host": "93.184.216.34",
                    "port": 80,
                    "timeout": None,
                    "local_address": None,
                    "socket_options": None,
                }
            ],
        )

    def test_connection_rejects_private_address_at_connection_boundary(self) -> None:
        backend = _RecordingNetworkBackend()
        target = source_url.ValidatedSourceURL(
            url="http://example.com/source",
            host="example.com",
            port=80,
            addresses=("127.0.0.1",),
        )
        with patch.object(source_url.httpcore, "AnyIOBackend", return_value=backend):
            with self.assertRaises(source_url.httpcore.ConnectError):
                _run(
                    source_url._PinnedAsyncNetworkBackend(target).connect_tcp(
                        host="example.com",
                        port=80,
                    )
                )

        self.assertEqual(backend.calls, [])


class SourceArchiveGuardTests(unittest.TestCase):
    def test_normal_archive_passes(self) -> None:
        payload = _make_zip([("a.txt", b"hello world" * 10)])
        source_text._guard_zip_bounds(
            payload, max_bytes=10_000, max_members=10, max_ratio=100
        )

    def test_compression_ratio_bomb_is_rejected(self) -> None:
        payload = _make_zip([("bomb.txt", b"A" * 20_000)])
        with self.assertRaises(source_text.SourceArchiveLimitError):
            source_text._guard_zip_bounds(
                payload, max_bytes=10_000_000, max_members=10, max_ratio=100
            )

    def test_member_count_is_enforced(self) -> None:
        payload = _make_zip([(f"f{i}.txt", b"x") for i in range(6)])
        with self.assertRaises(source_text.SourceArchiveLimitError):
            source_text._guard_zip_bounds(
                payload, max_bytes=10_000, max_members=3, max_ratio=100
            )

    def test_aggregate_uncompressed_size_is_enforced(self) -> None:
        payload = _make_zip([("a.txt", b"x" * 100), ("b.txt", b"y" * 100)])
        with self.assertRaises(source_text.SourceArchiveLimitError):
            source_text._guard_zip_bounds(
                payload, max_bytes=150, max_members=10, max_ratio=100
            )

    def test_zip_slip_paths_are_rejected(self) -> None:
        for name in (
            "../evil.txt",
            "nested/../../evil.txt",
            "/abs.txt",
            "..\\evil.txt",
        ):
            with self.subTest(member=name):
                payload = _make_zip([(name, b"x")])
                with self.assertRaises(source_text.SourceArchiveLimitError):
                    source_text._guard_zip_bounds(
                        payload, max_bytes=10_000, max_members=10, max_ratio=100
                    )

    def test_bomb_archive_rejected_before_pptx_extraction(self) -> None:
        payload = _make_zip([("ppt/slides/slide1.xml", b"<p:sld/>" + b"A" * 50_000)])
        with self.assertRaises(source_text.SourceArchiveLimitError):
            _run(source_text._extract_text_from_file(payload, "deck.pptx"))


class SourceXMLGuardTests(unittest.TestCase):
    def test_doctype_and_entity_declarations_are_rejected(self) -> None:
        payloads = [
            b'<!DOCTYPE foo [<!ENTITY a "x">]><foo>&a;</foo>',
            b'<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///etc/passwd">]><foo>&x;</foo>',
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(source_text.SourceXMLLimitError):
                    source_text._parse_xml_bytes(payload, max_depth=10)

    def test_nesting_depth_is_enforced(self) -> None:
        with self.assertRaises(source_text.SourceXMLLimitError):
            source_text._parse_xml_bytes(b"<a><b><c/></b></a>", max_depth=2)

    def test_xml_byte_limit_is_enforced_before_parse(self) -> None:
        with self.assertRaises(source_text.SourceXMLLimitError):
            source_text._parse_xml_bytes(
                b"<a>more-than-ten-bytes</a>",
                max_depth=4,
                max_bytes=10,
            )

    def test_malformed_xml_is_reported_as_a_source_limit_error(self) -> None:
        with self.assertRaises(source_text.SourceXMLLimitError):
            source_text._parse_xml_bytes(b"<unclosed>", max_depth=4)

    def test_normal_xml_parses(self) -> None:
        root = source_text._parse_xml_bytes(b"<a><b/></a>", max_depth=4)
        self.assertEqual(root.tag, "a")


class SourceContentTypeGuardTests(unittest.TestCase):
    def _remote_extract(self, *, url: str, content_type: str, payload: bytes):
        fetched = source_url.SourceURLResponse(
            url=url,
            content_type=content_type,
            payload=payload,
        )
        with patch.object(source_text, "fetch_public_source_url", return_value=fetched):
            return _run(source_text._extract_text_from_url(url))

    def test_unsupported_response_content_type_is_rejected(self) -> None:
        with self.assertRaises(source_text.SourceContentTypeError):
            self._remote_extract(
                url="https://example.com/document.txt",
                content_type="image/png",
                payload=b"\x89PNG\r\n\x1a\n",
            )

    def test_filename_response_type_mismatch_is_rejected(self) -> None:
        with self.assertRaises(source_text.SourceContentTypeError):
            self._remote_extract(
                url="https://example.com/document.pdf",
                content_type="text/plain",
                payload=b"%PDF-1.7 not actually fetched",
            )

    def test_xml_source_path_uses_entity_and_depth_guard(self) -> None:
        with self.assertRaises(source_text.SourceXMLLimitError):
            _run(
                source_text._extract_text_from_file(
                    b'<!DOCTYPE foo [<!ENTITY a "x">]><foo>&a;</foo>',
                    "untrusted.xml",
                )
            )


class SourceUploadBoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(
            role="employee",
            global_role="contributor",
            department_ids=[],
            id=uuid.uuid4(),
        )
        self._size_patch = patch.object(settings, "max_source_upload_bytes", 1024)
        self._size_patch.start()
        self.addCleanup(self._size_patch.stop)

    def _upload(
        self,
        payload: bytes,
        *,
        preserve_verbatim: bool = False,
        department_ids=None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        db=None,
        language: str = "en",
    ):
        upload = UploadFile(file=io.BytesIO(payload), filename="doc.txt")
        return _run(
            sources_router.upload_source(
                file=upload,
                title=None,
                knowledge_type_id=None,
                department_ids=department_ids,
                scope_type=scope_type,
                scope_id=scope_id,
                preserve_verbatim=preserve_verbatim,
                language=language,
                db=db,
                user=cast(Any, self.user),
            )
        )

    class _BoomDB:
        async def execute(self, *args, **kwargs):
            raise AssertionError("db touched on oversized upload")

        def add(self, *args, **kwargs):
            raise AssertionError("db touched on oversized upload")

    def test_oversized_upload_fails_before_mutation(self) -> None:
        self.user.role = "admin"
        with self.assertRaises(HTTPException) as ctx:
            self._upload(b"x" * 2048, db=self._BoomDB())
        self.assertEqual(ctx.exception.status_code, 413)

    def test_preserve_verbatim_does_not_bypass_size_limit(self) -> None:
        self.user.role = "admin"
        with self.assertRaises(HTTPException) as ctx:
            self._upload(b"x" * 2048, preserve_verbatim=True, db=self._BoomDB())
        self.assertEqual(ctx.exception.status_code, 413)

    def test_foreign_department_assignment_rejected_before_mutation(self) -> None:
        own_department = uuid.uuid4()
        other_department = uuid.uuid4()
        self.user.department_ids = [own_department]
        with self.assertRaises(HTTPException) as ctx:
            self._upload(
                b"ok",
                department_ids=str(other_department),
                scope_type="department",
                scope_id=str(own_department),
                db=self._BoomDB(),
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_foreign_department_scope_rejected_before_mutation(self) -> None:
        own_department = uuid.uuid4()
        other_department = uuid.uuid4()
        self.user.department_ids = [own_department]
        with self.assertRaises(HTTPException) as ctx:
            self._upload(
                b"ok",
                scope_type="department",
                scope_id=str(other_department),
                db=self._BoomDB(),
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_own_dept_user_cannot_create_a_global_source(self) -> None:
        own_department = uuid.uuid4()
        self.user.department_ids = [own_department]
        with self.assertRaises(HTTPException) as ctx:
            self._upload(
                b"ok",
                department_ids=str(own_department),
                db=self._BoomDB(),
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_department_scope_derives_its_document_link(self) -> None:
        own_department = uuid.uuid4()
        self.user.department_ids = [own_department]
        spy = _SpySession()
        with (
            patch(
                "cygnus.runtime.services.storage_service.storage_service.upload_stream_async",
                AsyncMock(return_value="stored"),
            ),
            patch.object(
                sources_router,
                "enqueue_source_ingest_file",
                AsyncMock(return_value="job-1"),
            ),
        ):
            self._upload(
                b"scope-safe",
                scope_type="department",
                scope_id=str(own_department),
                db=spy,
            )

        links = [obj for obj in spy.added if hasattr(obj, "department_id")]
        self.assertEqual([link.department_id for link in links], [own_department])

    def test_at_limit_upload_streams_to_storage(self) -> None:
        self.user.role = "admin"
        payload = b"x" * 1024
        read_sizes: list[int] = []

        class ChunkedUpload:
            filename = "doc.txt"

            def __init__(self) -> None:
                self._remaining = payload

            async def read(self, size: int = -1) -> bytes:
                read_sizes.append(size)
                chunk, self._remaining = (
                    self._remaining[:size],
                    self._remaining[size:],
                )
                return chunk

        captured: dict[str, object] = {}

        async def capture_upload_stream(**kwargs) -> str:
            captured.update(kwargs)
            captured["payload"] = kwargs["stream"].read()
            return kwargs["object_name"]

        spy = _SpySession()
        with (
            patch(
                "cygnus.runtime.services.storage_service.storage_service.upload_stream_async",
                AsyncMock(side_effect=capture_upload_stream),
            ) as store_upload,
            patch.object(
                sources_router,
                "enqueue_source_ingest_file",
                AsyncMock(return_value="job-1"),
            ),
        ):
            response = _run(
                sources_router.upload_source(
                    file=cast(Any, ChunkedUpload()),
                    title=None,
                    knowledge_type_id=None,
                    department_ids=None,
                    scope_type=None,
                    scope_id=None,
                    preserve_verbatim=False,
                    language="en",
                    db=cast(Any, spy),
                    user=cast(Any, self.user),
                )
            )

        self.assertEqual(response.file_size, len(payload))
        self.assertEqual(response.status, "pending")
        store_upload.assert_awaited_once()
        self.assertEqual(read_sizes, [sources_router._UPLOAD_STREAM_CHUNK_BYTES] * 2)
        self.assertEqual(captured["length"], len(payload))
        self.assertEqual(captured["payload"], payload)


class SourceURLEndpointValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(
            role="employee",
            global_role="contributor",
            department_ids=[],
            id=uuid.uuid4(),
        )

    class _BoomDB:
        async def execute(self, *args, **kwargs):
            raise AssertionError("db touched on invalid URL")

        def add(self, *args, **kwargs):
            raise AssertionError("db touched on invalid URL")

    def _add_url(
        self,
        url: str,
        department_ids=None,
        language: str = "en",
        scope_type: str | None = None,
        scope_id: uuid.UUID | None = None,
    ):
        return _run(
            sources_router.add_url_source(
                sources_router.SourceCreateURL(
                    url=url,
                    department_ids=department_ids or [],
                    scope_type=scope_type,
                    scope_id=scope_id,
                    language=language,
                ),
                db=cast(Any, self._BoomDB()),
                user=cast(Any, self.user),
            )
        )

    def test_private_destination_rejected_before_persist(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            self._add_url("http://127.0.0.1/secret")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_non_http_scheme_rejected_before_persist(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            self._add_url("ftp://example.com/x")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_foreign_department_assignment_rejected_before_persist(self) -> None:
        own_department = uuid.uuid4()
        other_department = uuid.uuid4()
        self.user.department_ids = [own_department]
        validated = source_url.ValidatedSourceURL(
            url="https://example.com/x",
            host="example.com",
            port=443,
            addresses=("93.184.216.34",),
        )
        with patch.object(
            sources_router,
            "validate_source_url",
            AsyncMock(return_value=validated),
        ):
            with self.assertRaises(HTTPException) as ctx:
                self._add_url(
                    "https://example.com/x",
                    department_ids=[other_department],
                    scope_type="department",
                    scope_id=own_department,
                )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_foreign_department_scope_rejected_before_persist(self) -> None:
        own_department = uuid.uuid4()
        other_department = uuid.uuid4()
        self.user.department_ids = [own_department]
        validated = source_url.ValidatedSourceURL(
            url="https://example.com/source.txt",
            host="example.com",
            port=443,
            addresses=("93.184.216.34",),
        )
        with patch.object(
            sources_router,
            "validate_source_url",
            AsyncMock(return_value=validated),
        ):
            with self.assertRaises(HTTPException) as ctx:
                self._add_url(
                    "https://example.com/source.txt",
                    scope_type="department",
                    scope_id=other_department,
                )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_own_dept_user_cannot_create_a_global_url_source(self) -> None:
        own_department = uuid.uuid4()
        self.user.department_ids = [own_department]
        validated = source_url.ValidatedSourceURL(
            url="https://example.com/source.txt",
            host="example.com",
            port=443,
            addresses=("93.184.216.34",),
        )
        with patch.object(
            sources_router,
            "validate_source_url",
            AsyncMock(return_value=validated),
        ):
            with self.assertRaises(HTTPException) as ctx:
                self._add_url(
                    "https://example.com/source.txt",
                    department_ids=[own_department],
                )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_department_scope_derives_url_document_link(self) -> None:
        own_department = uuid.uuid4()
        self.user.department_ids = [own_department]
        spy = _SpySession()
        validated = source_url.ValidatedSourceURL(
            url="https://example.com/public-source.txt",
            host="example.com",
            port=443,
            addresses=("93.184.216.34",),
        )
        with (
            patch.object(
                sources_router,
                "validate_source_url",
                AsyncMock(return_value=validated),
            ),
            patch.object(sources_router, "log_audit", AsyncMock()),
            patch.object(
                sources_router,
                "enqueue_source_ingest_url",
                AsyncMock(return_value="job-url"),
            ),
        ):
            _run(
                sources_router.add_url_source(
                    sources_router.SourceCreateURL(
                        url="https://example.com/public-source.txt",
                        scope_type="department",
                        scope_id=own_department,
                        language="en",
                    ),
                    db=cast(Any, spy),
                    user=cast(Any, self.user),
                )
            )

        links = [obj for obj in spy.added if hasattr(obj, "department_id")]
        self.assertEqual([link.department_id for link in links], [own_department])


class SourceObjectScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.own_dept = uuid.uuid4()
        self.other_dept = uuid.uuid4()
        self.user = SimpleNamespace(
            role="employee",
            global_role="viewer",
            department_ids=[self.own_dept],
            id=uuid.uuid4(),
        )
        self._perms_patch = patch(
            "cygnus.runtime.services.permission_engine._get_user_permissions",
            return_value={
                "doc:read:own_dept",
                "doc:edit:own_dept",
                "doc:delete:own_dept",
            },
        )
        self._perms_patch.start()
        self.addCleanup(self._perms_patch.stop)

    def _cross_dept_db(self, source) -> _FakeDB:
        return _FakeDB(
            source=source,
            dept_ids=[self.other_dept],
            wiki=0,
            images=0,
            visible=False,
        )

    def test_out_of_scope_sources_return_404_on_every_endpoint(self) -> None:
        source = _make_source()
        # _FakeDB and the SimpleNamespace user are deliberate
        # AsyncSession/Employee doubles; cast once at the endpoint boundary.
        db = cast(Any, self._cross_dept_db(source))
        user = cast(Any, self.user)
        cases = [
            (
                "get_source",
                lambda: sources_router.get_source(source.id, db=db, user=user),
            ),
            (
                "progress",
                lambda: sources_router.get_source_progress(source.id, db=db, user=user),
            ),
            (
                "update",
                lambda: sources_router.update_source(
                    source.id, sources_router.SourceUpdate(), db=db, user=user
                ),
            ),
            ("retry", lambda: sources_router.retry_source(source.id, db=db, user=user)),
            (
                "delete",
                lambda: sources_router.delete_source(source.id, db=db, user=user),
            ),
            (
                "plan",
                lambda: sources_router.get_compilation_plan(
                    source.id, db=db, user=user
                ),
            ),
            (
                "approve-extraction",
                lambda: sources_router.approve_extraction(source.id, db=db, user=user),
            ),
            (
                "plan/approve",
                lambda: sources_router.approve_compilation_plan(
                    source.id, sources_router.PlanApproveRequest(), db=db, user=user
                ),
            ),
            (
                "plan/regenerate",
                lambda: sources_router.regenerate_compilation_plan(
                    source.id,
                    sources_router.PlanRegenerateRequest(note="x"),
                    db=db,
                    user=user,
                ),
            ),
            (
                "plan/reject",
                lambda: sources_router.reject_compilation_plan(
                    source.id,
                    sources_router.PlanRejectRequest(note="x"),
                    db=db,
                    user=user,
                ),
            ),
            (
                "freshness",
                lambda: sources_router.attest_source_freshness(
                    source.id,
                    sources_router.FreshnessAttestationRequest(
                        freshness_state="fresh", reason="x"
                    ),
                    db=db,
                    user=user,
                ),
            ),
        ]
        for name, call in cases:
            with self.subTest(endpoint=name):
                with self.assertRaises(HTTPException) as ctx:
                    _run(call())
                self.assertEqual(ctx.exception.status_code, 404)

    def test_missing_source_returns_404(self) -> None:
        db = cast(Any, _FakeDB(source=None))
        user = cast(Any, self.user)
        with self.assertRaises(HTTPException) as ctx:
            _run(sources_router.get_source(uuid.uuid4(), db=db, user=user))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_in_scope_source_is_readable(self) -> None:
        source = _make_source()
        db = cast(
            Any, _FakeDB(source=source, dept_ids=[self.own_dept], wiki=2, images=0)
        )
        user = cast(Any, self.user)
        detail = _run(sources_router.get_source(source.id, db=db, user=user))
        self.assertEqual(detail.title, "T")
        self.assertEqual(detail.wiki_page_count, 2)

    def test_global_source_is_readable(self) -> None:
        source = _make_source()
        db = cast(Any, _FakeDB(source=source, dept_ids=[], wiki=0, images=0))
        user = cast(Any, self.user)
        detail = _run(sources_router.get_source(source.id, db=db, user=user))
        self.assertEqual(detail.title, "T")

    def test_scoped_source_lookup_keeps_authorization_in_sql(self) -> None:
        source = _make_source()
        db = _FakeDB(source=source, visible=False)
        with self.assertRaises(HTTPException):
            _run(
                sources_router._get_scoped_source(
                    cast(Any, db), source.id, cast(Any, self.user), "read"
                )
            )

        self.assertIn("source_departments", str(db.statements[0]))

    def test_cross_department_download_never_presigns_storage(self) -> None:
        source = _make_source(minio_key="sources/hidden/original/secret.txt")
        db = cast(Any, self._cross_dept_db(source))
        with patch(
            "cygnus.runtime.services.storage_service.storage_service.get_presigned_url"
        ) as get_presigned_url:
            with self.assertRaises(HTTPException) as ctx:
                _run(
                    sources_router.get_source(
                        source.id, db=db, user=cast(Any, self.user)
                    )
                )

        self.assertEqual(ctx.exception.status_code, 404)
        get_presigned_url.assert_not_called()

    def test_no_document_permission_returns_same_not_found(self) -> None:
        source = _make_source()
        db = cast(Any, _FakeDB(source=source, visible=False))
        with patch(
            "cygnus.runtime.services.permission_engine._get_user_permissions",
            return_value=set(),
        ):
            with self.assertRaises(HTTPException) as ctx:
                _run(
                    sources_router.get_source(
                        source.id, db=db, user=cast(Any, self.user)
                    )
                )

        self.assertEqual(ctx.exception.status_code, 404)

    def test_admin_can_read_cross_department_source(self) -> None:
        source = _make_source()
        admin = SimpleNamespace(
            role="admin",
            global_role="admin",
            department_ids=[],
            id=uuid.uuid4(),
        )
        detail = _run(
            sources_router.get_source(
                source.id,
                db=cast(Any, _FakeDB(source=source, dept_ids=[self.other_dept])),
                user=cast(Any, admin),
            )
        )

        self.assertEqual(detail.id, source.id)


class SourceAssignmentUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.own_dept = uuid.uuid4()
        self.other_dept = uuid.uuid4()
        self.user = SimpleNamespace(
            role="employee",
            global_role="viewer",
            department_ids=[self.own_dept],
            id=uuid.uuid4(),
        )

    def test_scope_change_cleans_old_identity_and_derives_scope_link(self) -> None:
        source = _make_source(scope_type="global", scope_id=None)
        db = _UpdateDB()
        observed_scopes: list[tuple[str, uuid.UUID | None]] = []

        async def resolve_old_scopes(_db, current_source):
            observed_scopes.append((current_source.scope_type, current_source.scope_id))
            return [("global", None)]

        async def enqueue_reingest(*_args, **_kwargs):
            source.dispatch_generation += 1
            return "job-scope"

        with (
            patch.object(
                sources_router,
                "_get_scoped_source",
                AsyncMock(side_effect=[source, source]),
            ),
            patch.object(
                sources_router,
                "_get_user_permissions",
                return_value={"doc:edit:own_dept"},
            ),
            patch(
                "cygnus.runtime.ai.mrp.pipeline._resolve_wiki_scopes",
                AsyncMock(side_effect=resolve_old_scopes),
            ),
            patch(
                "cygnus.review.contributions.invalidate_stale_compiler_drafts",
                AsyncMock(),
            ) as invalidate,
            patch(
                "cygnus.runtime.services.wiki_service.detach_source_from_wiki",
                AsyncMock(return_value=1),
            ) as detach,
            patch(
                "cygnus.runtime.services.wiki_service.regenerate_index",
                AsyncMock(),
            ) as regenerate,
            patch.object(sources_router, "log_audit", AsyncMock()),
            patch.object(
                sources_router,
                "enqueue_source_map_reduce",
                AsyncMock(side_effect=enqueue_reingest),
            ),
        ):
            response = _run(
                sources_router.update_source(
                    source.id,
                    sources_router.SourceUpdate(
                        scope_type="department",
                        scope_id=self.own_dept,
                    ),
                    db=cast(Any, db),
                    user=cast(Any, self.user),
                )
            )

        self.assertEqual(observed_scopes, [("global", None)])
        invalidate.assert_awaited_once_with(
            cast(Any, db),
            source_id=source.id,
            current_generation=2,
            reason="Source re-ingest required after scope change",
        )
        detach.assert_awaited_once_with(cast(Any, db), source.id)
        regenerate.assert_awaited_once_with(
            cast(Any, db), scope_type="global", scope_id=None
        )
        self.assertEqual(source.scope_type, "department")
        self.assertEqual(source.scope_id, self.own_dept)
        self.assertEqual(source.status, "processing")
        self.assertEqual(response.status, "processing")
        self.assertEqual(source.dispatch_generation, 2)
        links = [obj for obj in db.added if hasattr(obj, "department_id")]
        self.assertEqual([link.department_id for link in links], [self.own_dept])

    def test_scope_only_invalid_value_fails_before_mutation(self) -> None:
        source = _make_source()
        db = _UpdateDB()
        with (
            patch.object(
                sources_router,
                "_get_scoped_source",
                AsyncMock(return_value=source),
            ),
            patch.object(
                sources_router,
                "_get_user_permissions",
                return_value={"doc:edit:own_dept"},
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                _run(
                    sources_router.update_source(
                        source.id,
                        sources_router.SourceUpdate(scope_type="project"),
                        db=cast(Any, db),
                        user=cast(Any, self.user),
                    )
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(source.scope_type, "global")
        self.assertEqual(db.added, [])

    def test_scope_only_foreign_department_fails_before_mutation(self) -> None:
        source = _make_source()
        db = _UpdateDB()
        with (
            patch.object(
                sources_router,
                "_get_scoped_source",
                AsyncMock(return_value=source),
            ),
            patch.object(
                sources_router,
                "_get_user_permissions",
                return_value={"doc:edit:own_dept"},
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                _run(
                    sources_router.update_source(
                        source.id,
                        sources_router.SourceUpdate(
                            scope_type="department",
                            scope_id=self.other_dept,
                        ),
                        db=cast(Any, db),
                        user=cast(Any, self.user),
                    )
                )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(source.scope_type, "global")
        self.assertEqual(db.added, [])

    def test_own_dept_user_cannot_make_a_source_global(self) -> None:
        source = _make_source(scope_type="department", scope_id=self.own_dept)
        db = _UpdateDB(department_ids=[self.own_dept])
        with (
            patch.object(
                sources_router,
                "_get_scoped_source",
                AsyncMock(return_value=source),
            ),
            patch.object(
                sources_router,
                "_get_user_permissions",
                return_value={"doc:edit:own_dept"},
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                _run(
                    sources_router.update_source(
                        source.id,
                        sources_router.SourceUpdate(scope_type="global"),
                        db=cast(Any, db),
                        user=cast(Any, self.user),
                    )
                )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(source.scope_type, "department")
        self.assertEqual(source.scope_id, self.own_dept)
        self.assertEqual(db.added, [])


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, value, rows: bool = False) -> None:
        self._value = value
        self._rows = rows

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value if self._value is not None else 0

    def scalars(self):
        return self

    def all(self):
        if self._rows:
            return [(v,) for v in self._value]
        return self._value if isinstance(self._value, list) else []


class _FakeDB:
    def __init__(
        self,
        source=None,
        dept_ids=(),
        wiki: int = 0,
        images: int = 0,
        *,
        visible: bool = True,
    ) -> None:
        self._source = source
        self._dept_ids = list(dept_ids)
        self._wiki = wiki
        self._images = images
        self._visible = visible
        self.statements: list[object] = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        text = str(stmt)
        # The direct source query now embeds SourceDepartment EXISTS clauses;
        # recognize the primary FROM first so the fake models SQL filtering.
        if "FROM sources" in text:
            return _FakeResult(self._source if self._visible else None)
        if "source_departments" in text:
            return _FakeResult(self._dept_ids, rows=True)
        if "wiki_pages" in text:
            return _FakeResult(self._wiki)
        if "source_images" in text:
            return _FakeResult(self._images)
        raise AssertionError(f"unexpected query in fake: {text[:120]}")


class _UpdateDB:
    """Minimal transaction double for source scope re-ingestion updates."""

    def __init__(self, department_ids=()) -> None:
        self.department_ids = list(department_ids)
        self.added: list[object] = []
        self.statements: list[object] = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        text = str(stmt).lstrip()
        if text.startswith("SELECT") and "source_departments" in text:
            return _FakeResult(self.department_ids)
        if "wiki_pages" in text:
            return _FakeResult(0)
        return _FakeResult(None)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass


class _SpySession:
    """Records created source/link rows and supplies scoped source snapshots."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self._source: Source | None = None

    async def execute(self, stmt):
        text = str(stmt)
        if "sources" in text:
            return _FakeResult(self._snapshot_source())
        return _FakeResult(None)

    def add(self, obj) -> None:
        self.added.append(obj)
        if getattr(obj, "source_type", None) in {"file", "url"}:
            self._source = cast(Source, obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "source_type", None) in {"file", "url"}:
                source = cast(Source, obj)
                if getattr(obj, "id", None) is None:
                    source.id = uuid.uuid4()
                if getattr(obj, "created_at", None) is None:
                    source.created_at = datetime.now(timezone.utc)
                if getattr(obj, "updated_at", None) is None:
                    source.updated_at = source.created_at

    async def refresh(self, obj) -> None:
        pass

    async def commit(self) -> None:
        pass

    def _snapshot_source(self) -> SimpleNamespace | None:
        obj = self._source
        if obj is None:
            return None
        return SimpleNamespace(
            id=obj.id,
            title=obj.title,
            source_type=obj.source_type,
            file_name=getattr(obj, "file_name", None),
            url=getattr(obj, "url", None),
            file_size=getattr(obj, "file_size", None),
            status=getattr(obj, "status", "pending"),
            error_message=None,
            progress=getattr(obj, "progress", 0),
            progress_message=None,
            job_id=getattr(obj, "job_id", None),
            page_offsets=getattr(obj, "page_offsets", []) or [],
            extracted_token_count=None,
            auto_recover_count=getattr(obj, "auto_recover_count", 0) or 0,
            knowledge_type=None,
            knowledge_type_id=getattr(obj, "knowledge_type_id", None),
            departments=[],
            contributor=None,
            contributed_by_employee_id=obj.contributed_by_employee_id,
            scope_type=getattr(obj, "scope_type", "global") or "global",
            scope_id=getattr(obj, "scope_id", None),
            language=getattr(obj, "language", "en"),
            preserve_verbatim=bool(getattr(obj, "preserve_verbatim", False)),
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


def _make_source(**overrides) -> SimpleNamespace:
    base = dict(
        id=uuid.uuid4(),
        title="T",
        source_type="file",
        file_name="f.txt",
        url=None,
        file_size=10,
        status="ready",
        delete_requested_at=None,
        error_message=None,
        progress=100,
        progress_message=None,
        job_id=None,
        dispatch_generation=1,
        page_offsets=[],
        extracted_token_count=10,
        auto_recover_count=0,
        knowledge_type=None,
        knowledge_type_id=None,
        departments=[],
        contributor=None,
        contributed_by_employee_id=None,
        scope_type="global",
        scope_id=None,
        language="en",
        preserve_verbatim=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        minio_key=None,
        full_text=None,
        outline_json=None,
        pipeline_phase=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


if __name__ == "__main__":
    unittest.main()
