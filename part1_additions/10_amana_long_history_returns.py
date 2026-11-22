"""
Step 3c: Same test as Step 3, on Amana's full history (2004-2026).

Does a stock beat SPY after Amana's purchase becomes public?
  2004-2019 : additions from the old N-Q / N-CSR filings (data/events_old_amana.csv, from 09).
              Public day = the actual SEC filing date.
  2020-2026 : additions from N-PORT (clean flips in data/events_step2.csv).
              Public day = period end + 60 days (when SEC releases N-PORT).
The 2004-2019 period was NOT used to form the idea, so it is a fresh, out-of-sample test of the
2020-2026 result (Amana Growth: about +2-3% vs SPY after the public day).

Same rules as Step 3: return minus SPY, DURING (quarter of buying, not tradeable) and AFTER the
public day for 20/60/120 trading days. Dropped: stocks that started trading inside the window
(spin-offs, merger shares, new share classes) and stocks with no Yahoo prices.

Usage (needs internet; run on your Mac):
    python3 10_amana_long_history_returns.py 2>&1 | tee step3c_output.txt

Output: data/amana_long_returns.csv and tables on screen.
"""

import os

import numpy as np
import pandas as pd

START = "2003-06-01"
HORIZONS = [20, 60, 120]
CACHE = "data/prices_close_long.csv"


def yahoo_symbol(t):
    return t.replace("/", "-").replace(".", "-")


def load_closes(tickers):
    tickers = sorted(set(tickers))
    px = pd.read_csv(CACHE, index_col=0, parse_dates=True) if os.path.exists(CACHE) else pd.DataFrame()
    missing = [t for t in tickers if t not in px.columns]
    if missing:
        import yfinance as yf
        cols = {}
        for i in range(0, len(missing), 100):
            batch = missing[i:i + 100]
            print("  prices {}-{} of {}".format(i + 1, i + len(batch), len(missing)))
            raw = yf.download([yahoo_symbol(t) for t in batch], start=START, auto_adjust=True,
                              group_by="ticker", threads=True, progress=False)
            for t in batch:
                try:
                    s = (raw[yahoo_symbol(t)]["Close"] if len(batch) > 1 else raw["Close"]).dropna()
                    if len(s):
                        cols[t] = s
                except KeyError:
                    pass
        new = pd.DataFrame(cols)
        px = pd.concat([px, new], axis=1) if len(px) else new
        px.to_csv(CACHE)
    return px


def ret(px, ticker, start, end_or_days):
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


def first_trade(px, ticker):
    if ticker not in px.columns:
        return pd.NaT
    s = px[ticker].dropna()
    return s.index.min() if len(s) else pd.NaT


def summarize(df, cols):
    rows = {}
    for c in cols:
        x = df[c].dropna()
        n = len(x)
        rows[c] = {"n": n,
                   "mean_%": round(100 * x.mean(), 2) if n else np.nan,
                   "median_%": round(100 * x.median(), 2) if n else np.nan,
                   "hit_rate_%": round(100 * (x > 0).mean(), 1) if n else np.nan,
                   "t_stat": round(x.mean() / (x.std(ddof=1) / np.sqrt(n)), 2) if n > 2 and x.std() > 0 else np.nan}
    return pd.DataFrame(rows).T


def main(px=None):
    old = pd.read_csv("data/events_old_amana.csv")
    old = old[(old["change"] == "add") & old["mapped"]].copy()
    old["era"] = "2004-2019"
    new = pd.read_csv("data/events_step2.csv")
    new = new[(new["change"] == "add") & (~new["not_a_flip"]) & new["fund"].isin(["AMAGX", "AMANX"])].copy()
    new["public_date"] = (pd.to_datetime(new["period_end"]) + pd.Timedelta(days=60)).dt.strftime("%Y-%m-%d")
    new["era"] = "2020-2026"
    cols = ["fund", "era", "period_start", "period_end", "public_date", "ticker", "name", "weight_pct", "position_musd"]
    ev = pd.concat([old[cols], new[cols]], ignore_index=True)
    for c in ["period_start", "period_end", "public_date"]:
        ev[c] = pd.to_datetime(ev[c])

    if px is None:
        print("Loading prices...")
        px = load_closes(list(ev["ticker"]) + ["SPY"])

    ev["first_trade"] = [first_trade(px, t) for t in ev["ticker"]]
    ev["no_price_data"] = ev["first_trade"].isna()
    ev["new_listing"] = ev["first_trade"] > ev["period_start"] - pd.Timedelta(days=10)
    keep = ev[~ev["no_price_data"] & ~ev["new_listing"]].copy()

    keep["xs_during"] = [ret(px, t, s, e) - ret(px, "SPY", s, e)
                         for t, s, e in zip(keep["ticker"], keep["period_start"], keep["period_end"])]
    xs_cols = ["xs_during"]
    for h in HORIZONS:
        c = "xs_after_{}d".format(h)
        keep[c] = [ret(px, t, s, h) - ret(px, "SPY", s, h) for t, s in zip(keep["ticker"], keep["public_date"])]
        xs_cols.append(c)
    keep["public_lag_days"] = (keep["public_date"] - keep["period_end"]).dt.days
    keep.to_csv("data/amana_long_returns.csv", index=False)

    pd.set_option("display.width", 220)
    print("\nEvents: {} additions with a ticker | dropped: {} new listings/spin-offs, {} no Yahoo prices | kept: {}".format(
        len(ev), int(ev["new_listing"].sum()), int(ev["no_price_data"].sum()), len(keep)))
    print("Median days from quarter end to public day, 2004-2019 (actual filing dates): {:.0f}".format(
        keep[keep["era"] == "2004-2019"]["public_lag_days"].median()))

    print("\n" + "=" * 90)
    print("RETURN MINUS SPY AFTER AMANA ADDS A STOCK  (during = not tradeable, after = from public day)")
    print("=" * 90)
    for fund in ["AMAGX", "AMANX"]:
        for era in ["2004-2019", "2020-2026", "ALL"]:
            part = keep[keep["fund"] == fund] if era == "ALL" else keep[(keep["fund"] == fund) & (keep["era"] == era)]
            print("\n-- {} | {} ({} additions) --".format(fund, era, len(part)))
            print(summarize(part, xs_cols).to_string())

    print("\n" + "=" * 90)
    print("SIDE BY SIDE: mean return minus SPY, % (t-stat)")
    print("=" * 90)
    rows = []
    for fund in ["AMAGX", "AMANX"]:
        for era in ["2004-2019", "2020-2026", "ALL"]:
            part = keep[keep["fund"] == fund] if era == "ALL" else keep[(keep["fund"] == fund) & (keep["era"] == era)]
            s = summarize(part, xs_cols)
            rows.append(dict({"fund": fund, "era": era, "n": int(s.loc["xs_after_60d", "n"])},
                             **{c.replace("xs_", ""): "{:+.2f} ({:.2f})".format(s.loc[c, "mean_%"], s.loc[c, "t_stat"])
                                for c in xs_cols}))
    print(pd.DataFrame(rows).to_string(index=False))
    print("\nSaved data/amana_long_returns.csv")


if __name__ == "__main__":
    main()
