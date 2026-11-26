import json

import pytest
import requests
import responses

from tests.utilities.mocks.mock_features import MOCK_FEATURE_RESPONSE
from UnleashClient.constants import FEATURES_URL

BOOTSTRAP_URL = "https://example.com/bootstrap.json"


@pytest.mark.parametrize("status", [404, 503])
@pytest.mark.parametrize("previously_bootstrapped", [False, True])
@responses.activate
def test_bootstrap_from_url_http_error_preserves_cache(
    cache_empty, status, previously_bootstrapped
):
    if previously_bootstrapped:
        cache_empty.bootstrap_from_dict(MOCK_FEATURE_RESPONSE)
    cached_features = cache_empty.get(FEATURES_URL)
    responses.get(BOOTSTRAP_URL, json={"error": "bootstrap unavailable"}, status=status)

    with pytest.raises(requests.HTTPError) as error:
        cache_empty.bootstrap_from_url(BOOTSTRAP_URL)

    assert error.value.response.status_code == status
    assert cache_empty.get(FEATURES_URL) == cached_features
    assert cache_empty.bootstrapped is previously_bootstrapped


@responses.activate
def test_bootstrap_from_url_success_stores_feature_configuration(cache_empty):
    responses.get(BOOTSTRAP_URL, json=MOCK_FEATURE_RESPONSE, status=200)

    cache_empty.bootstrap_from_url(BOOTSTRAP_URL)

    assert json.loads(cache_empty.get(FEATURES_URL)) == MOCK_FEATURE_RESPONSE
    assert cache_empty.bootstrapped is True
