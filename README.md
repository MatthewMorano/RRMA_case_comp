# ETF analysis

This is the existing ETF project, updated to download Yahoo Finance market
prices instead of reading BMO NAV exports. It still compares growth of $10,000,
annualized return, volatility, drawdown and correlations over the same period.

## Run the analysis

Open this project folder in VS Code. With your usual Python environment selected:

```powershell
python -m pip install -r requirements.txt
python step_04_correlation.py
```

The second command runs the ETF comparison and correlation calculation together.
It downloads prices on the first run and reuses local copies on later runs.
It needs an internet connection when a requested download is not already saved.
The yfinance version is pinned to the version used to test this integration.

## The analysis steps

| File | What it does |
| --- | --- |
| `step_01_load_prices.py` | Downloads, checks and saves Yahoo ETF prices |
| `step_02_total_returns.py` | Calculates returns and performance |
| `step_03_batch_analysis.py` | Compares the ticker list in `settings.py` |
| `step_04_correlation.py` | Runs the comparison and calculates correlations |
| `step_05_optimize_portfolio.py` | Maximizes historical Sharpe with risk limits and a fixed ZMMK reserve |

You can also run steps 1, 2 or 3 separately. Steps 1 and 2 demonstrate the first
ETF in the list; steps 3 and 4 process all listed ETFs.
The old `step_01_load_nav.py` and BMO files are retained for reference and are
not used by this Yahoo workflow. Earlier LESSON files describe that NAV version.

## Choose the ETFs and period

Edit `settings.py`. Add or remove Yahoo symbols in this list:

```python
TICKERS = [
    "ZLB.TO",
    "ZSP.TO",
    "ZLU.TO",
    "ZGLD.TO",
    "ZST.TO",
    "ZNQ.TO",
    "ZMMK.TO",
]
```

Adding another ETF means adding one symbol to that list. No JSON entry, fund
name, file path or separate currency entry is needed. This is your chosen ETF
universe; the code verifies ETF type and currency but does not automatically
classify funds as equity, bonds or gold. All listed ETFs are attempted. To
exclude one, remove or comment out its line. Duplicate symbols are rejected.

The settings immediately below the list control the analysis:

```python
END_DATE = "2026-09-30"
LOOKBACK_YEARS = 5
START_DATE = "2021-12-02"
INITIAL_INVESTMENT = 10_000
CURRENCY = "CAD"
REFRESH_YAHOO_DATA = False
```

The target is five years. The explicit `START_DATE` overrides the lookback to
use December 2, 2021 through September 30, 2026, about 4 years and 10 months.
This shorter common period was chosen to use actual ZMMK prices without a
pre-launch proxy. Set `START_DATE = None` to use the lookback instead, but the
optimizer will stop if the required ZMMK history is too short.
All included ETFs must trade in
the selected currency; this version does not convert currencies. CAD trading
currency alone does not mean the underlying investments have no currency exposure.

Reports retain short display labels such as `ZLB`, plus the exact `yahoo_ticker`
such as `ZLB.TO`. A fund name is shown if supplied in the saved Yahoo metadata;
otherwise the Yahoo symbol is used. The old manually entered asset-class labels
are no longer part of the output. The first successfully analyzed ETF supplies
the reference observation calendar.

## Understand the return calculation

Yahoo returns a regular `close` column and an `adjusted_close` column. The latter
reflects Yahoo's split and distribution adjustments. We request both explicitly
with `auto_adjust=False` so the column used in calculations is clear.

```python
returns["previous_adjusted_close"] = returns["adjusted_close"].shift(1)
returns["total_return"] = (
    returns["adjusted_close"] / returns["previous_adjusted_close"] - 1
)
```

Do not add dividends or capital-gain events again. That would count adjustments
twice. The first return remains missing because there is no preceding price in
the study period. Rates are decimals: `0.01` means 1%.

These are estimates based on Yahoo-adjusted market prices, before client taxes
and trading costs. They can differ from BMO NAV total returns. Our earlier ZLB
agreement with BMO's NAV factsheet does not validate this new price source.
Validate Yahoo prices and corporate actions before relying on final results.

## Saved downloads and refreshes

Downloads are stored under `data/yahoo`, grouped by symbol and requested period.
Each CSV has a companion JSON file with symbol, currency, retrieval time and
yfinance version. The run notes identify the exact files used for calculations.

With `REFRESH_YAHOO_DATA = False`, an existing download is reused, so you can run
calculations offline. Set it to `True` for one run to fetch new data, then change
it back to `False`. Refreshing creates a new snapshot and preserves older ones.
Yahoo may revise adjusted history; save the snapshots used in a team submission.
A shorter study can reuse a wider saved download. The original snapshot and
its metadata stay unchanged; only observations inside the study are analyzed.

Yahoo can temporarily rate-limit fresh requests. Affected ETFs get a
`download_error` message. Cached runs do not need another request; a failed
explicit refresh is reported rather than silently substituted with old data.

The loader verifies identity, currency, ETF type, unique dates and positive,
finite adjusted prices. A returned row with a missing adjusted price is rejected.
It does not fill missing values or invent absent dates. Failed ETFs appear in the
comparison with a message; the remaining ETFs can still be processed.

Both requested boundary dates must have observed prices. A shorter-history ETF
or a missing boundary is excluded and flagged. For weekend/holiday boundaries,
choose observed trading dates explicitly; this version does not silently shift
the configured dates. `available_start` and `available_end`
refer to the requested download window, not the ETF's complete lifetime history.

## Output files

The existing `results` folder contains:

- `etf_comparison.csv`: performance, status and validation notes per ETF.
- `daily_returns.csv`: common matched return intervals for risk estimates.
- `correlation_matrix.csv`: Pearson correlations on that common sample.
- `run_notes.json`: assumptions, sources, sample sizes and excluded intervals.

Growth and drawdown use each ETF's full observed price path. For shared
volatility and correlations, returns must match on both starting and ending
dates. For example, a two-session return spanning a missing price is not paired
with a one-session return. Adding ETFs can change this shared sample and thus
the reported volatility. Missing prices can hide larger drawdowns.

Annualized volatility is sample daily standard deviation multiplied by sqrt(252).
The matched `daily_returns.csv` may have gaps: use it for risk estimates, not to
reconstruct full-period growth or a complete portfolio backtest. A constant
return series or fewer than two matched observations gives undefined correlation
(`NaN`), not a fabricated zero. Status `ok` means the calculation checks passed;
it does not mean independent provider validation or investment suitability.

## Holdings and taxes

Yahoo automates price data. Its available top-holdings/sector information does
not replace complete BMO holdings or Canadian tax-character records, including
eligible dividends, foreign income, return of capital and noncash distributions.
Those remain separate inputs for Client B's taxable portfolio. The historical
optimizer enforces a 15% observed drawdown cap, an optional annualized volatility cap
and a fixed initial ZMMK allocation. Tax and income constraints remain to be
implemented. Carlyle is deferred and is not included.

## Historical Sharpe optimizer

After installing the updated requirements, run:

```powershell
python step_05_optimize_portfolio.py
```

Edit these assumptions in `settings.py`:

```python
ANNUAL_RISK_FREE_RATE = 0.0384
MAX_ETF_WEIGHT = 1.0
MAX_DRAWDOWN = 0.15
MAX_ANNUAL_VOLATILITY = None  # Set to 0.075 to cap volatility at 7.5%.
CLIENT_PORTFOLIO_VALUE = 6_500_000
ZMMK_RESERVE = 175_000
USE_GLD_PROXY_FOR_ZGLD = True
```

Weights are long-only and total 100%. The optimizer uses average daily excess
returns, not CAGR, and rejects a final historical drawdown above 15%.
The volatility cap is currently disabled with `None`; set it to `0.075` to
restore the 7.5% limit. Risk checks cover the full portfolio, including ZMMK. It reads
full observed price paths rather than compounding the risk sample after gaps
have been removed. It assumes daily rebalancing before client taxes and costs.
The 3.84% cash rate is the user-provided annual assumption, held constant
throughout the study. It is not a historical Canadian cash-rate series.

All seven tickers are included over the approved shorter period: ZLB, ZSP, ZLU,
ZGLD, ZST, ZNQ and ZMMK. ZMMK is fixed at $175,000 / $6,500,000 = 2.6923%; the
remaining $6,325,000 is optimized. This fixes its starting dollar allocation and
portfolio weight. Under daily rebalancing its dollar balance subsequently
changes with total portfolio wealth; it is not a permanent $175,000 floor.
ZGLD uses the user-approved
GLD proxy in CAD before its first observed price, with a labelled, scaled splice
into actual ZGLD prices. See `gold_proxy.py` and the recorded source metadata.
No other fund receives an invented or substituted history. Any data error in a
required eligible fund stops optimization rather than silently excluding it.

New results include `portfolio_weights.csv`, `portfolio_summary.csv`,
`portfolio_path.csv`, and `optimizer_notes.json`. If the solver cannot find a
portfolio satisfying the constraints, it reports that result and saves no
approved weights. Equal allocation of the remainder and a low-drawdown search
are diagnostics only. `client_allocation` shows amounts for the $6.5 million
client portfolio; `initial_allocation` retains the separate $10,000 study scale.

The fitted historical drawdown is not a guarantee of future or intraday losses.
Read [Lesson 5](LESSON_05.md) for the formula, proxy assumptions and tests.

## References

- [yfinance](https://github.com/ranaroussi/yfinance) is an unofficial,
  unaffiliated Yahoo Finance interface. Yahoo's usage terms apply.
- [Download options](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)
  explain the exclusive end date and adjustment settings.
- [Yahoo adjusted-close explanation](https://help.yahoo.com/kb/SLN28256.html).
- [Available fund information](https://ranaroussi.github.io/yfinance/reference/api/yfinance.scrapers.funds.FundsData.html).
