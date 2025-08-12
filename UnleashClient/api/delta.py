from typing import Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from UnleashClient.constants import DELTA_URL
from UnleashClient.utils import LOGGER, log_resp_info

# pylint: disable=broad-except
def get_feature_deltas(
    url: str,
    app_name: str,
    instance_id: str,
    headers: dict,
    custom_options: dict,
    request_timeout: int,
    request_retries: int,
    cached_etag: str = "",
) -> Tuple[Optional[str], str]:
    """
    Retrieves feature deltas from the Unleash server.

    Returns a tuple of (raw_json_string_or_None, etag).
    """
    try:
        LOGGER.info("Getting feature deltas.")

        request_specific_headers = {
            "UNLEASH-APPNAME": app_name,
            "UNLEASH-INSTANCEID": instance_id,
        }

        if cached_etag:
            request_specific_headers["If-None-Match"] = cached_etag

        base_url = f"{url}{DELTA_URL}"

        adapter = HTTPAdapter(
            max_retries=Retry(total=request_retries, status_forcelist=[500, 502, 504])
        )
        with requests.Session() as session:
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            resp = session.get(
                base_url,
                headers={**headers, **request_specific_headers},
                timeout=request_timeout,
                **custom_options,
            )

        if resp.status_code not in [200, 304]:
            log_resp_info(resp)
            LOGGER.warning(
                "Unleash Client delta fetch failed due to unexpected HTTP status code: %s",
                resp.status_code,
            )
            raise Exception("Unleash Client delta fetch failed!")

        etag = resp.headers.get("etag", "")

        if resp.status_code == 304:
            return None, etag

        return resp.text, etag
    except Exception as exc:
        LOGGER.exception("Unleash Client delta fetch failed due to exception: %s", exc)

    return None, ""
