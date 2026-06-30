"""Runtime-owned services and infrastructure helpers for Cygnus.

Ownership:
- auth, config, storage, policy, notification, wiki, and outward runtime adapters live here
- governance draft pre-review no longer lives here; it converged to ``cygnus.review.pre_review``
- this package is runtime/service wiring, not the governance control plane
"""
