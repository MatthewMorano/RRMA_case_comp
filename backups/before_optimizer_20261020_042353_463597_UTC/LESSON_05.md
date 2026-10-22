# Lesson 5: historical Sharpe with a 15% drawdown limit

Run:

```powershell
python -m pip install -r requirements.txt
python step_05_optimize_portfolio.py
```

## What this step chooses

The optimizer chooses weights for the eligible ETFs to maximize historical
Sharpe. All weights must be nonnegative, must add up to 100%, and must respect
`MAX_ETF_WEIGHT`. The compounded portfolio path must also satisfy
`MAX_DRAWDOWN = 0.15`: no observed historical decline from a previous peak may
exceed 15%.

The portfolio is the full collection of assets passed to this model. This
includes the available equity, gold and short-term bond exposures, not just an
equity sleeve. No minimum allocation to an asset class has been imposed.

## Settings you can change

In `settings.py`:

```python
ANNUAL_RISK_FREE_RATE = 0.0507
MAX_ETF_WEIGHT = 1.0
MAX_DRAWDOWN = 0.15
USE_GLD_PROXY_FOR_ZGLD = True
```

The 5.07% cash rate is the user-provided scenario assumption, held constant
throughout the study. It is not the realized historical cash return series.
Confirm its currency and tenor before treating it as a CAD benchmark.
For example, `0.04` means a constant 4% effective annual rate. The code converts that to a daily rate using
`(1 + annual_rate) ** (1 / 252) - 1` before calculating excess returns. A different
cash-rate assumption can change the optimal weights substantially.

Keep the drawdown limit at 0.15 for Client B. A maximum ETF weight of 1.0 allows
concentration in one fund; 0.5 caps each at 50%. The cap must still permit the
weights to total 100%. No borrowing or short sales are allowed.

## How Sharpe is calculated

For one row of the return table:

```python
portfolio_return = daily_etf_returns @ weights
```

The `@` multiplies each ETF return by its weight and adds the results. For a
60%/40% portfolio, this is `0.6 * return_A + 0.4 * return_B`.

Over the historical sample, Sharpe is:

```python
excess_returns = portfolio_returns - daily_cash_rate
sharpe = excess_returns.mean() / excess_returns.std(ddof=1) * sqrt(252)
```

The optimizer's annualized mean return is the arithmetic daily mean times 252.
It is not CAGR. The reported annualized volatility is daily sample standard
deviation times sqrt(252). This annualization is the conventional approximation;
it does not adjust for serial correlation.

## How the drawdown limit is checked

The code compounds all daily portfolio returns, starting with the original
investment. It tracks the highest value reached and measures each decline from
that peak. The initial investment counts as a peak too: a 20% loss on the very
first day must not disappear from the drawdown calculation.

The model assumes weights are restored at each observed daily close, with
fractional units and no client taxes or trading costs. It is a constant-weight
historical simulation, not a buy-and-hold allocation with drifting weights.

The optimizer reads the full saved price paths. It does not compound the risk
sample after mismatched intervals have been deleted. All eligible assets must
share the same observed price dates; otherwise this step stops for reconciliation.
The resulting limit applies to those observed daily closes, including the gold
proxy assumptions below. Intraday losses and missing common observations may
hide larger drawdowns. A historical 15% limit is not a guarantee about future losses.

## What the numerical search does

1. Tries equal and tilted starting weights to search for a low-drawdown allocation.
2. Searches for higher Sharpe while enforcing the drawdown and weight constraints.
3. Independently recomputes drawdown from the exact final weights before saving.

SciPy's SLSQP solver minimizes functions, so the objective is negative Sharpe.
Several starting points reduce dependence on one initial guess. This remains a
numerical search, not a proof of global optimality. Likewise, “no feasible
portfolio found” is a search result, not a mathematical proof of infeasibility.

An equal-weight portfolio is shown as a comparison. It may itself breach 15% and
is never approved just because it is a benchmark. If the search cannot produce
valid weights, `portfolio_weights.csv` and `portfolio_path.csv` contain no approved
allocation. Diagnostics and status explain the result. A failed run invalidates
old allocation files so they cannot be mistaken for a newly checked portfolio.

## The 10-year rule and shorter ETF histories

The study stays September 30, 2016 through September 30, 2026. ZNQ and ZMMK have
shorter observed histories, so they are flagged `insufficient_history` and left
out of this 10-year optimization. They are still listed in the comparison and
optimizer notes. We do not shorten the period or invent returns for them.

ZGLD has an explicitly approved exception: the user requested GLD as a historical
proxy. ZST has the requested 10-year history. Carlyle is deferred and is not part
of the current model.

## ZGLD's labelled GLD proxy

`gold_proxy.py` builds a synthetic history before ZGLD's first observed price:

1. Download GLD's adjusted USD prices and Yahoo `CAD=X` spot rates (CAD per USD).
2. Use the observed Canadian calendar supplied by ZLB. If a US/FX quote is absent,
   use only the last available quote, at most four calendar days old. Quote dates
   are saved. Future quotes are never used and older/missing quotes cause failure.
   Unavailable quote rows remain in the raw cache and are listed in metadata;
   they are omitted only from the auxiliary as-of quote lookup. Actual ETF
   histories still reject missing prices.
3. Multiply GLD's USD price by CAD per USD to obtain an unhedged CAD price series.
4. Scale that series to meet ZGLD's adjusted price at their overlap date, then
   use actual ZGLD prices from that point onward.

For example, if GLD rises 10% in USD and USD/CAD rises 10%, the CAD return is
`1.10 * 1.10 - 1 = 21%`, not 10% or 20%.

Scaling removes an artificial level jump; it does not change the proxy's
returns. The return ending on the first observed ZGLD date still spans the
proxy splice. Actual ZGLD returns begin after that date. Missing observations
inside ZGLD's actual history are never filled by this procedure.

This is not ZGLD's actual performance before launch. It retains GLD's historical
fees and tracking, without retroactively imposing ZGLD's fee schedule. FX and
ETF closes also differ in timing, and carried proxy quotes can affect daily
volatility/correlations. The source CSV labels every proxy/actual row, preserves
quote dates, and the JSON records the input snapshots and splice date.

ZGLD is flagged `ok_with_proxy`; its synthetic history and the resulting
optimized performance must be labelled as a modelling assumption in the case
submission. If any proxy input fails, optimization stops instead of quietly
dropping gold or switching to USD returns.

## Output files

- `portfolio_weights.csv`: passing weights and initial dollar allocations.
- `portfolio_summary.csv`: Sharpe, arithmetic mean return, volatility and drawdown
  for the optimized, equal-weight and low-drawdown diagnostic portfolios.
- `portfolio_path.csv`: the full simulated value path and drawdown.
- `optimizer_notes.json`: status, constraints, included/excluded funds, assumptions
  and solver messages. Complete data provenance also appears in `run_notes.json`.

The initial dollar allocations use the existing $10,000 study amount. Optimizing
and evaluating on the same history produces an in-sample result, not evidence
of future performance. Client B's tax, income and liquidity needs remain separate
constraints to add before making a client-specific recommendation.

## Verification

```powershell
python -m unittest test_optimizer.py -v
```

The checks include an analytical tangency solution, an independent weight-grid
comparison with a binding drawdown limit, an impossible first-day crash,
currency conversion and the proxy splice.

## Primary references

- [Sharpe's definition](https://web.stanford.edu/~wfsharpe/art/sr/sr.htm).
- [SciPy SLSQP](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-slsqp.html).
- [BMO gold ETF launch](https://newsroom.bmo.com/2024-03-08-BMO-Launches-ETFs-Investing-in-Physical-Gold-Stored-in-Canada).
- [SPDR GLD information](https://www.spdrgoldshares.com/usa/gld/).
