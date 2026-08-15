"""Graceful worker drain runner.

A thin wrapper around the arq worker that makes SIGTERM/SIGINT follow the
runtime drain contract:

1. Publish a ``draining`` worker heartbeat so readiness observes the drain
   for its full duration (the refresh loop keeps it fresh).
2. Stop claiming new jobs (arq's ``handle_sig_wait_for_completion`` sets
   ``allow_pick_jobs = False``).
3. Wait up to the configured drain grace for in-flight jobs to complete.
   Jobs that cannot finish inside the window keep their in-progress lease:
   arq cancels them and they return to the queue after the lease expires
   (``retry_jobs`` + the stuck-worker sweep crons), so work is neither
   silently lost nor duplicated.
4. Let arq's ``close()`` run ``on_shutdown`` — the worker heartbeat is
   published as ``stopped``, its refresh task is canceled, and the Redis
   pool is closed.

The compose worker commands use this runner for both worker roles.  The
plain ``arq`` CLI remains available but does not publish ``draining``.
"""

from __future__ import annotations

import signal
from functools import partial
from typing import Any, Protocol

from arq.cli import create_worker
from arq.worker import Worker

from cygnus.runtime.readiness import (
    WORKER_HEARTBEAT_CONTEXT_KEY,
    WorkerHeartbeat,
)

_DRAIN_STATES = frozenset({"draining", "stopped"})


class _DrainableHeartbeat(Protocol):
    """Duck-typed heartbeat surface the drain runner needs.

    The real worker stores a ``WorkerHeartbeat`` in its context; graceful
    drain shims and test doubles only need ``state`` plus ``mark_draining``.
    """

    @property
    def state(self) -> str: ...

    async def mark_draining(self) -> None: ...


def _worker_heartbeat(worker: Worker) -> _DrainableHeartbeat | None:
    """Return the worker heartbeat from its context, duck-typed.

    ``worker_heartbeat_from_context`` stays strict for the public lifecycle
    helpers; the drain runner accepts any drain-capable heartbeat object so
    graceful drain never depends on the concrete class.
    """
    heartbeat = worker.ctx.get(WORKER_HEARTBEAT_CONTEXT_KEY)
    if isinstance(heartbeat, WorkerHeartbeat):
        return heartbeat
    if heartbeat is None:
        return None
    return heartbeat


def _install_drain_signal_handlers(worker: Worker) -> None:
    """Wrap arq's installed signal handlers so a drain publishes ``draining``.

    arq installs its handlers in ``Worker.__init__``.  We re-install the same
    handlers behind a wrapper that first transitions the worker heartbeat to
    ``draining`` (scheduled on the running loop), then delegates so arq stops
    claiming jobs and drains in-flight work inside the grace window.
    """
    completion_wait = getattr(worker, "_job_completion_wait", 0)
    arq_handler = (
        worker.handle_sig_wait_for_completion if completion_wait else worker.handle_sig
    )
    loop = worker.loop

    def drain_handler(signum: signal.Signals) -> None:
        heartbeat = _worker_heartbeat(worker)
        if heartbeat is not None and heartbeat.state not in _DRAIN_STATES:
            loop.create_task(heartbeat.mark_draining())
        arq_handler(signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, partial(drain_handler, signum))


def run_graceful_worker(settings_cls: type[Any]) -> None:
    """Run one arq worker role under the runtime drain contract."""
    worker = create_worker(settings_cls)
    _install_drain_signal_handlers(worker)
    worker.run()
