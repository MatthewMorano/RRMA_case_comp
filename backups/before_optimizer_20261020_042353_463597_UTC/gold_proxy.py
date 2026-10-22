"""Extend ZGLD with an explicitly labelled CAD-converted GLD proxy."""

import hashlib
import json
from pathlib import Path

import pandas as pd

from step_01_load_prices import load_prices


def align_proxy_quotes(dates, quotes, value_column, label):
    """Use only the last available quote; record its date and reject stale data."""
    quote_date = f"{label}_quote_date"
    right = quotes[["date", value_column]].rename(
        columns={"date": quote_date, value_column: label}
    )
    if not right[label].between(0, float("inf"), inclusive="neither").all():
        raise ValueError(f"Invalid {label} quotes in the gold proxy.")
    left = pd.DataFrame({"date": dates})
    # Cached and freshly downloaded dates can have different pandas time units.
    left["date"] = left["date"].astype("datetime64[ns]")
    right[quote_date] = right[quote_date].astype("datetime64[ns]")
    aligned = pd.merge_asof(
        left, right.sort_values(quote_date),
        left_on="date", right_on=quote_date, direction="backward",
        tolerance=pd.Timedelta(days=4),
    )
    if aligned[label].isna().any():
        raise ValueError(f"Missing or stale {label} quotes in the gold proxy.")
    return aligned


def extend_gold_history(actual, currency, start_date, end_date, cache_dir, refresh):
    """Chain GLD in CAD to ZGLD at its first observed adjusted closing price."""
    if currency.upper() != "CAD":
        raise ValueError("The approved ZGLD proxy model is for CAD only.")
    cache_dir = Path(cache_dir) if cache_dir else Path(__file__).parent / "data/yahoo"
    anchor = actual["date"].iloc[0]
    buffer_start = pd.Timestamp(start_date) - pd.Timedelta(days=7)

    # ZLB supplies the observed Canadian price calendar, not an investment return.
    calendar = load_prices(
        "ZLB.TO", "CAD", start_date, end_date, cache_dir, refresh=False
    )["date"]
    actual_dates = pd.DatetimeIndex(actual["date"])
    expected_actual = pd.DatetimeIndex(calendar.loc[calendar >= anchor])
    if not actual_dates.equals(expected_actual):
        raise ValueError("ZGLD's actual history has calendar gaps. Inspect it first.")
    proxy_dates = calendar.loc[calendar <= anchor].reset_index(drop=True)
    if proxy_dates.empty or proxy_dates.iloc[-1] != anchor:
        raise ValueError("The gold proxy needs an observed Canadian overlap date.")

    gld = load_prices(
        "GLD", "USD", buffer_start, anchor, cache_dir, refresh,
        allow_missing_quotes=True,
    )
    fx = load_prices(
        "CAD=X", "CAD", buffer_start, anchor, cache_dir, refresh,
        instrument_type="CURRENCY", allow_missing_quotes=True,
    )
    aligned_gld = align_proxy_quotes(proxy_dates, gld, "adjusted_close", "gld_usd")
    aligned_fx = align_proxy_quotes(proxy_dates, fx, "close", "cad_per_usd")
    proxy = aligned_gld.merge(aligned_fx, on="date", validate="one_to_one")

    # USD price times CAD per USD gives a CAD price; these are not hedged returns.
    proxy["gld_cad"] = proxy["gld_usd"] * proxy["cad_per_usd"]
    scale = actual["adjusted_close"].iloc[0] / proxy["gld_cad"].iloc[-1]
    proxy["adjusted_close"] = proxy["gld_cad"] * scale
    proxy["history_source"] = "GLD converted to CAD (proxy)"
    proxy = proxy.loc[proxy["date"] < anchor].copy()
    observed = actual.copy()
    observed["history_source"] = "ZGLD actual"
    observed.loc[0, "history_source"] = "ZGLD price; return crosses proxy splice"
    combined = pd.concat([proxy, observed], ignore_index=True)
    if not pd.DatetimeIndex(combined["date"]).equals(pd.DatetimeIndex(calendar)):
        raise ValueError("The assembled gold history does not match the calendar.")

    inputs = {
        "zgld": actual.attrs["source"],
        "gld": gld.attrs["source"],
        "fx": fx.attrs["source"],
    }
    fingerprint = hashlib.sha256(
        json.dumps({"method": "gold_proxy_v1", "inputs": inputs},
                   sort_keys=True).encode()
    ).hexdigest()[:16]
    folder = cache_dir.parent / "proxy_histories"
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / f"ZGLD_CAD_proxy_{fingerprint}.csv"
    source = {
        **actual.attrs["source"],
        "source": "ZGLD actual plus GLD/USD-CAD historical proxy",
        "cache_file": str(file.resolve()),
        "history_type": "proxy_extended",
        "proxy_anchor_date": anchor.strftime("%Y-%m-%d"),
        "proxy_price_rows": len(proxy),
        "proxy_return_end_date": anchor.strftime("%Y-%m-%d"),
        "proxy_scale": float(scale),
        "gld_carried_quote_rows": int(
            (proxy["gld_usd_quote_date"] != proxy["date"]).sum()
        ),
        "fx_carried_quote_rows": int(
            (proxy["cad_per_usd_quote_date"] != proxy["date"]).sum()
        ),
        "proxy_inputs": inputs,
        "calendar_ticker": "ZLB.TO",
        "alignment_policy": (
            "previous available GLD and FX quotes, maximum age 4 calendar days; "
            "quote dates retained; actual ZGLD prices are never filled"
        ),
        "limitations": (
            "synthetic history, not ZGLD's actual pre-launch performance; GLD's "
            "fees and tracking are retained; daily FX/ETF closes differ in timing"
        ),
    }
    combined.to_csv(file, index=False, date_format="%Y-%m-%d")
    with file.with_suffix(".json").open("w", encoding="utf-8") as output:
        json.dump(source, output, indent=2)
    combined.attrs["source"] = source
    return combined
