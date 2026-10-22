"""Calculate total returns, select a period, and summarize performance."""

from math import isfinite

import pandas as pd

import settings
from step_01_load_prices import load_analysis_prices


def calculate_total_returns(
    ticker, currency, start_date, end_date, cache_dir=None, refresh=False
) -> pd.DataFrame:
    """Calculate returns from Yahoo's adjusted closing market prices."""
    returns = load_analysis_prices(
        ticker, currency, start_date, end_date, cache_dir, refresh
    )
    if len(returns) < 2:
        raise ValueError("At least two price observations are needed.")

    returns["previous_adjusted_close"] = returns["adjusted_close"].shift(1)
    # Adjusted prices already reflect distributions: do not add dividends again.
    returns["total_return"] = (
        returns["adjusted_close"] / returns["previous_adjusted_close"] - 1
    )
    return returns


def select_period(
    returns: pd.DataFrame, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> pd.DataFrame:
    """Use the last available price on or before each requested boundary."""
    start_date = pd.Timestamp(start_date).normalize()
    end_date = pd.Timestamp(end_date).normalize()
    if pd.isna(start_date) or pd.isna(end_date) or start_date >= end_date:
        raise ValueError("Choose valid start and end dates, with start before end.")
    if returns.empty:
        raise ValueError("There are no observations to select.")
    dates = returns["date"]
    if (
        dates.isna().any()
        or dates.duplicated().any()
        or not dates.is_monotonic_increasing
    ):
        raise ValueError("Dates must be present, unique, and oldest to newest.")
    if start_date < dates.iloc[0] or end_date > dates.iloc[-1]:
        raise ValueError(
            "Prices do not cover both boundaries. Check history or trading dates."
        )

    actual_start = dates.loc[dates <= start_date].iloc[-1]
    actual_end = dates.loc[dates <= end_date].iloc[-1]
    period = returns.loc[dates.between(actual_start, actual_end)].copy()
    period = period.reset_index(drop=True)
    if len(period) < 3:
        raise ValueError("The selected period needs at least two observed returns.")

    # An investment bought at the first closing price earns no earlier return.
    period.loc[0, ["previous_adjusted_close", "total_return"]] = float("nan")
    return period


def analyze_performance(
    returns: pd.DataFrame,
    initial_investment: float = settings.INITIAL_INVESTMENT,
    trading_days_per_year: int = 252,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Return the investment's value history and a summary of growth and risk."""
    performance = returns.copy()

    if len(performance) < 3:
        raise ValueError("At least two returns are needed to estimate volatility.")
    dates = performance["date"]
    if (
        dates.isna().any()
        or dates.duplicated().any()
        or not dates.is_monotonic_increasing
    ):
        raise ValueError("Dates must be present, unique, and oldest to newest.")
    if not isfinite(initial_investment) or initial_investment <= 0:
        raise ValueError("The starting investment must be positive and finite.")
    if not isfinite(trading_days_per_year) or trading_days_per_year <= 0:
        raise ValueError("Trading days per year must be positive and finite.")
    if not pd.isna(performance["total_return"].iloc[0]):
        raise ValueError("The first return must be missing at the starting price.")
    daily_returns = performance["total_return"].iloc[1:]
    if daily_returns.isna().any() or not daily_returns.between(
        -1, float("inf"), inclusive="neither"
    ).all():
        raise ValueError("Later returns must be present, finite, and above -100%.")
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    if years <= 0:
        raise ValueError("The measurement period must span at least one day.")

    # Growth starts at the initial investment, with no return on the first row.
    growth_factors = 1 + performance["total_return"]
    growth_factors.iloc[0] = 1
    performance["investment_value"] = initial_investment * growth_factors.cumprod()
    ending_value = performance["investment_value"].iloc[-1]

    annualized_return = (ending_value / initial_investment) ** (1 / years) - 1

    daily_volatility = daily_returns.std(ddof=1)
    annualized_volatility = daily_volatility * (trading_days_per_year ** 0.5)

    performance["running_peak"] = performance["investment_value"].cummax()
    performance["drawdown"] = (
        performance["investment_value"] / performance["running_peak"] - 1
    )
    maximum_drawdown = performance["drawdown"].min()

    summary = {
        "starting_value": initial_investment,
        "ending_value": ending_value,
        "years": years,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "maximum_drawdown": maximum_drawdown,
    }
    return performance, summary


if __name__ == "__main__":
    if not settings.TICKERS:
        raise SystemExit("Add at least one Yahoo ETF symbol in settings.py.")
    ticker = settings.TICKERS[0]
    end_date = pd.Timestamp(settings.END_DATE)
    start_date = end_date - pd.DateOffset(years=settings.LOOKBACK_YEARS)
    if settings.START_DATE is not None:
        start_date = pd.Timestamp(settings.START_DATE)
    returns = calculate_total_returns(
        ticker, settings.CURRENCY, start_date, end_date,
        refresh=settings.REFRESH_YAHOO_DATA,
    )
    returns = select_period(returns, start_date, end_date)
    returns, summary = analyze_performance(returns, settings.INITIAL_INVESTMENT)

    print(f"ETF: {ticker}")
    print(f"Period: {start_date:%Y-%m-%d} to {end_date:%Y-%m-%d}")
    print(f"Starting value: {summary['starting_value']:,.2f} {settings.CURRENCY}")
    print(f"Ending value: {summary['ending_value']:,.2f} {settings.CURRENCY}")
    print(f"Annualized total return estimate: {summary['annualized_return']:.2%}")
    print(f"Annualized volatility estimate: {summary['annualized_volatility']:.2%}")
    print(f"Maximum drawdown: {summary['maximum_drawdown']:.2%}")
    print("\nYahoo adjusted market prices; before client taxes and trading costs.")
