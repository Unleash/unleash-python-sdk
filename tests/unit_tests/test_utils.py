import pytest

from UnleashClient.utils import _validate_url, extract_environment_from_api_key


def test_valid_api_key():
    result = extract_environment_from_api_key("project:environment.hash")
    assert result == "environment"


def test_api_key_not_present():
    assert extract_environment_from_api_key(None) is None
    assert extract_environment_from_api_key("") is None


def test_environment_part_is_empty():
    result = extract_environment_from_api_key("project:.hash")
    assert result is None


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:4242/api",
        "https://unleash.example.com/api",
        "https://unleash.example.com:8443/api",
        "http://127.0.0.1/api",
        "http://[::1]:4242/api",
    ],
)
def test_validate_url_accepts_http_urls_with_a_host(url):
    _validate_url(url)


@pytest.mark.parametrize(
    "url, message",
    [
        ("thisisnotavalidurl", "must start with http:// or https://"),
        ("localhost:4242/api", "must start with http:// or https://"),
        ("ftp://unleash.example.com", "must start with http:// or https://"),
        ("", "must start with http:// or https://"),
        ("https:", "has no host"),
        ("https:///api", "has no host"),
        ("https://unleash.example.com:abc/api", "Invalid Unleash URL"),
        ("https://unleash.example.com:99999/api", "Invalid Unleash URL"),
        ("https://unleash.example.com/my api", "contains whitespace"),
        (" https://unleash.example.com/api", "contains whitespace"),
    ],
)
def test_validate_url_rejects_malformed_urls(url, message):
    with pytest.raises(ValueError, match=message):
        _validate_url(url)
