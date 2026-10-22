import asyncio
import threading

import anyio
import pytest

from rag.concurrency import native_call


async def test_cancelled_native_operation_keeps_cpu_lock_until_thread_finishes():
    entered, release = threading.Event(), threading.Event()
    lock = asyncio.Lock()

    def native_work():
        entered.set()
        release.wait(timeout=3)

    async def run():
        async with lock:
            await native_call(native_work)

    operation = asyncio.create_task(run())
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        operation.cancel()
        await asyncio.sleep(0.01)
        assert lock.locked()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert not lock.locked()


async def test_anyio_response_cancellation_waits_for_native_thread():
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    lock = asyncio.Lock()

    def native_work():
        entered.set()
        release.wait(timeout=3)
        completed.set()

    async def run():
        async with lock:
            await native_call(native_work)

    timer = threading.Timer(0.15, release.set)
    timer.start()
    try:
        async with anyio.create_task_group() as group:
            group.start_soon(run)
            assert await asyncio.to_thread(entered.wait, 3)
            group.cancel_scope.cancel()
        assert completed.is_set()
        assert not lock.locked()
    finally:
        release.set()
        timer.join(timeout=1)
