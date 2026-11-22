"""
Step 4 - Classify every exit by its most likely cause (research question 3).

Each exit gets ONE cause, checked in this order:

  1. no_prices       no price history at all (usually bought out / delisted)
  2. delisted_soon   prices stop within DELIST_DAYS after the exit (buyout, merger)
  3. sp500_removal   SPUS only: the stock left the S&P 500 at the same time
                     (no Shariah reason - SPUS can only hold S&P 500 stocks)
  4. still_in_HLAL   HLAL (total-assets screen) still held it -> CANDIDATE:
                     most likely pushed out by its price / market-cap screen
  5. left_HLAL_too   HLAL did not hold it either -> debt, business or other reason
  (HLAL's own exits are labelled hlal_exit / hlal_exit_no_prices / hlal_exit_delisted)

S&P 500 membership comes from the SEC holdings filings of Vanguard's S&P 500
fund (VOO), downloaded with the same code as step 1. A stock VOO held before
the SPUS exit and no longer held right after it = removed from the S&P 500.

It also measures how far each stock had fallen BEFORE the exit
(return over 6, 12 and 36 months up to the report date, minus SPY's return
over the same period), to check that candidates really were "cold".

Output:
    data/sp500_holdings.csv   (VOO holdings, cached)
    data/exits_classified.csv
    output/04_exit_causes.txt

Run:  python3 04_classify_exits_by_cause.py
"""

import importlib.util
import os
import sys

import pandas as pd

EVENTS_FILE = os.path.join("data", "events.csv")
MAP_FILE = os.path.join("data", "ticker_map.csv")
PRICE_DIR = os.path.join("data", "prices")
SP500_FILE = os.path.join("data", "sp500_holdings.csv")
OUT_FILE = os.path.join("data", "exits_classified.csv")
OUT_DIR = "output"
STEP1_FILE = "01_download_fund_holdings.py"

SP500_FUNDS = ["VOO", "VFIAX", "IVV"]   # first one found in the SEC list is used
DELIST_DAYS = 180          # prices ending within this many days after the exit = bought out / delisted
BEFORE_MAX_DAYS = 100      # VOO report used for "before" can be at most this old
AFTER_MAX_DAYS = 45        # VOO report used for "after" must come within this many days of the exit report
LOOKBACKS = {"6m": 126, "12m": 252, "36m": 756}   # trading days


# ----------------------------------------------------------------------------
# S&P 500 membership (from VOO's N-PORT holdings)
# ----------------------------------------------------------------------------
def load_sp500_holdings():
    """VOO holdings per report date: {date: set of sec_id}. Cached in data/sp500_holdings.csv."""
    if not os.path.exists(SP500_FILE):
        if not os.path.exists(STEP1_FILE):
            sys.exit(f"{STEP1_FILE} must be in this folder (step 4 reuses its SEC download code).")
        spec = importlib.util.spec_from_file_location("step1", STEP1_FILE)
        step1 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(step1)
        if "your_email@example.com" in step1.SEC_CONTACT:
            sys.exit(f"Put your name and email in SEC_CONTACT in {STEP1_FILE} first.")
        os.makedirs(step1.RAW_DIR, exist_ok=True)

        print("Downloading S&P 500 membership from an S&P 500 fund's holdings (first run only)...")
        found = step1.find_series(SP500_FUNDS)
        fund = next((f for f in SP500_FUNDS if f in found), None)
        if fund is None:
            sys.exit(f"None of {SP500_FUNDS} found in the SEC fund list.")
        cik, series_id = found[fund]
        print(f"   using {fund}")
        filings = step1.list_nport_filings(cik)
        mine = [f for f in filings if step1.series_of_filing(cik, f) == series_id]
        print(f"   {len(mine)} {fund} reports found")
        rows = []
        for f in mine:
            xml_bytes = step1.download_filing(cik, f)
            if xml_bytes is None:
                continue
            rep_date, holdings = step1.parse_holdings(xml_bytes)
            for h in holdings:
                if h["asset_cat"] == "EC" and h["cusip"] and h["cusip"] != "000000000":
                    rows.append({"report_date": rep_date or f["report_date"],
                                 "sec_id": h["cusip"].upper(), "name": h["name"]})
        if not rows:
            sys.exit(f"No {fund} holdings could be downloaded.")
        pd.DataFrame(rows).drop_duplicates(["report_date", "sec_id"]).to_csv(SP500_FILE, index=False)

    df = pd.read_csv(SP500_FILE, dtype=str)
    df["report_date"] = pd.to_datetime(df["report_date"])
    return {d: set(g["sec_id"]) for d, g in df.groupby("report_date")}


def left_sp500(sp500, sec_id, prev_report, report_date):
    """True if the S&P 500 fund held the stock before the exit window and not right after it.
    None if there is no usable report on one side."""
    dates = sorted(sp500)
    before = [d for d in dates if d <= prev_report and (prev_report - d).days <= BEFORE_MAX_DAYS]
    after = [d for d in dates if d >= report_date and (d - report_date).days <= AFTER_MAX_DAYS]
    if not after:   # end of data: fall back to the latest report inside the window
        after = [d for d in dates if prev_report < d <= report_date]
    if not before or not after:
        return None
    return (sec_id in sp500[before[-1]]) and (sec_id not in sp500[after[0]])


# ----------------------------------------------------------------------------
# Prices
# ----------------------------------------------------------------------------
_cache = {}


def prices(ticker):
    if ticker in _cache:
        return _cache[ticker]
    path = os.path.join(PRICE_DIR, f"{ticker}.csv")
    s = None
    if ticker and os.path.exists(path):
        df = pd.read_csv(path, parse_dates=["date"])
        if not df.empty:
            s = df.set_index("date")["close"].dropna()
    _cache[ticker] = s
    return s


def trailing_return(s, date, days):
    """Return over `days` trading days ending on the last close <= date."""
    if s is None:
        return None
    upto = s[s.index <= date]
    if len(upto) <= days:
        return None
    return upto.iloc[-1] / upto.iloc[-1 - days] - 1


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    for f in (EVENTS_FILE, MAP_FILE):
        if not os.path.exists(f):
            sys.exit(f"{f} not found. Run steps 2 and 3 first.")
    os.makedirs(OUT_DIR, exist_ok=True)

    ev = pd.read_csv(EVENTS_FILE, dtype=str).fillna("")
    tmap = pd.read_csv(MAP_FILE, dtype=str).fillna("")[["sec_id", "ticker"]]
    ex = ev[ev["event"] == "exit"].drop(columns=["ticker"]).merge(tmap, on="sec_id", how="left")
    ex["ticker"] = ex["ticker"].fillna("")
    ex["prev_report"] = pd.to_datetime(ex["prev_report"])
    ex["report_date"] = pd.to_datetime(ex["report_date"])

    sp500 = load_sp500_holdings()
    spy = prices("SPY")
    if spy is None:
        sys.exit("SPY prices missing - run step 3 again.")
    data_end = spy.index.max()

    causes, last_dates, rel = [], [], {k: [] for k in LOOKBACKS}
    for _, r in ex.iterrows():
        s = prices(r["ticker"])
        last = s.index.max() if s is not None else pd.NaT
        last_dates.append(last.date() if pd.notna(last) else "")
        bought_out = (s is not None and (last - r["report_date"]).days < DELIST_DAYS
                      and last < data_end - pd.Timedelta(days=10))

        if r["fund"] == "HLAL":
            cause = "hlal_exit_no_prices" if s is None else ("hlal_exit_delisted" if bought_out else "hlal_exit")
        elif s is None:
            cause = "no_prices"
        elif bought_out:
            cause = "delisted_soon"
        elif r["fund"] == "SPUS" and left_sp500(sp500, r["sec_id"], r["prev_report"], r["report_date"]):
            cause = "sp500_removal"
        elif r.get("in_HLAL", "") == "True":
            cause = "still_in_HLAL"
        else:
            cause = "left_HLAL_too"
        causes.append(cause)

        for k, days in LOOKBACKS.items():
            a = trailing_return(s, r["report_date"], days)
            b = trailing_return(spy, r["report_date"], days)
            rel[k].append(round((a - b) * 100, 2) if a is not None and b is not None else None)

    ex["cause"] = causes
    ex["last_price_date"] = last_dates
    for k in LOOKBACKS:
        ex[f"rel_ret_{k}_vs_SPY_pct"] = rel[k]
    ex = ex.sort_values(["fund", "report_date", "cause", "name"])
    ex["prev_report"] = ex["prev_report"].dt.date
    ex["report_date"] = ex["report_date"].dt.date
    ex.to_csv(OUT_FILE, index=False)

    # ---------------- report ----------------
    order = ["still_in_HLAL", "left_HLAL_too", "sp500_removal", "delisted_soon", "no_prices",
             "hlal_exit", "hlal_exit_delisted", "hlal_exit_no_prices"]
    table = pd.crosstab(ex["fund"], ex["cause"]).reindex(columns=[c for c in order if c in set(ex["cause"])],
                                                         fill_value=0)
    table["total"] = table.sum(axis=1)

    lines = ["STEP 4 - EXITS CLASSIFIED BY CAUSE", "",
             "Number of exits per fund and cause:", "", table.to_string(), ""]
    sp_dates = sorted(sp500)
    lines.append(f"S&P 500 membership: {len(sp_dates)} S&P 500 fund reports, "
                 f"{sp_dates[0].date()} to {sp_dates[-1].date()}")
    lines += ["", "How far had the stock fallen before the exit? (return minus SPY, in %, median / share below SPY)", ""]
    lines.append(f"{'Cause':<16} {'Fund':<6} {'N':>4}  " +
                 "  ".join(f"{k + ' median':>11} {k + ' <SPY':>9}" for k in LOOKBACKS))
    for (cause, fund), g in ex.groupby(["cause", "fund"]):
        if cause not in ("still_in_HLAL", "left_HLAL_too", "hlal_exit"):
            continue
        parts = []
        for k in LOOKBACKS:
            v = pd.to_numeric(g[f"rel_ret_{k}_vs_SPY_pct"], errors="coerce").dropna()
            parts.append(f"{v.median():>11.1f} {(v < 0).mean() * 100:>8.0f}%" if len(v) else f"{'n/a':>11} {'':>9}")
        lines.append(f"{cause:<16} {fund:<6} {len(g):>4}  " + "  ".join(parts))

    cand = ex[ex["cause"] == "still_in_HLAL"]
    lines += ["", f"FINAL CANDIDATES (still in HLAL, priced, not removed from S&P 500, not bought out): "
                  f"{len(cand)} exits, {cand['sec_id'].nunique()} stocks"]
    lines += ["", f"Saved: {OUT_FILE}"]

    summary = "\n".join(lines)
    print(summary)
    with open(os.path.join(OUT_DIR, "04_exit_causes.txt"), "w") as fh:
        fh.write(summary + "\n")


if __name__ == "__main__":
    main()