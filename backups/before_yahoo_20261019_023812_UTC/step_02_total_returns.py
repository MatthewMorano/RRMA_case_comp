"""Calculate daily total returns and summarize one ETF's performance.

Run: python step_02_total_returns.py
Read LESSON_02.md for assumptions and the documented NAV-source date choice.
"""

from math import isfinite
from pathlib import Path

import pandas as pd

from step_01_load_nav import load_nav


PROJECT_DIR = Path(__file__).resolve().parent
NAV_FILE = PROJECT_DIR / "data" / "Historical_NAV_Extract_en_CA_ZLB.csv"
EXPECTED_CURRENCY = "CAD"
INITIAL_INVESTMENT = 10_000.0
LOOKBACK_YEARS = 10
# None uses the latest NAV in the file. Set e.g. "2026-09-30" to match a report.
ANALYSIS_END_DATE = "2026-09-30"

# "2026-09-30"


def calculate_total_returns(file_path: Path, currency: str) -> pd.DataFrame:
    """Add cash distributions, previous NAV, and returns to lesson 1's table.

    Assumes per-unit NAV is not already adjusted for cash distributions and
    that no unhandled unit split changes the number of units. Uses the cash
    amounts and dates in the NAV export, not the tax-distribution total.
    """
    nav = load_nav(file_path, currency)
    if len(nav) < 2:
        raise ValueError("At least two NAV observations are needed for a return.")

    # 1. Read the cash column we did not use in lesson 1.
    cash = pd.read_csv(
        file_path, usecols=["Date", "Cash Distributions"], na_values=["-"]
    )
    cash.columns = ["date", "cash_distribution"]
    cash["date"] = pd.to_datetime(cash["date"], format="%Y-%m-%d", errors="raise")
    cash["cash_distribution"] = pd.to_numeric(
        cash["cash_distribution"], errors="raise"
    )

    # For this BMO export, a dash/blank in CASH means no cash event that day.
    # We never fill a missing NAV with zero or with the previous day's NAV.
    cash["cash_distribution"] = cash["cash_distribution"].fillna(0.0)
    if not cash["cash_distribution"].between(0, float("inf"), inclusive="left").all():
        raise ValueError("Cash distributions must be finite and nonnegative.")

    # 2. Match by date, so the order of the CSV rows cannot misalign the cash.
    returns = nav.merge(cash, on="date", how="left", validate="one_to_one")
    if returns["cash_distribution"].isna().any():
        raise ValueError("A NAV observation has no matching cash-source row.")

    # 3. shift(1) moves the previous observed NAV onto the current row.
    # Friday is the previous observation for Monday if no other NAV intervenes.
    returns["previous_nav"] = returns["nav"].shift(1)

    # 4. Compare NAV-only return with the return including cash entitlement.
    returns["nav_return"] = returns["nav"] / returns["previous_nav"] - 1
    returns["total_return"] = (
        (returns["nav"] + returns["cash_distribution"])
        / returns["previous_nav"]
        - 1
    )
    # The first return stays missing: there is no earlier NAV to compare with.
    return returns


def select_period(
    returns: pd.DataFrame, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> pd.DataFrame:
    """Select a period, using the latest NAV on or before each boundary.

    Requires history covering both requested dates. Rebase the first row so
    an investment starting at its closing NAV excludes any preceding return.
    """
    start_date = pd.Timestamp(start_date).normalize()
    end_date = pd.Timestamp(end_date).normalize()
    if pd.isna(start_date) or pd.isna(end_date) or start_date >= end_date:
        raise ValueError("Choose valid start and end dates, with start before end.")
    if returns.empty:
        raise ValueError("There are no observations to select.")
    dates = returns["date"]
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("Dates must be present, unique, and oldest to newest.")
    if start_date < dates.iloc[0] or end_date > dates.iloc[-1]:
        raise ValueError("The file does not cover the full requested period.")

    actual_start = dates.loc[dates <= start_date].iloc[-1]
    actual_end = dates.loc[dates <= end_date].iloc[-1]
    period = returns.loc[dates.between(actual_start, actual_end)].copy()
    period = period.reset_index(drop=True)
    if len(period) < 3:
        raise ValueError("The selected period needs at least two observed returns.")

    # The initial purchase is at this row's closing NAV. Its earlier return
    # and cash entitlement are not earned by the new investment.
    period.loc[0, ["previous_nav", "nav_return", "total_return"]] = float("nan")
    return period


def analyze_performance(
    returns: pd.DataFrame,
    initial_investment: float = INITIAL_INVESTMENT,
    trading_days_per_year: int = 252,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Return an enriched table and a dictionary of performance measures.

    Expects a chronological table from calculate_total_returns or select_period,
    with only the first return missing. Rates in the summary remain decimals.
    Annualized volatility uses the conventional square-root-of-time estimate.
    """
    # Work on a copy so this function does not change the caller's input table.
    performance = returns.copy()

    # Check the assumptions needed by these calculations.
    if len(performance) < 3:
        raise ValueError("At least two returns are needed to estimate volatility.")
    dates = performance["date"]
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("Dates must be present, unique, and oldest to newest.")
    if not isfinite(initial_investment) or initial_investment <= 0:
        raise ValueError("The starting investment must be positive and finite.")
    if not isfinite(trading_days_per_year) or trading_days_per_year <= 0:
        raise ValueError("Trading days per year must be positive and finite.")
    if not pd.isna(performance["total_return"].iloc[0]):
        raise ValueError("The first return must be missing at the starting NAV.")
    daily_returns = performance["total_return"].iloc[1:]
    if daily_returns.isna().any() or not daily_returns.between(
        -1, float("inf"), inclusive="neither"
    ).all():
        raise ValueError("Later returns must be present, finite, and above -100%.")
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    if years <= 0:
        raise ValueError("The measurement period must span at least one day.")

    # 1. Compound the returns to build the investment's value over time.
    growth_factors = 1 + performance["total_return"]
    growth_factors.iloc[0] = 1
    performance["investment_value"] = initial_investment * growth_factors.cumprod()
    ending_value = performance["investment_value"].iloc[-1]

    # 2. Convert the full period's growth into an equivalent yearly return.
    annualized_return = (ending_value / initial_investment) ** (1 / years) - 1

    # 3. Estimate annualized volatility from the daily sample standard deviation.
    daily_volatility = daily_returns.std(ddof=1)
    annualized_volatility = daily_volatility * (trading_days_per_year ** 0.5)

    # 4. Track declines from the highest investment value reached so far.
    performance["running_peak"] = performance["investment_value"].cummax()
    performance["drawdown"] = (
        performance["investment_value"] / performance["running_peak"] - 1
    )
    maximum_drawdown = performance["drawdown"].min()

    # A dictionary gives each summary number a name we can reuse later.
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
    returns = calculate_total_returns(NAV_FILE, EXPECTED_CURRENCY)
    end_date = (
        returns["date"].iloc[-1]
        if ANALYSIS_END_DATE is None
        else pd.Timestamp(ANALYSIS_END_DATE)
    )
    start_date = end_date - pd.DateOffset(years=LOOKBACK_YEARS)
    returns = select_period(returns, start_date, end_date)
    returns, summary = analyze_performance(returns, INITIAL_INVESTMENT)

    print(f"Requested period: {start_date:%Y-%m-%d} to {end_date:%Y-%m-%d}")
    print(f"Period: {returns['date'].iloc[0]:%Y-%m-%d} to {returns['date'].iloc[-1]:%Y-%m-%d}")
    print(f"Starting value: {summary['starting_value']:,.2f} {EXPECTED_CURRENCY}")
    print(f"Ending value: {summary['ending_value']:,.2f} {EXPECTED_CURRENCY}")
    print(f"Annualized total return: {summary['annualized_return']:.2%}")
    print(f"Annualized volatility (estimate): {summary['annualized_volatility']:.2%}")
    print(f"Maximum drawdown: {summary['maximum_drawdown']:.2%}")
    print("\nCash distributions use the NAV export's dates and amounts.")
    print("See LESSON_02.md. Assumes reinvestment; excludes investor taxes and trading costs.")
