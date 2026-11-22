"""
Step 1c: Combine the additions of all halal funds and look for "waves":
stocks that several funds added one after another.

Usage (after running 01 and 02 for each fund):
    python3 03_combine_all_funds.py

Reads every data/changes_<TICKER>.csv that exists.

Output:
    data/additions_all_funds.csv   one row per stock, with which funds added it and when

Notes:
- Each fund files on its own quarter-end dates, so dates are only accurate to
  about 3 months. "days_first_to_last" is a rough gap, not an exact one.
- A stock added, removed and added again by the same fund counts once per fund
  (its first addition).
"""

import glob
import os

import pandas as pd


def main():
    files = sorted(glob.glob("data/changes_*.csv"))
    if not files:
        raise SystemExit("No data/changes_*.csv files found. Run 01 and 02 first.")

    parts = []
    for f in files:
        fund = os.path.basename(f)[len("changes_"):-len(".csv")]
        d = pd.read_csv(f, dtype={"cusip": str})
        d = d[(d["change"] == "add") & (~d["id_change"].astype(bool))].copy()
        d["fund"] = fund
        parts.append(d)
        print("{:<6} {:>4} additions".format(fund, len(d)))
    adds = pd.concat(parts, ignore_index=True)
    adds["period_end"] = pd.to_datetime(adds["period_end"])

    # First addition of each stock by each fund
    first = (adds.sort_values("period_end")
                 .groupby(["cusip", "fund"], as_index=False).first())

    rows = []
    for cusip, g in first.groupby("cusip"):
        g = g.sort_values("period_end")
        rows.append({
            "cusip": cusip,
            "ticker": g["ticker"].dropna().iloc[0] if g["ticker"].notna().any() else None,
            "name": g["name"].iloc[0],
            "n_funds": len(g),
            "order": " -> ".join("{}({})".format(f, d.strftime("%Y-%m"))
                                 for f, d in zip(g["fund"], g["period_end"])),
            "first_add": g["period_end"].min().date(),
            "last_add": g["period_end"].max().date(),
            "days_first_to_last": (g["period_end"].max() - g["period_end"].min()).days,
            "total_forced_buy_musd": round(g["position_usd"].sum() / 1e6, 2),
        })
    out = pd.DataFrame(rows).sort_values(["n_funds", "first_add"], ascending=[False, True])
    out.to_csv("data/additions_all_funds.csv", index=False)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 2000)
    pd.set_option("display.max_colwidth", 60)

    print("\nStocks added, by number of funds that added them:\n")
    counts = out["n_funds"].value_counts().sort_index()
    print(pd.DataFrame({"n_funds": counts.index, "stocks": counts.values}).to_string(index=False))

    multi = out[out["n_funds"] >= 2]
    print("\nWAVES: stocks added by 2+ funds ({}):\n".format(len(multi)))
    if len(multi):
        print(multi[["ticker", "name", "n_funds", "order", "days_first_to_last",
                     "total_forced_buy_musd"]].to_string(index=False))
        print("\nGap from first to last fund (days, approx): median {:.0f}, mean {:.0f}".format(
            multi["days_first_to_last"].median(), multi["days_first_to_last"].mean()))
        print("Combined forced buy per wave stock ($M): median {:.2f}, max {:.2f}".format(
            multi["total_forced_buy_musd"].median(), multi["total_forced_buy_musd"].max()))

    print("\nSaved data/additions_all_funds.csv")


if __name__ == "__main__":
    main()