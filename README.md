# Do Halal Funds Move Stock Prices?

**When a stock enters or leaves a Shariah-screened fund, does its price move, and can a halal investor profit from it or lose because of it?**

## Paper

Chowdhry, Mohammad Azhan (2026). *Do Halal Funds Move Stock Prices? Evidence from Shariah Screen Changes in US Equity Funds.* Islamic Investment Research Working Paper No. 2026-03. https://doi.org/10.5281/zenodo.24329090

- IIR page: https://islamicinvestmentresearch.com/paper.html?n=2026-03

## Main findings

- **Additions.** From quarterly SEC filings of US Shariah-screened funds (2019–2026, and the Amana funds back to 2004), the study finds 666 additions and 620 deletions. Stocks added by index-based halal funds rise while the funds accumulate them, then drift slightly lower once the change is public: 120 trading days later, the median addition to SPUS and HLAL trails SPY by 4.6% and 3.3%. The effect is statistically weak.
- **Delaying purchases changes nothing.** A portfolio that waits before buying newly compliant stocks earns the same as one that buys them right away (12.89% versus 12.91% a year).
- **Deletions.** 79 deletions most likely caused by a falling share price (found from the differences between market-cap and total-assets debt screens) do not rebound. They trail HLAL by 4.0% on average over twelve months, but against matched stocks with similar past returns that stayed in the fund the shortfall is only 1–2% and not statistically significant.
- **Conclusion:** Shariah screen changes in US large caps produce no exploitable price effect, and following the screens strictly has no measurable hidden cost.

## Data

- **Fund holdings:** SEC EDGAR N-PORT filings (quarterly, 2019–2026) for SPUS, HLAL, MNZL, SPTE, SPRE, KWIN and the Amana funds (AMAGX, AMANX); older Amana N-Q / N-CSR filings back to 2004. The list of funds and why each is included is in `part1_additions/halal_funds.csv`.
- **Prices:** daily prices from Yahoo Finance (yfinance).
- **Tickers:** SEC company tickers and OpenFIGI to map fund holdings to tickers.

Data files are created by the scripts and are not stored in this repository. **The SEC requires a User-Agent with your name and email:** edit `USER_AGENT` / `UA` in part 1 and `SEC_CONTACT` in `part2_exits/01_download_fund_holdings.py` before running.

## How to run

```
pip install -r requirements.txt
```

**Part 1: additions** (run inside `part1_additions/`)

```
python3 run_step1_all_funds.py            # steps 01-03 for every fund in halal_funds.csv
python3 04_clean_index_changes.py
python3 05_flow_vs_volume.py
python3 06_event_returns.py
python3 07_download_amana_old_filings.py
python3 08_parse_amana_old_holdings.py
python3 09_build_amana_old_events.py
python3 10_amana_long_history_returns.py
python3 11_cooling_off_portfolio_backtest.py
```

**Part 2: deletions** (run inside `part2_exits/`)

```
python3 01_download_fund_holdings.py
python3 02_build_entry_exit_events.py
python3 03_match_tickers_and_download_prices.py
python3 04_classify_exits_by_cause.py
python3 05_measure_returns_after_entry_and_exit.py
python3 06_compare_with_control_group.py
```

The outputs from the runs used in the paper are saved in `part1_additions/results/` and `part2_exits/output/`, so you can compare your run with them. Yahoo Finance adjusts past prices over time, so a new download can differ slightly.

## Files

| Part | File | What it does |
| --- | --- | --- |
| 1 | `01_download_etf_holdings.py` | Downloads a fund's quarterly holdings from SEC N-PORT filings |
| 1 | `02_find_index_changes.py` | Finds each fund's additions and deletions between quarters |
| 1 | `03_combine_all_funds.py` | Combines all funds and finds stocks added by several funds |
| 1 | `04_clean_index_changes.py` | Cleans the events: ticker changes, share classes, non-US stocks, rule-change batches |
| 1 | `05_flow_vs_volume.py` | Forced buying compared with each stock's daily trading volume |
| 1 | `06_event_returns.py` | Returns around additions, during the buying quarter and after the change is public |
| 1 | `07`–`09` | Amana 2004–2019: downloads, parses and builds events from old filings |
| 1 | `10_amana_long_history_returns.py` | The step 06 test on Amana 2004–2026 |
| 1 | `11_cooling_off_portfolio_backtest.py` | Portfolio that buys newly compliant stocks immediately vs after a delay |
| 2 | `01_download_fund_holdings.py` | Quarterly holdings of HLAL and SPUS from SEC N-PORT |
| 2 | `02_build_entry_exit_events.py` | Builds the entry and exit events |
| 2 | `03_match_tickers_and_download_prices.py` | Maps holdings to tickers and downloads prices |
| 2 | `04_classify_exits_by_cause.py` | Separates exits likely caused by a falling share price (79 exits) from other causes |
| 2 | `05_measure_returns_after_entry_and_exit.py` | Returns after entries and exits |
| 2 | `06_compare_with_control_group.py` | Compares each excluded stock with 5 stocks that stayed after a similar past return |

## Limitations

- The SEC publishes N-PORT holdings mostly for the last month of each quarter, so changes are seen quarterly, not on the exact day.
- Halal funds listed outside the US (for example in London or Toronto) are not in SEC data, so total halal buying is understated.
- Returns are before trading costs unless stated otherwise.

## Use of AI

The author chose the research question, made all methodological decisions and ran the analysis. Code and text were drafted with the assistance of an AI model (Claude, Anthropic) and reviewed by the author.
