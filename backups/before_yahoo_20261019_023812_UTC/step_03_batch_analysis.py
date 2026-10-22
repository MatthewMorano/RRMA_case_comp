"""Lesson 3: apply the existing analysis to an editable list of ETFs.

Run: python step_03_batch_analysis.py
Edit etfs.json to add downloaded BMO NAV CSVs with the same source format.
"""

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

# Explicit columns keep the output consistent even when no ETF succeeds.
COMPARISON_COLUMNS = [
    "ticker", "fund_name", "asset_class", "currency", "nav_file",
    "status", "message", "validation_note", "requested_start", "requested_end",
    "available_start", "available_end", "actual_start", "actual_end",
    "return_observations", "volatility_observations", "excluded_shared_intervals",
    "starting_value", "ending_value", "years",
    "annualized_return", "annualized_volatility", "maximum_drawdown",
]


def load_etf_list(file_path: Path) -> dict:
    """Load settings and check that each ETF identifies a separate source."""
    with file_path.open(encoding="utf-8") as file:
        config = json.load(file)

    settings = config["analysis"]
    end_date = pd.Timestamp(settings["end_date"])
    if pd.isna(end_date) or end_date != end_date.normalize() or end_date.tzinfo is not None:
        raise ValueError("end_date must be a calendar date such as 2026-09-30.")
    years = settings["lookback_years"]
    if type(years) is not int or years <= 0:
        raise ValueError("lookback_years must be a positive whole number.")
    investment = settings["initial_investment"]
    if not isfinite(investment) or investment <= 0:
        raise ValueError("initial_investment must be positive and finite.")
    if not settings["comparison_currency"]:
        raise ValueError("Choose a comparison_currency.")

    tickers = set()
    sources = set()
    for etf in config["etfs"]:
        for field in ["ticker", "fund_name", "nav_file", "currency", "asset_class"]:
            if not isinstance(etf[field], str) or not etf[field].strip():
                raise ValueError(f"Each ETF needs a nonempty {field}.")
        if type(etf.get("enabled", True)) is not bool:
            raise ValueError("enabled must be true or false.")
        ticker = etf["ticker"].strip().upper()
        if ticker in tickers:
            raise ValueError(f"Duplicate ticker: {ticker}")
        tickers.add(ticker)
        source = str((file_path.parent / etf["nav_file"]).resolve()).casefold()
        if etf.get("enabled", True) and source in sources:
            raise ValueError("Enabled ETFs must not reuse the same NAV file.")
        if etf.get("enabled", True):
            sources.add(source)
    return config


def analyze_batch(config: dict, data_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return the comparison, aligned daily returns, and run notes.

    A source failure is recorded for its ETF, and the loop continues. An ETF
    keeps its full observed growth path. Daily risk inputs use only intervals
    whose start AND end dates match across included ETFs. No NAV is filled.
    No FX conversion, download automation, correlation, or optimization yet.
    """
    settings = config["analysis"]
    end_date = pd.Timestamp(settings["end_date"])
    start_date = end_date - pd.DateOffset(years=settings["lookback_years"])
    target_currency = settings["comparison_currency"].upper()
    asset_filter = settings.get("asset_class_filter")
    preferred_reference = settings.get("calendar_reference_ticker", "").upper()

    # Try the preferred calendar reference first. If it fails or is filtered,
    # the first eligible ETF becomes the reference; run notes record the choice.
    etfs = sorted(
        config["etfs"],
        key=lambda etf: etf["ticker"].strip().upper() != preferred_reference,
    )
    reference_dates = None
    reference_ticker = None
    rows = []
    return_series = {}
    interval_starts = {}

    for etf in etfs:
        ticker = etf["ticker"].strip().upper()
        currency = etf["currency"].strip().upper()
        row = {
            "ticker": ticker,
            "fund_name": etf["fund_name"],
            "asset_class": etf["asset_class"],
            "currency": currency,
            "nav_file": etf["nav_file"],
            "validation_note": etf.get("validation_note", "Not yet reconciled to provider."),
            "requested_start": start_date.strftime("%Y-%m-%d"),
            "requested_end": end_date.strftime("%Y-%m-%d"),
        }

        # These settings decide which products belong in this comparison.
        if not etf.get("enabled", True):
            row.update(status="disabled", message="Disabled in the ETF list.")
        elif asset_filter and etf["asset_class"].casefold() != asset_filter.casefold():
            row.update(status="filtered_out", message=f"Current asset-class filter: {asset_filter}.")
        elif currency != target_currency:
            row.update(status="currency_conversion_required", message=f"Needs conversion to {target_currency}.")
        else:
            try:
                nav_path = data_root / etf["nav_file"]
                # The source has a fund name, not a ticker. Check it against
                # the registry so an accidentally copied file is not mislabeled.
                names = pd.read_csv(nav_path, usecols=["Fund Name"])["Fund Name"]
                if names.isna().any() or set(names.unique()) != {etf["fund_name"]}:
                    raise ValueError("Fund Name in the CSV does not match the ETF list.")

                full_history = calculate_total_returns(nav_path, currency)
                row["available_start"] = full_history["date"].iloc[0].strftime("%Y-%m-%d")
                row["available_end"] = full_history["date"].iloc[-1].strftime("%Y-%m-%d")
                if full_history["date"].iloc[0] > start_date or full_history["date"].iloc[-1] < end_date:
                    row.update(status="insufficient_history", message="The file does not cover the full requested period.")
                else:
                    period = select_period(full_history, start_date, end_date)
                    dates = period["date"].reset_index(drop=True)
                    row["actual_start"] = dates.iloc[0].strftime("%Y-%m-%d")
                    row["actual_end"] = dates.iloc[-1].strftime("%Y-%m-%d")

                    if reference_dates is not None and (
                        dates.iloc[0] != reference_dates.iloc[0]
                        or dates.iloc[-1] != reference_dates.iloc[-1]
                    ):
                        row.update(status="calendar_mismatch", message=f"Actual start or end differs from {reference_ticker}; align the period boundaries.")
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
                            row.update(status="ok", message="Full observed growth; volatility uses matched intervals across included ETFs.")
                        else:
                            row.update(status="ok_with_calendar_gaps", message="Growth uses observed NAVs; mismatched intervals excluded from shared risk sample. Drawdown may miss unobserved extremes.")
                        # Retain full observed returns for growth, and separately
                        # track each return's starting date for daily alignment.
                        return_series[ticker] = performance.set_index("date")["total_return"].iloc[1:]
                        interval_starts[ticker] = pd.Series(
                            dates.shift(1).to_numpy(), index=pd.DatetimeIndex(dates)
                        ).iloc[1:]
            except FileNotFoundError as error:
                row.update(status="missing_file", message=str(error))
            except (ValueError, KeyError, OSError) as error:
                row.update(status="invalid_data", message=str(error))
        rows.append(row)

    # Matching ending dates alone is insufficient: after a missing NAV, one
    # fund's return may span two sessions while another spans only one.
    observed_returns = pd.DataFrame(return_series).sort_index()
    excluded_dates = []
    if return_series:
        starts = pd.DataFrame(interval_starts).reindex(observed_returns.index)
        same_start = starts.eq(starts[reference_ticker], axis="index")
        daily_returns = observed_returns.where(same_start).dropna(how="any")
        excluded_dates = observed_returns.index.difference(daily_returns.index).strftime("%Y-%m-%d").tolist()
        for row in rows:
            if row["ticker"] in return_series:
                row["volatility_observations"] = len(daily_returns)
                row["excluded_shared_intervals"] = len(excluded_dates)
                # All included ETFs use the identical sample for volatility.
                row["annualized_volatility"] = (
                    daily_returns[row["ticker"]].std(ddof=1) * (252 ** 0.5)
                    if len(daily_returns) >= 2 else float("nan")
                )
                if len(daily_returns) < 2:
                    row.update(status="insufficient_shared_intervals", message="Growth calculated; fewer than two matched intervals for daily risk estimates.")
    else:
        daily_returns = observed_returns
    daily_returns.index.name = "date"
    comparison = pd.DataFrame(rows, columns=COMPARISON_COLUMNS)
    notes = {
        "settings": settings,
        "calendar_reference_ticker_used": reference_ticker,
        "return_currency": target_currency,
        "return_units": "decimal: 0.01 means 1%",
        "daily_return_interval": "identical starting and ending NAV dates across all included ETFs",
        "shared_return_observations": len(daily_returns),
        "excluded_interval_end_dates": excluded_dates,
        "daily_returns_usage": "shared sample for volatility/covariance/correlation only; gaps mean it must not be compounded into full-period growth or used as a complete backtest",
        "growth_convention": "full observed return history per ETF, including returns spanning a missing observation; no NAV or omitted cash event is invented",
        "drawdown_convention": "observed NAV-based wealth path; missing NAVs may hide larger drawdowns",
        "cash_source": "NAV-export cash amounts and dates; cash reinvested at ex-date NAV",
        "volatility_convention": "sample standard deviation on shared matched intervals multiplied by sqrt(252); adding ETFs can change this shared sample",
        "status_ok_means": "calculation checks passed, not investment suitability or provider validation; calendar gaps remain flagged",
    }
    return comparison, daily_returns, notes


def save_results(comparison: pd.DataFrame, daily_returns: pd.DataFrame, notes: dict, folder: Path) -> None:
    """Write fresh results, including empty daily returns if nothing qualified."""
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
    print(f"\nIncluded {len(daily_returns.columns)} ETF(s), with {len(daily_returns):,} shared return observations.")
    print(f"Results saved to: {RESULTS_DIR}")
