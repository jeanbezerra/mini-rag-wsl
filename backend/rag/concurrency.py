import asyncio

import anyio


async def native_call(function, *args):
    """Keep the caller's CPU lock held until a non-cancellable native thread has finished."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # StreamingResponse cancels with an AnyIO cancel scope (level cancellation).
        # Shield cleanup too, otherwise every await is cancelled again immediately.
        with anyio.CancelScope(shield=True):
            try:
                await asyncio.shield(task)
            except Exception:
                pass
        raise
