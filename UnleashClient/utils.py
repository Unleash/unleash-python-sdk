import logging
from enum import Enum
from typing import Any, Optional

import mmh3  # pylint: disable=import-error

LOGGER = logging.getLogger("UnleashClient")


class InstanceAllowType(Enum):
    BLOCK = 1
    WARN = 2
    SILENTLY_ALLOW = 3


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


def extract_environment_from_api_key(api_key: Optional[str]) -> Optional[str]:
    if not api_key:
        return None

    _, sep, after_colon = api_key.partition(":")
    if not sep:
        return None

    environment, _, _ = after_colon.partition(".")
    return environment or None
