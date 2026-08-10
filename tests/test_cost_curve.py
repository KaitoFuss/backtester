from backtester.cost_curve import CostPoint, breakeven_cost


def _point(cost: float, sharpe: float) -> CostPoint:
    return CostPoint(
        cost_bps=cost,
        commission_bps=0.5,
        total_return=0.0,
        sharpe=sharpe,
        max_drawdown=0.0,
        annual_turnover=0.0,
    )


def test_interpolates_the_zero_crossing() -> None:
    points = [_point(0.0, 1.0), _point(2.0, -1.0)]

    # Sharpe falls 1.0 -> -1.0 across 0 -> 2 bp, so it crosses zero at 1.0 bp.
    assert breakeven_cost(points) == 1.0


def test_uses_the_first_crossing_only() -> None:
    points = [_point(0.0, 1.0), _point(1.0, -1.0), _point(2.0, 1.0), _point(3.0, -1.0)]

    assert breakeven_cost(points) == 0.5


def test_returns_none_when_sharpe_never_crosses() -> None:
    points = [_point(0.0, 1.0), _point(1.0, 0.8), _point(2.0, 0.5)]

    assert breakeven_cost(points) is None


def test_returns_none_when_already_negative_at_zero_cost() -> None:
    """The signal loses money before any cost, so there is no breakeven to report."""
    points = [_point(0.0, -0.1), _point(1.0, -0.5)]

    assert breakeven_cost(points) is None


def test_exact_zero_at_a_ladder_point_is_that_point() -> None:
    points = [_point(0.0, 1.0), _point(1.0, 0.0), _point(2.0, -1.0)]

    assert breakeven_cost(points) == 1.0


def test_a_descending_ladder_gives_the_same_answer_as_an_ascending_one() -> None:
    """``--ladder 5 1 0`` hands the rungs over high-to-low. Pairing them in that
    order interpolates across a negative span and reports nonsense, so the
    points are sorted by cost before pairing."""
    ascending = [_point(0.0, 1.0), _point(2.0, -1.0), _point(5.0, -3.0)]
    descending = list(reversed(ascending))

    assert breakeven_cost(descending) == breakeven_cost(ascending) == 1.0
