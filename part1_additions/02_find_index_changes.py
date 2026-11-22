"""
Step 1b: Find the stocks an ETF added and removed between filings.

Usage:
    python3 02_find_index_changes.py SPUS
    python3 02_find_index_changes.py HLAL

Needs data/holdings_<TICKER>.csv from 01_download_etf_holdings.py.

Output:
    data/changes_<TICKER>.csv   one row per addition or removal

Notes:
- Snapshots are usually quarterly, so a change listed for "2024-06-30" happened
  sometime between the previous snapshot and that date.
- "position_usd" for an addition is the value held at the first snapshot after the
  add. It is a rough size of what the fund was forced to buy (prices moved in between).
- A stock whose ID (CUSIP) changed after a merger or rename shows up as one removal
  plus one addition with the same name. Those rows are flagged "id_change".
"""

import re
import sys

import pandas as pd


def clean_name(s):
    s = str(s).upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\b(INC|CORP|CORPORATION|CO|LTD|PLC|CLASS [A-Z]|CL [A-Z]|THE)\b", " ", s)
    return " ".join(s.split())


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 02_find_index_changes.py TICKER")
    ticker = sys.argv[1].upper()
    df = pd.read_csv("data/holdings_{}.csv".format(ticker), dtype={"cusip": str})

    # Keep common stocks only (drop cash, money market, etc.)
    if df["asset_cat"].notna().any():
        df = df[df["asset_cat"] == "EC"].copy()

    # Stock ID: CUSIP, else ISIN, else name
    df["key"] = df["cusip"].where(df["cusip"].notna() & (df["cusip"] != "000000000"),
                                  df["isin"].fillna(df["name"]))
    df["clean"] = df["name"].map(clean_name)

    # One row per stock per date (a stock can appear twice in one filing)
    df = df.groupby(["report_date", "key"], as_index=False).agg(
        name=("name", "first"), ticker=("ticker", "first"), clean=("clean", "first"),
        pct=("pct", "sum"), value_usd=("value_usd", "sum"),
        net_assets=("net_assets", "first"))

    dates = sorted(df["report_date"].unique())
    snaps = {d: df[df["report_date"] == d].set_index("key") for d in dates}

    summary, changes = [], []
    for prev, cur in zip(dates[:-1], dates[1:]):
        a, b = snaps[prev], snaps[cur]
        added = b.index.difference(a.index)
        removed = a.index.difference(b.index)

        add_names = set(b.loc[added, "clean"])
        rem_names = set(a.loc[removed, "clean"])
        same = add_names & rem_names

        for k in added:
            r = b.loc[k]
            changes.append({
                "period_start": prev, "period_end": cur, "change": "add",
                "name": r["name"], "ticker": r["ticker"], "cusip": k,
                "weight_pct": r["pct"], "position_usd": r["value_usd"],
                "id_change": r["clean"] in same,
            })
        for k in removed:
            r = a.loc[k]
            changes.append({
                "period_start": prev, "period_end": cur, "change": "remove",
                "name": r["name"], "ticker": r["ticker"], "cusip": k,
                "weight_pct": r["pct"], "position_usd": r["value_usd"],
                "id_change": r["clean"] in same,
            })
        summary.append({
            "period_end": cur,
            "holdings": len(b),
            "net_assets_musd": round(b["net_assets"].iloc[0] / 1e6, 1),
            "adds": int(sum(1 for k in added if b.loc[k, "clean"] not in same)),
            "removes": int(sum(1 for k in removed if a.loc[k, "clean"] not in same)),
            "id_changes": len(same),
        })

    ch = pd.DataFrame(changes, columns=[
        "period_start", "period_end", "change", "name", "ticker", "cusip",
        "weight_pct", "position_usd", "id_change"])
    out = "data/changes_{}.csv".format(ticker)
    ch.to_csv(out, index=False)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 2000)
    pd.set_option("display.max_colwidth", 40)

    print("=" * 70)
    print("{}: snapshots {} (first {}, last {})".format(
        ticker, len(dates), dates[0], dates[-1]))
    print("=" * 70)
    print("\nChanges per period (ID changes not counted as adds/removes):\n")
    print(pd.DataFrame(summary).to_string(index=False))

    real = ch[~ch["id_change"]] if len(ch) else ch
    for kind in ["add", "remove"]:
        part = real[real["change"] == kind]
        print("\n{} ({}):\n".format("ADDITIONS" if kind == "add" else "REMOVALS", len(part)))
        if len(part):
            show = part[["period_end", "ticker", "name", "weight_pct", "position_usd"]].copy()
            show["position_usd"] = (show["position_usd"] / 1e6).round(2)
            show = show.rename(columns={"position_usd": "position_musd"})
            print(show.to_string(index=False))

    adds = real[real["change"] == "add"]
    print("\nTotals: {} additions, {} removals, {} ID changes".format(
        len(adds), int((real["change"] == "remove").sum()),
        int(ch["id_change"].sum() // 2) if len(ch) else 0))
    if len(adds):
        print("Forced buy per addition (position at next snapshot), $M:")
        print("  median {:.2f}   mean {:.2f}   max {:.2f}".format(
            adds["position_usd"].median() / 1e6,
            adds["position_usd"].mean() / 1e6,
            adds["position_usd"].max() / 1e6))
    print("\nSaved", out)


if __name__ == "__main__":
    main()