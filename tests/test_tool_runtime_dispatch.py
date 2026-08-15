"""Fault-injection tests for the CYG-140 manifest-driven dispatcher.

Covers the acceptance contract: malformed/hostile batches cannot abort the
turn or execute rejected handlers; every call has exactly one correlated
result and echoes contract_version; deadlines are bounded; retried writes
never create duplicate durable identity (writes are never blindly retried);
only read-only transient failures retry inside the bounded policy budget.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from cygnus.substrate.agent_protocol import (
    SESSION_CONTRACT_VERSION,
    SessionActorScope,
    ToolCall,
)
from cygnus.substrate.tool_runtime import (
    ToolRegistry,
    TransientToolError,
    dispatch_tool_calls,
    execute_governed_tool_call,
    session_tool_manifest,
    validate_arguments,
)


def _actor_scope(
    *, authenticated: bool = True, is_admin: bool = False
) -> SessionActorScope:
    return SessionActorScope(
        authenticated=authenticated,
        is_admin=is_admin,
        permissions=frozenset({"wiki:write:all"} if is_admin else ()),
    )


def _feedback_arguments(**overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "command_id": "feedback:test-1",
        "signal_type": "low_rating",
        "audience_context": {"visibility": "internal"},
    }
    arguments.update(overrides)
    return arguments


def _search_arguments(**overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "query": "billing",
        "audience_context": {"visibility": "internal"},
        "channel": "copilot",
    }
    arguments.update(overrides)
    return arguments


def _publish_arguments(**overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "draft_id": "00000000-0000-0000-0000-000000000000",
        "approval_ref": "00000000-0000-0000-0000-000000000000",
        "approval_digest": "a" * 64,
        "scope_digest": "b" * 64,
        "signal_id": "00000000-0000-0000-0000-000000000000",
        "signal_freshness": "fresh",
        "command_id": "publish:test-1",
        "action_key": "publish",
        "target_channels": ["help_center"],
        "expected_version": 1,
    }
    arguments.update(overrides)
    return arguments


class ManifestValidationTests(unittest.TestCase):
    def test_manifest_schema_rejects_wrong_types_and_unknown_fields(self) -> None:
        manifest = session_tool_manifest()
        tool = manifest.tool("record_feedback_signal")

        self.assertEqual(
            validate_arguments(
                tool.input_schema,
                _feedback_arguments(signal_type="not_a_signal"),
            ),
            ["signal_type: not one of the allowed values"],
        )
        self.assertEqual(
            validate_arguments(
                tool.input_schema,
                _feedback_arguments(audience_context=True),
            ),
            ["audience_context: expected object"],
        )
        self.assertEqual(
            validate_arguments(
                tool.input_schema,
                _feedback_arguments(command_id=""),
            ),
            ["command_id: shorter than 1 characters"],
        )
        self.assertEqual(
            validate_arguments(
                tool.input_schema,
                _feedback_arguments(command_id="x" * 221),
            ),
            ["command_id: longer than 220 characters"],
        )
        self.assertEqual(
            validate_arguments(tool.input_schema, _feedback_arguments()),
            [],
        )

    def test_manifest_schema_rejects_unknown_object_fields(self) -> None:
        manifest = session_tool_manifest()
        tool = manifest.tool("record_feedback_signal")
        errors = validate_arguments(
            tool.input_schema,
            _feedback_arguments(
                audience_context={"visibility": "internal", "mystery": "x"}
            ),
        )
        self.assertEqual(
            errors,
            ["audience_context: unexpected field 'mystery'"],
        )

    def test_manifest_schema_enforces_declared_patterns(self) -> None:
        manifest = session_tool_manifest()
        tool = manifest.tool("publish_knowledge_object")

        self.assertEqual(
            validate_arguments(
                tool.input_schema,
                _publish_arguments(approval_digest="A" * 64),
            ),
            ["approval_digest: does not match the required pattern"],
        )


class DispatchFaultInjectionTests(unittest.IsolatedAsyncioTestCase):
    def _registry_with(self, *tools: tuple[str, Any]) -> ToolRegistry:
        manifest = session_tool_manifest()
        registry = ToolRegistry()
        for name, handler in tools:
            registry.register(manifest.tool(name).to_tool_definition(), handler)
        return registry

    async def test_mixed_batch_returns_one_correlated_result_per_call(self) -> None:
        registry = self._registry_with(
            (
                "search_knowledge_objects",
                lambda **kw: {"status": "success", "data": {"n": 1}},
            ),
        )
        results = await dispatch_tool_calls(
            registry,
            (
                ToolCall(id="call-1", name="not_a_tool", arguments={}),
                ToolCall(
                    id="call-2",
                    name="search_knowledge_objects",
                    arguments=_search_arguments(),
                ),
            ),
            actor=_actor_scope(),
        )

        self.assertEqual(len(results), 2)
        first_id, first_name, first_envelope = results[0]
        self.assertEqual((first_id, first_name), ("call-1", "not_a_tool"))
        self.assertEqual(first_envelope["status"], "invalid")
        self.assertEqual(first_envelope["errors"], ["unknown_tool"])
        self.assertEqual(first_envelope["contract_version"], SESSION_CONTRACT_VERSION)

        second_id, second_name, second_envelope = results[1]
        self.assertEqual(
            (second_id, second_name), ("call-2", "search_knowledge_objects")
        )
        self.assertEqual(second_envelope["status"], "success")
        self.assertEqual(second_envelope["contract_version"], SESSION_CONTRACT_VERSION)

    async def test_rejected_call_never_runs_its_handler(self) -> None:
        calls: dict[str, int] = {}

        async def must_not_run(**kw: Any) -> dict[str, Any]:
            calls["ran"] = calls.get("ran", 0) + 1
            return {"status": "success"}

        registry = self._registry_with(("record_feedback_signal", must_not_run))
        results = await dispatch_tool_calls(
            registry,
            (
                ToolCall(
                    id="call-1",
                    name="record_feedback_signal",
                    arguments=_feedback_arguments(audience_context="hostile"),
                ),
            ),
            actor=_actor_scope(),
        )

        _, _, envelope = results[0]
        self.assertEqual(envelope["status"], "invalid")
        self.assertEqual(envelope["errors"], ["invalid_arguments"])
        self.assertNotIn("ran", calls)

    async def test_policy_denial_runs_before_handler(self) -> None:
        calls: dict[str, int] = {}

        async def must_not_run(**kw: Any) -> dict[str, Any]:
            calls["ran"] = calls.get("ran", 0) + 1
            return {"status": "success"}

        manifest = session_tool_manifest()
        envelope = await execute_governed_tool_call(
            tool=manifest.tool("publish_knowledge_object"),
            arguments=_publish_arguments(),
            handler=must_not_run,
            actor_scope=_actor_scope(is_admin=False),
        )

        self.assertEqual(envelope["status"], "denied")
        self.assertEqual(envelope["errors"], ["permission_denied"])
        self.assertNotIn("ran", calls)

    async def test_admin_scope_is_allowed_for_administrator_tools(self) -> None:
        manifest = session_tool_manifest()

        async def publish(**kw: Any) -> dict[str, Any]:
            return {"status": "success"}

        envelope = await execute_governed_tool_call(
            tool=manifest.tool("publish_knowledge_object"),
            arguments=_publish_arguments(),
            handler=publish,
            actor_scope=_actor_scope(is_admin=True),
        )

        self.assertEqual(envelope["status"], "success")

    async def test_deadline_is_bounded_by_class_timeout(self) -> None:
        manifest = session_tool_manifest()
        read_tool = manifest.tool("search_knowledge_objects")
        self.assertEqual(read_tool.timeout_seconds, 5)

        async def slow(**kw: Any) -> dict[str, Any]:
            await asyncio.sleep(60)
            return {"status": "success"}

        started = asyncio.get_event_loop().time()
        envelope = await execute_governed_tool_call(
            tool=read_tool,
            arguments=_search_arguments(),
            handler=slow,
            actor_scope=_actor_scope(),
        )
        elapsed = asyncio.get_event_loop().time() - started

        self.assertEqual(envelope["status"], "deadline_exceeded")
        self.assertEqual(envelope["errors"], ["deadline_exceeded"])
        self.assertLess(elapsed, 10)

    async def test_transient_read_retries_inside_policy_budget(self) -> None:
        manifest = session_tool_manifest()
        read_tool = manifest.tool("search_knowledge_objects")
        self.assertEqual(read_tool.retry_policy.max_attempts, 2)
        self.assertEqual(
            read_tool.retry_policy.retryable_error_codes,
            ("upstream_timeout", "temporarily_unavailable"),
        )

        attempts = {"n": 0}

        async def flaky(**kw: Any) -> dict[str, Any]:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise TransientToolError(code="temporarily_unavailable")
            return {"status": "success", "attempt": attempts["n"]}

        envelope = await execute_governed_tool_call(
            tool=read_tool,
            arguments=_search_arguments(),
            handler=flaky,
            actor_scope=_actor_scope(),
        )

        self.assertEqual(envelope["status"], "success")
        self.assertEqual(envelope["attempt"], 2)
        self.assertEqual(attempts["n"], 2)

    async def test_transient_read_retries_exhaust_and_fail_closed(self) -> None:
        manifest = session_tool_manifest()
        read_tool = manifest.tool("search_knowledge_objects")

        attempts = {"n": 0}

        async def always_fails(**kw: Any) -> dict[str, Any]:
            attempts["n"] += 1
            raise TransientToolError(code="temporarily_unavailable")

        envelope = await execute_governed_tool_call(
            tool=read_tool,
            arguments=_search_arguments(),
            handler=always_fails,
            actor_scope=_actor_scope(),
        )

        self.assertEqual(envelope["status"], "internal_error")
        self.assertEqual(envelope["errors"], ["temporarily_unavailable"])
        self.assertEqual(attempts["n"], read_tool.retry_policy.max_attempts)

    async def test_write_tools_are_never_blindly_retried(self) -> None:
        manifest = session_tool_manifest()
        write_tool = manifest.tool("record_feedback_signal")
        self.assertEqual(write_tool.side_effect_class, "durable_feedback_write")
        self.assertEqual(write_tool.retry_policy.mode, "never")

        attempts = {"n": 0}

        async def write_fails(**kw: Any) -> dict[str, Any]:
            attempts["n"] += 1
            raise TransientToolError(code="temporarily_unavailable")

        envelope = await execute_governed_tool_call(
            tool=write_tool,
            arguments=_feedback_arguments(),
            handler=write_fails,
            actor_scope=_actor_scope(),
        )

        self.assertEqual(envelope["status"], "internal_error")
        self.assertEqual(attempts["n"], 1)

    async def test_incompatible_contract_fails_before_any_work(self) -> None:
        calls: dict[str, int] = {}
        manifest = session_tool_manifest()
        registry = ToolRegistry()
        registry.register(
            manifest.tool("search_knowledge_objects").to_tool_definition(),
            lambda **kw: calls.__setitem__("ran", calls.get("ran", 0) + 1),
        )

        results = await dispatch_tool_calls(
            registry,
            (
                ToolCall(
                    id="call-1",
                    name="search_knowledge_objects",
                    arguments=_search_arguments(query="x"),
                ),
            ),
            actor=_actor_scope(),
            contract_version="2.0",
        )

        _, _, envelope = results[0]
        self.assertEqual(envelope["status"], "incompatible_contract_version")
        self.assertEqual(
            envelope["data"]["requested_contract_version"],
            "2.0",
        )
        self.assertNotIn("ran", calls)

    async def test_internal_error_is_structured_without_exception_text(self) -> None:
        manifest = session_tool_manifest()

        async def boom(**kw: Any) -> dict[str, Any]:
            raise RuntimeError("secret db password in message")

        envelope = await execute_governed_tool_call(
            tool=manifest.tool("search_knowledge_objects"),
            arguments=_search_arguments(query="x"),
            handler=boom,
            actor_scope=_actor_scope(),
        )

        self.assertEqual(envelope["status"], "internal_error")
        self.assertEqual(envelope["errors"], ["internal_error"])
        self.assertNotIn("secret", envelope["summary"])

    async def test_success_result_echoes_negotiated_contract_version(self) -> None:
        manifest = session_tool_manifest()

        async def ok(**kw: Any) -> dict[str, Any]:
            return {"status": "success", "summary": "ok"}

        envelope = await execute_governed_tool_call(
            tool=manifest.tool("search_knowledge_objects"),
            arguments=_search_arguments(query="x"),
            handler=ok,
            actor_scope=_actor_scope(),
        )

        self.assertEqual(envelope["status"], "success")
        self.assertEqual(envelope["contract_version"], SESSION_CONTRACT_VERSION)


class UnauthenticatedDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_schema_precedes_unauthenticated_policy(self) -> None:
        """Schema rejection takes precedence over unauthenticated policy denial."""
        manifest = session_tool_manifest()
        registry = ToolRegistry()
        registry.register(
            manifest.tool("search_knowledge_objects").to_tool_definition(),
            lambda **kw: {"status": "success"},
        )

        results = await dispatch_tool_calls(
            registry,
            (
                ToolCall(
                    id="call-1",
                    name="search_knowledge_objects",
                    arguments=_search_arguments(query=5),
                ),
            ),
        )

        _, _, envelope = results[0]
        self.assertEqual(envelope["status"], "invalid")
        self.assertEqual(envelope["errors"], ["invalid_arguments"])


if __name__ == "__main__":
    unittest.main()
