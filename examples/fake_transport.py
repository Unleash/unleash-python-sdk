"""
Test code that uses Unleash without a server or HTTP mocking.

The fake transport answers every feature fetch with fixed flags and accepts
registration and metrics. ``requests`` lists what the SDK sent.
"""

import json
from typing import Any, Dict, List

from UnleashClient import Method, Request, Response, UnleashClient


class FakeTransport:
    def __init__(self, *flags: Dict[str, Any]) -> None:
        self._features = json.dumps({"version": 1, "features": list(flags)}).encode()
        self.requests: List[Request] = []

    def execute(self, request: Request) -> Response:
        self.requests.append(request)
        if request.method == Method.GET:
            return Response(status=200, headers={}, body=self._features)
        return Response(status=202, headers={}, body=b"")


def flag(name: str, enabled: bool) -> Dict[str, Any]:
    return {
        "name": name,
        "enabled": enabled,
        "strategies": [{"name": "default", "parameters": {}}],
    }


def test_new_checkout_is_on(tmp_path):
    transport = FakeTransport(flag("new-checkout", True))

    with UnleashClient(
        "http://unleash.test/api",
        "my-app-tests",
        transport=transport,
        cache_directory=str(tmp_path),
    ) as client:
        assert client.is_enabled("new-checkout")
        assert not client.is_enabled("unknown-flag")
