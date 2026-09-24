import asyncio

import pytest
import pytest_asyncio
from pytest import mark

from tests.utilities.events import WAIT_TIMEOUT
from UnleashClient._async_scheduler import _AsyncScheduler

INTERVAL = 0.01


@pytest_asyncio.fixture
async def scheduler():
    built = _AsyncScheduler()
    try:
        yield built
    finally:
        await built.shutdown()


async def wait_for(event: asyncio.Event) -> None:
    await asyncio.wait_for(event.wait(), WAIT_TIMEOUT)


def counting_job(target: int):
    runs = []
    reached = asyncio.Event()

    async def job(**kwargs):
        runs.append(kwargs)
        if len(runs) >= target:
            reached.set()

    return job, runs, reached


async def let_ticks_pass(count: int = 3) -> None:
    witness = _AsyncScheduler()
    job, _, reached = counting_job(count)
    witness.every(INTERVAL, None, job)
    witness.start()
    try:
        await wait_for(reached)
    finally:
        await witness.shutdown()


def forever_job():
    started = asyncio.Event()
    unwound = []

    async def job():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            unwound.append(True)

    return job, started, unwound


@mark.asyncio
async def test_a_job_registered_before_start_runs_once_started(scheduler):
    job, _, reached = counting_job(1)
    scheduler.every(INTERVAL, None, job)

    scheduler.start()

    await wait_for(reached)


@mark.asyncio
async def test_a_job_registered_after_start_runs(scheduler):
    job, _, reached = counting_job(1)
    scheduler.start()

    scheduler.every(INTERVAL, None, job)

    await wait_for(reached)


@mark.asyncio
async def test_a_job_with_jitter_runs(scheduler):
    job, _, reached = counting_job(1)
    scheduler.every(INTERVAL, INTERVAL, job)

    scheduler.start()

    await wait_for(reached)


@mark.asyncio
async def test_the_job_receives_the_kwargs_it_was_registered_with(scheduler):
    job, runs, reached = counting_job(1)
    scheduler.every(INTERVAL, None, job, kwargs={"url": "http://localhost:4242/api"})

    scheduler.start()

    await wait_for(reached)
    assert runs[0] == {"url": "http://localhost:4242/api"}


@mark.asyncio
async def test_a_job_that_raises_keeps_running(scheduler):
    runs = []
    reached = asyncio.Event()

    async def job():
        runs.append(1)
        if len(runs) >= 2:
            reached.set()
        raise RuntimeError("boom")

    scheduler.every(INTERVAL, None, job)
    scheduler.start()

    await wait_for(reached)


@mark.asyncio
async def test_cancel_stops_further_runs(scheduler):
    job, runs, reached = counting_job(1)
    handle = scheduler.every(INTERVAL, None, job)
    scheduler.start()
    await wait_for(reached)

    scheduler.cancel(handle)
    runs_at_cancel = len(runs)
    await let_ticks_pass()

    assert len(runs) == runs_at_cancel


@mark.asyncio
async def test_cancel_tolerates_a_job_that_was_never_registered(scheduler):
    scheduler.cancel(None)


@mark.asyncio
async def test_cancel_tolerates_a_job_that_is_already_gone(scheduler):
    job, _, _ = counting_job(1)
    handle = scheduler.every(INTERVAL, None, job)
    scheduler.start()

    scheduler.cancel(handle)
    try:
        scheduler.cancel(handle)
    except Exception:
        pytest.fail("Canceling a job that is already gone should not raise an exception")


@mark.asyncio
async def test_cancel_and_wait_returns_once_the_run_in_progress_has_unwound(
    scheduler,
):
    job, started, unwound = forever_job()
    handle = scheduler.every(INTERVAL, None, job)
    scheduler.start()
    await wait_for(started)

    await scheduler.cancel_and_wait(handle)

    assert unwound == [True]


@mark.asyncio
async def test_a_job_can_cancel_and_wait_for_itself(scheduler):
    handle = None
    runs = []
    finished = asyncio.Event()

    async def job():
        runs.append(1)
        await scheduler.cancel_and_wait(handle)
        finished.set()

    handle = scheduler.every(INTERVAL, None, job)
    scheduler.start()
    await wait_for(finished)
    await let_ticks_pass()

    assert len(runs) == 1


@mark.asyncio
async def test_shutdown_returns_once_every_run_in_progress_has_unwound():
    scheduler = _AsyncScheduler()
    first, first_started, first_unwound = forever_job()
    second, second_started, second_unwound = forever_job()
    scheduler.every(INTERVAL, None, first)
    scheduler.every(INTERVAL, None, second)
    scheduler.start()
    await wait_for(first_started)
    await wait_for(second_started)

    await scheduler.shutdown()

    assert first_unwound == [True]
    assert second_unwound == [True]


@mark.asyncio
async def test_shutdown_tolerates_a_scheduler_that_was_never_started():
    await _AsyncScheduler().shutdown()


@mark.asyncio
async def test_a_job_can_shut_down_its_own_scheduler(scheduler):
    shut_down = asyncio.Event()

    async def shutting_down_job():
        shut_down.set()
        await scheduler.shutdown()

    job, runs, _ = counting_job(1)
    scheduler.every(INTERVAL, None, job)
    scheduler.every(INTERVAL, None, shutting_down_job)
    scheduler.start()
    await wait_for(shut_down)
    await let_ticks_pass(1)

    runs_after_shutdown = len(runs)
    await let_ticks_pass()

    assert len(runs) == runs_after_shutdown


def test_start_outside_a_running_event_loop_raises():
    with pytest.raises(RuntimeError):
        _AsyncScheduler().start()


@mark.asyncio
async def test_a_job_never_runs_concurrently_with_itself(scheduler):
    in_flight = []
    most_in_flight = []
    runs = []
    reached = asyncio.Event()

    async def slow_job():
        in_flight.append(1)
        most_in_flight.append(len(in_flight))
        await asyncio.sleep(INTERVAL * 3)
        in_flight.pop()
        runs.append(1)
        if len(runs) >= 3:
            reached.set()

    scheduler.every(INTERVAL, None, slow_job)
    scheduler.start()
    scheduler.start()

    await wait_for(reached)
    assert max(most_in_flight) == 1
