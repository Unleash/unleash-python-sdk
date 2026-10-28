from UnleashClient.utils import extract_environment_from_api_key


def test_valid_api_key():
    result = extract_environment_from_api_key("project:environment.hash")
    assert result == "environment"


def test_api_key_not_present():
    assert extract_environment_from_api_key(None) is None
    assert extract_environment_from_api_key("") is None


def test_environment_part_is_empty():
    result = extract_environment_from_api_key("project:.hash")
    assert result is None
