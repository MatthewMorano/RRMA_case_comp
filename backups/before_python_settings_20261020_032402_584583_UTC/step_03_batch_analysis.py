"""Analyze the funds in etfs.json and save their performance and returns."""

import json
from math import isfinite
from pathlib import Path

import pandas as pd

from step_02_total_returns import (
    analyze_performance,
    calculate_total_returns,
    select_period,
)


PROJECT_DIR = Path(__file__).resolve().parent
ETF_LIST_FILE = PROJECT_DIR / "etfs.json"
RESULTS_DIR = PROJECT_DIR / "results"

COMPARISON_COLUMNS = [
    "ticker",
    "fund_name",
    "asset_class",
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


def load_etf_list(file_path: Path) -> dict:
    """Read settings and check for missing fields or duplicate sources."""
    with file_path.open(encoding="utf-8") as file:
        config = json.load(file)

    settings = config["analysis"]
    end_date = pd.Timestamp(settings["end_date"])
    if (
        pd.isna(end_date)
        or end_date != end_date.normalize()
        or end_date.tzinfo is not None
    ):
        raise ValueError("end_date must be a calendar date such as 2026-09-30.")

    years = settings["lookback_years"]
    if type(years) is not int or years <= 0:
        raise ValueError("lookback_years must be a positive whole number.")

    investment = settings["initial_investment"]
    if not isfinite(investment) or investment <= 0:
        raise ValueError("initial_investment must be positive and finite.")
    if not settings["comparison_currency"]:
        raise ValueError("Choose a comparison_currency.")

    if type(settings.get("refresh_yahoo_data", False)) is not bool:
        raise ValueError("refresh_yahoo_data must be true or false.")

    tickers = set()
    sources = set()

    for etf in config["etfs"]:
        for field in ["ticker", "fund_name", "yahoo_ticker", "currency", "asset_class"]:
            if not isinstance(etf[field], str) or not etf[field].strip():
                raise ValueError(f"Each ETF needs a nonempty {field}.")
        if type(etf.get("enabled", True)) is not bool:
            raise ValueError("enabled must be true or false.")

        ticker = etf["ticker"].strip().upper()
        if ticker in tickers:
            raise ValueError(f"Duplicate ticker: {ticker}")
        tickers.add(ticker)
        source = etf["yahoo_ticker"].strip().upper()
        if etf.get("enabled", True) and source in sources:
            raise ValueError("Enabled ETFs must not reuse the same Yahoo symbol.")
        if etf.get("enabled", True):
            sources.add(source)
    return config


def analyze_batch(
    config: dict, data_root: Path
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return fund summaries, matched daily returns, and notes about the run."""
    settings = config["analysis"]
    end_date = pd.Timestamp(settings["end_date"])
    start_date = end_date - pd.DateOffset(years=settings["lookback_years"])
    target_currency = settings["comparison_currency"].upper()
    asset_filter = settings.get("asset_class_filter")
    preferred_reference = settings.get("calendar_reference_ticker", "").upper()

    # Try the preferred reference first; otherwise use the first eligible fund.
    etfs = sorted(
        config["etfs"],
        key=lambda etf: etf["ticker"].strip().upper() != preferred_reference,
    )
    reference_dates = None
    reference_ticker = None
    rows = []
    return_series = {}
    interval_starts = {}
    data_sources = {}

    for etf in etfs:
        ticker = etf["ticker"].strip().upper()
        currency = etf["currency"].strip().upper()
        row = {
            "ticker": ticker,
            "fund_name": etf["fund_name"],
            "asset_class": etf["asset_class"],
            "currency": currency,
            "yahoo_ticker": etf["yahoo_ticker"],
            "validation_note": etf.get(
                "validation_note",
                "Yahoo adjusted market prices; not yet independently validated.",
            ),
            "requested_start": start_date.strftime("%Y-%m-%d"),
            "requested_end": end_date.strftime("%Y-%m-%d"),
        }

        if not etf.get("enabled", True):
            row.update(status="disabled", message="Disabled in the ETF list.")
        elif (
            asset_filter
            and etf["asset_class"].casefold() != asset_filter.casefold()
        ):
            row.update(
                status="filtered_out",
                message=f"Current asset-class filter: {asset_filter}.",
            )
        elif currency != target_currency:
            row.update(
                status="currency_conversion_required",
                message=f"Needs conversion to {target_currency}.",
            )
        else:
            try:
                full_history = calculate_total_returns(
                    etf["yahoo_ticker"], currency, start_date, end_date,
                    cache_dir=data_root / "data" / "yahoo",
                    refresh=settings.get("refresh_yahoo_data", False),
                )
                data_sources[ticker] = full_history.attrs["source"]
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
                            period, initial_investment=settings["initial_investment"]
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
        "settings": settings,
        "data_source": "Yahoo Finance via yfinance",
        "data_sources": data_sources,
        "price_basis": "Yahoo adjusted market prices, not issuer NAV",
        "available_dates_mean": "observations in the requested download window",
        "boundary_policy": "both requested dates must have observed prices",
        "calendar_reference_ticker_used": reference_ticker,
        "return_currency": target_currency,
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
    config = load_etf_list(ETF_LIST_FILE)
    comparison, daily_returns, notes = analyze_batch(config, ETF_LIST_FILE.parent)
    save_results(comparison, daily_returns, notes, RESULTS_DIR)

    print(comparison[["ticker", "status", "message"]].to_string(index=False))
    print(
        f"\nIncluded {len(daily_returns.columns)} ETF(s), "
        f"with {len(daily_returns):,} shared return observations."
    )
    print(f"Results saved to: {RESULTS_DIR}")
    if len(daily_returns.columns) == 0:
        raise SystemExit("No ETFs could be analyzed. Check the messages above.")
