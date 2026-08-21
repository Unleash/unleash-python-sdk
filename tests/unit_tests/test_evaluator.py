import json
import logging
from datetime import datetime, timezone

from yggdrasil_engine.engine import UnleashEngine

from tests.utilities.mocks.mock_features import (
    MOCK_FEATURE_RESPONSE,
    MOCK_FEATURE_RESPONSE_PROJECT,
)
from UnleashClient.config import UnleashConfig
from UnleashClient.context import ContextEnricher
from UnleashClient.evaluator import Evaluator
from UnleashClient.events import UnleashEventType

URL = "http://localhost:4242/api"
APP_NAME = "pytest"

FEATURES = json.dumps(MOCK_FEATURE_RESPONSE)
PROJECT_FEATURES = json.dumps(MOCK_FEATURE_RESPONSE_PROJECT)

# testFlag and testVariations carry impressionData; testFlag2 does not.
IMPRESSION_FLAG = "testFlag"
SILENT_FLAG = "testFlag2"
VARIANT_FLAG = "testVariations"


class FailingDispatcher:
    """A dispatcher whose delivery is broken."""

    def emit_event(self, event):
        raise RuntimeError("dispatcher is broken")


def build_evaluator(state=FEATURES, events=None, **kwargs):
    config = UnleashConfig(URL, APP_NAME, **kwargs)
    engine = UnleashEngine()
    if state:
        engine.take_state(state)
    return Evaluator(
        engine=engine,
        enricher=ContextEnricher(config),
        config=config,
        events=events,
    )


def test_is_enabled_resolves_a_known_flag():
    evaluator = build_evaluator()

    assert evaluator.is_enabled(IMPRESSION_FLAG) is True


def test_is_enabled_defaults_to_false_for_an_unknown_flag():
    evaluator = build_evaluator()

    assert evaluator.is_enabled("notAFlag") is False


def test_is_enabled_enriches_the_context_before_asking_the_engine():
    evaluator = build_evaluator()
    before_the_deadline = datetime(2020, 1, 1, tzinfo=timezone.utc)

    # testConstraintFlag is gated on currentTime being before 2022-01-22, and the
    # engine only understands that as a string: passing a datetime works because
    # the enricher isoformatted it on the way through.
    assert (
        evaluator.is_enabled("testConstraintFlag", {"currentTime": before_the_deadline})
        is True
    )


def test_is_enabled_hands_the_fallback_the_enriched_context(mocker):
    evaluator = build_evaluator()
    fallback = mocker.Mock(return_value=True)

    assert evaluator.is_enabled("notAFlag", {"userId": "7"}, fallback) is True

    feature_name, context = fallback.call_args[0]
    assert feature_name == "notAFlag"
    assert context["userId"] == "7"
    assert context["appName"] == APP_NAME
    assert "currentTime" in context


def test_get_variant_returns_the_variant_and_that_it_was_found():
    evaluator = build_evaluator()

    result = evaluator.get_variant(VARIANT_FLAG, {"userId": "2"})

    assert result.is_found is True
    assert result.variant["name"] == "VarA"
    assert result.variant["enabled"] is True


def test_get_variant_reports_an_unknown_flag_as_not_found():
    evaluator = build_evaluator()

    result = evaluator.get_variant("notAFlag")

    assert result.is_found is False
    assert result.variant["name"] == "disabled"


def test_get_variant_drops_the_variants_empty_fields():
    evaluator = build_evaluator()

    result = evaluator.get_variant("notAFlag")

    # The engine reports payload=None on a miss; the public shape omits it.
    assert "payload" not in result.variant


def test_get_variant_keeps_a_payload_it_was_given():
    evaluator = build_evaluator()

    result = evaluator.get_variant(VARIANT_FLAG, {"userId": "2"})

    assert result.variant["payload"] == {"type": "string", "value": "Test1"}


def test_an_impression_event_carries_the_flag_result(dispatcher, recorder):
    evaluator = build_evaluator(events=dispatcher)

    evaluator.is_enabled(IMPRESSION_FLAG)

    events = recorder.wait_for(UnleashEventType.FEATURE_FLAG)
    assert events is not None
    assert events[0].feature_name == IMPRESSION_FLAG
    assert events[0].enabled is True


def test_an_impression_event_carries_the_enriched_context(dispatcher, recorder):
    evaluator = build_evaluator(events=dispatcher, environment="unit")

    evaluator.is_enabled(IMPRESSION_FLAG, {"userId": "7"})

    events = recorder.wait_for(UnleashEventType.FEATURE_FLAG)
    assert events is not None
    assert events[0].context["userId"] == "7"
    assert events[0].context["appName"] == APP_NAME
    assert events[0].context["environment"] == "unit"


def test_a_variant_impression_event_carries_the_variant_name(dispatcher, recorder):
    evaluator = build_evaluator(events=dispatcher)

    evaluator.get_variant(VARIANT_FLAG, {"userId": "2"})

    events = recorder.wait_for(UnleashEventType.VARIANT)
    assert events is not None
    assert events[0].feature_name == VARIANT_FLAG
    assert events[0].variant == "VarA"
    assert events[0].enabled is True


def test_no_impression_event_for_a_flag_that_did_not_ask_for_one(dispatcher, recorder):
    evaluator = build_evaluator(events=dispatcher)

    evaluator.is_enabled(SILENT_FLAG)
    evaluator.is_enabled(IMPRESSION_FLAG)

    # Waiting on the second call's event is what proves the first produced none.
    assert recorder.wait_for(UnleashEventType.FEATURE_FLAG) is not None
    assert len(recorder.of_type(UnleashEventType.FEATURE_FLAG)) == 1


def test_without_a_dispatcher_evaluation_still_answers():
    evaluator = build_evaluator(events=None)

    assert evaluator.is_enabled(IMPRESSION_FLAG) is True
    assert (
        evaluator.get_variant(VARIANT_FLAG, {"userId": "2"}).variant["name"] == "VarA"
    )


def test_a_failing_dispatcher_does_not_break_evaluation(caplog):
    evaluator = build_evaluator(events=FailingDispatcher())

    with caplog.at_level(logging.WARNING):
        assert evaluator.is_enabled(IMPRESSION_FLAG) is True
        assert evaluator.get_variant(VARIANT_FLAG, {"userId": "2"}).is_found is True

    assert "Error emitting impression event" in caplog.text


def test_the_verbose_log_level_is_read_on_every_call(caplog):
    # UnleashClient.unleash_verbose_log_level has a setter, so a client can
    # change it after the evaluator was constructed.
    config = UnleashConfig(URL, APP_NAME)
    engine = UnleashEngine()
    engine.take_state(FEATURES)
    evaluator = Evaluator(
        engine=engine,
        enricher=ContextEnricher(config),
        config=config,
        events=FailingDispatcher(),
    )

    config.verbose_log_level = logging.ERROR
    with caplog.at_level(logging.DEBUG):
        evaluator.is_enabled(IMPRESSION_FLAG)

    levels = {
        record.levelno
        for record in caplog.records
        if "Error emitting impression event" in record.message
    }
    assert levels == {logging.ERROR}


def test_feature_definitions_reports_every_known_toggle():
    evaluator = build_evaluator()

    definitions = evaluator.feature_definitions()

    assert set(definitions) == {
        "testFlag",
        "testFlag2",
        "testContextFlag",
        "testConstraintFlag",
        "testVariations",
    }


def test_feature_definitions_reports_the_type_and_project():
    evaluator = build_evaluator(state=PROJECT_FEATURES)

    definitions = evaluator.feature_definitions()

    assert definitions["ivan-project"] == {"type": "release", "project": "default"}


def test_feature_definitions_is_empty_before_any_state_arrives():
    evaluator = build_evaluator(state=None)

    assert evaluator.feature_definitions() == {}
