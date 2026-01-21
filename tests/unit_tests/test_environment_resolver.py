from UnleashClient.environment_resolver import extract_environment_from_headers


def test_valid_headers():
    custom_headers = {
        "Authorization": "project:environment.hash",
        "Content-Type": "application/json",
    }

    result = extract_environment_from_headers(custom_headers)
    assert result == "environment"


def test_case_insensitive_header_keys():
    custom_headers = {
        "AUTHORIZATION": "project:environment.hash",
        "Content-Type": "application/json",
    }

    result = extract_environment_from_headers(custom_headers)
    assert result == "environment"


def test_authorization_header_not_present():
    result = extract_environment_from_headers({})
    assert result is None


def test_environment_part_is_empty():
    custom_headers = {
        "Authorization": "project:.hash",
    }

    result = extract_environment_from_headers(custom_headers)
    assert result is None
