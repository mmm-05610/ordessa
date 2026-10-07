"""Cooperative deadline context compatible with Python 3.10 and later.

Trusted steps must yield and propagate cancellation. This cannot hard-kill a
blocking synchronous step or a step which deliberately swallows cancellation.
"""
import asyncio
import time
from contextlib import asynccontextmanager

@asynccontextmanager
async def deadline_at(deadline):
    task = asyncio.current_task()
    expired = False
    initial_cancels = task.cancelling() if hasattr(task, 'cancelling') else 0
    def expire():
        nonlocal expired
        if hasattr(task, 'cancelling') and task.cancelling() > initial_cancels:
            return
        expired = True
        task.cancel()
    timer = asyncio.get_running_loop().call_later(max(0, deadline-time.monotonic()),expire)
    try:
        yield
    except asyncio.CancelledError:
        if expired:
            if hasattr(task, 'uncancel'):
                if task.uncancel() > initial_cancels:
                    raise
            raise TimeoutError() from None
        raise
    finally:
        timer.cancel()
