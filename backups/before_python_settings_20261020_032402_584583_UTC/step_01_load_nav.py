"""Lesson 1: load and validate one ETF's NAV history.

Run in a terminal: python step_01_load_nav.py
This lesson prepares data; it does not calculate investment returns yet.
"""

from pathlib import Path

import pandas as pd


# 1. Settings: change these when using another ETF with the same BMO CSV format.
PROJECT_DIR = Path(__file__).resolve().parent
NAV_FILE = PROJECT_DIR / "data" / "Historical_NAV_Extract_en_CA_ZLB.csv"
EXPECTED_CURRENCY = "CAD"


# 2. A function lets us reuse these steps for other ETFs later.
def load_nav(file_path: Path, expected_currency: str) -> pd.DataFrame:
    """Return a table containing date, NAV per unit, and NAV currency."""

    # BMO uses '-' for missing values. Keep all original columns in raw_nav.
    raw_nav = pd.read_csv(file_path, na_values=["-"])
    required_columns = ["Fund Name", "Date", "Price (NAV)", "Price (NAV) Currency"]
    missing_columns = set(required_columns) - set(raw_nav.columns)
    if missing_columns:
        raise ValueError(f"CSV is missing required columns: {sorted(missing_columns)}")

    if raw_nav.empty:
        raise ValueError("The NAV file contains no observations.")
    if raw_nav["Fund Name"].isna().any() or raw_nav["Fund Name"].nunique() != 1:
        raise ValueError("Expected exactly one fund with no missing fund names.")

    # Select the fields for this lesson and give them shorter names.
    nav = raw_nav[["Date", "Price (NAV)", "Price (NAV) Currency"]].copy()
    nav.columns = ["date", "nav", "currency"]

    # Text such as '2011-10-21' becomes a date; NAV becomes a number.
    # errors='raise' stops the script if a non-missing value cannot be converted.
    nav["date"] = pd.to_datetime(nav["date"], format="%Y-%m-%d", errors="raise")
    nav["nav"] = pd.to_numeric(nav["nav"], errors="raise")

    # Stop on unusable data instead of silently deleting or filling observations.
    if nav.isna().any().any():
        raise ValueError("Missing date, NAV, or currency. Inspect the source file.")
    if nav["date"].duplicated().any():
        raise ValueError("Duplicate NAV dates. Inspect the source file.")
    # Strictly between zero and infinity means positive and finite.
    if not nav["nav"].between(0, float("inf"), inclusive="neither").all():
        raise ValueError("Every NAV must be a positive, finite number.")
    if not nav["currency"].eq(expected_currency).all():
        raise ValueError(f"Expected all NAV observations to be in {expected_currency}.")

    # Returns will require oldest-to-newest order. Reset the row labels too.
    return nav.sort_values("date").reset_index(drop=True)


# 3. This block runs when you execute the file directly.
# Importing load_nav from another script will not run this preview.
if __name__ == "__main__":
    nav = load_nav(NAV_FILE, EXPECTED_CURRENCY)

    print(f"Source: {NAV_FILE.name}")
    print(f"Observations: {len(nav):,}")
    print(f"Date range: {nav['date'].min():%Y-%m-%d} to {nav['date'].max():%Y-%m-%d}")
    print(f"NAV currency: {EXPECTED_CURRENCY}")
    print("\nFirst five observations:")
    print(nav.head().to_string(index=False))
    print("\nLast five observations:")
    print(nav.tail().to_string(index=False))
    print("\nChecks passed. Cash distributions have not been included yet.")
