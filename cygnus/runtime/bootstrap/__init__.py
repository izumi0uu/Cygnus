"""Runtime bootstrap helpers for Cygnus.

Ownership:
- startup self-seeding and boot-time initialization helpers live here
- this package is runtime bootstrap behavior, not repo-tooling scripts
"""

__all__ = ["bootstrap_local_stack", "seed_builtin_skills"]


def __getattr__(name: str):
    if name == "bootstrap_local_stack":
        from cygnus.runtime.bootstrap.init_local_stack import bootstrap_local_stack

        return bootstrap_local_stack
    if name == "seed_builtin_skills":
        from cygnus.runtime.bootstrap.seed_builtin_skills import seed_builtin_skills

        return seed_builtin_skills
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
