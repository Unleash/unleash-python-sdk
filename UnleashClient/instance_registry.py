"""Duplicate-instance detection, shared by the sync and async Unleash clients."""

import threading
from typing import Dict

from UnleashClient.utils import LOGGER, InstanceAllowType


class InstanceRegistry:
    """
    Counts live client configurations and applies the duplicate-instance policy.

    Clients are keyed by
    :attr:`~UnleashClient.config.UnleashConfig.instance_identifier`, which
    redacts the API key. A client rejected under
    :attr:`~UnleashClient.utils.InstanceAllowType.BLOCK` is not counted, so the
    count only ever covers clients that were actually built.
    """

    def __init__(self) -> None:
        self.instances: Dict[str, int] = {}
        self.lock = threading.RLock()

    def register(self, identifier: str, mode: InstanceAllowType) -> None:
        """
        Record a client under ``identifier`` and apply ``mode`` if it repeats.

        Raises on :attr:`~UnleashClient.utils.InstanceAllowType.BLOCK`, logs an
        error on :attr:`~UnleashClient.utils.InstanceAllowType.WARN`, and is
        silent on :attr:`~UnleashClient.utils.InstanceAllowType.SILENTLY_ALLOW`.
        """
        with self.lock:
            if identifier in self:
                msg = f"You already have {self.count(identifier)} instance(s) configured for this config: {identifier}, please double check the code where this client is being instantiated."
                if mode == InstanceAllowType.BLOCK:
                    raise Exception(msg)  # pylint: disable=broad-exception-raised
                if mode == InstanceAllowType.WARN:
                    LOGGER.error(msg)
            self.increment(identifier)

    def __contains__(self, key: str) -> bool:
        with self.lock:
            return key in self.instances

    def count(self, key: str) -> int:
        with self.lock:
            return self.instances.get(key) or 0

    def increment(self, key: str) -> None:
        with self.lock:
            if key in self:
                self.instances[key] += 1
            else:
                self.instances[key] = 1

    def _reset(self) -> None:
        with self.lock:
            self.instances = {}


_REGISTRY = InstanceRegistry()


def get_instance() -> InstanceRegistry:
    """Return the process-wide registry every Unleash client registers into."""
    return _REGISTRY
