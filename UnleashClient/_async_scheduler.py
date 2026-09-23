"""Job scheduling for the asynchronous Unleash client."""

import asyncio
import random
from typing import Any, Awaitable, Callable, Dict, Optional, Set

from UnleashClient.utils import LOGGER

_AsyncJobFn = Callable[..., Awaitable[Any]]


class _AsyncJob:
    """A job registered with :meth:`_AsyncScheduler.every`."""

    __slots__ = ("interval", "jitter", "fn", "kwargs", "task")

    def __init__(
        self,
        interval: float,
        jitter: Optional[float],
        fn: _AsyncJobFn,
        kwargs: Dict[str, Any],
    ) -> None:
        self.interval = interval
        self.jitter = jitter
        self.fn = fn
        self.kwargs = kwargs
        self.task: Optional["asyncio.Task[None]"] = None


_AsyncScheduledJob = Optional[_AsyncJob]
"""
An opaque handle on a job registered with :meth:`_AsyncScheduler.every`. Pass it to
:meth:`_AsyncScheduler.cancel` or :meth:`_AsyncScheduler.cancel_and_wait` to remove
the job.
"""


class _AsyncScheduler:
    """
    Runs the asynchronous client's recurring jobs as tasks on the running event
    loop. Cancelling a job or shutting down interrupts a run in progress.

    Example::

        async def refresh(url: str) -> None:
            ...

        scheduler = _AsyncScheduler()
        job = scheduler.every(15, None, refresh, kwargs={"url": url})
        scheduler.start()

        await scheduler.cancel_and_wait(job)
        await scheduler.shutdown()
    """

    def __init__(self) -> None:
        self._jobs: Set[_AsyncJob] = set()
        self._running = False

    def every(
        self,
        interval_seconds: float,
        jitter_seconds: Optional[float],
        fn: _AsyncJobFn,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> _AsyncScheduledJob:
        """
        Runs ``fn`` repeatedly at a fixed interval. The job starts right away when
        the scheduler is running, and on :meth:`start` otherwise.

        :param interval_seconds: Seconds between runs. ``0`` means one second.
        :param jitter_seconds: Maximum seconds to randomly delay each run by, or
                               ``None`` for no jitter.
        :param fn: The coroutine function to run.
        :param kwargs: Keyword arguments to call ``fn`` with.
        :return: A handle to pass to :meth:`cancel` or :meth:`cancel_and_wait`.
        """
        job = _AsyncJob(interval_seconds or 1, jitter_seconds, fn, dict(kwargs or {}))
        self._jobs.add(job)
        if self._running:
            self._spawn(job)
        return job

    def cancel(self, job: _AsyncScheduledJob) -> None:
        """
        Removes a job registered with :meth:`every`, interrupting a run in progress.
        Does nothing if the job is ``None`` or has already been removed.

        :param job: The handle returned by :meth:`every`.
        """
        if job is None:
            return
        self._jobs.discard(job)
        if job.task is not None:
            job.task.cancel()

    async def cancel_and_wait(self, job: _AsyncScheduledJob) -> None:
        """
        Removes a job like :meth:`cancel`, and returns once a run in progress has
        fully unwound. When a job cancels itself, the cancellation takes effect at
        its next ``await`` instead.

        :param job: The handle returned by :meth:`every`.
        """
        if job is None:
            return
        task = job.task
        self.cancel(job)
        if task is None or task is asyncio.current_task():
            return
        await asyncio.gather(task, return_exceptions=True)

    def start(self) -> None:
        """
        Starts every registered job. Does nothing if the scheduler is already
        running.

        :raises RuntimeError: If called outside a running event loop.
        """
        if self._running:
            return
        asyncio.get_running_loop()
        self._running = True
        for job in self._jobs:
            self._spawn(job)

    async def shutdown(self, wait: bool = True) -> None:
        """
        Removes every job and stops the scheduler. Safe to call on a scheduler that
        was never started, and from inside one of its own jobs.

        :param wait: Whether to wait for interrupted runs to fully unwind.
        """
        self._running = False
        tasks = [job.task for job in self._jobs if job.task is not None]
        self._jobs.clear()
        for task in tasks:
            task.cancel()
        if wait:
            current = asyncio.current_task()
            await asyncio.gather(
                *(task for task in tasks if task is not current),
                return_exceptions=True,
            )

    def _spawn(self, job: _AsyncJob) -> None:
        name = getattr(job.fn, "__name__", "job")
        job.task = asyncio.create_task(self._run(job), name=f"unleash-{name}")

    async def _run(self, job: _AsyncJob) -> None:
        loop = asyncio.get_running_loop()
        next_at = loop.time() + job.interval
        while True:
            delay = next_at - loop.time()
            if job.jitter:
                delay += random.uniform(0, job.jitter)
            await asyncio.sleep(max(0.0, delay))
            try:
                await job.fn(**job.kwargs)
            except Exception:
                LOGGER.exception("Scheduled job %r failed", job.fn)
            next_at += job.interval
            now = loop.time()
            if next_at < now:
                next_at += ((now - next_at) // job.interval + 1) * job.interval
