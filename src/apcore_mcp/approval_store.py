"""ApprovalStore: pluggable persistence interface for Phase B approval polling.

Users supply a concrete implementation (Redis, DB, etc.).
InMemoryApprovalStore is provided for testing and local development only —
it does NOT survive process restarts and is not suitable for production.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class ApprovalStore(Protocol):
    """Pluggable storage for Phase B approval state.

    The bridge writes a pending record on first request and reads it on
    each poll. External systems (Slack bot, web UI, etc.) call ``resolve()``
    out-of-band to approve or reject.
    """

    async def save_pending(self, approval_id: str, module_id: str, arguments: dict) -> None:
        """Persist a new pending approval record."""
        ...

    async def get_result(self, approval_id: str) -> dict[str, Any] | None:
        """Return the current record, or None if approval_id is unknown.

        Record shape: {"status": "pending"|"approved"|"rejected", "reason": str|None}
        """
        ...

    async def resolve(self, approval_id: str, *, approved: bool, reason: str | None = None) -> bool:
        """Mark approval_id as approved or rejected.

        Returns False if the id is unknown or already resolved.
        """
        ...


class InMemoryApprovalStore:
    """In-process approval store for testing and local development.

    NOT suitable for production: state is lost on restart, not shared
    across processes.

    Memory management
    -----------------
    - Resolved records are deleted after ``resolved_ttl`` seconds (default 120 s)
      — long enough for the agent to poll the result, short enough to reclaim.
    - Pending records that are never resolved are deleted after
      ``pending_ttl`` seconds (default 3600 s).
    - A background sweep runs every ``sweep_interval`` seconds to collect
      records whose ``call_later`` was skipped (e.g. event-loop restart in tests).
    - Hard cap ``max_records``: when exceeded, the oldest pending record is
      evicted to prevent unbounded growth under sustained load.
    """

    def __init__(
        self,
        *,
        resolved_ttl: float = 120.0,
        pending_ttl: float = 3600.0,
        sweep_interval: float = 300.0,
        max_records: int = 10_000,
    ) -> None:
        self._resolved_ttl = resolved_ttl
        self._pending_ttl = pending_ttl
        self._sweep_interval = sweep_interval
        self._max_records = max_records

        self._records: dict[str, dict[str, Any]] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._sweep_task: asyncio.Task | None = None

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background sweep task.

        Call once after the event loop is running (e.g. inside async_serve).
        Safe to call multiple times — a running sweep is not restarted.
        """
        if self._sweep_task is None or self._sweep_task.done():
            self._sweep_task = asyncio.get_event_loop().create_task(self._sweep_loop(), name="approval-store-sweep")

    def stop(self) -> None:
        """Stop the background sweep task."""
        if self._sweep_task and not self._sweep_task.done():
            self._sweep_task.cancel()
            self._sweep_task = None

    # ── public API ───────────────────────────────────────────────────────

    async def save_pending(self, approval_id: str, module_id: str, arguments: dict) -> None:
        if len(self._records) >= self._max_records:
            self._evict_oldest_pending()

        now = time.monotonic()
        self._records[approval_id] = {
            "status": "pending",
            "module_id": module_id,
            "arguments": arguments,
            "reason": None,
            "created_at": now,
            "resolved_at": None,
        }
        self._events[approval_id] = asyncio.Event()
        self._schedule_cleanup(approval_id, self._pending_ttl)

    async def get_result(self, approval_id: str) -> dict[str, Any] | None:
        return self._project(self._records.get(approval_id))

    async def resolve(self, approval_id: str, *, approved: bool, reason: str | None = None) -> bool:
        record = self._records.get(approval_id)
        if record is None or record["status"] != "pending":
            return False

        now = time.monotonic()
        record["status"] = "approved" if approved else "rejected"
        record["reason"] = reason
        record["resolved_at"] = now
        record.pop("arguments", None)

        event = self._events.pop(approval_id, None)
        if event:
            event.set()

        self._schedule_cleanup(approval_id, self._resolved_ttl)
        return True

    async def wait_for_resolution(self, approval_id: str, timeout: float = 300.0) -> dict[str, Any] | None:
        """Block until resolved or timeout. Helper for tests."""
        event = self._events.get(approval_id)
        if event is None:
            return self._project(self._records.get(approval_id))
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(event.wait()), timeout=timeout)
        return self._project(self._records.get(approval_id))

    # ── read projection ──────────────────────────────────────────────────

    # Fields a reader is allowed to see. ``arguments`` is deliberately absent:
    # while a record is pending it still holds the module's raw inputs, and the
    # Phase B contract states they are not part of the returned record so
    # sensitive inputs are never handed back to a poller. Mirrors the fresh
    # projections built in approval-store.ts:109-115 and approval_store.rs:197-201.
    _PROJECTED_FIELDS = ("status", "module_id", "reason", "created_at", "resolved_at")

    @classmethod
    def _project(cls, record: dict[str, Any] | None) -> dict[str, Any] | None:
        """Return a detached copy of ``record`` without the stored arguments.

        Returning the live dict would also hand the caller a mutable alias to
        store state, letting external code flip ``status`` and bypass the
        resolve() idempotency guard.
        """
        if record is None:
            return None
        return {field: record[field] for field in cls._PROJECTED_FIELDS if field in record}

    # ── cleanup internals ────────────────────────────────────────────────

    def _schedule_cleanup(self, approval_id: str, delay: float) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.call_later(delay, self._delete_record, approval_id)

    def _delete_record(self, approval_id: str) -> None:
        self._records.pop(approval_id, None)
        event = self._events.pop(approval_id, None)
        if event and not event.is_set():
            event.set()

    def _evict_oldest_pending(self) -> None:
        oldest_id = None
        oldest_time = float("inf")
        for aid, rec in self._records.items():
            if rec["status"] == "pending":
                t = rec.get("created_at", 0.0)
                if t < oldest_time:
                    oldest_time = t
                    oldest_id = aid
        if oldest_id:
            logger.warning(
                "InMemoryApprovalStore at capacity (%d); evicting oldest pending %s",
                self._max_records,
                oldest_id,
            )
            self._delete_record(oldest_id)

    async def _sweep_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._sweep_interval)
                self._sweep()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("approval store sweep raised", exc_info=True)

    def _sweep(self) -> None:
        now = time.monotonic()
        to_delete = []
        for aid, rec in self._records.items():
            status = rec["status"]
            created = rec.get("created_at", 0.0)
            resolved = rec.get("resolved_at")
            if (status == "pending" and (now - created) > self._pending_ttl) or (
                status in ("approved", "rejected") and resolved is not None and (now - resolved) > self._resolved_ttl
            ):
                to_delete.append(aid)
        for aid in to_delete:
            self._delete_record(aid)
        if to_delete:
            logger.debug("approval store sweep: deleted %d expired records", len(to_delete))
