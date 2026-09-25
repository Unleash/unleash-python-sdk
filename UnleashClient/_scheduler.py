"""Job scheduling, shared by the sync and async Unleash clients."""

import random
import string
from typing import Any, Callable, Dict, Optional

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_RUNNING, BaseScheduler
from apscheduler.triggers.interval import IntervalTrigger

from UnleashClient.utils import LOGGER

_ScheduledJob = Optional[Any]
"""
An opaque handle on a job registered with :meth:`_Scheduler.every`. Pass it to
:meth:`_Scheduler.cancel` to remove the job.
"""


def _generated_executor_name() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"unleash_executor_{suffix}"


class _Scheduler:
    """
    Runs the client's recurring jobs, such as refreshing feature flags and sending
    metrics.
    """

    scheduler: BaseScheduler
    executor_name: str

    def __init__(
        self,
        scheduler: Optional[BaseScheduler] = None,
        executor_name: Optional[str] = None,
    ) -> None:
        """
        :param scheduler: Custom APScheduler instance. When unset, a
                          ``BackgroundScheduler`` with its own executor is used.
        :param executor_name: Name of the executor to run jobs on. Required with a
                              custom scheduler, ignored with a warning otherwise.
        :raises ValueError: If ``scheduler`` is given without ``executor_name``.
        """
        if scheduler and executor_name:
            self.executor_name = executor_name
        elif scheduler and not executor_name:
            raise ValueError(
                "If using a custom scheduler, you must specify a executor."
            )
        else:
            if not scheduler and executor_name:
                LOGGER.warning(
                    "scheduler_executor should only be used with a custom scheduler."
                )

            self.executor_name = _generated_executor_name()

        if scheduler:
            self.scheduler = scheduler
        else:
            executors = {self.executor_name: ThreadPoolExecutor()}
            self.scheduler = BackgroundScheduler(executors=executors)

    def every(
        self,
        interval_seconds: int,
        jitter_seconds: Optional[int],
        fn: Callable[..., Any],
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> _ScheduledJob:
        """
        Runs ``fn`` repeatedly at a fixed interval.

        :param interval_seconds: Seconds between runs.
        :param jitter_seconds: Maximum seconds to randomly offset each run by, or
                               ``None`` for no jitter.
        :param fn: The callable to run.
        :param kwargs: Keyword arguments to call ``fn`` with.
        :return: A handle to pass to :meth:`cancel`.
        """
        return self.scheduler.add_job(
            fn,
            trigger=IntervalTrigger(seconds=interval_seconds, jitter=jitter_seconds),
            executor=self.executor_name,
            kwargs=kwargs,
        )

    def cancel(self, job: _ScheduledJob) -> None:
        """
        Removes a job registered with :meth:`every`. Does nothing if the job is
        ``None`` or has already been removed.

        :param job: The handle returned by :meth:`every`.
        """
        if job is None:
            return

        try:
            job.remove()
        except JobLookupError as exc:
            LOGGER.info("Exception during connector teardown: %s", exc)

    def start(self) -> None:
        """
        Starts the scheduler. Does nothing if it is already running.
        """
        if getattr(self.scheduler, "state", None) == STATE_RUNNING:
            return

        self.scheduler.start()

    def shutdown(self, wait: bool = True) -> None:
        """
        Removes every job and stops the scheduler.

        :param wait: Whether to wait for running jobs to finish.
        :raises SchedulerNotRunningError: If the scheduler was never started.
        """
        self.scheduler.remove_all_jobs()
        self.scheduler.shutdown(wait=wait)
