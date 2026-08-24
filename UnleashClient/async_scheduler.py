"""Job scheduling for the asynchronous Unleash client.

Jobs run as :class:`asyncio.Task` objects rather than on APScheduler's worker threads,
which is what lets a job body await.  Nothing here imports aiohttp, so this module is
available without the optional ``[async]`` dependency.
"""

import asyncio
import inspect
import random
import time
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from UnleashClient.utils import LOGGER


class AsyncScheduledJob:
    """
    A repeating job registered through :meth:`AsyncScheduler.every`.

    Callers store the handle and hand it back to :meth:`AsyncScheduler.cancel`; the
    schedule and the task behind it are the scheduler's business.
    """

    def __init__(
        self,
        interval_seconds: int,
        jitter_seconds: Optional[int],
        fn: Callable[..., Any],
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        :param interval_seconds: Seconds between runs.
        :param jitter_seconds: Maximum seconds to randomly offset each run by, or None
                               for no jitter.
        :param fn: The callable to run.  A coroutine function is awaited; anything else
                   is called inline on the event loop.
        :param kwargs: Keyword arguments to call ``fn`` with.
        """
        self.interval: timedelta = timedelta(seconds=interval_seconds)
        self.jitter: Optional[int] = jitter_seconds
        self.fn: Callable[..., Any] = fn
        self.kwargs: Dict[str, Any] = kwargs or {}
        self.task: Optional["asyncio.Task"] = None

    def _start(self) -> None:
        """Puts the job's loop on the running event loop."""
        self.task = asyncio.create_task(self._run())

    def _next_fire(self, previous_fire: float) -> float:
        """
        When the run after ``previous_fire`` is due, on :func:`time.monotonic`'s clock.

        Jitter is drawn from ``[0, jitter)`` and delays the run; it never brings one
        forward.

        :param previous_fire: the fire time this one follows.
        """
        next_fire = previous_fire + self.interval.total_seconds()

        if self.jitter:
            next_fire += random.uniform(0, self.jitter)

        return next_fire

    async def _wait_until(self, fire: float) -> None:
        """
        Sleeps until ``fire``, returning at once if it has already passed.

        :param fire: a :func:`time.monotonic` timestamp.
        """
        await asyncio.sleep(max(fire - time.monotonic(), 0))

    async def _call(self) -> None:
        """Runs the callable once, awaiting it when there is something to await."""
        outcome = self.fn(**self.kwargs)

        if inspect.isawaitable(outcome):
            await outcome

    async def _run(self) -> None:
        """
        Runs on the configured interval until cancelled.

        Each fire is measured from the previous one rather than from the clock, so the
        schedule does not drift by however long each run takes.  A run that overruns its
        interval is followed immediately by the next one.

        A run that raises is logged and the schedule continues, so one failure does not
        end the job for the life of the client.
        """
        next_fire = time.monotonic()

        while True:
            next_fire = self._next_fire(next_fire)
            await self._wait_until(next_fire)

            try:
                await self._call()
            except Exception as exc:
                LOGGER.warning("Exception during scheduled job: %s", exc)

    def _cancel(self) -> None:
        """Asks the job's task to stop.  Does not wait for it."""
        if self.task is not None:
            self.task.cancel()

    async def _drain(self) -> None:
        """Waits for a cancelled task to unwind."""
        if self.task is None:
            return

        task, self.task = self.task, None
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            LOGGER.warning("Scheduled job had already stopped: %s", exc)


class AsyncScheduler:
    """
    Owns the recurring jobs the asynchronous client runs.

    The asynchronous counterpart of :class:`UnleashClient.scheduler.Scheduler`, with the
    same four methods, so a caller that only registers and cancels jobs works against
    either.  Only :meth:`shutdown` is a coroutine, because awaiting the cancelled tasks
    is the one thing that needs the event loop.

    Jobs run on the loop that called :meth:`start`, not on a worker thread, so a job may
    be a coroutine function.  The loop must stay open for as long as jobs are running.
    """

    def __init__(self) -> None:
        self._jobs: List[AsyncScheduledJob] = []
        self._running: bool = False

    @property
    def running(self) -> bool:
        """Whether :meth:`start` has been called and :meth:`shutdown` has not."""
        return self._running

    @property
    def jobs(self) -> Tuple[AsyncScheduledJob, ...]:
        """The jobs registered and not yet cancelled."""
        return tuple(self._jobs)

    def every(
        self,
        interval_seconds: int,
        jitter_seconds: Optional[int],
        fn: Callable[..., Any],
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> AsyncScheduledJob:
        """
        Registers ``fn`` to run on a repeating interval.

        A job registered before :meth:`start` is pending and runs from the moment the
        scheduler starts; one registered afterwards starts at once.  Either way the
        first run is one interval later, never immediate.

        :param interval_seconds: Seconds between runs.  Passed uncoerced, so a string
                                 raises here rather than inside a task.
        :param jitter_seconds: Maximum seconds to randomly offset each run by, or None
                               for no jitter.
        :param fn: The callable to run.  A coroutine function is awaited; anything else
                   is called inline on the event loop.
        :param kwargs: Keyword arguments to call ``fn`` with.
        """
        job = AsyncScheduledJob(interval_seconds, jitter_seconds, fn, kwargs)
        self._jobs.append(job)

        if self._running:
            job._start()

        return job

    def cancel(self, job: Optional[AsyncScheduledJob]) -> None:
        """
        Drops a job registered through :meth:`every`.

        Tolerates a job that was never started, and a ``None`` handle from a caller
        that is stopping before it started.

        :param job: The handle :meth:`every` returned.
        """
        if job is None:
            return

        job._cancel()

        if job in self._jobs:
            self._jobs.remove(job)

    def start(self) -> None:
        """
        Starts every pending job on the running event loop.

        A no-op when the scheduler is already running, so a caller that cannot tell
        whether it is the first to start it does not have to check.
        """
        if self._running:
            return

        self._running = True

        for job in self._jobs:
            job._start()

    async def shutdown(self, wait: bool = True) -> None:
        """
        Drops every job and stops the scheduler.

        Unlike its synchronous counterpart, this returns quietly on a scheduler that was
        never started, so a client being destroyed before it was initialized needs no
        special case.

        :param wait: Whether to wait for the cancelled jobs to unwind.  With False the
                     jobs are asked to stop and this returns immediately.
        """
        jobs, self._jobs = self._jobs, []
        self._running = False

        for job in jobs:
            job._cancel()

        if not wait:
            return

        for job in jobs:
            await job._drain()
