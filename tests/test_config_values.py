"""Compatibility cases for configuration coercion shared by plugin consumers."""

from copy import deepcopy

import pytest

from quant_strategy_plugins import strategy_plugin_runner, volatility_delever_price_rebound


@pytest.fixture(params=[strategy_plugin_runner, volatility_delever_price_rebound], ids=["runner", "rebound"])
def consumer(request):
    return request.param


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (None, False, False),
        (None, True, True),
        (False, True, False),
        (True, False, True),
        (" TRUE ", False, True),
        (" yes ", False, True),
        ("Y", False, True),
        ("on", False, True),
        ("1", False, True),
        (1, False, True),
        (0, True, False),
        (2, True, False),
        (-1, True, False),
        ("false", True, False),
        ("off", True, False),
        ("", True, False),
        ("   ", True, False),
        ("unrecognized", True, False),
    ],
)
def test_boolean_values_keep_existing_defaults_and_accepted_spellings(consumer, value, default, expected):
    assert consumer._as_bool(value, default=default) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ()),
        ("", ()),
        (" , , ", ()),
        (" HYG, LQD ,, HYG ", ("HYG", "LQD", "HYG")),
        ([" HYG ", "", "   ", 2, None], ("HYG", "2", "None")),
        (("a", "a", "B"), ("a", "a", "B")),
        ({" first ": 10, "second": 20}, ("first", "second")),
    ],
)
def test_string_tuples_preserve_order_and_do_not_mutate_inputs(consumer, value, expected):
    original = deepcopy(value)
    assert consumer._as_str_tuple(value) == expected
    assert value == original


def test_string_tuple_accepts_a_single_pass_iterable(consumer):
    values = (value for value in [" a ", "", "b", "a"])
    assert consumer._as_str_tuple(values) == ("a", "b", "a")
    assert list(values) == []


@pytest.mark.parametrize("value", [1, True, 1.5])
def test_noniterable_string_tuple_input_preserves_type_error(consumer, value):
    with pytest.raises(TypeError):
        consumer._as_str_tuple(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ()),
        ([], ()),
        (" , ", ()),
        (" hyg / lqd , HYG:LQD, lqd:hyg ", (("HYG", "LQD"), ("LQD", "HYG"))),
        (["a/b", "c:d", " A : B "], (("A", "B"), ("C", "D"))),
    ],
)
def test_credit_pairs_normalize_and_deduplicate_in_first_seen_order(consumer, value, expected):
    original = deepcopy(value)
    assert consumer._as_credit_pairs(value) == expected
    assert value == original


@pytest.mark.parametrize("item", ["HYG", "HYG:", ":LQD", "HYG:LQD:SPY", "HYG/LQD/SPY", "7"])
def test_malformed_credit_pairs_preserve_error_class_and_message(consumer, item):
    with pytest.raises(ValueError) as failure:
        consumer._as_credit_pairs(["A:B", item, "C:D"])
    assert str(failure.value) == f"credit pair must use NUMERATOR:DENOMINATOR syntax: {item!r}"


def test_credit_pair_coercion_still_finishes_before_syntax_validation(consumer):
    class InvalidText:
        def __str__(self):
            raise RuntimeError("synthetic string conversion failed")

    with pytest.raises(RuntimeError, match="^synthetic string conversion failed$"):
        consumer._as_credit_pairs(["missing-delimiter", InvalidText()])


def test_credit_pairs_keep_the_consumer_string_tuple_hook(consumer, monkeypatch):
    seen = []
    supplied = object()

    def string_tuple(value):
        seen.append(value)
        return ("b/a", " A : B ", "B:A")

    monkeypatch.setattr(consumer, "_as_str_tuple", string_tuple)
    assert consumer._as_credit_pairs(supplied) == (("B", "A"), ("A", "B"))
    assert seen == [supplied]
