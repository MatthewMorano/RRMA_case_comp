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
LOOKBACK_YEARS = 5
# Explicitly approved shorter window so ZMMK uses only actual observations.
# Set to None to use END_DATE minus LOOKBACK_YEARS instead.
START_DATE = "2021-12-02"
INITIAL_INVESTMENT = 10_000
CURRENCY = "CAD"

# False reuses saved prices. True downloads a new snapshot on each run.
REFRESH_YAHOO_DATA = False

# Optimizer assumptions. Rates and weights are decimals: 0.04 means 4%.
ANNUAL_RISK_FREE_RATE = 0.0507  # User's annual assumption: 5.07%.
MAX_ETF_WEIGHT = 1.0        # 1.0 allows 100% in one ETF; 0.5 caps each at 50%.
MAX_DRAWDOWN = 0.15        # Maximum historical loss from a portfolio peak.
MAX_ANNUAL_VOLATILITY = 0.075

# Client B: reserve this amount in ZMMK; optimize the remaining capital.
CLIENT_PORTFOLIO_VALUE = 6_500_000
ZMMK_RESERVE = 175_000

# Approved proxy: CAD-converted GLD before ZGLD's first observed price.
USE_GLD_PROXY_FOR_ZGLD = True
