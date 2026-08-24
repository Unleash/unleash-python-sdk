import asyncio
from datetime import timedelta
from typing import Callable

import pytest
from pytest import mark

from UnleashClient.async_scheduler import AsyncScheduledJob, AsyncScheduler

# Long enough that a job registered with it never runs during a test, so anything a
# test observes can only have come from the call it made.
NEVER = 3600


def noop() -> None:
    pass


def noop_with_kwargs(**kwargs) -> None:
    pass


# registration


def test_every_returns_a_job_and_registers_it():
    scheduler = AsyncScheduler()

    job = scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)

    assert isinstance(job, AsyncScheduledJob)
    assert scheduler.jobs == (job,)


def test_every_stores_the_interval_as_a_timedelta():
    scheduler = AsyncScheduler()

    job = scheduler.every(interval_seconds=15, jitter_seconds=10, fn=noop)

    assert job.interval == timedelta(seconds=15)
    assert job.jitter == 10


def test_every_does_not_coerce_the_interval():
    # The refresh interval has never been coerced, and the synchronous scheduler hands
    # a string straight to IntervalTrigger. Raising at registration rather than inside
    # a task is what keeps the two the same. See test_UC_type_violation.
    scheduler = AsyncScheduler()

    with pytest.raises(TypeError):
        scheduler.every(interval_seconds="15", jitter_seconds=None, fn=noop)  # type: ignore[arg-type]


def test_a_job_registered_before_start_is_pending():
    # BackgroundScheduler treats a job added before it runs the same way.
    scheduler = AsyncScheduler()

    job = scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)

    assert job.task is None


@mark.asyncio
async def test_a_job_registered_after_start_runs_at_once():
    scheduler = AsyncScheduler()
    scheduler.start()

    job = scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)

    assert isinstance(job.task, asyncio.Task)
    await scheduler.shutdown()


def test_registering_a_job_needs_no_event_loop():
    # The client's constructor is synchronous and runs with no loop, so everything it
    # does to the scheduler has to work without one.
    scheduler = AsyncScheduler()

    scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)

    assert not scheduler.running


# the schedule


def test_the_next_fire_is_one_interval_after_the_previous_one():
    job = AsyncScheduledJob(30, None, noop)

    assert job._next_fire(1000.0) == 1030.0


def test_the_next_fire_is_measured_from_the_previous_fire_not_from_now():
    # Anchoring on the previous fire is what stops a slow run pushing the schedule out.
    job = AsyncScheduledJob(30, None, noop)

    assert job._next_fire(job._next_fire(0.0)) == 60.0


def test_the_jitter_only_ever_delays_a_fire():
    job = AsyncScheduledJob(30, 10, noop)

    fires = [job._next_fire(0.0) for _ in range(50)]

    assert all(30 <= fire < 40 for fire in fires)
    assert len(set(fires)) > 1


def test_the_interval_and_jitter_are_fixed_at_registration():
    # Unlike AsyncMetricsReporter, which re-reads both from the config before every
    # send: they are arguments here, so a job keeps the schedule it was given.
    scheduler = AsyncScheduler()

    job = scheduler.every(interval_seconds=30, jitter_seconds=None, fn=noop)

    assert job._next_fire(0.0) == 30.0
    assert job._next_fire(0.0) == 30.0


# running


@mark.asyncio
async def test_a_job_registered_through_every_actually_runs():
    scheduler = AsyncScheduler()
    ran = asyncio.Event()

    scheduler.every(interval_seconds=0, jitter_seconds=None, fn=ran.set)
    scheduler.start()
    try:
        await asyncio.wait_for(ran.wait(), timeout=5)
    finally:
        await scheduler.shutdown()


@mark.asyncio
async def test_the_job_is_called_with_its_kwargs():
    scheduler = AsyncScheduler()
    calls = []

    scheduler.every(
        interval_seconds=0,
        jitter_seconds=None,
        fn=lambda **kwargs: calls.append(kwargs),
        kwargs={"url": "http://localhost:4242/api"},
    )
    scheduler.start()
    await _until(lambda: calls)
    await scheduler.shutdown()

    assert calls[0] == {"url": "http://localhost:4242/api"}


@mark.asyncio
async def test_a_coroutine_job_is_awaited():
    # The reason this class exists: the async polling connector has to await its fetch.
    scheduler = AsyncScheduler()
    finished = []

    async def fetch() -> None:
        await asyncio.sleep(0)
        finished.append(1)

    scheduler.every(interval_seconds=0, jitter_seconds=None, fn=fetch)
    scheduler.start()
    await _until(lambda: finished)
    await scheduler.shutdown()


@mark.asyncio
async def test_a_plain_job_runs_on_the_event_loop():
    # OfflineConnector passes store.load_from_cache, so a cache read and a take_state
    # run here rather than on a worker thread.
    scheduler = AsyncScheduler()
    loops = []

    scheduler.every(
        interval_seconds=0,
        jitter_seconds=None,
        fn=lambda: loops.append(asyncio.get_running_loop()),
    )
    scheduler.start()
    await _until(lambda: loops)
    await scheduler.shutdown()

    assert loops[0] is asyncio.get_running_loop()


@mark.asyncio
async def test_a_failed_run_does_not_end_the_job():
    # One failed refresh must not end provisioning for the life of the client.
    scheduler = AsyncScheduler()
    runs = []

    def boom() -> None:
        runs.append(len(runs))
        if len(runs) == 1:
            raise TypeError("boom")

    scheduler.every(interval_seconds=0, jitter_seconds=None, fn=boom)
    scheduler.start()
    await _until(lambda: len(runs) > 1)
    await scheduler.shutdown()


# start


@mark.asyncio
async def test_start_runs_every_pending_job():
    scheduler = AsyncScheduler()
    first = scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)
    second = scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)

    scheduler.start()

    assert first.task is not None
    assert second.task is not None
    await scheduler.shutdown()


@mark.asyncio
async def test_start_is_a_no_op_on_an_already_running_scheduler():
    # The client cannot always tell whether it is the first caller to start it.
    scheduler = AsyncScheduler()
    job = scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)
    scheduler.start()
    task = job.task

    scheduler.start()

    assert job.task is task
    await scheduler.shutdown()


@mark.asyncio
async def test_a_job_does_not_run_until_the_scheduler_starts():
    scheduler = AsyncScheduler()
    ran = []
    scheduler.every(interval_seconds=0, jitter_seconds=None, fn=lambda: ran.append(1))

    await asyncio.sleep(0)

    assert ran == []
    await scheduler.shutdown()


# cancel


@mark.asyncio
async def test_cancel_stops_the_job_and_drops_it():
    scheduler = AsyncScheduler()
    job = scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)
    scheduler.start()

    scheduler.cancel(job)

    assert scheduler.jobs == ()
    await _until(job.task.done)


def test_cancel_tolerates_a_job_that_was_never_registered():
    # The connectors initialize `self.job = None`, and stop() may run before start().
    scheduler = AsyncScheduler()

    scheduler.cancel(None)


def test_cancel_tolerates_a_job_that_never_started():
    scheduler = AsyncScheduler()
    job = scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)

    scheduler.cancel(job)

    assert scheduler.jobs == ()


@mark.asyncio
async def test_cancel_is_idempotent():
    scheduler = AsyncScheduler()
    job = scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)
    scheduler.start()

    scheduler.cancel(job)
    scheduler.cancel(job)

    assert scheduler.jobs == ()
    await scheduler.shutdown()


# shutdown


@mark.asyncio
async def test_shutdown_cancels_every_job():
    scheduler = AsyncScheduler()
    first = scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)
    second = scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)
    scheduler.start()

    await scheduler.shutdown()

    assert scheduler.jobs == ()
    assert not scheduler.running
    assert first.task is None
    assert second.task is None


@mark.asyncio
async def test_shutdown_waits_for_a_job_that_is_mid_run():
    # AsyncIOScheduler.shutdown(wait=True) does not wait: its executor cancels pending
    # futures and `running` only flips after a loop tick. This one really waits.
    scheduler = AsyncScheduler()
    running = asyncio.Event()

    async def forever() -> None:
        running.set()
        await asyncio.sleep(NEVER)

    job = scheduler.every(interval_seconds=0, jitter_seconds=None, fn=forever)
    scheduler.start()
    await asyncio.wait_for(running.wait(), timeout=5)
    task = job.task

    await scheduler.shutdown()

    assert task.done()


@mark.asyncio
async def test_shutdown_without_waiting_returns_before_the_job_unwinds():
    scheduler = AsyncScheduler()
    job = scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)
    scheduler.start()
    task = job.task

    await scheduler.shutdown(wait=False)

    assert not task.done()
    await _until(task.done)


@mark.asyncio
async def test_shutdown_swallows_a_job_that_had_already_died():
    # A job whose schedule raises dies on its first cycle; destroy() still has to work.
    scheduler = AsyncScheduler()
    job = scheduler.every(interval_seconds=0, jitter_seconds=None, fn=noop)
    job.jitter = "10"
    scheduler.start()
    await _until(job.task.done)

    await scheduler.shutdown()


@mark.asyncio
async def test_shutdown_is_quiet_when_the_scheduler_was_never_started():
    # Unlike the synchronous scheduler, which raises SchedulerNotRunningError here.
    # Destroying a client that was never initialized still reaches shutdown().
    scheduler = AsyncScheduler()

    await scheduler.shutdown()


@mark.asyncio
async def test_shutdown_is_idempotent():
    scheduler = AsyncScheduler()
    scheduler.every(interval_seconds=NEVER, jitter_seconds=None, fn=noop)
    scheduler.start()

    await scheduler.shutdown()
    await scheduler.shutdown()

    assert scheduler.jobs == ()


@mark.asyncio
async def test_constructing_the_scheduler_starts_nothing():
    scheduler = AsyncScheduler()

    assert not scheduler.running
    assert scheduler.jobs == ()


async def _until(condition: Callable, timeout: float = 5) -> None:
    async def wait() -> None:
        while not condition():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout=timeout)
