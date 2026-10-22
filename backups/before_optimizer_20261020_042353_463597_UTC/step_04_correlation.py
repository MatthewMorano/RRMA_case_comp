"""Refresh the batch results and calculate correlations between the ETFs."""

from math import isfinite
from pathlib import Path

import pandas as pd

from step_03_batch_analysis import analyze_batch, save_results


PROJECT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_DIR / "results"


def calculate_correlations(daily_returns: pd.DataFrame) -> pd.DataFrame:
    """Calculate Pearson correlations from the complete matched return sample."""
    if not daily_returns.empty:
        if not isinstance(daily_returns.index, pd.DatetimeIndex):
            raise ValueError("The input needs a date index from analyze_batch().")
        if daily_returns.index.hasnans or daily_returns.index.has_duplicates:
            raise ValueError("Return dates must be present and unique.")
        if not daily_returns.index.is_monotonic_increasing:
            raise ValueError("Return dates must be oldest to newest.")
    if daily_returns.columns.has_duplicates:
        raise ValueError("Each ETF ticker must identify one column.")
    # Reject gaps here so every ETF pair uses the same observations.
    if daily_returns.isna().any().any():
        raise ValueError("Use the complete matched sample from analyze_batch().")
    for ticker in daily_returns.columns:
        column = daily_returns[ticker]
        if not pd.api.types.is_numeric_dtype(column):
            raise ValueError(f"Returns for {ticker} must be numeric.")
        if not column.map(isfinite).all():
            raise ValueError(f"Returns for {ticker} must be finite.")

    correlation = daily_returns.corr(method="pearson", min_periods=2)
    correlation.index.name = "ticker"
    return correlation


if __name__ == "__main__":
    # Load the configured Yahoo prices and rebuild the matched return sample.
    comparison, daily_returns, notes = analyze_batch()
    correlation = calculate_correlations(daily_returns)

    notes["correlation_method"] = "Pearson correlation of matched daily total returns"
    notes["correlation_observations"] = len(daily_returns)
    notes["undefined_correlation_tickers"] = [
        ticker
        for ticker in daily_returns.columns
        if len(daily_returns) < 2 or daily_returns[ticker].nunique() <= 1
    ]
    save_results(comparison, daily_returns, notes, RESULTS_DIR)
    correlation.to_csv(RESULTS_DIR / "correlation_matrix.csv", na_rep="NaN")

    print(comparison[["ticker", "status", "message"]].to_string(index=False))
    print(f"\nShared return observations: {len(daily_returns):,}")
    if len(daily_returns.columns) < 2:
        print("Add at least two eligible ETFs for a cross-ETF comparison.")
    print("\nCorrelation matrix (rounded for display only):")
    print(correlation.round(3).to_string())
    if notes["undefined_correlation_tickers"]:
        print(
            "\nNaN means correlation is undefined: "
            "fewer than two returns or no return variation."
        )
    print(f"\nSaved: {RESULTS_DIR / 'correlation_matrix.csv'}")
    if len(daily_returns.columns) == 0:
        raise SystemExit("No ETFs could be analyzed. Check the messages above.")
