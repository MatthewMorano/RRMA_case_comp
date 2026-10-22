"""Edit this file to choose ETFs and change the analysis period."""

# Add or remove Yahoo symbols here. No separate entry is needed for each ETF.
TICKERS = [
    "ZLB.TO",
    "ZSP.TO",
    "ZLU.TO",
    "ZGLD.TO",
    "ZST.TO",
    "ZNQ.TO",
    "ZMMK.TO",
]

END_DATE = "2026-09-30"
LOOKBACK_YEARS = 10
INITIAL_INVESTMENT = 10_000
CURRENCY = "CAD"

# False reuses saved prices. True downloads a new snapshot on each run.
REFRESH_YAHOO_DATA = False

# Optimizer assumptions. Rates and weights are decimals: 0.04 means 4%.
ANNUAL_RISK_FREE_RATE = 0.0507  # User's annual assumption: 5.07%.
MAX_ETF_WEIGHT = 1.0        # 1.0 allows 100% in one ETF; 0.5 caps each at 50%.
MAX_DRAWDOWN = 0.15        # Maximum historical loss from a portfolio peak.

# Approved proxy: CAD-converted GLD before ZGLD's first observed price.
USE_GLD_PROXY_FOR_ZGLD = True
