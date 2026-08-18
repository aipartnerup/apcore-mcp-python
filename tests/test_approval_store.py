"""Tests for InMemoryApprovalStore and ApprovalStore protocol."""

from __future__ import annotations

import asyncio

import pytest

from apcore_mcp.approval_store import ApprovalStore, InMemoryApprovalStore

# ---------------------------------------------------------------------------
# Protocol check
# ---------------------------------------------------------------------------


def test_in_memory_store_implements_protocol() -> None:
    store = InMemoryApprovalStore()
    assert isinstance(store, ApprovalStore)


# ---------------------------------------------------------------------------
# save_pending / get_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_get_pending() -> None:
    store = InMemoryApprovalStore()
    await store.save_pending("aid-1", "my_module", {"x": 1})
    record = await store.get_result("aid-1")
    assert record is not None
    assert record["status"] == "pending"
    assert record["module_id"] == "my_module"
    assert record["reason"] is None
    # [A-D-AP-6] arguments are never part of the returned record, not even while
    # pending — the Phase B contract keeps sensitive module inputs inside the store.
    assert "arguments" not in record


@pytest.mark.asyncio
async def test_get_result_omits_arguments_while_pending() -> None:
    """[A-D-AP-6] A pending record must not leak the module's raw arguments."""
    store = InMemoryApprovalStore()
    await store.save_pending("aid-proj", "my_module", {"password": "hunter2"})

    record = await store.get_result("aid-proj")

    assert record is not None
    assert record["status"] == "pending"
    assert "arguments" not in record
    assert "hunter2" not in repr(record)


@pytest.mark.asyncio
async def test_get_result_returns_detached_copy() -> None:
    """[A-D-AP-6] Mutating the returned record must not reach into store state."""
    store = InMemoryApprovalStore()
    await store.save_pending("aid-detach", "mod", {"x": 1})

    first = await store.get_result("aid-detach")
    assert first is not None
    first["status"] = "approved"

    # The store still considers the record pending, so resolve() still succeeds
    # and its idempotency guard has not been bypassed.
    assert await store.resolve("aid-detach", approved=True) is True
    second = await store.get_result("aid-detach")
    assert second is not None
    assert second["status"] == "approved"


@pytest.mark.asyncio
async def test_wait_for_resolution_omits_arguments() -> None:
    """[A-D-AP-6] The wait helper reads through the same projection."""
    store = InMemoryApprovalStore()
    await store.save_pending("aid-wait-proj", "mod", {"secret": "s3cr3t"})

    record = await store.wait_for_resolution("aid-wait-proj", timeout=0.01)

    assert record is not None
    assert "arguments" not in record


@pytest.mark.asyncio
async def test_get_result_unknown_id_returns_none() -> None:
    store = InMemoryApprovalStore()
    result = await store.get_result("nonexistent")
    assert result is None


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_approved() -> None:
    store = InMemoryApprovalStore()
    await store.save_pending("aid-2", "mod", {})
    ok = await store.resolve("aid-2", approved=True)
    assert ok is True
    record = await store.get_result("aid-2")
    assert record is not None
    assert record["status"] == "approved"
    assert record["reason"] is None
    # arguments are cleared on resolve
    assert "arguments" not in record


@pytest.mark.asyncio
async def test_resolve_rejected() -> None:
    store = InMemoryApprovalStore()
    await store.save_pending("aid-3", "mod", {"a": 1})
    ok = await store.resolve("aid-3", approved=False, reason="not allowed")
    assert ok is True
    record = await store.get_result("aid-3")
    assert record is not None
    assert record["status"] == "rejected"
    assert record["reason"] == "not allowed"
    assert "arguments" not in record


@pytest.mark.asyncio
async def test_resolve_unknown_returns_false() -> None:
    store = InMemoryApprovalStore()
    ok = await store.resolve("no-such-id", approved=True)
    assert ok is False


@pytest.mark.asyncio
async def test_resolve_already_resolved_returns_false() -> None:
    store = InMemoryApprovalStore()
    await store.save_pending("aid-4", "mod", {})
    await store.resolve("aid-4", approved=True)
    # second resolve on already-resolved record must return False
    ok = await store.resolve("aid-4", approved=False)
    assert ok is False
    # status must remain "approved"
    record = await store.get_result("aid-4")
    assert record is not None
    assert record["status"] == "approved"


# ---------------------------------------------------------------------------
# wait_for_resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_resolution_unblocks_after_resolve() -> None:
    store = InMemoryApprovalStore()
    await store.save_pending("aid-5", "mod", {})

    async def _resolve_later() -> None:
        await asyncio.sleep(0.05)
        await store.resolve("aid-5", approved=True)

    task = asyncio.create_task(_resolve_later())
    record = await store.wait_for_resolution("aid-5", timeout=2.0)
    await task
    assert record is not None
    assert record["status"] == "approved"


@pytest.mark.asyncio
async def test_wait_for_resolution_timeout_returns_pending() -> None:
    store = InMemoryApprovalStore()
    await store.save_pending("aid-6", "mod", {})
    record = await store.wait_for_resolution("aid-6", timeout=0.05)
    # should still return the pending record, not raise
    assert record is not None
    assert record["status"] == "pending"


@pytest.mark.asyncio
async def test_wait_for_resolution_unknown_id_returns_none() -> None:
    store = InMemoryApprovalStore()
    result = await store.wait_for_resolution("no-such-id", timeout=0.01)
    assert result is None


# ---------------------------------------------------------------------------
# max_records eviction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_records_evicts_oldest_pending() -> None:
    store = InMemoryApprovalStore(max_records=2)
    await store.save_pending("first", "mod", {})
    await asyncio.sleep(0.001)  # ensure monotonic ordering
    await store.save_pending("second", "mod", {})
    # Adding a third should evict "first" (oldest pending)
    await store.save_pending("third", "mod", {})
    assert await store.get_result("first") is None
    assert await store.get_result("second") is not None
    assert await store.get_result("third") is not None


# ---------------------------------------------------------------------------
# sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_deletes_expired_pending_records() -> None:
    store = InMemoryApprovalStore(pending_ttl=0.0, resolved_ttl=9999.0)
    await store.save_pending("sweep-1", "mod", {})
    # Force created_at far in the past so sweep sees it as expired
    store._records["sweep-1"]["created_at"] = 0.0
    store._sweep()
    assert "sweep-1" not in store._records


@pytest.mark.asyncio
async def test_sweep_deletes_expired_resolved_records() -> None:
    store = InMemoryApprovalStore(pending_ttl=9999.0, resolved_ttl=0.0)
    await store.save_pending("sweep-2", "mod", {})
    await store.resolve("sweep-2", approved=True)
    # Force resolved_at far in the past
    store._records["sweep-2"]["resolved_at"] = 0.0
    store._sweep()
    assert "sweep-2" not in store._records


@pytest.mark.asyncio
async def test_sweep_keeps_non_expired_records() -> None:
    store = InMemoryApprovalStore(pending_ttl=9999.0, resolved_ttl=9999.0)
    await store.save_pending("keep-1", "mod", {})
    store._sweep()
    assert "keep-1" in store._records


# ---------------------------------------------------------------------------
# lifecycle: start / stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_creates_sweep_task() -> None:
    store = InMemoryApprovalStore()
    store.start()
    assert store._sweep_task is not None
    assert not store._sweep_task.done()
    store.stop()


@pytest.mark.asyncio
async def test_start_idempotent() -> None:
    store = InMemoryApprovalStore()
    store.start()
    task1 = store._sweep_task
    store.start()  # should not restart
    task2 = store._sweep_task
    assert task1 is task2
    store.stop()


@pytest.mark.asyncio
async def test_stop_cancels_sweep_task() -> None:
    store = InMemoryApprovalStore()
    store.start()
    store.stop()
    assert store._sweep_task is None
