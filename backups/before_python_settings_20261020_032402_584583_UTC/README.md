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

## The four steps

| File | What it does |
| --- | --- |
| `step_01_load_prices.py` | Downloads, checks and saves Yahoo ETF prices |
| `step_02_total_returns.py` | Calculates returns and performance |
| `step_03_batch_analysis.py` | Compares the ETFs in `etfs.json` |
| `step_04_correlation.py` | Runs the comparison and calculates correlations |

You can also run steps 1, 2 or 3 separately. Steps 1 and 2 demonstrate the first
enabled ETF in the list; steps 3 and 4 process all eligible enabled ETFs.
The old `step_01_load_nav.py` and BMO files are retained for reference and are
not used by this Yahoo workflow. Earlier LESSON files describe that NAV version.

## Choose the ETFs and period

Edit `etfs.json`. The analysis settings are:

```json
"end_date": "2026-09-30",
"lookback_years": 10,
"initial_investment": 10000,
"comparison_currency": "CAD",
"asset_class_filter": "Equity",
"calendar_reference_ticker": "ZLB",
"refresh_yahoo_data": false
```

The start date is the end date minus the lookback years. Our current dates
are September 30, 2016 through September 30, 2026.

An ETF entry now uses `yahoo_ticker` instead of `nav_file`:

```json
{
  "ticker": "ZSP",
  "fund_name": "BMO S&P 500 Index ETF",
  "yahoo_ticker": "ZSP.TO",
  "currency": "CAD",
  "asset_class": "Equity",
  "enabled": true,
  "validation_note": "Yahoo adjusted market prices; not yet independently validated."
}
```

Add entries with verified Yahoo symbols to expand the comparison. This is a list
you control; it does not automatically discover every BMO ETF. Set `enabled`
to `false` to exclude an ETF. All included ETFs must use the comparison currency;
this version does not convert currencies. CAD trading currency alone does not
mean that the underlying investments have no currency exposure.

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

With `refresh_yahoo_data: false`, an existing download is reused, so you can run
calculations offline. Set it to `true` for one run to fetch new data, then change
it back to `false`. Refreshing creates a new snapshot and preserves older ones.
Yahoo may revise adjusted history; save the snapshots used in a team submission.

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
the dates or shorten the 10-year study. `available_start` and `available_end`
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
Those remain separate inputs for Client B's taxable portfolio. This analysis
does not yet select an optimal portfolio or enforce the client's risk constraints.

## References

- [yfinance](https://github.com/ranaroussi/yfinance) is an unofficial,
  unaffiliated Yahoo Finance interface. Yahoo's usage terms apply.
- [Download options](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)
  explain the exclusive end date and adjustment settings.
- [Yahoo adjusted-close explanation](https://help.yahoo.com/kb/SLN28256.html).
- [Available fund information](https://ranaroussi.github.io/yfinance/reference/api/yfinance.scrapers.funds.FundsData.html).
