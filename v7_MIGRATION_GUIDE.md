# Migrating to Unleash-Client-Python 7.0.0

This guide highlights the key changes you should be aware of when upgrading to v7.0.0 of the Unleash client.

## Settings are grouped into option objects

`url` and `app_name` are still the first two arguments. Most other settings moved into four option objects: `IdentityOptions`, `HttpOptions`, `FetchOptions` and `MetricsOptions`. All other arguments must now be passed by keyword.

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
    FetchOptions, HttpOptions, IdentityOptions, MetricsOptions, UnleashClient,
)

client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    identity=IdentityOptions(environment="production"),
    http=HttpOptions(headers={"Authorization": "<API token>"}),
    fetching=FetchOptions(interval=30, mode="streaming"),
    metrics=MetricsOptions(disabled=True),
    custom_strategies={"EmailStrategy": EmailStrategy()},
)
```

The same applies to `AsyncUnleashClient`.

### Migrating arguments

| v6 argument            | v7                                          |
| ---------------------- | ------------------------------------------- |
| `url`                  | unchanged                                   |
| `app_name`             | unchanged                                   |
| `environment`          | `IdentityOptions(environment=...)`          |
| `instance_id`          | `IdentityOptions(instance_id=...)`          |
| `sdk_flavor`           | `IdentityOptions(sdk_flavor=...)`           |
| `sdk_flavor_version`   | `IdentityOptions(sdk_flavor_version=...)`   |
| `custom_headers`       | `HttpOptions(headers=...)`                  |
| `custom_options`       | `HttpOptions(options=...)`                  |
| `request_timeout`      | `HttpOptions(timeout=...)`                  |
| `request_retries`      | `HttpOptions(retries=...)`                  |
| `refresh_interval`     | `FetchOptions(interval=...)`                |
| `refresh_jitter`       | `FetchOptions(jitter=...)`                  |
| `project_name`         | `FetchOptions(project_name=...)`            |
| `experimental_mode`    | `FetchOptions(mode="streaming")`, a string instead of `{"type": ...}` |
| `metrics_interval`     | `MetricsOptions(interval=...)`              |
| `metrics_jitter`       | `MetricsOptions(jitter=...)`                |
| `disable_metrics`      | `MetricsOptions(disabled=...)`              |
| `disable_registration` | `MetricsOptions(disable_registration=...)`  |
| `verbose_log_level`    | unchanged, keyword-only                     |
| `custom_strategies`, `cache`, `cache_directory`, `scheduler`, `scheduler_executor`, `multiple_instance_mode`, `event_callback` | unchanged, keyword-only |

The `ExperimentalMode` type has been removed.

## Settings can't be changed after construction

A client's settings can't be changed after it is created. To change a setting, create a new client.

In v6.9, assigning to `unleash_url`, `unleash_custom_headers` and the other request settings on a running client took effect on the next request; that is no longer possible. Headers and options are copied when the option objects are built, so changing the dicts you passed in has no effect either.

## Removed `unleash_*` properties

The `unleash_*` properties that mirrored settings (`unleash_url`, `unleash_app_name`, `unleash_refresh_interval`, `unleash_custom_headers`, and so on), as well as `strategy_mapping`, `connector_mode` and `unleash_metrics_interval_str_millis`, have been removed. There is no replacement: the settings are the ones you passed in, so keep a reference to the option objects if you need them later.

``` python
http = HttpOptions(headers={"Authorization": "<API token>"})
client = UnleashClient(url, app_name, http=http)

http.headers  # instead of client.unleash_custom_headers
```

`client.connection_id`, `client.unleash_scheduler`, `client.unleash_executor_name` and `client.metric_job` are unchanged.
