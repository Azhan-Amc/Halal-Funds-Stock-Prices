"""
Step 2 - Build the list of entry and exit events for every fund.

Reads data/holdings_quarterly.csv (from step 1) and compares each fund's
holdings report with its previous one:

    entry = stock held now, not held in the previous report
    exit  = stock held in the previous report, not held now

For every exit it also records whether the stock was still held by the
other funds at that time. Most important: still held by HLAL, which
screens debt against TOTAL ASSETS. A stock that leaves a market-cap-screened
fund (SPUS, MNZL, Amana) but stays in HLAL most likely left because its
PRICE fell, not because its debt grew.

Output:
    data/events.csv
    output/02_events_summary.txt

Run:  python3 02_build_entry_exit_events.py
"""

import os
import sys

import pandas as pd

HOLDINGS_FILE = os.path.join("data", "holdings_quarterly.csv")
EVENTS_FILE = os.path.join("data", "events.csv")
OUT_DIR = "output"

ASSETS_SCREEN_FUND = "HLAL"     # FTSE / Yasaar: debt / total assets
MAX_GAP_DAYS = 100              # reports further apart than this are flagged (missing quarter)
LOOKBACK_DAYS = 100             # how old another fund's report may be when checking "still held"


def security_id(row):
    """One stable ID per stock: CUSIP, else ISIN, else name."""
    for col in ("cusip", "isin"):
        v = str(row.get(col, "") or "").strip()
        if v and v.upper() not in ("NAN", "N/A", "000000000"):
            return v.upper()
    return "NAME:" + str(row.get("name", "")).strip().upper()


def load_holdings():
    if not os.path.exists(HOLDINGS_FILE):
        sys.exit(f"{HOLDINGS_FILE} not found. Run step 1 first.")
    df = pd.read_csv(HOLDINGS_FILE, dtype=str)
    df = df[df["asset_cat"] == "EC"].copy()          # equity (common stock) only
    df["sec_id"] = df.apply(security_id, axis=1)
    df["report_date"] = pd.to_datetime(df["report_date"])
    df["pct_value"] = pd.to_numeric(df["pct_value"], errors="coerce")
    # one row per fund / report / stock (a stock can appear twice, e.g. two lots)
    df = (df.groupby(["fund", "report_date", "sec_id"], as_index=False)
            .agg(name=("name", "first"), cusip=("cusip", "first"), isin=("isin", "first"),
                 ticker=("ticker", "first"), pct_value=("pct_value", "sum")))
    return df


def held_by(report_index, fund, sec_id, date):
    """Was sec_id held by `fund` in its latest report on or before `date`
    (and not older than LOOKBACK_DAYS)? Returns True / False / None (no report)."""
    dates, sets = report_index[fund]
    earlier = [d for d in dates if d <= date]
    if not earlier:
        return None
    last = earlier[-1]
    if (date - last).days > LOOKBACK_DAYS:
        return None
    return sec_id in sets[last]


def build_events(df):
    funds = sorted(df["fund"].unique())
    holdings_sets = {(f, d): set(g["sec_id"]) for (f, d), g in df.groupby(["fund", "report_date"])}
    info = df.set_index(["fund", "report_date", "sec_id"])
    report_index = {f: (sorted(d for (ff, d) in holdings_sets if ff == f),
                        {d: holdings_sets[(ff, d)] for (ff, d) in holdings_sets if ff == f})
                    for f in funds}
    events, gaps = [], []

    for fund in funds:
        dates = sorted(df.loc[df["fund"] == fund, "report_date"].unique())
        for prev, cur in zip(dates[:-1], dates[1:]):
            prev, cur = pd.Timestamp(prev), pd.Timestamp(cur)
            gap = (cur - prev).days
            if gap > MAX_GAP_DAYS:
                gaps.append(f"{fund}: {gap} days between {prev.date()} and {cur.date()} (missing report?)")
            before, after = holdings_sets[(fund, prev)], holdings_sets[(fund, cur)]
            for kind, ids, ref_date in (("entry", after - before, cur), ("exit", before - after, prev)):
                for sid in ids:
                    r = info.loc[(fund, ref_date, sid)]
                    ev = {
                        "fund": fund, "event": kind,
                        "prev_report": prev.date(), "report_date": cur.date(), "gap_days": gap,
                        "sec_id": sid, "name": r["name"], "cusip": r["cusip"], "isin": r["isin"],
                        "ticker": r["ticker"],
                        "weight_pct": round(r["pct_value"], 4),   # weight before exit / after entry
                    }
                    for other in funds:
                        if other != fund:
                            ev[f"in_{other}"] = held_by(report_index, other, sid, cur)
                    events.append(ev)
    return pd.DataFrame(events), gaps


def fmt_bool_share(s):
    known = s.dropna()
    if known.empty:
        return "   n/a"
    return f"{known.astype(bool).mean() * 100:5.1f}%"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    df = load_holdings()
    ev, gaps = build_events(df)
    if ev.empty:
        sys.exit("No events found (each fund needs at least 2 reports).")
    ev = ev.sort_values(["fund", "report_date", "event", "name"])
    ev.to_csv(EVENTS_FILE, index=False)

    lines = ["STEP 2 - ENTRY AND EXIT EVENTS (equity holdings, quarter to quarter)", ""]
    lines.append(f"{'Fund':<6} {'Reports':>7} {'Avg stocks':>10} {'Entries':>8} {'Exits':>6} "
                 f"{'Exits/qtr':>9} {'Exits still in ' + ASSETS_SCREEN_FUND:>20}")
    for fund in sorted(df["fund"].unique()):
        d = df[df["fund"] == fund]
        n_rep = d["report_date"].nunique()
        avg = d.groupby("report_date").size().mean()
        e = ev[ev["fund"] == fund]
        n_in, n_out = (e["event"] == "entry").sum(), (e["event"] == "exit").sum()
        col = f"in_{ASSETS_SCREEN_FUND}"
        share = fmt_bool_share(e.loc[e["event"] == "exit", col]) if col in e else "   n/a"
        per_q = n_out / max(n_rep - 1, 1)
        lines.append(f"{fund:<6} {n_rep:>7} {avg:>10.0f} {n_in:>8} {n_out:>6} {per_q:>9.1f} {share:>20}")

    # Candidate set: exits from market-cap-screened funds that the assets-screen fund still holds
    col = f"in_{ASSETS_SCREEN_FUND}"
    if col in ev:
        cand = ev[(ev["event"] == "exit") & (ev["fund"] != ASSETS_SCREEN_FUND) & (ev[col] == True)]
        lines += ["", f"Candidate exits (left a market-cap fund, still held by {ASSETS_SCREEN_FUND}): "
                      f"{len(cand)} events, {cand['sec_id'].nunique()} different stocks"]
        by_fund = cand.groupby("fund").size()
        for f, n in by_fund.items():
            lines.append(f"   {f}: {n}")

    lines += ["", f"Events saved: {len(ev):,}  ->  {EVENTS_FILE}"]
    if gaps:
        lines += ["", "Gaps between reports (check these):"] + ["  " + g for g in gaps]
    summary = "\n".join(lines)
    print(summary)
    with open(os.path.join(OUT_DIR, "02_events_summary.txt"), "w") as fh:
        fh.write(summary + "\n")


if __name__ == "__main__":
    main()