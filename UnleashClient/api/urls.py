def build_normalized_url(url: str, path: str) -> str:
    return f"{url.rstrip('/')}{path}"
