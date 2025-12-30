from UnleashClient.impact_metrics.metric_types import (
    CounterImpl,
    MetricOptions,
)


def test_counter_increments_by_default_value():
    counter = CounterImpl(MetricOptions(name="test_counter", help="testing"))

    counter.inc()

    result = counter.collect()

    assert result.to_dict() == {
        "name": "test_counter",
        "help": "testing",
        "type": "counter",
        "samples": [{"labels": {}, "value": 1}],
    }


def test_counter_increments_with_custom_value_and_labels():
    counter = CounterImpl(MetricOptions(name="labeled_counter", help="with labels"))

    counter.inc(3, {"foo": "bar"})
    counter.inc(2, {"foo": "bar"})

    result = counter.collect()

    assert result.to_dict() == {
        "name": "labeled_counter",
        "help": "with labels",
        "type": "counter",
        "samples": [{"labels": {"foo": "bar"}, "value": 5}],
    }


def test_different_label_combinations_are_stored_separately():
    counter = CounterImpl(MetricOptions(name="multi_label", help="label test"))

    counter.inc(1, {"a": "x"})
    counter.inc(2, {"b": "y"})
    counter.inc(3)

    result = counter.collect()

    result.samples.sort(key=lambda s: s.value)

    assert result.to_dict() == {
        "name": "multi_label",
        "help": "label test",
        "type": "counter",
        "samples": [
            {"labels": {"a": "x"}, "value": 1},
            {"labels": {"b": "y"}, "value": 2},
            {"labels": {}, "value": 3},
        ],
    }


def test_collect_returns_counter_with_zero_value_after_flushing_previous_values():
    counter = CounterImpl(MetricOptions(name="flush_test", help="flush"))

    counter.inc(1)
    first = counter.collect()
    assert first is not None
    assert len(first.samples) == 1

    second = counter.collect()

    assert second.to_dict() == {
        "name": "flush_test",
        "help": "flush",
        "type": "counter",
        "samples": [{"labels": {}, "value": 0}],
    }
