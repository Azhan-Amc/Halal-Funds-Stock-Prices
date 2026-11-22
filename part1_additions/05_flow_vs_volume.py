"""
Step 2: Is the halal funds' forced buying big enough to move prices?

For every usable addition and removal (from 04_clean_index_changes.py) it:
  A. flags events that are NOT Shariah compliance flips:
     - new_listing      : stock started trading during the change window (spin-off / IPO)
     - delisted         : removed stock stopped trading (merger / buyout)
     - no_price_data    : Yahoo has nothing (usually delisted or a ticker that changed)
     - sp500_add/remove : SPUS change on the same window as an S&P 500 membership change
     - russell_recon    : MNZL change in a window containing the June Russell reconstitution
  B. compares the fund's buying (or selling) to the stock's normal trading:
     flow_pct_adv = dollars traded by the fund / average daily dollar volume
                    (60 trading days before the change window), in %
     Done twice: at the fund's size back then, and at the fund's size today.

Usage (needs internet; run on your Mac):
    pip3 install yfinance
    python3 05_flow_vs_volume.py

Output: data/events_step2.csv   and a summary printed on screen
"""

import io
import sys

import numpy as np
import pandas as pd
import requests

START = "2019-06-01"
ADV_DAYS = 60
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
UA = {"User-Agent": "Mozilla/5.0 (research; your-email@example.com)"}


# ---------------------------------------------------------------- data sources
def yahoo_symbol(t):
    return t.replace("/", "-").replace(".", "-")


def load_prices(tickers):
    """Daily close and volume for each ticker. Returns {ticker: DataFrame[Close, Volume]}."""
    import yfinance as yf
    out = {}
    syms = sorted(set(tickers))
    for i in range(0, len(syms), 100):
        batch = syms[i:i + 100]
        print("  prices {}-{} of {}".format(i + 1, i + len(batch), len(syms)))
        raw = yf.download([yahoo_symbol(t) for t in batch], start=START, auto_adjust=False,
                          group_by="ticker", threads=True, progress=False)
        for t in batch:
            y = yahoo_symbol(t)
            try:
                d = raw[y][["Close", "Volume"]].dropna() if len(batch) > 1 else raw[["Close", "Volume"]].dropna()
            except KeyError:
                d = pd.DataFrame(columns=["Close", "Volume"])
            out[t] = d
    return out


def load_sp500_changes():
    """S&P 500 additions/removals with dates, from Wikipedia's 'Selected changes' table."""
    html = requests.get(SP500_URL, headers=UA, timeout=60).text
    tables = pd.read_html(io.StringIO(html))
    for tb in tables:
        cols = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in tb.columns]
        if any("Added" in c for c in cols) and any("Removed" in c for c in cols):
            tb.columns = cols
            date_col = [c for c in cols if "Date" in c][0]
            add_col = [c for c in cols if "Added" in c and "Ticker" in c][0]
            rem_col = [c for c in cols if "Removed" in c and "Ticker" in c][0]
            rows = []
            for _, r in tb.iterrows():
                d = pd.to_datetime(r[date_col], errors="coerce")
                if pd.isna(d):
                    continue
                for col, kind in [(add_col, "add"), (rem_col, "remove")]:
                    t = r[col]
                    if isinstance(t, str) and t.strip() and t.strip().lower() != "nan":
                        rows.append({"date": d, "ticker": t.strip().upper(), "change": kind})
            return pd.DataFrame(rows)
    raise RuntimeError("S&P 500 changes table not found on Wikipedia page")


# ---------------------------------------------------------------- per-event work
def window_flags(ev, prices, sp):
    ps, pe = pd.Timestamp(ev.period_start), pd.Timestamp(ev.period_end)
    d = prices.get(ev.ticker)
    f = {"new_listing": False, "delisted": False, "no_price_data": False,
         "sp500_add": False, "sp500_remove": False, "russell_recon": False}
    if d is None or d.empty:
        f["no_price_data"] = True
    else:
        first, last = d.index.min(), d.index.max()
        if ev.change == "add" and first > ps - pd.Timedelta(days=10):
            f["new_listing"] = True
        if ev.change == "remove" and last <= pe + pd.Timedelta(days=5):
            f["delisted"] = True
    if ev.fund == "SPUS" and sp is not None:
        hit = sp[(sp["ticker"] == ev.ticker) & (sp["date"] > ps) & (sp["date"] <= pe + pd.Timedelta(days=3))]
        f["sp500_add"] = bool((hit["change"] == "add").any())
        f["sp500_remove"] = bool((hit["change"] == "remove").any())
    if ev.fund == "MNZL":
        june = pd.Timestamp(year=pe.year, month=6, day=25)
        f["russell_recon"] = ps < june <= pe
    return f


def adv_dollars(prices, ticker, before):
    d = prices.get(ticker)
    if d is None or d.empty:
        return np.nan
    d = d[d.index <= pd.Timestamp(before)].tail(ADV_DAYS)
    if len(d) < 20:
        return np.nan
    return float((d["Close"] * d["Volume"]).mean())


def bucket(x):
    if pd.isna(x):
        return "n/a"
    if x < 1:
        return "a) <1%"
    if x < 5:
        return "b) 1-5%"
    if x < 20:
        return "c) 5-20%"
    return "d) 20%+"


# ---------------------------------------------------------------- main
def main(prices=None, sp=None):
    ev = pd.read_csv("data/events_clean.csv", dtype={"cusip": str})
    ev = ev[ev["usable"]].copy()
    print("Usable events:", len(ev))

    if prices is None:
        print("Downloading prices from Yahoo...")
        prices = load_prices(ev["ticker"])
    if sp is None:
        try:
            print("Downloading S&P 500 change history from Wikipedia...")
            sp = load_sp500_changes()
            print("  {} S&P 500 changes, {} to {}".format(len(sp), sp["date"].min().date(), sp["date"].max().date()))
        except Exception as e:
            print("  WARNING: could not load S&P 500 changes ({}); sp500 flags left False".format(e))
            sp = None

    flags = pd.DataFrame([window_flags(r, prices, sp) for r in ev.itertuples()], index=ev.index)
    ev = pd.concat([ev, flags], axis=1)
    ev["adv_musd"] = [adv_dollars(prices, t, ps) / 1e6 for t, ps in zip(ev["ticker"], ev["period_start"])]
    ev["flow_pct_adv"] = 100 * ev["position_musd"] / ev["adv_musd"]
    ev["flow_pct_adv_today_aum"] = 100 * ev["buy_at_today_aum_musd"] / ev["adv_musd"]
    ev["not_a_flip"] = ev[["new_listing", "delisted", "no_price_data", "sp500_add",
                           "sp500_remove", "russell_recon", "rule_change_batch"]].any(axis=1)
    ev.to_csv("data/events_step2.csv", index=False)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 300)

    print("\n" + "=" * 80)
    print("A. EVENTS THAT ARE NOT SHARIAH FLIPS (count per fund)")
    print("=" * 80)
    fl = ["new_listing", "delisted", "no_price_data", "sp500_add", "sp500_remove",
          "russell_recon", "rule_change_batch", "not_a_flip"]
    t = ev.groupby(["fund", "change"])[fl].sum().astype(int)
    t["total"] = ev.groupby(["fund", "change"]).size()
    t["clean_flips"] = t["total"] - t["not_a_flip"]
    print(t.to_string())

    flips = ev[~ev["not_a_flip"]]
    print("\n" + "=" * 80)
    print("B. FORCED TRADING vs DAILY VOLUME  (clean flips only, % of avg daily $ volume)")
    print("=" * 80)
    for label, col in [("At the fund's size back then", "flow_pct_adv"),
                       ("If the fund traded the same weight at TODAY's size", "flow_pct_adv_today_aum")]:
        print("\n-- {} --\n".format(label))
        g = flips.groupby(["fund", "change"])
        s = pd.DataFrame({
            "events": g.size(),
            "median_%adv": g[col].median().round(3),
            "p90_%adv": g[col].quantile(0.9).round(3),
            "max_%adv": g[col].max().round(2),
            "median_adv_musd": g["adv_musd"].median().round(0),
        })
        b = flips.assign(b=flips[col].map(bucket)).groupby(["fund", "change", "b"]).size().unstack(fill_value=0)
        print(s.join(b).to_string())

    big = flips[flips["flow_pct_adv_today_aum"] >= 5].sort_values("flow_pct_adv_today_aum", ascending=False)
    print("\nClean flips where today's fund size would be 5%+ of a day's volume ({}):\n".format(len(big)))
    if len(big):
        print(big[["period_end", "fund", "change", "ticker", "name", "weight_pct", "adv_musd",
                   "position_musd", "flow_pct_adv", "buy_at_today_aum_musd",
                   "flow_pct_adv_today_aum"]].round(2).head(60).to_string(index=False))
    print("\nSaved data/events_step2.csv")


if __name__ == "__main__":
    main()