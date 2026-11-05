import asyncio

import pytest

from task_04_limiter.providers import Deadlines, DeadlineExceeded
from .conftest import Clock


@pytest.mark.asyncio
async def test_early_timer_wakeup_does_not_trigger_fallback_before_3000ms():
    clock = Clock(0)
    closed = asyncio.Event()
    attempts = []

    async def wait(tasks, *, timeout, return_when):
        attempts.append(timeout)
        await asyncio.sleep(0)  # Start the child, not a time-based delay.
        clock.advance(2.999 if len(attempts) == 1 else 0.001)
        return set(), tasks

    async def primary():
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    deadlines = Deadlines(clock=clock, waiter=wait)
    with pytest.raises(DeadlineExceeded):
        await deadlines.run(primary(), 3.0)
    assert len(attempts) == 2 and attempts[0] == 3.0
    assert clock.now == 3.0
    await asyncio.wait_for(closed.wait(), timeout=2)


@pytest.mark.asyncio
async def test_response_exactly_at_deadline_loses_race():
    clock = Clock(0)

    async def result():
        return "late"

    async def wait(tasks, *, timeout, return_when):
        done, pending = await asyncio.wait(tasks, return_when=return_when)
        clock.advance(3.0)
        return done, pending

    with pytest.raises(DeadlineExceeded):
        await Deadlines(clock=clock, waiter=wait).run(result(), 3.0)
