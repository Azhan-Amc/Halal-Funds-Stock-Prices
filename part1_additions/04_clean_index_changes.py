"""
Step 1d: Clean the additions/removals of all funds and rebuild the waves table.

Usage (after run_step1_all_funds.py):
    python3 04_clean_index_changes.py

Reads:  data/changes_<FUND>.csv, data/holdings_<FUND>.csv
Writes: data/events_clean.csv   every add/remove, with flags and a "usable" column
        data/waves_clean.csv    stocks added by 2+ independent screens

What it fixes:
  1. Missing tickers (old SPUS/SPRE/KWIN filings): filled from the same CUSIP in any fund's holdings.
  2. Missed ID changes: an add and a remove of the same ticker (or same name) in the same
     fund and period = one stock whose ID changed, not a real change.
  3. Second share classes (LEN/B, LBRDA, UA, NWS...): only the bigger line is kept.
  4. Tiny/junk rows (weight under 0.001%).
  5. Non-US listings (Tokyo, Paris, Istanbul...): flagged; the strategy trades US listings only.
  6. Known one-off rule-change batches: flagged separately (they are not normal compliance flips).
  7. Waves are counted by independent SCREEN FAMILY, not by fund:
       S&P Shariah (SPUS, SPTE, SPRE) | FTSE/Yasaar (HLAL) | Russell-IdealRatings (MNZL)
       Wahed (KWIN) | Saturna/Amana (AMAGX, AMANX)
     and a fund only counts if it already existed when the wave started
     (MNZL "adding" stocks HLAL added in 2020 is not a wave).

Spin-offs and mergers need price data to detect, so they are flagged in Step 2.
"""

import glob
import os
import re

import pandas as pd

FAMILY = {"SPUS": "S&P", "SPTE": "S&P", "SPRE": "S&P", "HLAL": "FTSE", "MNZL": "Russell-IR",
          "KWIN": "Wahed", "AMAGX": "Saturna", "AMANX": "Saturna"}
PASSIVE = {"SPUS", "SPTE", "SPRE", "HLAL", "MNZL", "KWIN"}

# One-off batches caused by a methodology change, not by companies' ratios moving.
# SPUS May 2024: 53 adds in one quarter (AMZN, ABBV, ACN, MCK, COR, CAH...), consistent with
# S&P dropping its accounts-receivable screen (announced Aug 2023). Inferred, not confirmed.
RULE_CHANGE_BATCHES = {("SPUS", "2024-05-31")}

US_TICKER = re.compile(r"^[A-Z]{1,5}([./][A-Z])?$")


def clean_name(s):
    s = str(s).upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\b(INC|CORP|CORPORATION|CO|COS|LTD|PLC|NV|SA|AG|LLC|HOLDINGS?|GROUP|THE|"
               r"CLASS [A-Z]|CL [A-Z])\b", " ", s)
    return " ".join(s.split())


def norm_ticker(t):
    if not isinstance(t, str) or not t.strip():
        return None
    t = t.strip().upper()
    t = re.sub(r"\s+US$", "", t)          # "AAPL US" -> "AAPL"
    t = re.sub(r"-W[I]?$", "", t)         # when-issued "BBWI-W" -> "BBWI"
    return t


def main():
    # ---- load
    ch, hold = [], []
    for f in sorted(glob.glob("data/changes_*.csv")):
        fund = os.path.basename(f)[8:-4]
        d = pd.read_csv(f, dtype={"cusip": str, "ticker": str})
        d["fund"] = fund
        ch.append(d)
        h = pd.read_csv(f.replace("changes_", "holdings_"), dtype={"cusip": str, "ticker": str})
        h["fund"] = fund
        hold.append(h)
    ch = pd.concat(ch, ignore_index=True)
    hold = pd.concat(hold, ignore_index=True)
    n_raw = len(ch)

    # ---- 1. fill tickers from any fund's holdings with the same CUSIP
    hold["t"] = hold["ticker"].map(norm_ticker)
    known = hold[hold["t"].notna() & hold["t"].str.match(US_TICKER)]
    cusip_map = known.groupby("cusip")["t"].agg(lambda s: s.value_counts().index[0])
    ch["ticker_raw"] = ch["ticker"]
    ch["ticker"] = ch["ticker"].map(norm_ticker)
    ch["ticker"] = ch["ticker"].where(ch["ticker"].notna(), ch["cusip"].map(cusip_map))
    ch["clean"] = ch["name"].map(clean_name)

    # ---- 2. extra ID changes: same ticker or same name added AND removed in same fund+period
    ch["id_change"] = ch["id_change"].astype(bool)
    for (fund, per), g in ch.groupby(["fund", "period_end"]):
        a, r = g[g["change"] == "add"], g[g["change"] == "remove"]
        both_t = set(a["ticker"].dropna()) & set(r["ticker"].dropna())
        both_n = set(a["clean"]) & set(r["clean"])
        hit = g.index[g["ticker"].isin(both_t) | g["clean"].isin(both_n)]
        ch.loc[hit, "id_change"] = True

    # ---- 3. second share classes: same company name, same fund/period/direction
    ch["second_class"] = False
    for _, g in ch[~ch["id_change"]].groupby(["fund", "period_end", "change", "clean"]):
        if len(g) > 1:
            keep = g["weight_pct"].idxmax()
            ch.loc[g.index.drop(keep), "second_class"] = True

    # ---- 4/5/6. flags
    ch["tiny"] = ch["weight_pct"].fillna(0) < 0.001
    ch["us_listed"] = ch["ticker"].fillna("").str.match(US_TICKER)
    ch["rule_change_batch"] = [(f, p) in RULE_CHANGE_BATCHES for f, p in zip(ch["fund"], ch["period_end"])]
    ch["family"] = ch["fund"].map(FAMILY)
    ch["passive"] = ch["fund"].isin(PASSIVE)

    # size if the fund bought the same weight today (latest net assets)
    latest_na = hold.sort_values("report_date").groupby("fund")["net_assets"].last()
    ch["buy_at_today_aum_musd"] = (ch["weight_pct"] / 100 * ch["fund"].map(latest_na) / 1e6).round(3)
    ch["position_musd"] = (ch["position_usd"] / 1e6).round(3)

    ch["usable"] = (~ch["id_change"]) & (~ch["second_class"]) & (~ch["tiny"]) & ch["us_listed"]

    cols = ["fund", "family", "passive", "period_start", "period_end", "change", "ticker", "name",
            "cusip", "weight_pct", "position_musd", "buy_at_today_aum_musd", "usable",
            "id_change", "second_class", "tiny", "us_listed", "rule_change_batch", "ticker_raw"]
    ev = ch[cols].sort_values(["period_end", "fund", "change", "ticker"])
    ev.to_csv("data/events_clean.csv", index=False)

    # ---- 7. waves by screen family, only funds alive when the wave started
    first_snap = hold.groupby("fund")["report_date"].min()
    adds = ev[ev["usable"] & (ev["change"] == "add")].copy()
    adds["period_end"] = pd.to_datetime(adds["period_end"])
    rows = []
    for t, g in adds.groupby("ticker"):
        g = g.sort_values("period_end")
        start = g["period_end"].iloc[0]
        g = g[pd.to_datetime(g["fund"].map(first_snap)) < start]  # fund existed before wave start
        if g.empty:
            continue
        fam = g.groupby("family").agg(date=("period_end", "min"),
                                      buy=("position_musd", "sum"),
                                      funds=("fund", lambda s: "+".join(sorted(set(s)))))
        fam = fam.sort_values("date")
        rows.append({
            "ticker": t, "name": g["name"].iloc[0], "n_families": len(fam),
            "order": " -> ".join("{}[{}]({})".format(f, r.funds, r.date.strftime("%Y-%m"))
                                 for f, r in fam.iterrows()),
            "first_add": fam["date"].min().date(), "last_add": fam["date"].max().date(),
            "days_first_to_last": (fam["date"].max() - fam["date"].min()).days,
            "forced_buy_musd": round(g[g["passive"]]["position_musd"].sum(), 2),
            "amana_buy_musd": round(g[~g["passive"]]["position_musd"].sum(), 2),
            "in_rule_change_batch": bool(g["rule_change_batch"].any()),
        })
    waves = pd.DataFrame(rows).sort_values(["n_families", "first_add"], ascending=[False, True])
    waves.to_csv("data/waves_clean.csv", index=False)

    # ---- report
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    pd.set_option("display.max_colwidth", 90)
    print("=" * 80)
    print("CLEANING: {} raw rows".format(n_raw))
    print("=" * 80)
    print("ID changes (now): {}   second share classes: {}   tiny: {}   non-US/unknown ticker: {}".format(
        int(ch["id_change"].sum()), int(ch["second_class"].sum()), int(ch["tiny"].sum()),
        int((~ch["us_listed"]).sum())))
    print("Tickers filled from CUSIP: {}".format(int(ch["ticker_raw"].isna().sum() - ch["ticker"].isna().sum())))

    print("\nUSABLE EVENTS PER FUND (US-listed, real changes):\n")
    u = ev[ev["usable"]]
    tab = u.groupby(["fund", "change"]).size().unstack(fill_value=0)
    a = u[u["change"] == "add"].groupby("fund")
    tab["add_median_musd"] = a["position_musd"].median().round(2)
    tab["add_mean_musd"] = a["position_musd"].mean().round(2)
    tab["add_max_musd"] = a["position_musd"].max().round(2)
    tab["add_median_at_today_aum_musd"] = a["buy_at_today_aum_musd"].median().round(2)
    tab["latest_aum_musd"] = (latest_na / 1e6).round(0)
    print(tab.to_string())

    b = u[u["rule_change_batch"]]
    print("\nRULE-CHANGE BATCH (kept, but flagged): {} events, ${:.1f}M bought".format(
        len(b), b["position_musd"].sum()))

    print("\nWAVES BY INDEPENDENT SCREEN FAMILY:\n")
    cnt = waves["n_families"].value_counts().sort_index()
    print(pd.DataFrame({"n_families": cnt.index, "stocks": cnt.values}).to_string(index=False))
    multi = waves[waves["n_families"] >= 2]
    print("\nGap first -> last family (days): median {:.0f}, mean {:.0f}".format(
        multi["days_first_to_last"].median(), multi["days_first_to_last"].mean()))
    print("Forced (passive) buy per wave stock ($M): median {:.2f}, max {:.2f}".format(
        multi["forced_buy_musd"].median(), multi["forced_buy_musd"].max()))
    print("\nStocks reached by 3+ families:\n")
    print(waves[waves["n_families"] >= 3][["ticker", "name", "order", "days_first_to_last",
                                           "forced_buy_musd", "amana_buy_musd"]].to_string(index=False))
    print("\nSaved data/events_clean.csv and data/waves_clean.csv")


if __name__ == "__main__":
    main()