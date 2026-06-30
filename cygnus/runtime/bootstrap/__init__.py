"""Runtime bootstrap helpers for Cygnus.

Ownership:
- startup self-seeding and boot-time initialization helpers live here
- this package is runtime bootstrap behavior, not repo-tooling scripts
"""

from cygnus.runtime.bootstrap.seed_builtin_skills import seed_builtin_skills

__all__ = ["seed_builtin_skills"]
