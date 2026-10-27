# Migrating to Unleash-Client-Python 7.0.0

This guide highlights the key changes you should be aware of when upgrading to v7.0.0 of the Unleash client.

## Settings are grouped into option objects

`url` and `app_name` are still the first two arguments. The API token is now its own `api_key` argument. All other arguments must now be passed by keyword. Most other settings moved into option objects: `IdentityOptions`, `HttpOptions`, `MetricsOptions`, and either `PollingOptions` or `StreamingOptions`. The option objects take keyword arguments only.

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
    IdentityOptions, MetricsOptions, StreamingOptions, UnleashClient,
)

client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    api_key="<API token>",
    identity=IdentityOptions(environment="production"),
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
| `environment`          | `IdentityOptions(environment=...)`          |
| `instance_id`          | `IdentityOptions(instance_id=...)`          |
| `sdk_flavor`           | `IdentityOptions(sdk_flavor=...)`           |
| `sdk_flavor_version`   | `IdentityOptions(sdk_flavor_version=...)`   |
| `custom_headers`       | `HttpOptions(headers=...)`, without `Authorization` |
| `custom_options`       | `HttpOptions(options=...)`                  |
| `request_timeout`      | `HttpOptions(timeout=...)`                  |
| `request_retries`      | `HttpOptions(retries=...)`                  |
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

An `Authorization` header in `HttpOptions.headers` raises a `ValueError`, in any letter case. It is not silently ignored, because a client without a key still starts: its requests fail with 401 and it keeps serving the flags in its cache, so the mistake could go unnoticed. All other custom headers work as before.

## Settings can't be changed after construction

A client's settings can't be changed after it is created. To change a setting, create a new client.

In v6.9, assigning to `unleash_url`, `unleash_custom_headers` and the other request settings on a running client took effect on the next request; that is no longer possible. Headers and options are copied when the option objects are built, so changing the dicts you passed in has no effect either.

## Removed `unleash_*` properties

The `unleash_*` properties that mirrored settings (`unleash_url`, `unleash_app_name`, `unleash_refresh_interval`, `unleash_custom_headers`, and so on), as well as `strategy_mapping`, `connector_mode` and `unleash_metrics_interval_str_millis`, have been removed. There is no replacement: the settings are the ones you passed in, so keep a reference to the option objects if you need them later.

``` python
http = HttpOptions(headers={"X-Custom": "<value>"})
client = UnleashClient(url, app_name, http=http)

http.headers  # instead of client.unleash_custom_headers
```

`client.connection_id`, `client.unleash_scheduler`, `client.unleash_executor_name` and `client.metric_job` are unchanged.
