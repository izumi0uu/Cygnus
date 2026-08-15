"""
CYG-128 queue security: safe ARQ serializer + loopback/password local Redis.

These tests pin the replacement of arq's default pickle job/result
serialization with the versioned, deterministic, allowlisted format in
``cygnus/runtime/arq_serializer.py``:

- a crafted pickle payload can never reach a worker function,
- unsupported/malformed payloads fail safely (never execute),
- real job payloads dispatch unchanged through arq's own serialize/deserialize
  entry points,
- the local docker Redis is loopback-only and requires a password that every
  client (env examples, compose healthcheck) uses.
"""

from __future__ import annotations

import asyncio
import pickle
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from arq.jobs import (
    DeserializationError,
    SerializationError,
    deserialize_job_raw,
    deserialize_result,
    serialize_job,
    serialize_result,
)

from cygnus.runtime import arq_serializer
from cygnus.runtime.arq_serializer import (
    MAGIC,
    MAX_CONTAINER_ITEMS,
    MAX_DEPTH,
    MAX_SERIALIZED_BYTES,
    VERSION,
    QueueDeserializationError,
    QueueSerializationError,
    dumps,
    loads,
)


def _valid_payload(body: bytes) -> bytes:
    return MAGIC + bytes([VERSION]) + body


class RejectionSecurityTests(unittest.TestCase):
    """Malicious or unsupported payloads must be rejected, never executed."""

    def test_crafted_pickle_payload_is_rejected(self) -> None:
        evil = pickle.dumps(
            {"t": 1, "f": "ingest_file_task", "a": ("src-1",), "k": {}, "et": 1}
        )
        with self.assertRaises(QueueDeserializationError):
            loads(evil)
        # The exact worker gate: deserialize_job_raw is what the worker runs
        # before dispatch; a pickle payload fails here -> job_failed, no run.
        with self.assertRaises(DeserializationError):
            deserialize_job_raw(evil, deserializer=loads)

    def test_pickle_of_native_gadget_style_object_is_rejected(self) -> None:
        class Gadget:
            def __reduce__(self):
                return (eval, ("__import__('os').getcwd()",))

        payload = pickle.dumps({"f": "ingest_file_task", "a": (Gadget(),), "k": {}})
        with self.assertRaises(QueueDeserializationError):
            loads(payload)

    def test_missing_or_wrong_magic_is_rejected(self) -> None:
        for payload in (b"", b"\x80\x04\x95", b"cygq", b"not-a-payload", b"\x00" * 32):
            with self.assertRaises(QueueDeserializationError):
                loads(payload)

    def test_unknown_version_is_rejected(self) -> None:
        with self.assertRaises(QueueDeserializationError):
            loads(b"cygq\x02" + b"\x00")

    def test_non_bytes_input_is_rejected(self) -> None:
        for bad in ("payload", None, 42, ["cygq"]):
            with self.assertRaises(QueueDeserializationError):
                loads(bad)

    def test_oversize_payload_is_rejected(self) -> None:
        big = _valid_payload(b"\x00" * (MAX_SERIALIZED_BYTES + 1))
        with self.assertRaises(QueueDeserializationError):
            loads(big)
        with self.assertRaises(QueueSerializationError):
            dumps("x" * (MAX_SERIALIZED_BYTES + 1))

    def test_excessive_nesting_is_rejected_on_decode(self) -> None:
        nested = _valid_payload(b"\x06\x01" * (MAX_DEPTH + 2) + b"\x00")
        with self.assertRaises(QueueDeserializationError):
            loads(nested)

    def test_excessive_nesting_is_rejected_on_encode(self) -> None:
        value: object = None
        for _ in range(MAX_DEPTH + 2):
            value = [value]
        with self.assertRaises(QueueSerializationError):
            dumps(value)

    def test_unknown_type_tag_is_rejected(self) -> None:
        with self.assertRaises(QueueDeserializationError):
            loads(_valid_payload(b"\xfe"))

    def test_truncated_and_malformed_values_are_rejected(self) -> None:
        # header only
        with self.assertRaises(QueueDeserializationError):
            loads(MAGIC + bytes([VERSION]))
        # STR claiming 5 bytes with only 2 present
        with self.assertRaises(QueueDeserializationError):
            loads(_valid_payload(b"\x04\x05ab"))
        # unterminated varint
        with self.assertRaises(QueueDeserializationError):
            loads(_valid_payload(b"\x03\x80"))
        # invalid utf-8 in a string
        with self.assertRaises(QueueDeserializationError):
            loads(_valid_payload(b"\x04\x01\xff"))

    def test_trailing_garbage_is_rejected(self) -> None:
        payload = dumps({"a": 1}) + b"\x00"
        with self.assertRaises(QueueDeserializationError):
            loads(payload)

    def test_map_with_non_string_key_is_rejected(self) -> None:
        with self.assertRaises(QueueSerializationError):
            dumps({1: "x"})
        # hand-crafted MAP whose key decodes to an int
        with self.assertRaises(QueueDeserializationError):
            loads(_valid_payload(b"\x08\x01\x03\x02\x04\x01x"))

    def test_unsupported_payload_types_are_rejected(self) -> None:
        for obj in (datetime.now(), {"a", "b"}, 3.14, object()):
            with self.assertRaises(QueueSerializationError):
                dumps(obj)

    def test_container_item_limit_is_enforced_on_encode(self) -> None:
        with self.assertRaises(QueueSerializationError):
            dumps(list(range(MAX_CONTAINER_ITEMS + 1)))

    def test_unsupported_argument_fails_safely_at_enqueue(self) -> None:
        # arq wraps serializer failure in SerializationError, so the caller
        # sees a normal enqueue error and can mark the job failed.
        with self.assertRaises(SerializationError):
            serialize_job("ingest_file_task", (object(),), {}, 1, 1, serializer=dumps)
        with self.assertRaises(SerializationError):
            serialize_job(
                "ingest_file_task", (datetime.now(),), {}, 1, 1, serializer=dumps
            )


class CompatibilityRoundTripTests(unittest.TestCase):
    """Valid payloads must survive the arq contract unchanged."""

    def test_job_envelope_round_trips(self) -> None:
        job = {
            "t": 1,
            "f": "ingest_file_task",
            "a": ("src-123",),
            "k": {},
            "et": 1720000000000,
        }
        self.assertEqual(loads(dumps(job)), job)

    def test_all_real_task_payloads_dispatch_through_arq(self) -> None:
        # Every task signature the codebase enqueues today.
        task_calls = [
            ("ingest_file_task", ("src-1",)),
            ("ingest_url_task", ("src-2",)),
            ("caption_images_task", ("src-3",)),
            ("ingest_map_reduce_task", ("src-4",)),
            ("ingest_refine_task", ("src-5",)),
            ("regenerate_plan_task", ("src-6", "reviewer note")),
            ("reembed_all_pages_task", ("job-7",)),
            ("ai_pre_review_draft_task", ("draft-8", 2)),
            ("ingest_skill_task", ("skill-9", "version-9", "/tmp/file.md", "name.md")),
            ("delete_skill_task", ("skill-9",)),
        ]
        for function, args in task_calls:
            with self.subTest(function=function):
                payload = serialize_job(
                    function, args, {}, 1, 1720000000000, serializer=dumps
                )
                name, decoded_args, kwargs, job_try, enqueue_time = deserialize_job_raw(
                    payload, deserializer=loads
                )
                self.assertEqual(name, function)
                self.assertEqual(decoded_args, args)
                self.assertIsInstance(decoded_args, tuple)
                self.assertEqual(kwargs, {})
                self.assertEqual(job_try, 1)
                self.assertIsInstance(enqueue_time, int)

    def test_successful_result_round_trips_through_arq(self) -> None:
        raw = serialize_result(
            "ingest_file_task",
            ("src-1",),
            {},
            1,
            1720000000000,
            True,
            {"status": "ready", "verbatim_chunks": 12},
            10,
            20,
            "ref",
            "arq.queue",
            "job-1",
            serializer=dumps,
        )
        assert raw is not None
        info = deserialize_result(raw, deserializer=loads)
        self.assertTrue(info.success)
        self.assertEqual(info.result, {"status": "ready", "verbatim_chunks": 12})
        self.assertEqual(info.queue_name, "arq.queue")
        self.assertEqual(info.job_id, "job-1")

    def test_failed_result_exception_round_trips_through_arq(self) -> None:
        raw = serialize_result(
            "ingest_file_task",
            ("src-1",),
            {},
            1,
            1720000000000,
            False,
            RuntimeError("boom"),
            10,
            20,
            "ref",
            "arq.queue",
            "job-1",
            serializer=dumps,
        )
        assert raw is not None
        info = deserialize_result(raw, deserializer=loads)
        self.assertFalse(info.success)
        self.assertIsInstance(info.result, RuntimeError)
        self.assertEqual(str(info.result), "boom")

    def test_known_exception_classes_are_reconstructed(self) -> None:
        for exc in (
            RuntimeError("r"),
            ValueError("v"),
            KeyError("k"),
            TypeError("t"),
            TimeoutError("to"),
            asyncio.CancelledError("c"),
        ):
            with self.subTest(exc=type(exc).__name__):
                decoded = loads(dumps({"r": exc}))["r"]
                self.assertIsInstance(decoded, type(exc))
                self.assertEqual(str(decoded), str(exc))

    def test_unknown_exception_class_degrades_to_exception(self) -> None:
        class WeirdError(Exception):
            pass

        decoded = loads(dumps({"r": WeirdError("x")}))["r"]
        self.assertIsInstance(decoded, Exception)
        self.assertEqual(str(decoded), "x")

    def test_primitive_types_round_trip_exactly(self) -> None:
        self.assertIs(loads(dumps(None)), None)
        self.assertIs(loads(dumps(True)), True)
        self.assertIs(loads(dumps(False)), False)
        self.assertIsInstance(loads(dumps(1)), int)
        # ``bool`` subclasses ``int`` in Python, so identity above is not enough
        # to prove the wire keeps the bool/int distinction: the decoded value
        # must be *exactly* ``bool``, never a plain ``int``.
        self.assertIs(type(loads(dumps(True))), bool)
        self.assertIs(type(loads(dumps(False))), bool)
        for n in (0, 1, -1, 2**63 - 1, -(2**63), 2**100):
            with self.subTest(n=n):
                self.assertEqual(loads(dumps(n)), n)
        self.assertEqual(loads(dumps("héllo→世界")), "héllo→世界")
        self.assertEqual(loads(dumps(b"\x00\xff\x80")), b"\x00\xff\x80")
        self.assertEqual(loads(dumps([1, "two", None, True])), [1, "two", None, True])
        self.assertEqual(
            loads(dumps({"a": {"b": [1, 2]}, "c": "d"})),
            {"a": {"b": [1, 2]}, "c": "d"},
        )

    def test_encoding_is_deterministic_regardless_of_key_order(self) -> None:
        first = {"b": 1, "a": {"y": [1, 2], "x": "s"}, "c": None}
        second = {"c": None, "b": 1, "a": {"x": "s", "y": [1, 2]}}
        self.assertEqual(dumps(first), dumps(second))
        self.assertEqual(dumps(first), dumps(dict(first)))


class WorkerWiringTests(unittest.IsolatedAsyncioTestCase):
    """worker.py must wire the safe serializer on both sides of the queue."""

    def test_settings_expose_the_safe_serializer(self) -> None:
        from cygnus.runtime import worker as worker_module

        self.assertIs(worker_module.WorkerSettings.job_serializer, arq_serializer.dumps)
        self.assertIs(
            worker_module.WorkerSettings.job_deserializer, arq_serializer.loads
        )
        self.assertIs(
            worker_module.SkillWorkerSettings.job_serializer, arq_serializer.dumps
        )
        self.assertIs(
            worker_module.SkillWorkerSettings.job_deserializer, arq_serializer.loads
        )

    async def test_get_arq_pool_passes_serializer_to_create_pool(self) -> None:
        from cygnus.runtime import worker as worker_module

        fake_pool = object()
        fake_create_pool = AsyncMock(return_value=fake_pool)
        with (
            patch.object(worker_module, "_arq_pool", None),
            patch.object(worker_module, "create_pool", fake_create_pool),
        ):
            pool = await worker_module.get_arq_pool()

        self.assertIs(pool, fake_pool)
        fake_create_pool.assert_awaited_once()
        assert fake_create_pool.await_args is not None
        kwargs = fake_create_pool.await_args.kwargs
        self.assertIs(kwargs["job_serializer"], arq_serializer.dumps)
        self.assertIs(kwargs["job_deserializer"], arq_serializer.loads)


class LocalRedisStackSecurityTests(unittest.TestCase):
    """Local docker Redis must be loopback-only, passworded, healthchecked."""

    def test_compose_redis_is_loopback_only_and_passworded(self) -> None:
        text = Path("docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("127.0.0.1:6379", text)
        self.assertIn("--requirepass", text)
        self.assertIn("REDIS_PASSWORD", text)
        self.assertIn("$$REDIS_PASSWORD", text)
        self.assertIn("--no-auth-warning", text)

    def test_env_examples_carry_the_redis_password(self) -> None:
        docker_text = Path(".env.docker.example").read_text(encoding="utf-8")
        self.assertIn("redis_password=cygnus_redis_secret", docker_text)
        root_text = Path(".env.example").read_text(encoding="utf-8")
        self.assertIn("redis_password=cygnus_redis_secret", root_text)


if __name__ == "__main__":
    unittest.main()
