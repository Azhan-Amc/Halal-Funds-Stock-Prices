"""
Step 3: Do stocks go up while (and after) halal funds buy them?

Focus: Amana Growth (AMAGX) and SPRE additions, with SPUS / HLAL / AMANX shown for comparison.
Uses only clean flips from Step 2 (data/events_step2.csv).

For each addition it measures the stock's return MINUS the market's (SPY) over:
  DURING   : period_start -> period_end
             (the quarter in which the fund bought it; we could NOT have traded this:
              we only learn about the purchase later)
  AFTER    : from the day the holdings became public, for 20 / 60 / 120 trading days.
             Public day = period_end + 60 days (when the SEC releases N-PORT holdings).
             This is the part we COULD trade.

Confluence: how many OTHER independent screen families had already added the same stock
in the 12 months before the public day (known at the time, so no look-ahead).

Amana follow-through: did Amana keep buying after the first appearance?
(shares held at the next snapshot vs the first)

Usage (needs internet; run on your Mac):
    python3 06_event_returns.py 2>&1 | tee step3_output.txt

Output: data/event_returns.csv, data/prices_close.csv (cache), and summary tables.
"""

import glob
import os

import numpy as np
import pandas as pd

START = "2019-06-01"
PUBLIC_LAG_DAYS = 60
HORIZONS = [20, 60, 120]
FOCUS = ["AMAGX", "SPRE"]
COMPARE = ["SPUS", "HLAL", "AMANX"]
FAMILY = {"SPUS": "S&P", "SPTE": "S&P", "SPRE": "S&P", "HLAL": "FTSE", "MNZL": "Russell-IR",
          "KWIN": "Wahed", "AMAGX": "Saturna", "AMANX": "Saturna"}
CACHE = "data/prices_close.csv"


def yahoo_symbol(t):
    return t.replace("/", "-").replace(".", "-")


def load_closes(tickers):
    """Adjusted daily closes (dividends included). Uses data/prices_close.csv if present."""
    tickers = sorted(set(tickers))
    if os.path.exists(CACHE):
        px = pd.read_csv(CACHE, index_col=0, parse_dates=True)
        missing = [t for t in tickers if t not in px.columns]
        if not missing:
            return px
    else:
        px, missing = pd.DataFrame(), tickers
    import yfinance as yf
    cols = {}
    for i in range(0, len(missing), 100):
        batch = missing[i:i + 100]
        print("  prices {}-{} of {}".format(i + 1, i + len(batch), len(missing)))
        raw = yf.download([yahoo_symbol(t) for t in batch], start=START, auto_adjust=True,
                          group_by="ticker", threads=True, progress=False)
        for t in batch:
            try:
                s = raw[yahoo_symbol(t)]["Close"] if len(batch) > 1 else raw["Close"]
                s = s.dropna()
                if len(s):
                    cols[t] = s
            except KeyError:
                pass
    new = pd.DataFrame(cols)
    px = pd.concat([px, new], axis=1) if len(px) else new
    px.to_csv(CACHE)
    return px


def ret(px, ticker, start, end_or_days):
    """Return from the first trading day >= start, to a date or to N trading days later."""
    if ticker not in px.columns:
        return np.nan
    s = px[ticker].dropna()
    i0 = s.index.searchsorted(pd.Timestamp(start))
    if i0 >= len(s):
        return np.nan
    if isinstance(end_or_days, int):
        i1 = i0 + end_or_days
        if i1 >= len(s):
            return np.nan
    else:
        i1 = s.index.searchsorted(pd.Timestamp(end_or_days), side="right") - 1
        if i1 <= i0:
            return np.nan
    return s.iloc[i1] / s.iloc[i0] - 1


def summarize(df, cols):
    rows = {}
    for c in cols:
        x = df[c].dropna()
        n = len(x)
        rows[c] = {
            "n": n,
            "mean_%": round(100 * x.mean(), 2) if n else np.nan,
            "median_%": round(100 * x.median(), 2) if n else np.nan,
            "hit_rate_%": round(100 * (x > 0).mean(), 1) if n else np.nan,
            "t_stat": round(x.mean() / (x.std(ddof=1) / np.sqrt(n)), 2) if n > 2 and x.std() > 0 else np.nan,
        }
    return pd.DataFrame(rows).T


def main(px=None):
    ev = pd.read_csv("data/events_step2.csv", dtype={"cusip": str})
    ev = ev[(~ev["not_a_flip"]) & (ev["change"] == "add")].copy()
    ev["family"] = ev["fund"].map(FAMILY)
    for c in ["period_start", "period_end"]:
        ev[c] = pd.to_datetime(ev[c])
    ev["public_date"] = ev["period_end"] + pd.Timedelta(days=PUBLIC_LAG_DAYS)

    # confluence known at public date: other families' adds in prior 12 months
    conf = []
    for r in ev.itertuples():
        o = ev[(ev["ticker"] == r.ticker) & (ev["family"] != r.family) &
               (ev["public_date"] <= r.public_date) &
               (ev["public_date"] > r.public_date - pd.Timedelta(days=365))]
        conf.append(o["family"].nunique())
    ev["other_families_before"] = conf
    ev["confluence"] = ev["other_families_before"] > 0

    use = ev[ev["fund"].isin(FOCUS + COMPARE)].copy()
    if px is None:
        print("Loading prices...")
        px = load_closes(list(use["ticker"]) + ["SPY", "VNQ"])

    for r_col, start_col, end in [("during", "period_start", "period_end")]:
        use["ret_" + r_col] = [ret(px, t, s, e) for t, s, e in zip(use["ticker"], use[start_col], use[end])]
        use["spy_" + r_col] = [ret(px, "SPY", s, e) for s, e in zip(use[start_col], use[end])]
        use["xs_" + r_col] = use["ret_" + r_col] - use["spy_" + r_col]
    for h in HORIZONS:
        use["ret_after_{}d".format(h)] = [ret(px, t, s, h) for t, s in zip(use["ticker"], use["public_date"])]
        use["spy_after_{}d".format(h)] = [ret(px, "SPY", s, h) for s in use["public_date"]]
        use["xs_after_{}d".format(h)] = use["ret_after_{}d".format(h)] - use["spy_after_{}d".format(h)]
        # REITs also vs the REIT market
        use["xs_vnq_after_{}d".format(h)] = use["ret_after_{}d".format(h)] - \
            pd.Series([ret(px, "VNQ", s, h) for s in use["public_date"]], index=use.index)
    use["xs_vnq_during"] = use["ret_during"] - pd.Series(
        [ret(px, "VNQ", s, e) for s, e in zip(use["period_start"], use["period_end"])], index=use.index)

    # Amana follow-through: shares at next snapshot vs first snapshot
    follow = {}
    for fund in ["AMAGX", "AMANX"]:
        f = "data/holdings_{}.csv".format(fund)
        if not os.path.exists(f):
            continue
        h = pd.read_csv(f, dtype={"cusip": str})
        h = h.groupby(["report_date", "cusip"], as_index=False)["shares"].sum()
        dates = sorted(h["report_date"].unique())
        for r in use[use["fund"] == fund].itertuples():
            d0 = r.period_end.strftime("%Y-%m-%d")
            if d0 not in dates or dates.index(d0) + 1 >= len(dates):
                continue
            d1 = dates[dates.index(d0) + 1]
            s0 = h[(h["report_date"] == d0) & (h["cusip"] == r.cusip)]["shares"].sum()
            s1 = h[(h["report_date"] == d1) & (h["cusip"] == r.cusip)]["shares"].sum()
            if s0 > 0:
                follow[r.Index] = s1 / s0 - 1
    use["amana_shares_change_next_q"] = pd.Series(follow)

    use.to_csv("data/event_returns.csv", index=False)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 300)
    xs_cols = ["xs_during"] + ["xs_after_{}d".format(h) for h in HORIZONS]

    print("\n" + "=" * 90)
    print("RETURN MINUS SPY, BY FUND (additions, clean flips)")
    print("  during = while the fund bought (not tradeable) | after = from public day (tradeable)")
    print("=" * 90)
    for fund in FOCUS + COMPARE:
        part = use[use["fund"] == fund]
        print("\n-- {} ({} additions) --".format(fund, len(part)))
        print(summarize(part, xs_cols).to_string())

    print("\n" + "=" * 90)
    print("SPRE vs the REIT market (VNQ) instead of SPY")
    print("=" * 90)
    print(summarize(use[use["fund"] == "SPRE"],
                    ["xs_vnq_during"] + ["xs_vnq_after_{}d".format(h) for h in HORIZONS]).to_string())

    print("\n" + "=" * 90)
    print("CONFLUENCE: focus funds, split by whether another screen family had already added it")
    print("=" * 90)
    foc = use[use["fund"].isin(FOCUS)]
    for flag, label in [(True, "WITH confluence"), (False, "NO confluence")]:
        part = foc[foc["confluence"] == flag]
        print("\n-- {} ({} additions) --".format(label, len(part)))
        print(summarize(part, xs_cols).to_string())
    print("\nConfluence additions:")
    show = foc[foc["confluence"]][["fund", "period_end", "ticker", "name", "other_families_before"] + xs_cols]
    print(show.assign(**{c: (100 * show[c]).round(1) for c in xs_cols}).to_string(index=False))

    print("\n" + "=" * 90)
    print("AMANA FOLLOW-THROUGH: shares held one quarter after first appearance vs at first appearance")
    print("=" * 90)
    for fund in ["AMAGX", "AMANX"]:
        x = use[use["fund"] == fund]["amana_shares_change_next_q"].dropna()
        if len(x):
            print("{}: {} additions | kept buying (shares up >5%): {:.0f}% | median change {:+.1f}% | "
                  "sold out next quarter: {:.0f}%".format(
                      fund, len(x), 100 * (x > 0.05).mean(), 100 * x.median(), 100 * (x <= -0.999).mean()))

    print("\nSaved data/event_returns.csv")


if __name__ == "__main__":
    main()