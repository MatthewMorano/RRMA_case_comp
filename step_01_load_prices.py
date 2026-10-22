"""Load daily ETF market prices from Yahoo, or reuse a saved download."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

import settings


PROJECT_DIR = Path(__file__).resolve().parent


def load_prices(
    ticker, currency, start_date, end_date, cache_dir=None, refresh=False,
    instrument_type="ETF", allow_missing_quotes=False,
):
    """Download one ETF's prices once, then use the local copy on later runs."""
    ticker = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.=-]*", ticker):
        raise ValueError("Use a Yahoo ETF symbol such as ZLB.TO.")
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    for date in [start, end]:
        if pd.isna(date) or date.tzinfo is not None or date != date.normalize():
            raise ValueError("Use calendar dates such as 2026-09-30.")
    if start >= end:
        raise ValueError("The start date must be before the end date.")

    cache_dir = Path(cache_dir) if cache_dir else PROJECT_DIR / "data" / "yahoo"
    folder = cache_dir / f"{ticker}_{start:%Y-%m-%d}_{end:%Y-%m-%d}"
    saved_files = sorted(folder.glob("*.csv"))
    # A shorter study can reuse an existing wider download without changing it.
    if not saved_files and not refresh:
        for metadata_file in cache_dir.glob(f"{ticker}_*/*.json"):
            with metadata_file.open(encoding="utf-8") as file:
                metadata = json.load(file)
            if (metadata.get("ticker") == ticker
                    and pd.Timestamp(metadata["requested_start"]) <= start
                    and pd.Timestamp(metadata["requested_end"]) >= end
                    and metadata_file.with_suffix(".csv").exists()):
                saved_files.append(metadata_file.with_suffix(".csv"))
        saved_files.sort(key=lambda path: path.name)
    use_cache = bool(saved_files) and not refresh

    if use_cache:
        csv_file = saved_files[-1]
        prices = pd.read_csv(csv_file, parse_dates=["date"])
        with csv_file.with_suffix(".json").open(encoding="utf-8") as file:
            source = json.load(file)
    else:
        # Yahoo excludes its end date, so add one day to include our end date.
        yf.set_tz_cache_location(str(cache_dir / ".yfinance_cache"))
        fund = yf.Ticker(ticker)
        prices = fund.history(
            start=start.strftime("%Y-%m-%d"),
            end=(end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=False,  # Request Close and Adj Close separately.
            actions=True,
            keepna=True,       # Never fill a missing price.
            repair=False,
            timeout=20,
        )
        if prices.empty:
            raise ValueError(f"Yahoo returned no prices for {ticker}.")
        details = fund.get_history_metadata()

        # Remove the time-zone label while keeping the exchange's local dates.
        prices.index = prices.index.tz_localize(None).normalize()
        prices.index.name = "date"
        prices = prices.reset_index().rename(
            columns=lambda name: name.lower().replace(" ", "_")
        )
        prices = prices.rename(columns={"adj_close": "adjusted_close"})
        source = {
            "source": "Yahoo Finance via yfinance",
            "fund_name": details.get("longName") or details.get("shortName") or ticker,
            "ticker": details.get("symbol"),
            "currency": details.get("currency"),
            "instrument_type": details.get("instrumentType"),
            "requested_start": start.strftime("%Y-%m-%d"),
            "requested_end": end.strftime("%Y-%m-%d"),
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
            "yfinance_version": yf.__version__,
            "auto_adjust": False,
        }

    # Apply the same checks to downloaded and cached data.
    if source.get("ticker") != ticker:
        raise ValueError("The source symbol does not match the requested ETF.")
    if source.get("currency") != currency.upper():
        raise ValueError(
            f"Expected {currency}; source reports {source.get('currency')}."
        )
    if source.get("instrument_type") != instrument_type:
        raise ValueError(f"Yahoo did not identify this symbol as {instrument_type}.")
    if (
        pd.Timestamp(source.get("requested_start")) > start
        or pd.Timestamp(source.get("requested_end")) < end
        or source.get("auto_adjust") is not False
    ):
        raise ValueError("The saved source settings do not match this request.")
    if prices.empty or not {"date", "adjusted_close"}.issubset(prices.columns):
        raise ValueError("The price table needs dates and adjusted closing prices.")
    prices = prices.sort_values("date").reset_index(drop=True)
    prices["date"] = prices["date"].astype("datetime64[ns]")
    if use_cache:
        prices = prices.loc[prices["date"].between(start, end)].reset_index(drop=True)
        if prices.empty:
            raise ValueError("The saved download has no observations in this period.")
    dates = prices["date"]
    if dates.isna().any() or dates.duplicated().any():
        raise ValueError("Missing or duplicate price dates. Inspect the source.")
    if not dates.between(start, end).all():
        raise ValueError("The source contains dates outside the requested period.")
    adjusted = pd.to_numeric(prices["adjusted_close"], errors="raise")
    observed = adjusted.dropna()
    if observed.empty or not observed.between(
        0, float("inf"), inclusive="neither"
    ).all():
        raise ValueError("Missing or invalid adjusted prices. Inspect the source.")
    missing = adjusted.isna()
    if missing.any() and not allow_missing_quotes:
        raise ValueError("Missing or invalid adjusted prices. Inspect the source.")
    prices["adjusted_close"] = adjusted
    source["unavailable_quote_dates"] = (
        dates.loc[missing].dt.strftime("%Y-%m-%d").tolist()
    )

    if not use_cache:
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f_UTC")
        csv_file = folder / f"{stamp}.csv"
        prices.to_csv(csv_file, index=False, date_format="%Y-%m-%d")
        with csv_file.with_suffix(".json").open("w", encoding="utf-8") as file:
            json.dump(source, file, indent=2)

    # Auxiliary proxy feeds can omit unavailable quotes for dated as-of matching.
    # The raw cached CSV still preserves those missing rows. Actual ETFs stay strict.
    if allow_missing_quotes:
        prices = prices.loc[~missing].reset_index(drop=True)
    prices.attrs["source"] = {
        **source, "cache_file": str(csv_file.resolve()), "read_from_cache": use_cache
    }
    return prices


def load_analysis_prices(
    ticker, currency, start_date, end_date, cache_dir=None, refresh=False
):
    """Use actual ETF prices, with the explicitly approved gold proxy if needed."""
    actual = load_prices(
        ticker, currency, start_date, end_date, cache_dir, refresh
    )
    needs_proxy = actual["date"].iloc[0] > pd.Timestamp(start_date)
    if ticker.upper() == "ZGLD.TO" and settings.USE_GLD_PROXY_FOR_ZGLD and needs_proxy:
        from gold_proxy import extend_gold_history
        return extend_gold_history(
            actual, currency, start_date, end_date, cache_dir, refresh
        )
    return actual


if __name__ == "__main__":
    if not settings.TICKERS:
        raise SystemExit("Add at least one Yahoo ETF symbol in settings.py.")
    end = pd.Timestamp(settings.END_DATE)
    start = end - pd.DateOffset(years=settings.LOOKBACK_YEARS)
    if settings.START_DATE is not None:
        start = pd.Timestamp(settings.START_DATE)
    prices = load_analysis_prices(
        settings.TICKERS[0], settings.CURRENCY, start, end,
        refresh=settings.REFRESH_YAHOO_DATA,
    )
    print(prices[["date", "close", "adjusted_close"]].head().to_string(index=False))
    print(f"\nObservations: {len(prices):,}")
    print(f"Source copy: {prices.attrs['source']['cache_file']}")
