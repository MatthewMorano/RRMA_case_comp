"""Maximize historical Sharpe while enforcing a historical drawdown limit."""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import settings
from step_03_batch_analysis import analyze_batch, save_results
from step_04_correlation import calculate_correlations


PROJECT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_DIR / "results"
TRADING_DAYS_PER_YEAR = 252


def calculate_drawdowns(weights, returns):
    """Build wealth starting at 1, including the initial purchase in the peak."""
    wealth = np.r_[1.0, np.cumprod(1 + returns @ weights)]
    peaks = np.maximum.accumulate(wealth)
    return wealth, wealth / peaks - 1


def portfolio_statistics(weights, returns, daily_cash_rate, drawdown_limit):
    """Calculate sample Sharpe and actual compounded historical drawdown."""
    portfolio_returns = returns @ weights
    daily_mean = portfolio_returns.mean()
    daily_volatility = portfolio_returns.std(ddof=1)
    _, drawdowns = calculate_drawdowns(weights, returns)
    maximum_drawdown = float(drawdowns.min())
    return {
        "annualized_mean_return": float(daily_mean * TRADING_DAYS_PER_YEAR),
        "annualized_volatility": float(daily_volatility * np.sqrt(252)),
        "historical_sharpe": float(
            (daily_mean - daily_cash_rate) / daily_volatility * np.sqrt(252)
        ),
        "maximum_drawdown": maximum_drawdown,
        "meets_drawdown_limit": bool(-maximum_drawdown <= drawdown_limit),
    }


def search_weights(objective, starts, max_weight, extra_constraints=()):
    """Try several starting allocations; keep only converged, valid weights."""
    candidates = []
    attempts = []
    number_of_etfs = len(starts[0])
    constraints = [
        {"type": "eq", "fun": lambda weights: weights.sum() - 1},
        *extra_constraints,
    ]
    for start in starts:
        result = minimize(
            objective, start, method="SLSQP",
            bounds=[(0, max_weight)] * number_of_etfs,
            constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-11},
        )
        valid = (
            np.isfinite(result.x).all()
            and abs(result.x.sum() - 1) <= 1e-8
            and (result.x >= -1e-8).all()
            and (result.x <= max_weight + 1e-8).all()
        )
        attempts.append({"success": bool(result.success),
                         "valid_weights": bool(valid),
                         "message": str(result.message)})
        if result.success and valid and np.isfinite(result.fun):
            clean = np.clip(result.x, 0, max_weight)
            clean = clean / clean.sum()
            if (clean <= max_weight + 1e-8).all():
                candidates.append(clean)
    return candidates, attempts


def optimize_sharpe(daily_returns, annual_cash_rate=0.0,
                    max_weight=1.0, max_drawdown=0.15):
    """Optimize a complete common return path; never approve a cap breach."""
    if daily_returns.shape[1] == 0 or len(daily_returns) < 2:
        raise ValueError("The optimizer needs ETFs and at least two returns.")
    calculate_correlations(daily_returns)  # Reuse date and finite-value checks.
    if (daily_returns <= -1).any().any():
        raise ValueError("ETF returns must be above -100%.")
    if not np.isfinite(annual_cash_rate) or annual_cash_rate <= -1:
        raise ValueError("The annual risk-free rate must be finite and above -100%.")
    if not np.isfinite(max_weight) or not 0 < max_weight <= 1:
        raise ValueError("MAX_ETF_WEIGHT must be above zero and at most 1.0.")
    if not np.isfinite(max_drawdown) or not 0 < max_drawdown < 1:
        raise ValueError("MAX_DRAWDOWN must be between 0 and 1, such as 0.15.")

    number_of_etfs = daily_returns.shape[1]
    if number_of_etfs * max_weight < 1 - 1e-12:
        raise ValueError("The weight cap is too low for weights to total 100%.")
    returns = daily_returns.to_numpy()
    covariance = daily_returns.cov().to_numpy()
    eigenvalues = np.linalg.eigvalsh(covariance)
    if eigenvalues[-1] <= 0 or eigenvalues[0] <= eigenvalues[-1] * 1e-12:
        raise ValueError("Constant or dependent histories: covariance is singular.")
    mean_returns = returns.mean(axis=0)
    daily_cash_rate = (1 + annual_cash_rate) ** (1 / 252) - 1
    equal = np.full(number_of_etfs, 1 / number_of_etfs)

    def drawdown_loss(weights):
        return -float(calculate_drawdowns(weights, returns)[1].min())

    def negative_sharpe(weights):
        volatility = np.sqrt(weights @ covariance @ weights)
        return -float((weights @ mean_returns - daily_cash_rate)
                      / volatility * np.sqrt(252))

    starts = [equal]
    if number_of_etfs > 1:
        for index in range(number_of_etfs):
            tilted = np.full(number_of_etfs,
                             (1 - max_weight) / (number_of_etfs - 1))
            tilted[index] = max_weight
            starts.append(tilted)
    fixed = number_of_etfs == 1 or abs(max_weight - 1 / number_of_etfs) <= 1e-12

    # First look for allocations that can satisfy the drawdown constraint.
    low_drawdown, feasibility_attempts = ([], []) if fixed else search_weights(
        drawdown_loss, starts, max_weight
    )
    diagnostic = min(starts + low_drawdown, key=drawdown_loss)
    feasible_starts = [w for w in starts + low_drawdown
                       if drawdown_loss(w) <= max_drawdown]
    optimized = None
    sharpe_attempts = []
    status = "no_feasible_portfolio_found"
    if feasible_starts:
        if fixed:
            optimized = equal
        else:
            # A small safety margin keeps numerical boundary errors below the cap.
            drawdown_constraint = {
                "type": "ineq",
                "fun": lambda weights: max_drawdown - 1e-8 - drawdown_loss(weights),
            }
            candidates, sharpe_attempts = search_weights(
                negative_sharpe, feasible_starts, max_weight, [drawdown_constraint]
            )
            candidates = [w for w in candidates if drawdown_loss(w) <= max_drawdown]
            if candidates:
                optimized = min(candidates + feasible_starts, key=negative_sharpe)
        status = "ok" if optimized is not None else "sharpe_search_failed"

    weights = pd.DataFrame(columns=["ticker", "weight"])
    portfolios = [("equal_weight", equal), ("lowest_drawdown_found", diagnostic)]
    if optimized is not None:
        # This final check applies to the exact weights that will be saved.
        if drawdown_loss(optimized) > max_drawdown:
            raise RuntimeError("The final portfolio breaches the drawdown cap.")
        weights = pd.DataFrame({"ticker": daily_returns.columns,
                                "weight": optimized})
        portfolios.insert(0, ("optimized", optimized))
    summary = pd.DataFrame([
        {"portfolio": name, **portfolio_statistics(
            w, returns, daily_cash_rate, max_drawdown
        )} for name, w in portfolios
    ])
    details = {
        "status": status,
        "annual_risk_free_rate": annual_cash_rate,
        "daily_risk_free_rate": daily_cash_rate,
        "max_etf_weight": max_weight,
        "max_drawdown_limit": max_drawdown,
        "lowest_drawdown_found": drawdown_loss(diagnostic),
        "diagnostic_weights_not_a_recommendation": dict(zip(
            daily_returns.columns, diagnostic.tolist()
        )),
        "feasibility_attempts": feasibility_attempts,
        "sharpe_attempts": sharpe_attempts,
        "solver_limit": (
            "numerical searches, not proof of global optimality or infeasibility"
        ),
    }
    return weights, summary, details


def load_portfolio_returns(comparison, sources):
    """Read full saved price paths; never compound a sample with deleted rows."""
    series = {}
    reference_dates = None
    for row in comparison.itertuples():
        path = sources[row.ticker]["cache_file"]
        prices = pd.read_csv(path, parse_dates=["date"]).set_index("date")
        prices = prices.loc[row.actual_start:row.actual_end, "adjusted_close"]
        if reference_dates is None:
            reference_dates = prices.index
        if not prices.index.equals(reference_dates):
            raise ValueError(
                "Price calendars differ. Reconcile them before imposing drawdown; "
                "do not use the risk sample with excluded intervals as a backtest."
            )
        series[row.ticker] = prices
    prices = pd.DataFrame(series)
    if prices.isna().any().any():
        raise ValueError("Missing prices in the full portfolio history.")
    returns = prices.pct_change(fill_method=None).iloc[1:]
    return returns, prices.index[0]


def main():
    comparison, daily_returns, notes = analyze_batch()
    print(comparison[["ticker", "status", "message"]].to_string(index=False))
    allowed = ["ok", "ok_with_calendar_gaps", "ok_with_proxy"]
    exclusions = ["insufficient_history"]
    errors = comparison.loc[~comparison["status"].isin(allowed + exclusions)]
    if not errors.empty:
        raise ValueError(
            "Resolve data errors before optimizing; no assets were silently dropped."
        )
    eligible = comparison.loc[comparison["status"].isin(allowed)]
    if eligible.empty:
        raise ValueError("No funds cover the required study period.")
    portfolio_returns, initial_date = load_portfolio_returns(
        eligible, notes["data_sources"]
    )
    weights, summary, details = optimize_sharpe(
        portfolio_returns, settings.ANNUAL_RISK_FREE_RATE,
        settings.MAX_ETF_WEIGHT, settings.MAX_DRAWDOWN,
    )
    weights["initial_allocation"] = weights["weight"] * settings.INITIAL_INVESTMENT
    details.update({
        "calculated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_observations": len(portfolio_returns),
        "actual_start": str(initial_date.date()),
        "actual_end": str(portfolio_returns.index[-1].date()),
        "included_tickers": list(portfolio_returns.columns),
        "excluded_tickers": comparison.loc[
            comparison["status"].isin(exclusions), ["ticker", "status", "message"]
        ].to_dict("records"),
        "sharpe_formula": "sqrt(252) * mean(daily excess return) / std(ddof=1)",
        "return_model": "constant weights, rebalanced daily, before taxes and costs",
        "evaluation": "optimized and evaluated on the same historical sample",
        "drawdown_scope": "historical observed daily closes; no future guarantee",
        "remaining_client_constraints": "liquidity, tax and income requirements",
    })
    notes["optimizer"] = details
    save_results(comparison, daily_returns, notes, RESULTS_DIR)
    calculate_correlations(daily_returns).to_csv(RESULTS_DIR / "correlation_matrix.csv")
    weights.to_csv(RESULTS_DIR / "portfolio_weights.csv", index=False)
    summary.to_csv(RESULTS_DIR / "portfolio_summary.csv", index=False)
    with (RESULTS_DIR / "optimizer_notes.json").open("w", encoding="utf-8") as file:
        json.dump(details, file, indent=2)

    path = pd.DataFrame(columns=["date", "investment_value", "drawdown"])
    if not weights.empty:
        wealth, drawdowns = calculate_drawdowns(
            weights["weight"].to_numpy(), portfolio_returns.to_numpy()
        )
        path = pd.DataFrame({
            "date": pd.DatetimeIndex([initial_date]).append(portfolio_returns.index),
            "investment_value": wealth * settings.INITIAL_INVESTMENT,
            "drawdown": drawdowns,
        })
    path.to_csv(RESULTS_DIR / "portfolio_path.csv", index=False)
    print(f"\nHistorical drawdown limit: {settings.MAX_DRAWDOWN:.2%}")
    print(f"Assumed annual risk-free rate: {settings.ANNUAL_RISK_FREE_RATE:.2%}")
    print("\nSample comparison (mean returns are arithmetic, not CAGR):")
    print(summary.to_string(index=False, formatters={
        "annualized_mean_return": "{:.2%}".format,
        "annualized_volatility": "{:.2%}".format,
        "historical_sharpe": "{:.3f}".format,
        "maximum_drawdown": "{:.2%}".format,
    }))
    if weights.empty:
        print("\nNo weights approved. See optimizer_notes.json for search diagnostics.")
        raise SystemExit(1)
    print("\nWeights passing the historical drawdown check:")
    print(weights.to_string(index=False, formatters={
        "weight": "{:.2%}".format, "initial_allocation": "{:,.2f}".format,
    }))
    print("\nIn-sample result; the historical limit is not a future loss guarantee.")
    print(f"Saved results in: {RESULTS_DIR}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, TypeError, OSError) as error:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        # Invalidate old allocations so a failed new run cannot leave approved weights.
        for filename, columns in [
            ("portfolio_weights.csv", ["ticker", "weight", "initial_allocation"]),
            ("portfolio_path.csv", ["date", "investment_value", "drawdown"]),
            ("portfolio_summary.csv", ["portfolio", "historical_sharpe"]),
        ]:
            pd.DataFrame(columns=columns).to_csv(RESULTS_DIR / filename, index=False)
        with (RESULTS_DIR / "optimizer_notes.json").open("w", encoding="utf-8") as file:
            json.dump({"status": "failed", "message": str(error)}, file, indent=2)
        raise SystemExit(f"Optimizer stopped: {error} No weights approved.")
