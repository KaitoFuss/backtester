from backtester.config import BacktestConfig
from backtester.core.engine import Portfolio, PriceSource
from backtester.portfolio.equal_weight import EqualWeightPortfolio
from backtester.portfolio.inverse_vol import InverseVolPortfolio
from backtester.portfolio.score_proportional import ScoreProportionalPortfolio

PORTFOLIO_NAMES = ("inverse_vol", "score_proportional", "equal_weight")


def build_portfolio(config: BacktestConfig, price_source: PriceSource) -> Portfolio:
    """Construct the portfolio named by ``config.portfolio``, passing each one
    the subset of the flat config it understands."""
    match config.portfolio:
        case "inverse_vol":
            return InverseVolPortfolio(
                price_source=price_source,
                initial_cash=config.initial_cash,
                entry_threshold=config.entry_threshold,
                exit_threshold=config.exit_threshold,
                vol_window=config.vol_window,
                max_gross=config.max_gross,
            )
        case "score_proportional":
            return ScoreProportionalPortfolio(
                price_source=price_source,
                initial_cash=config.initial_cash,
                entry_threshold=config.entry_threshold,
                exit_threshold=config.exit_threshold,
                max_gross=config.max_gross,
                dollar_neutral=config.dollar_neutral,
            )
        case "equal_weight":
            return EqualWeightPortfolio(
                price_source=price_source,
                initial_cash=config.initial_cash,
                max_gross=config.max_gross,
            )
        case unknown:
            raise ValueError(
                f"unknown portfolio {unknown!r}; expected one of {', '.join(PORTFOLIO_NAMES)}"
            )
