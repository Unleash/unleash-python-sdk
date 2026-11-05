# Migrating to Unleash-Client-Python 7.0.0

This guide highlights the key changes you should be aware of when upgrading to v7.0.0 of the Unleash client.

## Settings are grouped into option objects

`url` and `app_name` are still the first two arguments. The API token is now its own `api_key` argument. All other arguments must now be passed by keyword. Most other settings moved into option objects: `IdentityOptions`, `MetricsOptions`, and either `PollingOptions` or `StreamingOptions`. HTTP settings moved to the transport, see [below](#http-settings-are-set-on-the-transport). The option objects take keyword arguments only.

Before:

``` python
client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    environment="production",
    custom_headers={"Authorization": "<API token>"},
    refresh_interval=30,
    disable_metrics=True,
    experimental_mode={"type": "streaming"},
    custom_strategies={"EmailStrategy": EmailStrategy()},
)
```

After:

``` python
from UnleashClient import (
    MetricsOptions, StreamingOptions, UnleashClient,
)

client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    api_key="<API token>",
    mode=StreamingOptions(),
    metrics=MetricsOptions(disabled=True),
    custom_strategies={"EmailStrategy": EmailStrategy()},
)
```

A polling client passes it as `mode=PollingOptions(interval=30)`.
The same applies to `AsyncUnleashClient`, but only polling is supported.

### Migrating arguments

| v6 argument            | v7                                          |
| ---------------------- | ------------------------------------------- |
| `url`                  | unchanged                                   |
| `app_name`             | unchanged                                   |
| `custom_headers={"Authorization": ...}` | `api_key=...`              |
| `environment`          | removed, see [below](#environment-has-been-removed) |
| `instance_id`          | `IdentityOptions(instance_id=...)`          |
| `sdk_flavor`           | `IdentityOptions(sdk_flavor=...)`           |
| `sdk_flavor_version`   | `IdentityOptions(sdk_flavor_version=...)`   |
| `custom_headers`       | `transport=RequestsTransport(headers=...)`, without `Authorization` |
| `custom_options`       | removed: configure a `requests.Session`, see [below](#http-settings-are-set-on-the-transport) |
| `request_timeout`      | `transport=RequestsTransport(timeout=...)`  |
| `request_retries`      | removed: a failed feature fetch is retried up to 3 times |
| `refresh_interval`     | `PollingOptions(interval=...)`              |
| `refresh_jitter`       | `PollingOptions(jitter=...)`                |
| `project_name`         | `PollingOptions(project_name=...)`          |
| `experimental_mode`    | `mode=StreamingOptions()` instead of `experimental_mode={"type": "streaming"}`; polling is `mode=PollingOptions(...)` |
| `metrics_interval`     | `MetricsOptions(interval=...)`              |
| `metrics_jitter`       | `MetricsOptions(jitter=...)`                |
| `disable_metrics`      | `MetricsOptions(disabled=...)`              |
| `disable_registration` | `MetricsOptions(disable_registration=...)`  |
| `verbose_log_level`    | unchanged, keyword-only                     |
| `custom_strategies`, `cache`, `cache_directory`, `scheduler`, `scheduler_executor`, `multiple_instance_mode`, `event_callback` | unchanged, keyword-only |

The `ExperimentalMode` type has been removed.

Offline mode (`initialize_client(fetch_toggles=False)`) reloads the cache every `PollingOptions.interval` seconds. With `StreamingOptions` it uses the default, 15 seconds, where v6 used `refresh_interval`; to change it, pass `PollingOptions(interval=...)` instead.

## The API token is passed as `api_key`

Pass the API token as `api_key` instead of as an `Authorization` header:

``` python
client = UnleashClient(url, app_name, api_key="<API token>")
```

An `Authorization` header in the `headers` of a `RequestsTransport` or `AiohttpTransport` raises a `ValueError`, in any letter case. It is not silently ignored, because a client without a key still starts: its requests fail with 401 and it keeps serving the flags in its cache, so the mistake could go unnoticed. All other custom headers work as before.

## HTTP settings are set on the transport

Headers, timeout and anything else about how requests are sent are set on the transport, passed as `transport=`. For `UnleashClient` that's a `RequestsTransport`, for `AsyncUnleashClient` an `AiohttpTransport`, with the same `headers` and `timeout` arguments.

Before:

``` python
client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    custom_headers={"Authorization": "<API token>", "X-Team": "checkout"},
    custom_options={"verify": "/etc/ssl/certs/internal-ca.pem", "proxies": {"https": "http://proxy.internal:3128"}},
    request_timeout=10,
    request_retries=1,
)
```

After:

``` python
import requests
from UnleashClient import RequestsTransport, UnleashClient

session = requests.Session()
session.verify = "/etc/ssl/certs/internal-ca.pem"
session.proxies = {"https": "http://proxy.internal:3128"}

client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    api_key="<API token>",
    transport=RequestsTransport(session, headers={"X-Team": "checkout"}, timeout=10),
)
```

`custom_options` were keyword arguments for every `requests` call. Most of them are session settings, anything else, such as `allow_redirects`, can be done in your own transport, see [custom HTTP transport](./README.md#custom-http-transport). The client never closes a session you pass in.

`request_retries` has been removed. A failed feature fetch is retried up to 3 times, on a 500, 502 or 504 or when no response arrives, with a short backoff. Registration and metrics are never retried. To stop retries stacking, don't mount a retrying adapter on your session.

In streaming mode, the stream doesn't use the transport: it connects with the SDK's own headers and a 30 second timeout. In v6 it also received `custom_headers`, `request_timeout` and `custom_options`; there is no replacement for those. If your proxy or gateway needs a custom header on every request, use polling for now.

## The URL is validated

The client constructor raises a `ValueError` if `url` is not an absolute `http://` or `https://` URL with a host. Only the shape is checked, not whether the server can be reached.

This applies to every client, including one that never talks to the server (`fetch_toggles=False` with registration and metrics disabled). In v6 such a client accepted any string as `url`; pass a well-formed one instead:

``` python
client = UnleashClient(
    "http://localhost",
    app_name,
    metrics=MetricsOptions(disabled=True, disable_registration=True),
)
client.initialize_client(fetch_toggles=False)
```

In v6 a malformed URL only raised when the client registered. With registration disabled, every fetch and metrics send failed and was only logged.

## `environment` has been removed

The `environment` argument has been removed, with no replacement. Your API token decides which environment the client gets flags for.

The `environment` field of the evaluation context and the `environment` label on impact metrics are now taken from your API token, or are `"default"`.

In v6 the context got the `environment` setting, `"default"` unless you set it, whatever the token said. So if the token names an environment, the context value changes:

| API token             | v6 `environment` setting | v6 context     | v7 context     |
| --------------------- | ------------------------ | -------------- | -------------- |
| `*:production.abc123` | not set                  | `"default"`    | `"production"` |
| `*:production.abc123` | `"staging"`              | `"staging"`    | `"production"` |

This only matters if strategies or constraints use the `environment` context field. A constraint such as `environment IN [default]` matched every call in v6 and won't match in v7. Update the constraint to the token's environment, or pass the value you need with each call:

``` python
client.is_enabled("my-flag", {"environment": "default"})
```

## Settings can't be changed after construction

A client's settings can't be changed after it is created. To change a setting, create a new client.

In v6.9, assigning to `unleash_url`, `unleash_custom_headers` and the other request settings on a running client took effect on the next request; that is no longer possible. Option objects and transport headers are copied when they are built, so changing the dicts you passed in has no effect either.

## Removed `unleash_*` properties

The `unleash_*` properties that mirrored settings (`unleash_url`, `unleash_app_name`, `unleash_refresh_interval`, `unleash_custom_headers`, and so on), as well as `strategy_mapping`, `connector_mode` and `unleash_metrics_interval_str_millis`, have been removed. There is no replacement: the settings are the ones you passed in, so keep a reference to the option objects if you need them later.

``` python
mode = PollingOptions(interval=30)
client = UnleashClient(url, app_name, mode=mode)

mode.interval  # instead of client.unleash_refresh_interval
```

`client.connection_id`, `client.unleash_scheduler`, `client.unleash_executor_name` and `client.metric_job` are unchanged.
