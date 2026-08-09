import pytest

from backtester.config import BacktestConfig
from backtester.portfolio.equal_weight import EqualWeightPortfolio
from backtester.portfolio.factory import build_portfolio
from backtester.portfolio.inverse_vol import InverseVolPortfolio
from backtester.portfolio.score_proportional import ScoreProportionalPortfolio


class FakePriceSource:
    def get_price(self, ticker: str) -> float | None:
        return None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("inverse_vol", InverseVolPortfolio),
        ("score_proportional", ScoreProportionalPortfolio),
        ("equal_weight", EqualWeightPortfolio),
    ],
)
def test_each_name_builds_its_portfolio(name: str, expected: type) -> None:
    config = BacktestConfig(data="data/raw", portfolio=name)

    assert isinstance(build_portfolio(config, FakePriceSource()), expected)


def test_unknown_name_raises_with_the_valid_options() -> None:
    config = BacktestConfig(data="data/raw", portfolio="mean_variance")

    with pytest.raises(ValueError, match="score_proportional"):
        build_portfolio(config, FakePriceSource())
