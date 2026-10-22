"""Independent numerical checks. Run: python -m unittest test_optimizer.py"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from gold_proxy import align_proxy_quotes, extend_gold_history
from step_01_load_prices import load_prices
from step_05_optimize_portfolio import calculate_drawdowns, optimize_sharpe


class OptimizerTests(unittest.TestCase):
    def frame(self, values):
        dates = pd.bdate_range("2020-01-01", periods=len(values))
        return pd.DataFrame(values, index=dates)

    def test_initial_purchase_counts_as_a_peak(self):
        wealth, drawdowns = calculate_drawdowns(np.array([1.0]),
                                                np.array([[-0.20], [0.10]]))
        np.testing.assert_allclose(wealth, [1, .8, .88])
        self.assertAlmostEqual(drawdowns.min(), -.20)

    def test_unconstrained_tangency_and_risk_free_conversion(self):
        shocks = np.tile([[1, 1], [1, -1], [-1, 1], [-1, -1]], (20, 1))
        data = self.frame(shocks * [.01, .008] + [.001, .0006])
        cash = .04
        weights, summary, _ = optimize_sharpe(data, cash, max_drawdown=.99)
        daily_cash = (1 + cash) ** (1 / 252) - 1
        tangent = np.linalg.solve(data.cov(), data.mean() - daily_cash)
        tangent /= tangent.sum()
        np.testing.assert_allclose(weights["weight"], tangent, atol=1e-5)
        observed = data.to_numpy() @ weights["weight"].to_numpy()
        expected = ((observed - daily_cash).mean()
                    / (observed - daily_cash).std(ddof=1) * np.sqrt(252))
        self.assertAlmostEqual(summary.iloc[0]["historical_sharpe"], expected, places=9)

    def test_drawdown_cap_matches_an_independent_weight_grid(self):
        day = np.arange(200)
        risky = .01 + .002 * np.sin(day)
        defensive = .00005 + .003 * np.cos(day)
        risky[0], defensive[0] = -.30, 0
        data = self.frame(np.column_stack([risky, defensive]))
        weights, summary, details = optimize_sharpe(data, max_drawdown=.15)
        self.assertEqual(details["status"], "ok")
        w = weights["weight"].to_numpy()
        self.assertAlmostEqual(w.sum(), 1)
        self.assertTrue((w >= 0).all())
        self.assertLessEqual(w[0], .5 + 1e-9)
        self.assertTrue(summary.iloc[0]["meets_drawdown_limit"])
        self.assertGreaterEqual(summary.iloc[0]["maximum_drawdown"], -.15)
        grid_best = -np.inf
        for risky_weight in np.linspace(0, 1, 1001):
            daily = risky_weight * risky + (1 - risky_weight) * defensive
            wealth = np.r_[1., (1 + daily).cumprod()]
            drawdown = wealth / np.maximum.accumulate(wealth) - 1
            if drawdown.min() >= -.15:
                sharpe = daily.mean() / daily.std(ddof=1) * np.sqrt(252)
                grid_best = max(grid_best, sharpe)
        self.assertGreaterEqual(summary.iloc[0]["historical_sharpe"], grid_best - 1e-5)

    def test_known_impossible_crash_approves_no_weights(self):
        data = self.frame([[-.30, -.28], [.01, .015], [.02, -.01], [.015, .02]])
        weights, summary, details = optimize_sharpe(data, max_drawdown=.15)
        self.assertTrue(weights.empty)
        self.assertEqual(details["status"], "no_feasible_portfolio_found")
        self.assertGreaterEqual(details["lowest_drawdown_found"], .28 - 1e-9)
        self.assertFalse(summary["meets_drawdown_limit"].any())

    def test_weight_cap_and_single_asset(self):
        data = self.frame([[.01, .005], [-.002, .003], [.02, -.001], [.003, .006]])
        weights, _, _ = optimize_sharpe(data, max_weight=.6, max_drawdown=.99)
        self.assertTrue((weights["weight"] <= .6 + 1e-8).all())
        one, _, details = optimize_sharpe(data.iloc[:, :1], max_drawdown=.99)
        self.assertEqual(one.iloc[0]["weight"], 1)
        self.assertEqual(details["status"], "ok")
        with self.assertRaises(ValueError):
            optimize_sharpe(data, max_weight=.4)

    def test_invalid_samples_are_rejected(self):
        data = self.frame([[.01, .005], [-.002, .003], [.02, -.001]])
        missing = data.copy()
        missing.iloc[0, 0] = np.nan
        with self.assertRaises(ValueError):
            optimize_sharpe(missing)
        identical = pd.concat([data.iloc[:, 0], data.iloc[:, 0]], axis=1)
        identical.columns = ["A", "B"]
        with self.assertRaises(ValueError):
            optimize_sharpe(identical)


class GoldProxyTests(unittest.TestCase):
    def test_missing_auxiliary_quotes_are_retained_raw_and_omitted_for_alignment(self):
        dates = pd.date_range("2024-01-01", periods=3, tz="Europe/London")
        raw = pd.DataFrame({"Close": [1.3, np.nan, 1.4],
                            "Adj Close": [1.3, np.nan, 1.4]}, index=dates)
        with TemporaryDirectory() as temporary, \
             patch("step_01_load_prices.yf.Ticker") as constructor, \
             patch("step_01_load_prices.yf.set_tz_cache_location"):
            fund = constructor.return_value
            fund.history.return_value = raw
            fund.get_history_metadata.return_value = {
                "symbol": "CAD=X", "currency": "CAD", "instrumentType": "CURRENCY"
            }
            quotes = load_prices(
                "CAD=X", "CAD", "2024-01-01", "2024-01-03", temporary,
                instrument_type="CURRENCY", allow_missing_quotes=True,
            )
            self.assertEqual(len(quotes), 2)
            self.assertEqual(quotes.attrs["source"]["unavailable_quote_dates"],
                             ["2024-01-02"])
            cached = pd.read_csv(quotes.attrs["source"]["cache_file"])
            self.assertEqual(cached["adjusted_close"].isna().sum(), 1)
            with self.assertRaises(ValueError):
                load_prices("CAD=X", "CAD", "2024-01-01", "2024-01-03", temporary,
                            instrument_type="CURRENCY")

    def test_currency_conversion_splice_and_previous_quote_policy(self):
        dates = pd.date_range("2024-01-01", periods=5)
        actual = pd.DataFrame({"date": dates[3:], "adjusted_close": [20., 22.]})
        actual.attrs["source"] = {"ticker": "ZGLD.TO", "cache_file": "actual.csv"}
        gld = pd.DataFrame({"date": dates[[0, 1, 3]],
                            "adjusted_close": [100., 110., 120.]})
        fx = pd.DataFrame({"date": dates[:4], "close": [1., 1.1, 1.2, 1.3]})
        gld.attrs["source"] = {"ticker": "GLD", "cache_file": "gld.csv"}
        fx.attrs["source"] = {"ticker": "CAD=X", "cache_file": "fx.csv"}
        calendar = pd.DataFrame({"date": dates})
        def fetch(symbol, *args, **kwargs):
            return {"ZLB.TO": calendar, "GLD": gld, "CAD=X": fx}[symbol]
        with TemporaryDirectory() as temporary, \
             patch("gold_proxy.load_prices", side_effect=fetch):
            combined = extend_gold_history(actual, "CAD", dates[0], dates[-1],
                                          Path(temporary) / "data/yahoo", False)
            returns = combined["adjusted_close"].pct_change(fill_method=None)
            self.assertAlmostEqual(returns.iloc[1], .21)  # 10% gold + 10% CAD/USD.
            self.assertAlmostEqual(returns.iloc[2], 132 / 121 - 1)
            self.assertAlmostEqual(returns.iloc[3], 156 / 132 - 1)
            self.assertAlmostEqual(returns.iloc[4], .10)  # Actual ZGLD after splice.
            self.assertEqual(combined.loc[2, "gld_usd_quote_date"], dates[1])
            self.assertEqual(combined.loc[3, "adjusted_close"], 20)
            self.assertTrue(Path(combined.attrs["source"]["cache_file"]).is_file())

    def test_stale_proxy_quotes_are_rejected(self):
        quotes = pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "price": [100.]})
        with self.assertRaises(ValueError):
            align_proxy_quotes(pd.to_datetime(["2024-01-08"]), quotes, "price", "test")

    def test_mixed_pandas_date_units_are_supported(self):
        dates = pd.date_range("2024-01-01", periods=2).astype("datetime64[ns]")
        quotes = pd.DataFrame({"date": dates.astype("datetime64[us]"),
                               "price": [100., 101.]})
        aligned = align_proxy_quotes(dates, quotes, "price", "test")
        self.assertEqual(aligned["test"].tolist(), [100., 101.])


if __name__ == "__main__":
    unittest.main()
