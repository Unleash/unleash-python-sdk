import pytest

from UnleashClient import INSTANCES
from UnleashClient._instance_registry import _get_instance, _InstanceRegistry
from UnleashClient.utils import InstanceAllowType

IDENTIFIER = "apiKey:None appName:pytest instanceId:123"
OTHER_IDENTIFIER = "apiKey:None appName:pytest instanceId:456"


def duplicate_warnings(caplog) -> list:
    return [r.msg for r in caplog.records if "You already have" in str(r.msg)]


@pytest.mark.parametrize(
    "mode",
    [InstanceAllowType.BLOCK, InstanceAllowType.WARN, InstanceAllowType.SILENTLY_ALLOW],
)
def test_a_first_registration_is_silent_under_every_mode(caplog, mode):
    registry = _InstanceRegistry()

    registry.register(IDENTIFIER, mode)

    assert duplicate_warnings(caplog) == []
    assert registry.count(IDENTIFIER) == 1


def test_a_repeat_registration_warns_with_the_count_before_it(caplog):
    registry = _InstanceRegistry()
    registry.register(IDENTIFIER, InstanceAllowType.WARN)

    registry.register(IDENTIFIER, InstanceAllowType.WARN)

    assert duplicate_warnings(caplog) == [
        f"You already have 1 instance(s) configured for this config: {IDENTIFIER}, "
        "please double check the code where this client is being instantiated."
    ]


def test_the_warning_reports_a_growing_count(caplog):
    registry = _InstanceRegistry()
    for _ in range(3):
        registry.register(IDENTIFIER, InstanceAllowType.WARN)

    assert len(duplicate_warnings(caplog)) == 2
    assert "You already have 1 instance(s)" in duplicate_warnings(caplog)[0]
    assert "You already have 2 instance(s)" in duplicate_warnings(caplog)[1]
    assert registry.count(IDENTIFIER) == 3


def test_the_warning_is_logged_as_an_error(caplog):
    registry = _InstanceRegistry()
    registry.register(IDENTIFIER, InstanceAllowType.WARN)

    registry.register(IDENTIFIER, InstanceAllowType.WARN)

    duplicates = [r for r in caplog.records if "You already have" in str(r.msg)]
    assert [r.levelname for r in duplicates] == ["ERROR"]
    assert [r.name for r in duplicates] == ["UnleashClient"]


def test_block_raises_on_a_repeat_registration():
    registry = _InstanceRegistry()
    registry.register(IDENTIFIER, InstanceAllowType.BLOCK)

    with pytest.raises(Exception, match="You already have 1 instance"):
        registry.register(IDENTIFIER, InstanceAllowType.BLOCK)


def test_a_blocked_registration_is_not_counted():
    registry = _InstanceRegistry()
    registry.register(IDENTIFIER, InstanceAllowType.BLOCK)

    with pytest.raises(Exception):
        registry.register(IDENTIFIER, InstanceAllowType.BLOCK)

    assert registry.count(IDENTIFIER) == 1


def test_silently_allow_neither_logs_nor_raises(caplog):
    registry = _InstanceRegistry()
    registry.register(IDENTIFIER, InstanceAllowType.SILENTLY_ALLOW)

    registry.register(IDENTIFIER, InstanceAllowType.SILENTLY_ALLOW)

    assert duplicate_warnings(caplog) == []
    assert registry.count(IDENTIFIER) == 2


def test_different_identifiers_do_not_collide(caplog):
    registry = _InstanceRegistry()

    registry.register(IDENTIFIER, InstanceAllowType.WARN)
    registry.register(OTHER_IDENTIFIER, InstanceAllowType.WARN)

    assert duplicate_warnings(caplog) == []
    assert registry.count(IDENTIFIER) == 1
    assert registry.count(OTHER_IDENTIFIER) == 1


def test_the_mode_of_the_registration_that_repeats_is_the_one_applied(caplog):
    registry = _InstanceRegistry()
    registry.register(IDENTIFIER, InstanceAllowType.SILENTLY_ALLOW)

    registry.register(IDENTIFIER, InstanceAllowType.WARN)

    assert len(duplicate_warnings(caplog)) == 1


def test_an_unknown_identifier_counts_zero_and_is_not_contained():
    registry = _InstanceRegistry()

    assert registry.count(IDENTIFIER) == 0
    assert IDENTIFIER not in registry


def test_increment_counts_without_applying_any_policy(caplog):
    registry = _InstanceRegistry()

    registry.increment(IDENTIFIER)
    registry.increment(IDENTIFIER)

    assert registry.count(IDENTIFIER) == 2
    assert IDENTIFIER in registry
    assert duplicate_warnings(caplog) == []


def test_reset_clears_every_identifier():
    registry = _InstanceRegistry()
    registry.register(IDENTIFIER, InstanceAllowType.WARN)
    registry.register(OTHER_IDENTIFIER, InstanceAllowType.WARN)

    registry._reset()

    assert registry.count(IDENTIFIER) == 0
    assert OTHER_IDENTIFIER not in registry


def test_get_instance_returns_the_same_registry_every_time():
    assert _get_instance() is _get_instance()


def test_the_exported_instances_object_is_that_registry():
    assert INSTANCES is _get_instance()
    assert isinstance(INSTANCES, _InstanceRegistry)
