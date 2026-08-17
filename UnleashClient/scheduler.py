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

ScheduledJob = Optional[Any]
"""
An opaque handle on a registered job.  Callers only store it and hand it back to
:meth:`Scheduler.cancel`.

``Any`` rather than ``apscheduler.job.Job`` for two reasons: APScheduler ships no
``py.typed``, so its ``Job`` is untyped to a strict checker and would leak into every
caller; and a custom scheduler's ``add_job`` is free to return ``None``.
"""


def _generated_executor_name() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"unleash_executor_{suffix}"


class Scheduler:
    """
    Owns the recurring jobs the client runs: the provisioning refresh and the metrics
    send.

    This is the only module that imports APScheduler.  Callers describe a job as an
    interval in seconds, a jitter in seconds and a callable, and get back an opaque
    handle they can pass to :meth:`cancel`; the trigger and the executor are this
    class's business.
    """

    scheduler: BaseScheduler
    executor_name: str

    def __init__(
        self,
        scheduler: Optional[BaseScheduler] = None,
        executor_name: Optional[str] = None,
    ) -> None:
        """
        :param scheduler: Custom APScheduler instance.  When unset, a
                          ``BackgroundScheduler`` is built with a dedicated executor.
        :param executor_name: Name of the executor to run jobs on.  Required with a
                              custom scheduler, meaningless without one.
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
    ) -> ScheduledJob:
        """
        Registers ``fn`` to run on a repeating interval.

        :param interval_seconds: Seconds between runs.  Passed to the trigger
                                 uncoerced, which is what each call site has always
                                 done: the metrics interval is ``int()``-ed by its
                                 caller, the refresh interval is not.
        :param jitter_seconds: Maximum seconds to randomly offset each run by, or None
                               for no jitter.
        :param fn: The callable to run.
        :param kwargs: Keyword arguments to call ``fn`` with.
        """
        return self.scheduler.add_job(
            fn,
            trigger=IntervalTrigger(seconds=interval_seconds, jitter=jitter_seconds),
            executor=self.executor_name,
            kwargs=kwargs,
        )

    def cancel(self, job: ScheduledJob) -> None:
        """
        Removes a job registered through :meth:`every`.

        Tolerates a job that is already gone, and a scheduler whose ``add_job`` returned
        nothing to begin with.
        """
        if job is None:
            return

        try:
            job.remove()
        except JobLookupError as exc:
            LOGGER.info("Exception during connector teardown: %s", exc)

    def start(self) -> None:
        """
        Starts the underlying scheduler, unless it is already running.

        The state is read with ``getattr`` because a custom scheduler need not be an
        APScheduler one, and duck-typed schedulers without a ``state`` attribute are
        supported.
        """
        if getattr(self.scheduler, "state", None) == STATE_RUNNING:
            return

        self.scheduler.start()

    def shutdown(self, wait: bool = True) -> None:
        """
        Drops every job, then shuts the scheduler down.

        Raises ``SchedulerNotRunningError`` when the scheduler was never started; the
        caller decides whether that is worth reporting.
        """
        self.scheduler.remove_all_jobs()
        self.scheduler.shutdown(wait=wait)
