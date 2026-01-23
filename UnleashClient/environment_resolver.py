from typing import Dict, Optional


def extract_environment_from_headers(
    headers: Optional[Dict[str, str]],
) -> Optional[str]:
    if not headers:
        return None

    auth_key = next(
        (key for key in headers if key.lower() == "authorization"),
        None,
    )
    if not auth_key:
        return None

    auth_value = headers.get(auth_key)
    if not auth_value:
        return None

    _, sep, after_colon = auth_value.partition(":")
    if not sep:
        return None

    environment, _, _ = after_colon.partition(".")
    return environment or None
