"""
Step 4: Portfolio backtest of the cooling-off rule (and the "second wave" tilt).

Universe at each quarter = every US-listed stock held by SPUS or HLAL (from their SEC filings).
The portfolio is rebalanced on the day those holdings became public (quarter end + 60 days),
equal weight, held until the next public day. Each variant changes ONE rule versus the baseline:

  A_baseline     : hold the whole halal list
  B_cooling_off  : skip stocks that joined the list less than ~6 months ago
                   (present in fewer than 3 consecutive quarterly snapshots)
  C_second_wave  : like A, but DOUBLE weight on stocks 6-12 months after joining
                   (3 or 4 consecutive snapshots), to catch other funds' later buying

Benchmarks: SPY, SPUS, HLAL (bought and held over the same dates).
Costs: 0.05% per side on every dollar traded at each rebalance.

Usage (needs internet; run on your Mac):
    python3 11_cooling_off_portfolio_backtest.py 2>&1 | tee step4_output.txt

Reads:  data/holdings_SPUS.csv, data/holdings_HLAL.csv (and other holdings_*.csv for tickers)
Writes: data/portfolio_daily.csv, data/portfolio_periods.csv, data/prices_portfolio.csv (cache)
"""

import glob
import os
import re

import numpy as np
import pandas as pd

PUBLIC_LAG = 60
MIN_AGE_COOL = 3          # snapshots in a row on the list before B will hold it
TILT_AGES = (3, 4)        # C doubles these ages
COST_PER_SIDE = 0.0005
FIRST_SNAPSHOT = 2        # start once ages can reach 3 (third snapshot)
CACHE = "data/prices_portfolio.csv"
US_TICKER = re.compile(r"^[A-Z]{1,5}([./][A-Z])?$")
VARIANTS = ["A_baseline", "B_cooling_off", "C_second_wave"]
BENCH = ["SPY", "SPUS", "HLAL"]


def norm_ticker(t):
    if not isinstance(t, str) or not t.strip():
        return None
    t = re.sub(r"\s+US$", "", t.strip().upper())
    return re.sub(r"-W[I]?$", "", t)


def load_universe():
    allh = []
    for f in glob.glob("data/holdings_*.csv"):
        if "_old_" in f:
            continue
        h = pd.read_csv(f, dtype={"cusip": str, "ticker": str})
        h["fund"] = os.path.basename(f)[9:-4]
        allh.append(h)
    allh = pd.concat(allh, ignore_index=True)
    allh["t"] = allh["ticker"].map(norm_ticker)
    known = allh[allh["t"].notna() & allh["t"].str.match(US_TICKER)]
    cusip_map = known.groupby("cusip")["t"].agg(lambda s: s.value_counts().index[0])

    h = allh[allh["fund"].isin(["SPUS", "HLAL"])].copy()
    if h["asset_cat"].notna().any():
        h = h[h["asset_cat"] == "EC"]
    h["t"] = h["t"].where(h["t"].notna(), h["cusip"].map(cusip_map))
    h = h[h["t"].notna() & h["t"].str.match(US_TICKER) & (h["pct"].fillna(0) >= 0.001)]
    dates = sorted(set(h[h["fund"] == "SPUS"]["report_date"]) & set(h[h["fund"] == "HLAL"]["report_date"]))
    return {d: set(h[h["report_date"] == d]["t"]) for d in dates}, dates


def ages(universe, dates):
    out, prev = {}, {}
    for d in dates:
        cur = {t: prev.get(t, 0) + 1 for t in universe[d]}
        out[d], prev = cur, cur
    return out


def weights(age_d, variant):
    if variant == "A_baseline":
        raw = {t: 1.0 for t in age_d}
    elif variant == "B_cooling_off":
        raw = {t: 1.0 for t, a in age_d.items() if a >= MIN_AGE_COOL}
    else:
        raw = {t: (2.0 if a in TILT_AGES else 1.0) for t, a in age_d.items()}
    s = sum(raw.values())
    return {t: w / s for t, w in raw.items()}


def load_prices(tickers):
    tickers = sorted(set(tickers))
    px = pd.read_csv(CACHE, index_col=0, parse_dates=True) if os.path.exists(CACHE) else pd.DataFrame()
    missing = [t for t in tickers if t not in px.columns]
    if missing:
        import yfinance as yf
        cols = {}
        for i in range(0, len(missing), 100):
            batch = missing[i:i + 100]
            print("  prices {}-{} of {}".format(i + 1, i + len(batch), len(missing)))
            syms = [t.replace("/", "-").replace(".", "-") for t in batch]
            raw = yf.download(syms, start="2020-06-01", auto_adjust=True, group_by="ticker",
                              threads=True, progress=False)
            for t, y in zip(batch, syms):
                try:
                    s = (raw[y]["Close"] if len(batch) > 1 else raw["Close"]).dropna()
                    if len(s):
                        cols[t] = s
                except KeyError:
                    pass
        new = pd.DataFrame(cols)
        px = pd.concat([px, new], axis=1) if len(px) else new
        px.to_csv(CACHE)
    return px.sort_index()


def run(px, universe, dates):
    age = ages(universe, dates)
    rebal = [pd.Timestamp(d) + pd.Timedelta(days=PUBLIC_LAG) for d in dates]
    rebal = [px.index[px.index.searchsorted(r)] if px.index.searchsorted(r) < len(px.index) else None for r in rebal]
    daily = {v: [] for v in VARIANTS}
    periods = []
    held = {v: {} for v in VARIANTS}      # weights at end of last period (after drift)
    for k in range(FIRST_SNAPSHOT, len(dates)):
        start = rebal[k]
        if start is None:
            break
        end = rebal[k + 1] if k + 1 < len(dates) and rebal[k + 1] is not None else px.index[-1]
        win = px.loc[start:end]
        if len(win) < 2:          # a rebalance on the last price day has no days to hold yet
            break
        row = {"snapshot": dates[k], "start": start.date(), "end": end.date()}
        for v in VARIANTS:
            w = weights(age[dates[k]], v)
            w = {t: x for t, x in w.items() if t in px.columns and pd.notna(px.at[start, t])}
            s = sum(w.values())
            w = {t: x / s for t, x in w.items()}
            rel = win[list(w)].ffill() / win[list(w)].iloc[0]          # delisted: last price kept
            value = (rel * pd.Series(w)).sum(axis=1)
            traded = sum(abs(w.get(t, 0) - held[v].get(t, 0)) for t in set(w) | set(held[v]))
            cost = traded * COST_PER_SIDE
            value = value * (1 - cost)
            daily[v].append(value.iloc[1:] if daily[v] else value)
            end_w = rel.iloc[-1] * pd.Series(w)
            held[v] = (end_w / end_w.sum()).to_dict()
            row[v + "_ret"] = value.iloc[-1] - 1
            row[v + "_n"] = len(w)
            row[v + "_traded"] = traded
        for b in BENCH:
            row[b + "_ret"] = px.at[end, b] / px.at[start, b] - 1 if b in px.columns else np.nan
        periods.append(row)
    curves = {}
    for v in VARIANTS:
        level, parts = 1.0, []
        for seg in daily[v]:
            seg = seg / seg.iloc[0] if not parts else seg
            parts.append(seg * level)
            level = parts[-1].iloc[-1]
        curves[v] = pd.concat(parts)
    curves = pd.DataFrame(curves)
    for b in BENCH:
        if b in px.columns:
            curves[b] = px.loc[curves.index, b] / px.loc[curves.index[0], b]
    return curves, pd.DataFrame(periods)


def stats(curve):
    r = curve.pct_change().dropna()
    yrs = (curve.index[-1] - curve.index[0]).days / 365.25
    cagr = curve.iloc[-1] ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(252)
    dd = (curve / curve.cummax() - 1).min()
    return {"CAGR_%": 100 * cagr, "vol_%": 100 * vol, "Sharpe(0%)": r.mean() * 252 / vol,
            "max_drawdown_%": 100 * dd, "total_%": 100 * (curve.iloc[-1] - 1)}


def main(px=None):
    universe, dates = load_universe()
    print("Snapshots (SPUS and HLAL both):", len(dates), dates[0], "->", dates[-1])
    print("Halal list size per snapshot: min {} / median {:.0f} / max {}".format(
        min(len(universe[d]) for d in dates), np.median([len(universe[d]) for d in dates]),
        max(len(universe[d]) for d in dates)))
    if px is None:
        print("Loading prices...")
        px = load_prices(set().union(*universe.values()) | set(BENCH))
    curves, per = run(px, universe, dates)
    curves.to_csv("data/portfolio_daily.csv")
    per.to_csv("data/portfolio_periods.csv", index=False)

    pd.set_option("display.width", 220)
    print("\nBacktest: {} -> {} ({} rebalances)\n".format(curves.index[0].date(), curves.index[-1].date(), len(per)))
    st = pd.DataFrame({c: stats(curves[c]) for c in curves.columns}).T.round(2)
    st["avg_stocks"] = [round(per[c + "_n"].mean()) if c + "_n" in per else np.nan for c in st.index]
    st["avg_traded_per_rebal_%"] = [round(100 * per[c + "_traded"].iloc[1:].mean(), 1) if c + "_traded" in per else np.nan
                                    for c in st.index]
    print("=" * 100)
    print("RESULTS (after 0.05% per side trading costs)")
    print("=" * 100)
    print(st.to_string())

    print("\n" + "=" * 100)
    print("YEAR BY YEAR, % return")
    print("=" * 100)
    yearly = curves.resample("YE").last().pct_change()
    yearly.iloc[0] = curves.resample("YE").last().iloc[0] / curves.iloc[0] - 1
    yearly.index = yearly.index.year
    print((100 * yearly).round(1).to_string())

    print("\n" + "=" * 100)
    print("DOES THE RULE BEAT THE BASELINE?  (per rebalance period, return difference vs A)")
    print("=" * 100)
    for v in VARIANTS[1:]:
        d = per[v + "_ret"] - per["A_baseline_ret"]
        t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d))) if d.std() > 0 else np.nan
        print("{:<14} mean {:+.2f}% per quarter | median {:+.2f}% | beats A in {}/{} quarters | t = {:.2f}".format(
            v, 100 * d.mean(), 100 * d.median(), int((d > 0).sum()), len(d), t))
    print("\nSaved data/portfolio_daily.csv and data/portfolio_periods.csv")


if __name__ == "__main__":
    main()