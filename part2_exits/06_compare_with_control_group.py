"""
Step 6 - Control group (research question 5):
Do stocks EXCLUDED from SPUS do worse than stocks that fell just as much but STAYED?

Fixed in advance (see 00_research_plan.md):
  - Excluded groups:  SPUS candidate exits (still in HLAL)  = MAIN
                      SPUS other exits (left HLAL too)      = second view
  - Control pool: stocks SPUS held in BOTH the previous and the current report
    (same quarter, not excluded).
  - Matching: for each excluded stock, the K = 5 stayers with the closest
    return over the 12 months before day 0 (= equally "cold" stocks).
  - Result: excluded stock's return - average return of its 5 matches,
    at 1, 3, 6, 12 months. No benchmark needed: it cancels out.
  - Day 0 = report_date (MAIN) and filing_date (second view).
  - t-stat on quarter averages (events of the same quarter move together).

Needs prices for the stayers: missing ones are downloaded with step 3's code.

Output:
    data/control_matches.csv
    output/06_control_group.txt

Run:  python3 06_compare_with_control_group.py
"""

import importlib.util
import os
import sys

import numpy as np
import pandas as pd

STEP3_FILE = "03_match_tickers_and_download_prices.py"
STEP5_FILE = "05_measure_returns_after_entry_and_exit.py"
HOLDINGS_FILE = os.path.join("data", "holdings_quarterly.csv")
EXITS_FILE = os.path.join("data", "exits_classified.csv")
MAP_FILE = os.path.join("data", "ticker_map.csv")
OUT_FILE = os.path.join("data", "control_matches.csv")
OUT_DIR = "output"

FUND = "SPUS"
K = 5
MATCH_DAYS = 252          # 12 months before day 0
HORIZONS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
GROUPS = [("CANDIDATE exits - SPUS", "still_in_HLAL"), ("Other exits - SPUS", "left_HLAL_too")]
DATE_TYPES = ["report_date", "filing_date"]


def load_module(path, name):
    if not os.path.exists(path):
        sys.exit(f"{path} must be in this folder (step 6 reuses its code).")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    for f in (HOLDINGS_FILE, EXITS_FILE, MAP_FILE):
        if not os.path.exists(f):
            sys.exit(f"{f} not found. Run steps 1-4 first.")
    os.makedirs(OUT_DIR, exist_ok=True)
    s3 = load_module(STEP3_FILE, "step3")
    s5 = load_module(STEP5_FILE, "step5")

    # ---------------- SPUS holdings and stayers ----------------
    h = pd.read_csv(HOLDINGS_FILE, dtype=str).fillna("")
    h = h[(h["fund"] == FUND) & (h["asset_cat"] == "EC")].copy()
    # same stock ID as step 2: CUSIP, else ISIN, else name
    h["sec_id"] = [c.upper() if c.strip() and c.upper() not in ("NAN", "N/A", "000000000")
                   else (i.upper() if i.strip() and i.upper() not in ("NAN", "N/A") else "NAME:" + n.strip().upper())
                   for c, i, n in zip(h["cusip"], h["isin"], h["name"])]
    filing = h.groupby("report_date")["filing_date"].max()
    held = {d: set(g["sec_id"]) for d, g in h.groupby("report_date")}

    # ---------------- tickers for every SPUS stock ----------------
    tmap = pd.read_csv(MAP_FILE, dtype=str).fillna("")
    tick = dict(zip(tmap["sec_id"], tmap["ticker"]))
    for _, r in h.drop_duplicates("sec_id").iterrows():
        if not tick.get(r["sec_id"]):
            t = s3.clean_ticker(r["ticker"])
            if t:
                tick[r["sec_id"]] = t

    needed = sorted({t for t in tick.values() if t} -
                    {f[:-4] for f in os.listdir(s3.PRICE_DIR) if f.endswith(".csv")} -
                    {f[:-12] for f in os.listdir(s3.PRICE_DIR) if f.endswith(".csv.missing")})
    spus_tickers = {tick.get(s) for s in h["sec_id"].unique()}
    needed = [t for t in needed if t in spus_tickers]
    if needed:
        print(f"Downloading prices for {len(needed)} SPUS stocks not seen before...")
        for n, t in enumerate(needed, 1):
            s3.download_prices(t)
            if n % 50 == 0:
                print(f"   {n}/{len(needed)}")

    data_end = s5.prices("SPY").index.max()

    def trailing(sid, date0):
        s = s5.prices(tick.get(sid, ""))
        if s is None:
            return None
        i0 = s5.day0_index(s, date0)
        if i0 is None or i0 - MATCH_DAYS < 0 or abs((s.index[i0] - date0).days) > 7:
            return None
        return s.iloc[i0] / s.iloc[i0 - MATCH_DAYS] - 1

    def fwd(sid, date0, days):
        s = s5.prices(tick.get(sid, ""))
        if s is None:
            return None
        i0 = s5.day0_index(s, date0)
        if i0 is None or abs((s.index[i0] - date0).days) > 7:
            return None
        return s5.forward_return(s, i0, days, data_end)

    # ---------------- matching ----------------
    ex = pd.read_csv(EXITS_FILE, dtype=str).fillna("")
    ex = ex[(ex["fund"] == FUND) & ex["cause"].isin([c for _, c in GROUPS])]
    rows, unmatched = [], 0
    for _, e in ex.iterrows():
        prev, cur = e["prev_report"], e["report_date"]
        if prev not in held or cur not in held:
            continue
        stayers = held[prev] & held[cur]
        for date_type in DATE_TYPES:
            d = cur if date_type == "report_date" else filing.get(cur, "")
            if not d:
                continue
            date0 = pd.Timestamp(d)
            t_ex = trailing(e["sec_id"], date0)
            if t_ex is None:
                unmatched += date_type == "report_date"
                continue
            pool = [(abs(tr - t_ex), sid, tr) for sid in stayers
                    for tr in [trailing(sid, date0)] if tr is not None]
            pool.sort()
            matches = pool[:K]
            if len(matches) < K:
                unmatched += date_type == "report_date"
                continue
            row = {"cause": e["cause"], "name": e["name"], "ticker": tick.get(e["sec_id"], ""),
                   "report_date": cur, "date_type": date_type, "day0": date0.date(),
                   "trail12m_excluded": t_ex, "trail12m_controls": np.mean([m[2] for m in matches]),
                   "controls": " ".join(tick.get(m[1], m[1]) for m in matches)}
            for hname, days in HORIZONS.items():
                r_ex = fwd(e["sec_id"], date0, days)
                r_c = [fwd(m[1], date0, days) for m in matches]
                r_c = [x for x in r_c if x is not None]
                if r_ex is None or not r_c:
                    row[f"ex_{hname}"] = row[f"ctrl_{hname}"] = row[f"diff_{hname}"] = np.nan
                else:
                    row[f"ex_{hname}"], row[f"ctrl_{hname}"] = r_ex, np.mean(r_c)
                    row[f"diff_{hname}"] = r_ex - np.mean(r_c)
            rows.append(row)

    res = pd.DataFrame(rows)
    if res.empty:
        sys.exit("No matches could be built - check prices.")
    res.to_csv(OUT_FILE, index=False)

    # ---------------- report ----------------
    lines = ["STEP 6 - EXCLUDED STOCKS vs EQUALLY-FALLEN STOCKS THAT STAYED (control group)",
             f"Each excluded stock is compared with the {K} SPUS stayers with the closest 12-month return before day 0.",
             "Difference = excluded return - average control return (no benchmark needed). Before trading costs.", ""]
    for date_type in DATE_TYPES:
        tag = "MAIN TEST" if date_type == "report_date" else "second view"
        r = res[res["date_type"] == date_type]
        lines += ["=" * 92, f"[{tag}]  Day 0 = {date_type}", "=" * 92]

        lines += ["", "  Balance check - 12-month return BEFORE day 0 (should be close):",
                  f"  {'Group':<26}{'N':>5}{'excluded':>11}{'controls':>11}"]
        for name, cause in GROUPS:
            g = r[r["cause"] == cause]
            if len(g):
                lines.append(f"  {name:<26}{len(g):>5}{g['trail12m_excluded'].mean() * 100:>10.1f}%"
                             f"{g['trail12m_controls'].mean() * 100:>10.1f}%")

        for name, cause in GROUPS:
            g = r[r["cause"] == cause]
            lines += ["", f"  {name}",
                      f"  {'':<34}" + "".join(f"{h:>9}" for h in HORIZONS)]
            def cells(fn):
                out = []
                for h in HORIZONS:
                    v = g[f"diff_{h}"].dropna() if fn != "ex" and fn != "ctrl" else g[f"{fn}_{h}"].dropna()
                    if not len(v):
                        out.append(f"{'-':>9}")
                    elif fn in ("ex", "ctrl", "mean"):
                        out.append(f"{v.mean() * 100:>9.1f}")
                    elif fn == "median":
                        out.append(f"{v.median() * 100:>9.1f}")
                    elif fn == "beat":
                        out.append(f"{(v > 0).mean() * 100:>9.1f}")
                return "".join(out)
            lines.append(f"  {'Excluded stocks, mean return %':<34}" + cells("ex"))
            lines.append(f"  {'Controls, mean return %':<34}" + cells("ctrl"))
            lines.append(f"  {'DIFFERENCE, mean %':<34}" + cells("mean"))
            lines.append(f"  {'DIFFERENCE, median %':<34}" + cells("median"))
            lines.append(f"  {'% excluded beating its controls':<34}" + cells("beat"))
            tcells = []
            for h in HORIZONS:
                t, nq = s5.quarter_tstat(g, f"diff_{h}")
                n = g[f"diff_{h}"].notna().sum()
                tcells.append(f"{n:>3}({nq:>2}) t={t:5.2f}" if not np.isnan(t) else f"{n:>3}({nq:>2}) t=  n/a")
            lines.append(f"  {'N (quarters), t-stat':<34}" + "".join(f"{c:>17}" for c in tcells))
        lines.append("")

    lines += [f"Exits that could not be matched (no price 12 months before, or < {K} stayers with prices): {unmatched}",
              f"Saved: {OUT_FILE}  (each row lists the {K} control tickers)"]
    summary = "\n".join(lines)
    print(summary)
    with open(os.path.join(OUT_DIR, "06_control_group.txt"), "w") as fh:
        fh.write(summary + "\n")


if __name__ == "__main__":
    main()