import asyncio
import json

import aiohttp
import pytest
import pytest_asyncio
from pytest import mark

from tests.utilities.fake_unleash_server import FakeUnleash
from UnleashClient._aiohttp_transport import AiohttpTransport
from UnleashClient.errors import AlreadyClosedError
from UnleashClient.transport import AsyncTransport, Request

PATH = "/client/features"


@pytest_asyncio.fixture
async def server():
    fake = FakeUnleash()
    await fake.start()
    try:
        yield fake
    finally:
        await fake.close()


@pytest_asyncio.fixture
async def transport():
    transport = AiohttpTransport()
    try:
        yield transport
    finally:
        await transport.aclose()


def test_aiohttp_transport_is_an_async_transport():
    assert isinstance(AiohttpTransport(), AsyncTransport)


@mark.asyncio
async def test_execute_sends_a_get_with_its_headers_and_params(server, transport):
    server.on("GET", PATH)

    await transport.execute(
        Request(
            method="GET",
            url=server.base_url + PATH,
            headers={"X-Test": "value"},
            params={"project": "ivan"},
        )
    )

    sent = server.calls("GET", PATH)[0]
    assert sent.query == {"project": "ivan"}
    assert sent.headers["X-Test"] == "value"
    assert sent.body == ""


@mark.asyncio
async def test_execute_sends_a_post_with_its_body(server, transport):
    server.on("POST", PATH, status=202)

    await transport.execute(
        Request(
            method="POST",
            url=server.base_url + PATH,
            headers={},
            body=b'{"appName": "x"}',
        )
    )

    assert json.loads(server.calls("POST", PATH)[0].body) == {"appName": "x"}


@mark.asyncio
async def test_execute_returns_the_status_headers_and_body(server, transport):
    server.on("GET", PATH, payload={"version": 1}, headers={"ETag": "v1"})

    response = await transport.execute(
        Request(method="GET", url=server.base_url + PATH, headers={})
    )

    assert response.status == 200
    assert json.loads(response.body) == {"version": 1}
    assert response.headers["etag"] == "v1"


@mark.asyncio
@mark.parametrize("status", [304, 401, 500])
async def test_execute_returns_any_status_instead_of_raising(server, transport, status):
    server.on("GET", PATH, status=status)

    response = await transport.execute(
        Request(method="GET", url=server.base_url + PATH, headers={})
    )

    assert response.status == status


@mark.asyncio
async def test_execute_raises_when_no_response_arrives(server, transport):
    server.on("GET", PATH, disconnect=True, repeat=True)

    with pytest.raises(aiohttp.ClientConnectionError):
        await transport.execute(
            Request(method="GET", url=server.base_url + PATH, headers={})
        )


@mark.asyncio
async def test_execute_raises_when_the_server_does_not_answer_in_time(server):
    server.on("GET", PATH, hang=True)
    transport = AiohttpTransport(timeout=0.1)

    try:
        with pytest.raises(asyncio.TimeoutError):
            await transport.execute(
                Request(method="GET", url=server.base_url + PATH, headers={})
            )
    finally:
        await transport.aclose()


@mark.asyncio
async def test_execute_reuses_one_session(server, transport):
    server.on("GET", PATH, repeat=True)
    request = Request(method="GET", url=server.base_url + PATH, headers={})

    await transport.execute(request)
    first = transport._session
    await transport.execute(request)

    assert first is not None
    assert transport._session is first


@mark.asyncio
async def test_aclose_closes_the_session(server, transport):
    server.on("GET", PATH)
    await transport.execute(
        Request(method="GET", url=server.base_url + PATH, headers={})
    )
    session = transport._session

    await transport.aclose()

    assert session.closed


@mark.asyncio
async def test_execute_after_aclose_raises(server, transport):
    server.on("GET", PATH, repeat=True)
    request = Request(method="GET", url=server.base_url + PATH, headers={})
    await transport.execute(request)

    await transport.aclose()

    with pytest.raises(AlreadyClosedError):
        await transport.execute(request)
    assert len(server.calls("GET", PATH)) == 1


@mark.asyncio
async def test_execute_after_aclose_raises_without_an_earlier_request(server):
    transport = AiohttpTransport()

    await transport.aclose()

    with pytest.raises(AlreadyClosedError):
        await transport.execute(
            Request(method="GET", url=server.base_url + PATH, headers={})
        )
    assert server.requests == []


@mark.asyncio
async def test_closing_a_closed_transport_does_nothing(transport):
    await transport.aclose()
    await transport.aclose()


@mark.asyncio
async def test_execute_sends_on_the_session_passed_in(server):
    server.on("GET", PATH, headers={"Set-Cookie": "a=1"})
    server.on("GET", PATH)
    # unsafe: the fake server is on an IP address, whose cookies aiohttp
    # otherwise ignores
    async with aiohttp.ClientSession(
        headers={"X-From-Session": "yes"},
        cookie_jar=aiohttp.CookieJar(unsafe=True),
    ) as session:
        transport = AiohttpTransport(session)

        await transport.execute(
            Request(method="GET", url=server.base_url + PATH, headers={})
        )
        await transport.execute(
            Request(method="GET", url=server.base_url + PATH, headers={})
        )

    first, second = server.calls("GET", PATH)
    assert first.headers["X-From-Session"] == "yes"
    # the same session both times: it sends the cookie back
    assert second.headers["Cookie"] == "a=1"


@mark.asyncio
async def test_aclose_leaves_the_session_passed_in_open(server):
    async with aiohttp.ClientSession() as session:
        transport = AiohttpTransport(session)

        await transport.aclose()

        assert not session.closed


@mark.asyncio
async def test_a_closed_transport_raises_even_with_a_session_passed_in(server):
    async with aiohttp.ClientSession() as session:
        transport = AiohttpTransport(session)
        await transport.aclose()

        with pytest.raises(AlreadyClosedError):
            await transport.execute(
                Request(method="GET", url=server.base_url + PATH, headers={})
            )

    assert server.requests == []


@mark.asyncio
async def test_a_session_that_raises_for_status_still_returns_the_response(server):
    server.on("GET", PATH, status=500)
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        response = await AiohttpTransport(session).execute(
            Request(method="GET", url=server.base_url + PATH, headers={})
        )

    assert response.status == 500


# headers


@mark.asyncio
async def test_execute_sends_the_transport_headers(server):
    server.on("GET", PATH)
    transport = AiohttpTransport(headers={"X-Team": "checkout"})

    try:
        await transport.execute(
            Request(
                method="GET", url=server.base_url + PATH, headers={"X-Test": "value"}
            )
        )
    finally:
        await transport.aclose()

    sent = server.calls("GET", PATH)[0]
    assert sent.headers["X-Team"] == "checkout"
    assert sent.headers["X-Test"] == "value"


@mark.asyncio
async def test_the_request_headers_win_over_the_transport_headers_whatever_their_case(
    server,
):
    server.on("GET", PATH)
    transport = AiohttpTransport(headers={"UNLEASH-APPNAME": "spoofed"})

    try:
        await transport.execute(
            Request(
                method="GET",
                url=server.base_url + PATH,
                headers={"unleash-appname": "my-app"},
            )
        )
    finally:
        await transport.aclose()

    assert server.calls("GET", PATH)[0].headers.getall("unleash-appname") == ["my-app"]


@pytest.mark.parametrize("name", ["Authorization", "authorization"])
def test_an_authorization_header_raises(name):
    with pytest.raises(ValueError, match="api_key"):
        AiohttpTransport(headers={name: "token"})
