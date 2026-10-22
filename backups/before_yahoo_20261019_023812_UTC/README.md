# ETF analysis: lesson 1

This is the first small piece of a Python analysis for Client B. It loads and
checks ZLB's NAV history. It does not yet measure total returns, recommend ETF
weights, or optimize the portfolio. We will add those pieces as you learn them.

## Run it in VS Code

1. Open this `etf_starter` folder in VS Code.
2. Open a terminal in this folder. Optionally create an isolated environment:
   `python -m venv .venv`, then select `.venv` using **Python: Select Interpreter**.
   Open a new terminal after selecting it.
3. Install the dependency: `python -m pip install -r requirements.txt`.
4. Run: `python step_01_load_nav.py`.

If the terminal's `python` differs from VS Code's selected interpreter, use
**Run Python File in Terminal** with that interpreter selected.

Expected for the supplied file: **3,758 observations**, from **2011-10-21** to
**2026-10-16**, with NAV values in **CAD** and all implemented checks passing.
The last NAV is **60.95997 CAD per unit**. The script only reads the CSV and prints
a preview; it does not modify the data files.

## Understand the code

Read the script from top to bottom:

1. **Settings:** `Path(__file__)` locates the script itself. This makes the data
   path independent of where you launch Python. Change `NAV_FILE` to use another
   BMO export with the same column structure. The function checks for one fund;
   you still need to confirm that you selected the intended ticker's file.
2. **Read:** `pd.read_csv(...)` creates a pandas DataFrame, which is a table.
   `na_values=["-"]` treats BMO's dash markers as missing data. `raw_nav` retains
   all source columns while the function runs.
3. **Select:** `raw_nav[[...]].copy()` creates a separate working table. We use
   NAV per unit rather than the market price column in this lesson.
4. **Convert:** `pd.to_datetime` creates actual dates; `pd.to_numeric` creates
   numbers. Invalid entries cause an error that we can investigate.
5. **Validate:** the function rejects missing required values, duplicate dates,
   nonpositive or infinite NAVs, mixed funds, and an unexpected NAV currency.
   These checks do not establish that every trading day is present, or detect
   splits or other corporate actions; those require further checks before returns.
6. **Sort:** dates go from oldest to newest. `reset_index(drop=True)` gives the
   sorted rows simple labels starting at zero.
7. **Preview:** `head()` shows the first five rows and `tail()` the last five.
   The `if __name__ == "__main__":` block only runs when you execute this file
   directly. Later, another script can import `load_nav` without printing a preview.

Try changing `nav.head()` to `nav.head(10)` and rerunning. You can also place a
VS Code breakpoint inside `load_nav` and inspect `raw_nav` and `nav` as you step
through. No investment assumptions change in this exercise.

## What each supplied file will do

The `data` folder contains unchanged copies of your three ZLB exports.

| Input | Planned use | Important distinction |
| --- | --- | --- |
| Historical NAV CSV | Historical NAV-based performance | NAV changes alone omit cash distributions. The source also has a cash-distribution column that we will reconcile against the separate history. |
| Distribution history CSV | Cash distributions, reinvested amounts, and later tax analysis | The final `Total` row is a summary, not another distribution. This export lacks a detailed tax-character breakdown. |
| Holdings XLSX dated 2026-10-16 | Current sector and issuer concentration, then overlap across ETFs | This is one snapshot; applying it to past dates would introduce information unavailable at those dates. |

Keep the original files intact. The provided holdings file is not needed to run
lesson 1; we will add an Excel-reading dependency when we start that lesson.

## Client B: facts to carry into the later model

Source: your supplied **Topic - Rotman Case Competition Oct 2026.pdf**, Client B
on page 3 and final notes on page 4. All amounts are CAD.

| Item | Case fact |
| --- | --- |
| Age | 52 |
| Investable assets | $6,500,000, non-registered account |
| Salary | $280,000, growing 4% annually until retirement |
| Retirement | In 8 years, at age 60 |
| Risk tolerance | Medium; maximum acceptable portfolio drawdown of 15% |
| Annual liquidity need | $175,000 that the portfolio should be able to support |
| Average tax rate | 38% |
| Direction | Lower volatility as retirement approaches, tax efficiency, and a liquidity buffer |

The 15% limit is a requirement for the overall client portfolio. It is not an
automatic rule that every equity ETF must have historical drawdown below 15%.
Historical results cannot guarantee that a future portfolio stays within that
limit. Eight years is time until retirement, not necessarily the end of the
investment horizon. Salary does not automatically become portfolio contributions.
We will define contributions and withdrawals explicitly before planning cash flows.

## Proposed next lessons

1. **Current lesson:** load and validate one ETF's NAV history.
2. **Total returns:** clean distributions, reconcile cash amounts and ex-dividend
   dates with the NAV export, check corporate actions and NAV treatment, and then
   construct a consistent pre-tax total-return series. Do not fill missing NAVs
   to manufacture observations.
3. **Performance and risk:** calculate compounded growth, volatility, maximum
   drawdown, and rolling results, using a stated measurement period.
4. **Compare equity ETFs:** use a common currency and overlapping date window;
   examine correlations, holdings overlap, and sector concentration. A CAD
   listing alone does not imply that foreign-currency exposure is hedged.
5. **Portfolio construction:** choose an objective and explicit constraints for
   the equity sleeve, then integrate bonds, gold, and the client's liquidity
   needs to assess the overall portfolio. Future-return assumptions and stress
   tests will be separate from historical performance.

### Distribution and tax detail for the next lesson

Your December 2025 distribution row shows **$0.28 cash**, **$2.33 reinvested**,
and **$2.61 total for tax purposes**, per unit. We must not automatically add
$2.61 to NAV when calculating returns. BMO distinguishes cash payments from
reinvested distributions that can affect tax and adjusted cost base. Before
building a return series, we will confirm how the reinvested amounts are
reflected in the NAV and units to avoid counting the same value twice.

The history export also does not identify all tax categories, such as Canadian
dividends, foreign income, capital gains, and return of capital. A detailed
after-tax model needs annual tax factors and explicit tax-rate assumptions.
The case's 38% average rate is not a supplied marginal rate for each category.

References for this distinction:

- [BMO's annual reinvested-distribution announcement](https://newsroom.bmo.com/2025-12-19-BMO-Announces-Annual-Reinvested-Distributions-for-BMO-Exchange-Traded-Funds-and-ETF-Series-of-BMO-Mutual-Funds)
- [BMO ETF tax FAQ](https://bmogamhub.com/system/files/bmo_etfs_-_faq_tax_season_en.pdf?file=1&id=95149&type=node)
