"""Analyze the ETFs in settings.py and save their performance and returns."""

import json
from math import isfinite
from pathlib import Path

import pandas as pd

import settings

from step_02_total_returns import (
    analyze_performance,
    calculate_total_returns,
    select_period,
)


PROJECT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_DIR / "results"

COMPARISON_COLUMNS = [
    "ticker",
    "fund_name",
    "currency",
    "yahoo_ticker",
    "status",
    "message",
    "validation_note",
    "requested_start",
    "requested_end",
    "available_start",
    "available_end",
    "actual_start",
    "actual_end",
    "return_observations",
    "volatility_observations",
    "excluded_shared_intervals",
    "starting_value",
    "ending_value",
    "years",
    "annualized_return",
    "annualized_volatility",
    "maximum_drawdown",
]


def analyze_batch(
    tickers=None, data_root: Path = PROJECT_DIR
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Compare the ticker list and return summaries, matched returns and notes."""
    symbols = settings.TICKERS if tickers is None else tickers
    if not isinstance(symbols, (list, tuple)) or not symbols:
        raise ValueError("Add at least one Yahoo ETF symbol in settings.py.")
    if any(not isinstance(symbol, str) or not symbol.strip() for symbol in symbols):
        raise ValueError("Each ticker must be a nonempty string such as ZLB.TO.")
    symbols = [symbol.strip().upper() for symbol in symbols]
    labels = [symbol.removesuffix(".TO") for symbol in symbols]
    if len(set(labels)) != len(labels):
        raise ValueError("Duplicate ETF symbols or display labels in the ticker list.")

    end_date = pd.Timestamp(settings.END_DATE)
    if (
        pd.isna(end_date)
        or end_date.tzinfo is not None
        or end_date != end_date.normalize()
    ):
        raise ValueError("END_DATE must be a calendar date such as 2026-09-30.")
    if type(settings.LOOKBACK_YEARS) is not int or settings.LOOKBACK_YEARS <= 0:
        raise ValueError("LOOKBACK_YEARS must be a positive whole number.")
    if not isfinite(settings.INITIAL_INVESTMENT) or settings.INITIAL_INVESTMENT <= 0:
        raise ValueError("INITIAL_INVESTMENT must be positive and finite.")
    if not isinstance(settings.CURRENCY, str) or not settings.CURRENCY.strip():
        raise ValueError("Choose a CURRENCY such as CAD.")
    if type(settings.REFRESH_YAHOO_DATA) is not bool:
        raise ValueError("REFRESH_YAHOO_DATA must be True or False.")

    start_date = end_date - pd.DateOffset(years=settings.LOOKBACK_YEARS)
    if settings.START_DATE is not None:
        start_date = pd.Timestamp(settings.START_DATE)
        if (pd.isna(start_date) or start_date.tzinfo is not None
                or start_date != start_date.normalize() or start_date >= end_date):
            raise ValueError("START_DATE must be a calendar date before END_DATE.")
    currency = settings.CURRENCY.strip().upper()
    data_root = Path(data_root)
    reference_dates = None
    reference_ticker = None
    rows = []
    return_series = {}
    interval_starts = {}
    data_sources = {}

    # The first successful ETF supplies the reference observation calendar.
    for symbol, ticker in zip(symbols, labels):
        row = {
            "ticker": ticker,
            "fund_name": symbol,
            "currency": currency,
            "yahoo_ticker": symbol,
            "validation_note": (
                "Yahoo adjusted market prices; not yet independently validated."
            ),
            "requested_start": start_date.strftime("%Y-%m-%d"),
            "requested_end": end_date.strftime("%Y-%m-%d"),
        }
        try:
            full_history = calculate_total_returns(
                symbol, currency, start_date, end_date,
                cache_dir=data_root / "data" / "yahoo",
                refresh=settings.REFRESH_YAHOO_DATA,
            )
            data_sources[ticker] = full_history.attrs["source"]
            row["fund_name"] = data_sources[ticker].get("fund_name", symbol)
            has_proxy = data_sources[ticker].get("history_type") == "proxy_extended"
            if has_proxy:
                row["validation_note"] = (
                    "Includes GLD converted to CAD before ZGLD's observed launch; "
                    "synthetic history, not actual pre-launch ZGLD returns."
                )
            row["available_start"] = (
                full_history["date"].iloc[0].strftime("%Y-%m-%d")
            )
            row["available_end"] = (
                full_history["date"].iloc[-1].strftime("%Y-%m-%d")
            )

            if (
                full_history["date"].iloc[0] > start_date
                or full_history["date"].iloc[-1] < end_date
            ):
                row.update(
                    status="insufficient_history",
                    message=(
                        "Missing boundary prices: check fund history or trading dates."
                    ),
                )
            else:
                period = select_period(full_history, start_date, end_date)
                dates = period["date"].reset_index(drop=True)
                row["actual_start"] = dates.iloc[0].strftime("%Y-%m-%d")
                row["actual_end"] = dates.iloc[-1].strftime("%Y-%m-%d")

                if reference_dates is not None and (
                    dates.iloc[0] != reference_dates.iloc[0]
                    or dates.iloc[-1] != reference_dates.iloc[-1]
                ):
                    row.update(
                        status="calendar_mismatch",
                        message=(
                            f"Actual start or end differs from {reference_ticker}; "
                            "align the period boundaries."
                        ),
                    )
                else:
                    performance, summary = analyze_performance(
                        period, initial_investment=settings.INITIAL_INVESTMENT
                    )
                    if reference_dates is None:
                        reference_dates = dates.copy()
                        reference_ticker = ticker

                    row.update(summary)
                    row["return_observations"] = len(performance) - 1

                    if dates.equals(reference_dates):
                        row.update(
                            status="ok",
                            message=(
                                "Full observed growth; volatility uses matched "
                                "intervals across included ETFs."
                            ),
                        )
                    else:
                        row.update(
                            status="ok_with_calendar_gaps",
                            message=(
                                "Growth uses adjusted prices; mismatched intervals "
                                "excluded from shared risk sample. "
                                "Drawdown may miss unobserved extremes."
                            ),
                        )

                    if has_proxy:
                        row["status"] = "ok_with_proxy"
                        row["message"] += " Includes the approved gold proxy."

                    # Record both ends of each return interval.
                    return_series[ticker] = (
                        performance.set_index("date")["total_return"].iloc[1:]
                    )
                    interval_starts[ticker] = pd.Series(
                        dates.shift(1).to_numpy(), index=pd.DatetimeIndex(dates)
                    ).iloc[1:]
        except (ValueError, KeyError, OSError) as error:
            row.update(status="invalid_data", message=str(error))
        except Exception as error:
            row.update(status="download_error", message=str(error))
        rows.append(row)

    # Match both dates so a two-day return cannot be paired with a one-day return.
    observed_returns = pd.DataFrame(return_series).sort_index()
    excluded_dates = []
    if return_series:
        starts = pd.DataFrame(interval_starts).reindex(observed_returns.index)
        same_start = starts.eq(starts[reference_ticker], axis="index")
        daily_returns = observed_returns.where(same_start).dropna(how="any")
        excluded_dates = (
            observed_returns.index.difference(daily_returns.index)
            .strftime("%Y-%m-%d")
            .tolist()
        )

        for row in rows:
            if row["ticker"] in return_series:
                row["volatility_observations"] = len(daily_returns)
                row["excluded_shared_intervals"] = len(excluded_dates)
                # Every fund uses the same sample for volatility.
                row["annualized_volatility"] = (
                    daily_returns[row["ticker"]].std(ddof=1) * (252 ** 0.5)
                    if len(daily_returns) >= 2
                    else float("nan")
                )
                if len(daily_returns) < 2:
                    row.update(
                        status="insufficient_shared_intervals",
                        message=(
                            "Growth calculated; fewer than two matched intervals "
                            "for daily risk estimates."
                        ),
                    )
    else:
        daily_returns = observed_returns
    daily_returns.index.name = "date"
    comparison = pd.DataFrame(rows, columns=COMPARISON_COLUMNS)

    notes = {
        "settings": {
            "tickers": symbols,
            "end_date": settings.END_DATE,
            "lookback_years": settings.LOOKBACK_YEARS,
            "start_date_override": settings.START_DATE,
            "initial_investment": settings.INITIAL_INVESTMENT,
            "currency": currency,
            "refresh_yahoo_data": settings.REFRESH_YAHOO_DATA,
            "use_gld_proxy_for_zgld": settings.USE_GLD_PROXY_FOR_ZGLD,
        },
        "data_source": "Yahoo Finance via yfinance",
        "data_sources": data_sources,
        "price_basis": "Yahoo adjusted market prices, not issuer NAV",
        "available_dates_mean": "observations in the requested download window",
        "boundary_policy": "both requested dates must have observed prices",
        "calendar_reference_ticker_used": reference_ticker,
        "return_currency": currency,
        "return_units": "decimal: 0.01 means 1%",
        "daily_return_interval": (
            "identical starting and ending price dates across all included ETFs"
        ),
        "shared_return_observations": len(daily_returns),
        "excluded_interval_end_dates": excluded_dates,
        "daily_returns_usage": (
            "shared sample for volatility/covariance/correlation only; gaps mean "
            "it must not be compounded into full-period growth or used as a "
            "complete backtest"
        ),
        "growth_convention": (
            "full observed return history per ETF, including returns spanning a "
            "missing observation; no prices are filled or invented"
        ),
        "drawdown_convention": (
            "adjusted-price wealth path; gaps may hide larger drawdowns"
        ),
        "distribution_treatment": (
            "Yahoo adjustments already reflected in adjusted_close; dividends "
            "and capital gains are not added again; excludes client taxes and costs"
        ),
        "volatility_convention": (
            "sample standard deviation on shared matched intervals multiplied "
            "by sqrt(252); adding ETFs can change this shared sample"
        ),
        "status_ok_means": (
            "calculation checks passed, not investment suitability or provider "
            "validation; calendar gaps remain flagged"
        ),
    }
    return comparison, daily_returns, notes


def save_results(
    comparison: pd.DataFrame,
    daily_returns: pd.DataFrame,
    notes: dict,
    folder: Path,
) -> None:
    """Save the comparison, matched returns, and run notes."""
    folder.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(folder / "etf_comparison.csv", index=False)
    daily_returns.to_csv(folder / "daily_returns.csv", date_format="%Y-%m-%d")
    with (folder / "run_notes.json").open("w", encoding="utf-8") as file:
        json.dump(notes, file, indent=2)


if __name__ == "__main__":
    comparison, daily_returns, notes = analyze_batch()
    save_results(comparison, daily_returns, notes, RESULTS_DIR)

    print(comparison[["ticker", "status", "message"]].to_string(index=False))
    print(
        f"\nIncluded {len(daily_returns.columns)} ETF(s), "
        f"with {len(daily_returns):,} shared return observations."
    )
    print(f"Results saved to: {RESULTS_DIR}")
    if len(daily_returns.columns) == 0:
        raise SystemExit("No ETFs could be analyzed. Check the messages above.")
