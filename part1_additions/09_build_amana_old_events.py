"""
Step 3b (part 3): Turn Amana's 2004-2019 holdings into additions/removals with tickers.

Usage:
    python3 09_build_amana_old_events.py

Reads:  data/holdings_old_AMAGX.csv, data/holdings_old_AMANX.csv (from 08), amana_name_map.csv
Writes: data/holdings_old_mapped.csv   holdings with a ticker (or blank = company no longer trades)
        data/events_old_amana.csv      one row per addition/removal, 2004-2019

- Names are matched to tickers with amana_name_map.csv (first matching pattern wins).
  Companies that no longer trade have no ticker: their events are kept but marked mapped=False.
- Public date = the day the filing reached the SEC (actual filing date, not an estimate).
- Amana follow-through: for each addition, shares held at the next snapshot vs the first.
"""

import re

import pandas as pd


def clean(name):
    n = str(name).strip()
    n = re.sub(r"\(\d\)$", "", n)               # "Trimble(1)"
    n = re.sub(r"(?<=[A-Za-z.])1$", "", n)      # "Adobe1" (but not "Phillips 66")
    n = re.sub(r"[¹²³]+$", "", n)
    return " ".join(n.split()).lower()


def main():
    rules = pd.read_csv("amana_name_map.csv", dtype=str, keep_default_na=False)
    rules = [(re.compile(p, re.I), t.strip() or None, note) for p, t, note in rules.values]

    h = pd.concat([pd.read_csv("data/holdings_old_AMAGX.csv"), pd.read_csv("data/holdings_old_AMANX.csv")])
    h["clean"] = h["name"].map(clean)
    tick, matched, rule_id = [], [], []
    for c in h["clean"]:
        for i, (pat, t, _) in enumerate(rules):
            if pat.search(c):
                tick.append(t); matched.append(True); rule_id.append(i); break
        else:
            tick.append(None); matched.append(False); rule_id.append(-1)
    h["ticker"], h["rule_matched"], h["rule_id"] = tick, matched, rule_id
    if not all(matched):
        print("WARNING: names with no rule:", sorted(set(h.loc[~h["rule_matched"], "clean"])))
    # one key per company: ticker if it trades, otherwise the matched rule (so spelling variants
    # of the same dead company don't look like a removal + an addition)
    h["key"] = h["ticker"].fillna("RULE:" + h["rule_id"].astype(str) + ":" + h["clean"].where(h["rule_id"] < 0, ""))
    h = h.groupby(["fund", "report_date", "key"], as_index=False).agg(
        name=("name", "first"), ticker=("ticker", "first"), shares=("shares", "sum"),
        value_usd=("value_usd", "sum"), pct=("pct", "sum"), filing_date=("filing_date", "first"))
    h.to_csv("data/holdings_old_mapped.csv", index=False)

    events = []
    for fund, g in h.groupby("fund"):
        dates = sorted(g["report_date"].unique())
        snap = {d: g[g["report_date"] == d].set_index("key") for d in dates}
        for i in range(1, len(dates)):
            prev, cur = dates[i - 1], dates[i]
            a, b = snap[prev], snap[cur]
            for k in b.index.difference(a.index):
                r = b.loc[k]
                nxt = None
                if i + 1 < len(dates) and k in snap[dates[i + 1]].index:
                    nxt = snap[dates[i + 1]].loc[k, "shares"] / r["shares"] - 1
                elif i + 1 < len(dates):
                    nxt = -1.0
                events.append({"fund": fund, "period_start": prev, "period_end": cur,
                               "public_date": r["filing_date"], "change": "add", "ticker": r["ticker"],
                               "name": r["name"], "weight_pct": r["pct"],
                               "position_musd": round(r["value_usd"] / 1e6, 3),
                               "mapped": pd.notna(r["ticker"]), "amana_shares_change_next_q": nxt})
            for k in a.index.difference(b.index):
                r = a.loc[k]
                events.append({"fund": fund, "period_start": prev, "period_end": cur,
                               "public_date": b["filing_date"].iloc[0], "change": "remove",
                               "ticker": r["ticker"], "name": r["name"], "weight_pct": r["pct"],
                               "position_musd": round(r["value_usd"] / 1e6, 3),
                               "mapped": pd.notna(r["ticker"]), "amana_shares_change_next_q": None})
    ev = pd.DataFrame(events)
    ev.to_csv("data/events_old_amana.csv", index=False)

    pd.set_option("display.width", 200)
    print("Snapshots per fund:", h.groupby("fund")["report_date"].nunique().to_dict())
    t = ev.groupby(["fund", "change"]).agg(events=("name", "size"), with_ticker=("mapped", "sum"))
    t["without_ticker_%"] = (100 * (1 - t["with_ticker"] / t["events"])).round(0)
    print("\nEVENTS 2004-2019:\n")
    print(t.to_string())
    print("\nAmana follow-through on additions (shares one snapshot later vs first):")
    for fund, g in ev[(ev["change"] == "add")].groupby("fund"):
        x = g["amana_shares_change_next_q"].dropna()
        print("  {}: {} adds | kept buying (>5%): {:.0f}% | median {:+.1f}% | sold out next: {:.0f}%".format(
            fund, len(x), 100 * (x > 0.05).mean(), 100 * x.median(), 100 * (x <= -0.999).mean()))
    print("\nSaved data/holdings_old_mapped.csv and data/events_old_amana.csv")


if __name__ == "__main__":
    main()
