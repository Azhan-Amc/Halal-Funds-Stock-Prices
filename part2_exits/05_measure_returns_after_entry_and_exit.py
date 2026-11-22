"""
Step 5 - Event study: what happens to a stock's price after it ENTERS or EXITS a halal fund?

Research questions 1, 2 and 4:
  RQ1  entries ("hot" stocks): do they fall back after the funds buy them?
  RQ2  candidate exits ("cold" stocks still held by HLAL): do they climb back?
  RQ4  when does the move start (return path around the event)?

For every event, the "abnormal return" = stock return - benchmark return
over the same days, measured from the event date (day 0) forward.

Fixed in advance (see 00_research_plan.md):
  - Event date, MAIN:   report_date (end of the quarter in which the change happened)
    Event date, SECOND: filing_date (when the change became public on SEC)
  - Benchmark, MAIN: HLAL     SECOND: SPY
  - Horizons: 1, 3, 6, 12 months (21, 63, 126, 252 trading days)
  - t-stat: events of the same quarter are averaged first (one number per quarter),
    because stocks leaving in the same quarter move together.
  - If a stock is bought out / delisted during the horizon, its last price is used
    (the money waits in cash at 0% until the horizon ends).
  - Returns are BEFORE trading costs (round trip ~0.1-0.2% for these large stocks).

Output:
    data/event_returns.csv
    data/event_path.csv
    output/05_event_study.txt

Run:  python3 05_measure_returns_after_entry_and_exit.py
"""

import os
import sys

import numpy as np
import pandas as pd

EVENTS_FILE = os.path.join("data", "events.csv")
EXITS_FILE = os.path.join("data", "exits_classified.csv")
MAP_FILE = os.path.join("data", "ticker_map.csv")
HOLDINGS_FILE = os.path.join("data", "holdings_quarterly.csv")
PRICE_DIR = os.path.join("data", "prices")
OUT_DIR = "output"

HORIZONS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
PATH_DAYS = [-252, -126, -63, -21, 0, 21, 63, 126, 252]
BENCHMARKS = ["HLAL", "SPY"]
EVENT_DATES = ["report_date", "filing_date"]
AMANA = ("AMAGX", "AMANX")

# Groups compared side by side (fixed before looking at results)
GROUPS = [
    ("Entries - SPUS", lambda e: (e.event == "entry") & (e.fund == "SPUS")),
    ("Entries - HLAL", lambda e: (e.event == "entry") & (e.fund == "HLAL")),
    ("Entries - Amana", lambda e: (e.event == "entry") & e.fund.isin(AMANA)),
    ("CANDIDATE exits - SPUS", lambda e: (e.cause == "still_in_HLAL") & (e.fund == "SPUS")),
    ("CANDIDATE exits - Amana", lambda e: (e.cause == "still_in_HLAL") & e.fund.isin(AMANA)),
    ("CANDIDATE exits - all", lambda e: e.cause == "still_in_HLAL"),
    ("Other exits - SPUS", lambda e: (e.cause == "left_HLAL_too") & (e.fund == "SPUS")),
    ("Other exits - Amana", lambda e: (e.cause == "left_HLAL_too") & e.fund.isin(AMANA)),
    ("HLAL's own exits", lambda e: e.cause == "hlal_exit"),
]


# ----------------------------------------------------------------------------
# Data
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
            s = s[~s.index.duplicated()].sort_index()
    _cache[ticker] = s
    return s


def load_events():
    for f in (EVENTS_FILE, EXITS_FILE, MAP_FILE, HOLDINGS_FILE):
        if not os.path.exists(f):
            sys.exit(f"{f} not found. Run steps 1-4 first.")
    ev = pd.read_csv(EVENTS_FILE, dtype=str).fillna("")
    tmap = pd.read_csv(MAP_FILE, dtype=str).fillna("")[["sec_id", "ticker"]]

    entries = ev[ev["event"] == "entry"].drop(columns=["ticker"]).merge(tmap, on="sec_id", how="left")
    entries["cause"] = ""
    exits = pd.read_csv(EXITS_FILE, dtype=str).fillna("")
    keep = ["fund", "event", "prev_report", "report_date", "sec_id", "name", "ticker", "cause"]
    allev = pd.concat([entries[keep], exits[keep]], ignore_index=True)

    # filing date of the report that first showed the change
    h = pd.read_csv(HOLDINGS_FILE, dtype=str, usecols=["fund", "report_date", "filing_date"]).drop_duplicates()
    h = h.groupby(["fund", "report_date"], as_index=False)["filing_date"].max()
    allev = allev.merge(h, on=["fund", "report_date"], how="left")
    for c in ("report_date", "filing_date"):
        allev[c] = pd.to_datetime(allev[c])
    return allev


# ----------------------------------------------------------------------------
# Returns
# ----------------------------------------------------------------------------
def day0_index(s, date):
    """Position of the first trading day on or after `date`."""
    i = s.index.searchsorted(date)
    return i if i < len(s) else None


def forward_return(s, i0, days, data_end):
    """Return from position i0 over `days` trading days.
    None if the sample ends before the horizon; last price if delisted."""
    i1 = i0 + days
    if i1 < len(s):
        return s.iloc[i1] / s.iloc[i0] - 1
    if s.index[-1] < data_end - pd.Timedelta(days=10):      # delisted: hold last price
        return s.iloc[-1] / s.iloc[i0] - 1
    return None                                                # horizon not finished yet


def bench_return(b, date0, days):
    i0 = day0_index(b, date0)
    if i0 is None or i0 + days >= len(b):
        return None
    return b.iloc[i0 + days] / b.iloc[i0] - 1


def relative_level(s, b, date0, d):
    """(stock / stock at day 0) / (bench / bench at day 0) - 1, at d trading days from day 0."""
    i0, j0 = day0_index(s, date0), day0_index(b, date0)
    if i0 is None or j0 is None:
        return None
    i1, j1 = i0 + d, j0 + d
    if i1 < 0 or j1 < 0 or i1 >= len(s) or j1 >= len(b):
        return None
    return (s.iloc[i1] / s.iloc[i0]) / (b.iloc[j1] / b.iloc[j0]) - 1


def compute(allev):
    data_end = prices("SPY").index.max()
    rows, path_rows = [], []
    for _, e in allev.iterrows():
        s = prices(e["ticker"])
        if s is None:
            continue
        for date_col in EVENT_DATES:
            d0 = e[date_col]
            if pd.isna(d0):
                continue
            i0 = day0_index(s, d0)
            if i0 is None:
                continue
            date0 = s.index[i0]
            for bname in BENCHMARKS:
                b = prices(bname)
                if b is None or date0 < b.index.min():
                    continue
                row = {"fund": e["fund"], "event": e["event"], "cause": e["cause"], "name": e["name"],
                       "ticker": e["ticker"], "report_date": e["report_date"].date(),
                       "date_type": date_col, "benchmark": bname, "day0": date0.date()}
                for h, days in HORIZONS.items():
                    r = forward_return(s, i0, days, data_end)
                    rb = bench_return(b, date0, days)
                    row[f"abn_{h}"] = (r - rb) if (r is not None and rb is not None) else np.nan
                rows.append(row)
                if date_col == "report_date" and bname == "HLAL":
                    pr = {"fund": e["fund"], "event": e["event"], "cause": e["cause"],
                          "report_date": e["report_date"].date()}
                    for d in PATH_DAYS:
                        v = relative_level(s, b, date0, d)
                        pr[f"d{d}"] = v if v is not None else np.nan
                    path_rows.append(pr)
    return pd.DataFrame(rows), pd.DataFrame(path_rows)


# ----------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------
def quarter_tstat(g, col):
    """Average per quarter first, then t = mean / (sd / sqrt(n quarters))."""
    q = g.dropna(subset=[col]).groupby("report_date")[col].mean()
    if len(q) < 3 or q.std() < 1e-9:
        return np.nan, len(q)
    return q.mean() / (q.std() / np.sqrt(len(q))), len(q)


def block(res, date_type, bench):
    r = res[(res["date_type"] == date_type) & (res["benchmark"] == bench)]
    hdr = f"{'Group':<26}" + "".join(f"{h:>9}" for h in HORIZONS)
    out = []
    for title, fn in (("MEAN abnormal return (%)", lambda v: v.mean() * 100),
                      ("MEDIAN abnormal return (%)", lambda v: v.median() * 100),
                      ("% of events beating the benchmark", lambda v: (v > 0).mean() * 100)):
        out += ["", f"  {title}", "  " + hdr]
        for name, f in GROUPS:
            g = r[f(r)]
            cells = []
            for h in HORIZONS:
                v = g[f"abn_{h}"].dropna()
                cells.append(f"{fn(v):>9.1f}" if len(v) else f"{'-':>9}")
            out.append(f"  {name:<26}" + "".join(cells))
    out += ["", "  N events (quarters) and t-stat on quarter averages  (|t| > 2 = unlikely to be luck)",
            "  " + f"{'Group':<26}" + "".join(f"{h:>16}" for h in HORIZONS)]
    for name, f in GROUPS:
        g = r[f(r)]
        cells = []
        for h in HORIZONS:
            n = g[f"abn_{h}"].notna().sum()
            t, nq = quarter_tstat(g, f"abn_{h}")
            tt = f"{t:5.2f}" if not np.isnan(t) else "  n/a"
            cells.append(f"{n:>4} ({nq:>2}) t={tt}")
        out.append(f"  {name:<26}" + "".join(f"{c:>16}" for c in cells))
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if prices("SPY") is None or prices("HLAL") is None:
        sys.exit("SPY or HLAL prices missing - run step 3 again.")
    allev = load_events()
    res, path = compute(allev)
    res.to_csv(os.path.join("data", "event_returns.csv"), index=False)
    path.to_csv(os.path.join("data", "event_path.csv"), index=False)

    lines = ["STEP 5 - RETURNS AFTER ENTERING / EXITING A HALAL FUND",
             "Abnormal return = stock return - benchmark return, from day 0 (before trading costs)", ""]
    for date_type in EVENT_DATES:
        for bench in BENCHMARKS:
            tag = "MAIN TEST" if (date_type, bench) == ("report_date", "HLAL") else "second view"
            lines += ["=" * 92, f"[{tag}]  Day 0 = {date_type}   Benchmark = {bench}", "=" * 92]
            lines += block(res, date_type, bench)
            lines.append("")

    # RQ4: path around day 0 (main test)
    lines += ["=" * 92, "RETURN PATH vs HLAL around day 0 = report_date (mean %, stock relative to its own day-0 level)",
              "Negative before day 0 = stock was HIGHER before (it fell into the event).", "=" * 92]
    lines.append(f"  {'Group':<26}" + "".join(f"{('d' + str(d)):>8}" for d in PATH_DAYS))
    for name, f in GROUPS:
        g = path[f(path)] if not path.empty else path
        cells = [f"{g[f'd{d}'].mean() * 100:>8.1f}" if len(g) and g[f'd{d}'].notna().any() else f"{'-':>8}"
                 for d in PATH_DAYS]
        lines.append(f"  {name:<26}" + "".join(cells))

    lines += ["", f"Events measured: {res.loc[(res.date_type == 'report_date') & (res.benchmark == 'HLAL')].shape[0]} "
                  f"(of {len(allev)}; the rest have no prices)",
              f"Price data ends: {prices('SPY').index.max().date()}  (recent events have no 12m result yet)"]

    summary = "\n".join(lines)
    print(summary)
    with open(os.path.join(OUT_DIR, "05_event_study.txt"), "w") as fh:
        fh.write(summary + "\n")


if __name__ == "__main__":
    main()