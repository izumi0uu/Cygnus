"""Runtime-owned services and infrastructure helpers for Cygnus.

Ownership:
- auth, config, storage, policy, notification, wiki, and outward runtime adapters live here
- MCP auth/scope adapters no longer live here; they converged to ``cygnus.integrations``
- outward notification fan-out no longer lives here; it converged to ``cygnus.integrations``
- contribution lifecycle and governance draft pre-review no longer live here; they converged to ``cygnus.review``
- embedding persistence helpers no longer live here; they converged to ``cygnus.retrieval``
- source outline extraction and page-slice primitives no longer live here; they converged to ``cygnus.substrate``
- raw-source verbatim indexing and chunk retrieval no longer live here; they converged to ``cygnus.retrieval``
- this package is runtime/service wiring, not the governance control plane
"""
