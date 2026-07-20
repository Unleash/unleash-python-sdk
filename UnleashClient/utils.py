import logging
from enum import Enum
from threading import RLock
from typing import Any

import mmh3  # pylint: disable=import-error
from requests import Response

LOGGER = logging.getLogger("UnleashClient")


class InstanceAllowType(Enum):
    BLOCK = 1
    WARN = 2
    SILENTLY_ALLOW = 3


class InstanceCounter:
    def __init__(self):
        self.instances = {}
        self.lock = RLock()

    def __contains__(self, key):
        with self.lock:
            return key in self.instances

    def _reset(self):
        self.instances = {}

    def count(self, key):
        with self.lock:
            return self.instances.get(key) or 0

    def increment(self, key):
        with self.lock:
            if key in self:
                self.instances[key] += 1
            else:
                self.instances[key] = 1


def normalized_hash(
    identifier: str, activation_group: str, normalizer: int = 100, seed: int = 0
) -> int:
    return (
        mmh3.hash(f"{activation_group}:{identifier}", signed=False, seed=seed)
        % normalizer
        + 1
    )


def get_identifier(context_key_name: str, context: dict) -> Any:
    if context_key_name in context.keys():
        value = context[context_key_name]
    elif (
        "properties" in context.keys()
        and context_key_name in context["properties"].keys()
    ):
        value = context["properties"][context_key_name]
    else:
        value = None

    return value


def log_resp_info(resp: Response) -> None:
    LOGGER.debug("HTTP status code: %s", resp.status_code)
    LOGGER.debug("HTTP headers: %s", resp.headers)
    LOGGER.debug("HTTP content: %s", resp.text)
