import logging

from backtester.runner import verbosity_to_level


def test_no_flag_is_quiet() -> None:
    assert verbosity_to_level(0) == logging.WARNING


def test_single_v_is_the_trade_blotter() -> None:
    assert verbosity_to_level(1) == logging.INFO


def test_double_v_is_debug() -> None:
    assert verbosity_to_level(2) == logging.DEBUG


def test_more_vs_stay_at_debug() -> None:
    assert verbosity_to_level(7) == logging.DEBUG
