"""Edit this file to choose ETFs and change the analysis period."""

# Add or remove Yahoo symbols here. No separate entry is needed for each ETF.
TICKERS = [
    "ZLB.TO",
    "ZSP.TO",
    "ZLU.TO",
]

END_DATE = "2026-09-30"
LOOKBACK_YEARS = 10
INITIAL_INVESTMENT = 10_000
CURRENCY = "CAD"

# False reuses saved prices. True downloads a new snapshot on each run.
REFRESH_YAHOO_DATA = False
