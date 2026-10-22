"""Maximize historical Sharpe with liquidity, volatility and drawdown limits."""

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


def portfolio_statistics(weights, returns, daily_cash_rate, drawdown_limit,
                         volatility_limit=None):
    """Calculate sample Sharpe and actual compounded historical drawdown."""
    portfolio_returns = returns @ weights
    daily_mean = portfolio_returns.mean()
    daily_volatility = portfolio_returns.std(ddof=1)
    _, drawdowns = calculate_drawdowns(weights, returns)
    maximum_drawdown = float(drawdowns.min())
    volatility = float(daily_volatility * np.sqrt(252))
    meets_drawdown = bool(-maximum_drawdown <= drawdown_limit)
    meets_volatility = volatility_limit is None or volatility <= volatility_limit
    return {
        "annualized_mean_return": float(daily_mean * TRADING_DAYS_PER_YEAR),
        "annualized_volatility": volatility,
        "historical_sharpe": float(
            (daily_mean - daily_cash_rate) / daily_volatility * np.sqrt(252)
        ),
        "maximum_drawdown": maximum_drawdown,
        "meets_drawdown_limit": meets_drawdown,
        "meets_volatility_limit": bool(meets_volatility),
        "meets_all_risk_limits": bool(meets_drawdown and meets_volatility),
    }


def search_weights(objective, starts, bounds, extra_constraints=()):
    """Try several starting allocations; keep only converged, valid weights."""
    candidates = []
    attempts = []
    lower, upper = np.array(bounds).T
    free = upper > lower
    constraints = [
        {"type": "eq", "fun": lambda weights: weights.sum() - 1},
        *extra_constraints,
    ]
    for start in starts:
        result = minimize(
            objective, start, method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-11},
        )
        valid = (
            np.isfinite(result.x).all()
            and abs(result.x.sum() - 1) <= 1e-8
            and (result.x >= lower - 1e-8).all()
            and (result.x <= upper + 1e-8).all()
        )
        attempts.append({"success": bool(result.success),
                         "valid_weights": bool(valid),
                         "message": str(result.message)})
        if result.success and valid and np.isfinite(result.fun):
            clean = np.clip(result.x, lower, upper)
            # Correct roundoff in a free position, preserving exact fixed weights.
            residual = 1 - clean.sum()
            room = upper - clean if residual >= 0 else clean - lower
            index = np.argmax(np.where(free, room, -1))
            clean[index] += residual
            if ((clean >= lower).all() and (clean <= upper).all()):
                candidates.append(clean)
    return candidates, attempts


def optimize_sharpe(daily_returns, annual_cash_rate=0.0,
                    max_weight=1.0, max_drawdown=0.15,
                    max_volatility=None, fixed_weights=None):
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
    if max_volatility is not None and (
        not np.isfinite(max_volatility) or max_volatility <= 0
    ):
        raise ValueError("MAX_ANNUAL_VOLATILITY must be positive, such as 0.075.")

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
    fixed_weights = dict(fixed_weights or {})
    if not set(fixed_weights).issubset(daily_returns.columns):
        raise ValueError("A required fixed holding is missing from the return history.")
    if any(not np.isfinite(w) or w < 0 or w > max_weight
           for w in fixed_weights.values()):
        raise ValueError("Fixed weights must be finite and within the ETF weight cap.")
    equal = np.array([fixed_weights.get(ticker, 0.0)
                      for ticker in daily_returns.columns])
    free = np.array([ticker not in fixed_weights for ticker in daily_returns.columns])
    remaining = 1 - equal.sum()
    if remaining < -1e-12 or remaining > free.sum() * max_weight + 1e-12:
        raise ValueError("Fixed holdings and weight caps cannot total 100%.")
    if not free.any() and abs(remaining) > 1e-12:
        raise ValueError("Fully fixed weights must total 100%.")
    if free.any():
        equal[free] = max(0.0, remaining) / free.sum()
    bounds = [(0, max_weight) if is_free else (weight, weight)
              for weight, is_free in zip(equal, free)]

    def drawdown_loss(weights):
        return -float(calculate_drawdowns(weights, returns)[1].min())

    def negative_sharpe(weights):
        volatility = np.sqrt(weights @ covariance @ weights)
        return -float((weights @ mean_returns - daily_cash_rate)
                      / volatility * np.sqrt(252))

    def annual_volatility(weights):
        return float(np.sqrt(weights @ covariance @ weights * 252))

    def passes_risk_limits(weights):
        return (drawdown_loss(weights) <= max_drawdown
                and (max_volatility is None
                     or annual_volatility(weights) <= max_volatility))

    def risk_ratio(weights):
        # A value at most one satisfies both constraints simultaneously.
        ratios = [drawdown_loss(weights) / max_drawdown]
        if max_volatility is not None:
            ratios.append(annual_volatility(weights) / max_volatility)
        return max(ratios)

    starts = [equal]
    if free.sum() > 1:
        for index in np.flatnonzero(free):
            tilted = equal.copy()
            tilted[free] = (remaining - min(max_weight, remaining)) / (free.sum() - 1)
            tilted[index] = min(max_weight, remaining)
            starts.append(tilted)
    fixed = (free.sum() <= 1 or remaining <= 1e-12
             or abs(remaining - free.sum() * max_weight) <= 1e-12)

    # First look for allocations that can satisfy the drawdown constraint.
    low_drawdown, feasibility_attempts = ([], []) if fixed else search_weights(
        drawdown_loss, starts, bounds
    )
    diagnostic = min(starts + low_drawdown, key=drawdown_loss)
    joint_candidates, joint_attempts = ([], []) if fixed else search_weights(
        risk_ratio, starts + [diagnostic], bounds
    )
    feasible_starts = [w for w in starts + low_drawdown + joint_candidates
                       if passes_risk_limits(w)]
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
            constraints = [drawdown_constraint]
            if max_volatility is not None:
                constraints.append({
                    "type": "ineq",
                    "fun": lambda w: max_volatility - 1e-9 - annual_volatility(w),
                })
            candidates, sharpe_attempts = search_weights(
                negative_sharpe, feasible_starts, bounds, constraints
            )
            candidates = [w for w in candidates if passes_risk_limits(w)]
            if candidates:
                optimized = min(candidates + feasible_starts, key=negative_sharpe)
        status = "ok" if optimized is not None else "sharpe_search_failed"

    weights = pd.DataFrame(columns=["ticker", "weight"])
    benchmark = "reserve_plus_equal_weight" if fixed_weights else "equal_weight"
    portfolios = [(benchmark, equal), ("lowest_drawdown_found", diagnostic)]
    if optimized is not None:
        # This final check applies to the exact weights that will be saved.
        if (not np.isfinite(optimized).all() or abs(optimized.sum() - 1) > 1e-12
                or (optimized < 0).any() or (optimized > max_weight).any()):
            raise RuntimeError("The final portfolio has invalid weights.")
        if not passes_risk_limits(optimized):
            raise RuntimeError("The final portfolio breaches a risk cap.")
        for ticker, target in fixed_weights.items():
            index = daily_returns.columns.get_loc(ticker)
            if optimized[index] != target:
                raise RuntimeError("The final portfolio changed a fixed holding.")
        weights = pd.DataFrame({"ticker": daily_returns.columns,
                                "weight": optimized})
        portfolios.insert(0, ("optimized", optimized))
    summary = pd.DataFrame([
        {"portfolio": name, **portfolio_statistics(
            w, returns, daily_cash_rate, max_drawdown, max_volatility
        )} for name, w in portfolios
    ])
    details = {
        "status": status,
        "annual_risk_free_rate": annual_cash_rate,
        "daily_risk_free_rate": daily_cash_rate,
        "max_etf_weight": max_weight,
        "max_drawdown_limit": max_drawdown,
        "max_annual_volatility": max_volatility,
        "fixed_weights": fixed_weights,
        "lowest_drawdown_found": drawdown_loss(diagnostic),
        "diagnostic_weights_not_a_recommendation": dict(zip(
            daily_returns.columns, diagnostic.tolist()
        )),
        "feasibility_attempts": feasibility_attempts,
        "joint_risk_feasibility_attempts": joint_attempts,
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
    capital = settings.CLIENT_PORTFOLIO_VALUE
    reserve = settings.ZMMK_RESERVE
    if (not np.isfinite(capital) or capital <= 0 or not np.isfinite(reserve)
            or not 0 < reserve <= capital):
        raise ValueError("Choose positive client capital and a ZMMK reserve within it.")
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
    if "ZMMK" not in eligible["ticker"].values:
        raise ValueError("ZMMK is required for liquidity and must cover the study period.")
    portfolio_returns, initial_date = load_portfolio_returns(
        eligible, notes["data_sources"]
    )
    weights, summary, details = optimize_sharpe(
        portfolio_returns, settings.ANNUAL_RISK_FREE_RATE,
        settings.MAX_ETF_WEIGHT, settings.MAX_DRAWDOWN,
        max_volatility=settings.MAX_ANNUAL_VOLATILITY,
        fixed_weights={"ZMMK": reserve / capital},
    )
    weights["initial_allocation"] = weights["weight"] * settings.INITIAL_INVESTMENT
    weights["client_allocation"] = weights["weight"] * capital
    if not weights.empty:
        reserve_amount = weights.loc[weights["ticker"] == "ZMMK", "client_allocation"].iloc[0]
        if abs(reserve_amount - reserve) > 1e-6:
            raise RuntimeError("The ZMMK allocation does not match the required reserve.")
    details.update({
        "calculated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_observations": len(portfolio_returns),
        "actual_start": str(initial_date.date()),
        "actual_end": str(portfolio_returns.index[-1].date()),
        "target_lookback_years": settings.LOOKBACK_YEARS,
        "start_date_override": settings.START_DATE,
        "period_choice": "User approved actual ZMMK history; slightly under five years.",
        "client_portfolio_value": capital,
        "zmmk_reserve_amount": reserve,
        "remaining_capital": capital - reserve,
        "reserve_model": (
            "ZMMK has a fixed starting dollar allocation and constant portfolio weight; "
            "daily rebalancing means its dollar value subsequently changes with wealth"
        ),
        "included_tickers": list(portfolio_returns.columns),
        "excluded_tickers": comparison.loc[
            comparison["status"].isin(exclusions), ["ticker", "status", "message"]
        ].to_dict("records"),
        "sharpe_formula": "sqrt(252) * mean(daily excess return) / std(ddof=1)",
        "return_model": "constant weights, rebalanced daily, before taxes and costs",
        "evaluation": "optimized and evaluated on the same historical sample",
        "drawdown_scope": "historical observed daily closes; no future guarantee",
        "remaining_client_constraints": "tax and income requirements; liquidity weight fixed",
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
            "client_portfolio_value": wealth * capital,
            "zmmk_value": wealth * reserve,
            "drawdown": drawdowns,
        })
    path.to_csv(RESULTS_DIR / "portfolio_path.csv", index=False)
    print(f"\nHistorical drawdown limit: {settings.MAX_DRAWDOWN:.2%}")
    print(f"Annualized volatility limit: {settings.MAX_ANNUAL_VOLATILITY:.2%}")
    print(f"Period: {initial_date.date()} to {portfolio_returns.index[-1].date()}")
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
    print("\nWeights passing both historical risk checks and the fixed reserve:")
    print(weights.to_string(index=False, formatters={
        "weight": "{:.2%}".format, "initial_allocation": "{:,.2f}".format,
        "client_allocation": "{:,.2f}".format,
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
            ("portfolio_weights.csv", ["ticker", "weight", "initial_allocation", "client_allocation"]),
            ("portfolio_path.csv", ["date", "investment_value", "client_portfolio_value", "zmmk_value", "drawdown"]),
            ("portfolio_summary.csv", ["portfolio", "historical_sharpe"]),
        ]:
            pd.DataFrame(columns=columns).to_csv(RESULTS_DIR / filename, index=False)
        with (RESULTS_DIR / "optimizer_notes.json").open("w", encoding="utf-8") as file:
            json.dump({"status": "failed", "message": str(error)}, file, indent=2)
        raise SystemExit(f"Optimizer stopped: {error} No weights approved.")
