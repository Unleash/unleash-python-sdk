"""Metrics reporting for the asynchronous Unleash client.

Importing this module requires the optional ``aiohttp`` dependency:
``pip install UnleashClient[async]``.
"""

import asyncio
import random
import time
from typing import Optional

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.async_transport import AsyncTransport
from UnleashClient.config import UnleashConfig
from UnleashClient.impact_metrics import ImpactMetrics
from UnleashClient.payloads import build_metrics_payload
from UnleashClient.utils import LOGGER


class AsyncMetricsReporter:
    """
    Sends feature and impact metrics to Unleash on a recurring interval.

    The schedule is an :class:`asyncio.Task`, so :meth:`start` and :meth:`stop` must be
    awaited from the event loop the client runs on, and the loop must stay open for as
    long as metrics are being reported.

    Every value the request depends on is read from the
    :class:`~UnleashClient.config.UnleashConfig` at send time, so reassigning a client's
    ``unleash_*`` attributes takes effect from the next send.  That includes
    ``metrics_interval`` and ``metrics_jitter``, which are re-read before every cycle.
    """

    def __init__(
        self,
        config: UnleashConfig,
        transport: AsyncTransport,
        engine: UnleashEngine,
        impact_metrics: ImpactMetrics,
    ) -> None:
        """
        :param config: read on every send for the request body, the interval and the
                       jitter.
        :param transport: sends the request.
        :param engine: read for the feature metrics bucket.  Separate from
                       ``impact_metrics``, which is a different set of numbers that
                       happens to be stored in the same engine.
        :param impact_metrics: drained for each send, and restored when a send fails.
        """
        self._config: UnleashConfig = config
        self._transport: AsyncTransport = transport
        self._engine: UnleashEngine = engine
        self._impact_metrics: ImpactMetrics = impact_metrics
        self._task: Optional["asyncio.Task"] = None

    async def start(self) -> None:
        """Starts the recurring send on the current event loop."""
        self._task = asyncio.create_task(self._run())

    def _next_fire(self, previous_fire: float) -> float:
        """
        When the send after ``previous_fire`` is due, on :func:`time.monotonic`'s clock.

        Jitter is drawn from ``[0, jitter)`` and delays the fire; it never brings one
        forward.

        :param previous_fire: the fire time this one follows.
        """
        next_fire = previous_fire + int(self._config.metrics_interval)

        jitter = self._config.metrics_jitter
        if jitter:
            next_fire += random.uniform(0, jitter)

        return next_fire

    async def _wait_until(self, fire: float) -> None:
        """
        Sleeps until ``fire``, returning at once if it has already passed.

        :param fire: a :func:`time.monotonic` timestamp.
        """
        await asyncio.sleep(max(fire - time.monotonic(), 0))

    async def _run(self) -> None:
        """
        Sends on the configured interval until cancelled.

        Each fire is measured from the previous one rather than from the clock, so the
        schedule does not drift by however long each send takes.  A send that overruns
        its interval is followed immediately by the next one.

        A send that raises is logged and the schedule continues, so one failure does not
        end metrics reporting for the life of the client.
        """
        next_fire = time.monotonic()

        while True:
            next_fire = self._next_fire(next_fire)
            await self._wait_until(next_fire)

            try:
                await self.flush()
            except Exception as exc:
                LOGGER.warning("Exception during metrics submission: %s", exc)

    async def flush(self) -> None:
        """
        Sends one bucket of feature and impact metrics.

        Sends nothing when neither has anything to report.  Impact metrics are handed
        back to the engine when the send fails, so the next send carries them instead.
        """
        bucket = self._engine.get_metrics()
        impact_metrics = self._impact_metrics.collect()

        if not (bucket or impact_metrics):
            LOGGER.debug("No feature flags with metrics, skipping metrics submission.")
            return

        payload = build_metrics_payload(self._config, bucket, impact_metrics)
        if not await self._transport.send_metrics(payload) and impact_metrics:
            self._impact_metrics.restore(impact_metrics)

    async def stop(self) -> None:
        """
        Stops the recurring send and flushes whatever is left.

        Does nothing when :meth:`start` was never called.  Metrics drained by a send
        that is still in flight are lost with it.
        """
        if self._task is None:
            return

        task, self._task = self._task, None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            LOGGER.warning("Metrics reporting had already stopped: %s", exc)

        await self.flush()
