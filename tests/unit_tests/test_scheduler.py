import threading

import pytest
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.background import BackgroundScheduler

from tests.utilities.events import WAIT_TIMEOUT, wait_until
from UnleashClient.scheduler import Scheduler


def noop() -> None:
    pass


def noop_with_kwargs(**kwargs) -> None:
    pass


class RecordingScheduler(BackgroundScheduler):
    """
    Captures what reached add_job.  Deliberately mirrors the signature the client test
    suite relies on -- func positional, trigger by keyword -- so that a change to how
    Scheduler calls add_job shows up here rather than in the client tests.
    """

    def __init__(self):
        super().__init__()
        self.calls = []

    def add_job(self, func, trigger=None, **kwargs):
        self.calls.append({"func": func, "trigger": trigger, **kwargs})
        return super().add_job(func, trigger=trigger, **kwargs)


class MinimalScheduler:
    """
    A duck-typed scheduler with no `state` attribute, whose add_job returns nothing.
    Mirrors what a user can pass as `scheduler=`, and what the client test suite does.
    """

    def __init__(self):
        self.started = 0
        self.shutdowns = 0
        self.jobs_removed = 0
        self.lock = threading.Condition()

    def start(self):
        with self.lock:
            self.started += 1

    def shutdown(self, *args, **kwargs):
        with self.lock:
            self.shutdowns += 1

    def add_job(self, *args, **kwargs):
        return None

    def remove_all_jobs(self, *args, **kwargs):
        with self.lock:
            self.jobs_removed += 1


def test_a_custom_scheduler_adopts_the_given_executor_name():
    custom = BackgroundScheduler()

    scheduler = Scheduler(custom, "hamster_executor")

    assert scheduler.scheduler is custom
    assert scheduler.executor_name == "hamster_executor"


def test_a_custom_scheduler_without_an_executor_name_is_rejected():
    with pytest.raises(ValueError):
        Scheduler(BackgroundScheduler())


def test_an_executor_name_without_a_custom_scheduler_is_ignored():
    scheduler = Scheduler(executor_name="hamster_executor")

    assert scheduler.executor_name != "hamster_executor"
    assert scheduler.executor_name.startswith("unleash_executor_")


def test_the_generated_executor_is_registered_on_the_scheduler_it_built():
    scheduler = Scheduler()

    executor = scheduler.scheduler._lookup_executor(scheduler.executor_name)

    assert isinstance(executor, ThreadPoolExecutor)


def test_every_builds_an_interval_trigger_from_the_interval_and_jitter():
    recording = RecordingScheduler()
    scheduler = Scheduler(recording, "default")

    scheduler.every(interval_seconds=15, jitter_seconds=10, fn=noop)

    (call,) = recording.calls
    assert call["trigger"].interval.total_seconds() == 15
    assert call["trigger"].jitter == 10


def test_every_passes_the_callable_positionally():
    recording = RecordingScheduler()
    scheduler = Scheduler(recording, "default")

    scheduler.every(interval_seconds=15, jitter_seconds=None, fn=noop)

    (call,) = recording.calls
    assert call["func"] is noop


def test_every_runs_the_job_on_the_configured_executor():
    recording = RecordingScheduler()
    scheduler = Scheduler(recording, "hamster_executor")

    scheduler.every(interval_seconds=15, jitter_seconds=None, fn=noop)

    (call,) = recording.calls
    assert call["executor"] == "hamster_executor"


def test_every_forwards_the_job_kwargs():
    # These reach the job as its arguments -- how the metrics job gets its url, headers
    # and engine -- so APScheduler checks them against the callable's signature.
    recording = RecordingScheduler()
    scheduler = Scheduler(recording, "default")

    scheduler.every(
        interval_seconds=15,
        jitter_seconds=None,
        fn=noop_with_kwargs,
        kwargs={"url": "http://localhost:4242/api"},
    )

    (call,) = recording.calls
    assert call["kwargs"] == {"url": "http://localhost:4242/api"}


def test_every_does_not_coerce_the_interval():
    # The refresh interval has never been coerced -- the metrics call site int()s its
    # own. Coercing here would change what a str interval does. See test_UC_type_violation.
    scheduler = Scheduler(BackgroundScheduler(), "default")

    with pytest.raises(TypeError):
        scheduler.every(interval_seconds="15", jitter_seconds=None, fn=noop)  # type: ignore[arg-type]


def test_every_returns_whatever_the_scheduler_handed_back():
    scheduler = Scheduler(MinimalScheduler(), "default")

    job = scheduler.every(interval_seconds=15, jitter_seconds=None, fn=noop)

    assert job is None


def test_cancel_removes_the_job():
    scheduler = Scheduler(BackgroundScheduler(), "default")
    job = scheduler.every(interval_seconds=15, jitter_seconds=None, fn=noop)

    scheduler.cancel(job)

    assert scheduler.scheduler.get_jobs() == []


def test_cancel_tolerates_a_job_that_was_never_registered():
    scheduler = Scheduler(MinimalScheduler(), "default")

    scheduler.cancel(None)


def test_cancel_swallows_a_job_that_is_already_gone():
    scheduler = Scheduler(BackgroundScheduler(), "default")
    job = scheduler.every(interval_seconds=15, jitter_seconds=None, fn=noop)
    job.remove()

    scheduler.cancel(job)


def test_cancel_lets_other_failures_through():
    class ExplodingJob:
        def remove(self):
            raise RuntimeError("boom")

    scheduler = Scheduler(MinimalScheduler(), "default")

    with pytest.raises(RuntimeError):
        scheduler.cancel(ExplodingJob())


def test_start_starts_a_stopped_scheduler():
    minimal = MinimalScheduler()
    scheduler = Scheduler(minimal, "default")

    scheduler.start()

    assert minimal.started == 1


def test_start_is_a_no_op_on_an_already_running_scheduler():
    scheduler = Scheduler(BackgroundScheduler(), "default")
    scheduler.start()

    scheduler.start()

    assert scheduler.scheduler.running
    scheduler.scheduler.shutdown()


def test_start_works_on_a_scheduler_without_a_state_attribute():
    minimal = MinimalScheduler()
    scheduler = Scheduler(minimal, "default")

    scheduler.start()
    scheduler.start()

    # No `state` to consult, so every call goes through -- the guard must not raise.
    assert minimal.started == 2


def test_shutdown_removes_every_job_before_shutting_down():
    minimal = MinimalScheduler()
    scheduler = Scheduler(minimal, "default")

    scheduler.shutdown()

    assert minimal.jobs_removed == 1
    assert minimal.shutdowns == 1


def test_shutdown_forwards_the_wait_flag():
    recorded = {}

    class WaitRecordingScheduler(MinimalScheduler):
        def shutdown(self, *args, **kwargs):
            recorded.update(kwargs)
            super().shutdown(*args, **kwargs)

    scheduler = Scheduler(WaitRecordingScheduler(), "default")

    scheduler.shutdown(wait=False)

    assert recorded == {"wait": False}


def test_shutdown_raises_when_the_scheduler_was_never_started():
    # UnleashClient.destroy() relies on catching this: destroying a client that was
    # never initialized still reaches shutdown().
    scheduler = Scheduler()

    with pytest.raises(SchedulerNotRunningError):
        scheduler.shutdown()


def test_a_job_registered_through_every_actually_runs():
    scheduler = Scheduler()
    ran = []

    scheduler.every(interval_seconds=1, jitter_seconds=None, fn=lambda: ran.append(1))
    scheduler.start()
    try:
        assert wait_until(lambda: len(ran) >= 1, timeout=WAIT_TIMEOUT)
    finally:
        scheduler.shutdown()
