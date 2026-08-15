import random
import statistics

import pytest

from backtester.stats import mean_and_stdev


def test_matches_statistics_on_a_known_sample() -> None:
    values = [1.0, 2.0, 3.0, 4.0]

    mean, stdev = mean_and_stdev(values)

    assert mean == pytest.approx(2.5)
    assert stdev == pytest.approx(statistics.stdev(values))


def test_matches_statistics_over_a_long_random_series() -> None:
    rng = random.Random(0)
    for _ in range(200):
        values = [rng.gauss(0.0, 0.01) for _ in range(20)]

        mean, stdev = mean_and_stdev(values)

        assert mean == pytest.approx(statistics.fmean(values), rel=1e-12)
        assert stdev == pytest.approx(statistics.stdev(values), rel=1e-9)


def test_constant_series_has_zero_dispersion() -> None:
    mean, stdev = mean_and_stdev([3.0] * 10)

    assert mean == pytest.approx(3.0)
    assert stdev == 0.0


def test_near_constant_series_never_returns_nan() -> None:
    """Floating-point cancellation can drive the variance slightly negative;
    it must clamp to zero rather than reaching sqrt() and producing nan."""
    values = [1e8, 1e8, 1e8, 1e8 + 1e-9]

    _, stdev = mean_and_stdev(values)

    assert stdev >= 0.0


def test_single_value_raises() -> None:
    with pytest.raises(ValueError, match="at least two values"):
        mean_and_stdev([1.0])
