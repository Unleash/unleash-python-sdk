import uuid
from datetime import datetime, timezone

from UnleashClient.config import UnleashConfig
from UnleashClient.context import ContextEnricher

URL = "http://localhost:4242/api"
APP_NAME = "pytest"


def build_enricher(**kwargs) -> ContextEnricher:
    return ContextEnricher(UnleashConfig(URL, APP_NAME, **kwargs))


def test_static_context_is_merged_in():
    enricher = build_enricher(environment="unit")

    context = enricher.build({})

    assert context["appName"] == APP_NAME
    assert context["environment"] == "unit"


def test_caller_overrides_the_static_context():
    enricher = build_enricher(environment="unit")

    context = enricher.build({"environment": "qa", "appName": "other"})

    assert context["environment"] == "qa"
    assert context["appName"] == "other"


def test_no_context_at_all():
    enricher = build_enricher()

    context = enricher.build(None)

    assert context["appName"] == APP_NAME
    assert "currentTime" in context
    assert context["properties"] == {}


def test_base_context_properties_are_retained_in_root():
    enricher = build_enricher()

    context = enricher.build({"userId": "1234"})

    assert "userId" in context


def test_context_moves_properties_fields_to_properties():
    enricher = build_enricher()

    context = enricher.build({"myContext": "1234"})

    assert "myContext" in context["properties"]


def test_existing_properties_are_retained_when_custom_context_properties_are_in_the_root():
    enricher = build_enricher()

    context = enricher.build(
        {"myContext": "1234", "properties": {"yourContext": "1234"}}
    )

    assert "myContext" in context["properties"]
    assert "yourContext" in context["properties"]


def test_properties_win_over_the_root_on_a_name_clash():
    enricher = build_enricher()

    context = enricher.build(
        {"myContext": "root", "properties": {"myContext": "nested"}}
    )

    assert context["properties"]["myContext"] == "nested"


def test_current_time_is_added_when_missing():
    enricher = build_enricher()

    context = enricher.build({})

    assert datetime.fromisoformat(context["currentTime"]).tzinfo is timezone.utc


def test_a_supplied_current_time_is_kept_and_isoformatted():
    enricher = build_enricher()
    current_time = datetime.fromisoformat("1834-02-20").replace(tzinfo=timezone.utc)

    context = enricher.build({"currentTime": current_time})

    assert context["currentTime"] == current_time.isoformat()


def test_values_are_stringified():
    enricher = build_enricher()
    identifier = uuid.uuid4()

    context = enricher.build({"userId": 99999, "score": 1.5, "traceId": identifier})

    assert context["userId"] == "99999"
    assert context["properties"]["score"] == "1.5"
    assert context["properties"]["traceId"] == str(identifier)


def test_the_supplied_context_is_not_mutated():
    enricher = build_enricher()
    original = {"myContext": "1234"}

    enricher.build(original)

    assert original == {"myContext": "1234"}


def test_static_context_is_read_on_every_call():
    # UnleashClient.unleash_static_context has a setter, so a client can swap
    # the dict out after the enricher was constructed.
    config = UnleashConfig(URL, APP_NAME, environment="unit")
    enricher = ContextEnricher(config)

    config.static_context = {"appName": "replaced", "environment": "qa"}
    context = enricher.build({})

    assert context["appName"] == "replaced"
    assert context["environment"] == "qa"
