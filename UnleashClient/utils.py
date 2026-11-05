import logging
from enum import Enum
from typing import Any, Optional
from urllib.parse import urlsplit

LOGGER = logging.getLogger("UnleashClient")


class InstanceAllowType(Enum):
    BLOCK = 1
    WARN = 2
    SILENTLY_ALLOW = 3


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


def _validate_url(url: str) -> None:
    """
    Checks that ``url`` has the shape of an Unleash API url.

    Only the shape is checked, not whether the host exists or answers: that is a
    network failure, which the client reports.

    :raises ValueError: if ``url`` is not an absolute http(s) url with a host.
    """
    if any(c.isspace() for c in url):
        raise ValueError(f"Unleash URL contains whitespace: {url!r}")

    try:
        parts = urlsplit(url)
        _ = parts.port
    except ValueError as exc:
        raise ValueError(f"Invalid Unleash URL {url!r}: {exc}") from exc

    if parts.scheme not in ("http", "https"):
        raise ValueError(
            f"Unleash URL must start with http:// or https://, got {url!r}"
        )
    if not parts.hostname:
        raise ValueError(f"Unleash URL has no host: {url!r}")
