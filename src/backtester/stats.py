"""Plain-float descriptive statistics.

``statistics.stdev`` computes variance in exact rational arithmetic to
guarantee correct rounding, which costs roughly a quarter of a backtest's
runtime — over a million ``math.gcd`` calls per run on a 20-bar window.
Backtest signals do not need correctly-rounded variance; ordinary float
arithmetic is many times faster and accurate far beyond what a z-score
threshold can distinguish.

This stays an O(window) two-pass recompute rather than an incremental
rolling sum-of-squares: the cost was never the pass, and incremental
variance invites catastrophic cancellation for no gain here.
"""

import math
from collections.abc import Sequence


def mean_and_stdev(values: Sequence[float]) -> tuple[float, float]:
    """Arithmetic mean and sample (n-1) standard deviation.

    Raises ``ValueError`` for fewer than two values, matching
    ``statistics.stdev``.
    """
    count = len(values)
    if count < 2:
        raise ValueError("mean_and_stdev requires at least two values")

    mean = math.fsum(values) / count
    # max(..., 0.0) guards the one way this can fail: for a near-constant
    # series the summed squared deviations can land marginally below zero
    # through cancellation, and sqrt() of that is nan.
    variance = max(math.fsum((value - mean) ** 2 for value in values) / (count - 1), 0.0)
    return mean, math.sqrt(variance)
