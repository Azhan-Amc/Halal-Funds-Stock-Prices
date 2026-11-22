"""
Step 3b (part 2): Parse Amana's 2003-2019 filings (N-Q, N-CSR, N-CSRS) into holdings tables.

Usage:
    python3 08_parse_amana_old_holdings.py

Reads:  data/raw_amana_old/*.htm, data/raw_amana_old/filings_list.csv
Writes: data/holdings_old_AMANX.csv, data/holdings_old_AMAGX.csv
        data/old_parse_check.csv   one line per filing and fund: did the parsed holdings add up to the
                                   "Total investments" line printed in the filing?

How it reads a filing:
  - Every table row is read in document order.
  - Each fund's holdings list ends with a "Total investments" row, and the funds always come in the
    same order: Income, Growth, then Developing World and Participation (later years).
  - A holding row = a company name followed by at least 3 numbers:
      shares, [cost], market value, % of assets   (cost only in annual/semi-annual reports)
  - Check: the parsed market values must add up to the "Total investments" market value.
"""

import glob
import io
import os
import re

import pandas as pd

RAW = os.path.join("data", "raw_amana_old")
FUND_ORDER = ["AMANX", "AMAGX", "AMDWX", "AMAPX"]   # Income, Growth, Developing World, Participation

NOT_A_COMPANY = re.compile(
    r"(^(sub-?\s?)?total\b(?!\s*(ads|adr|s\.?a\.?|se|energies)\b))|\b(net|gain|loss|investments?|assets?|liabilit|receivable|payable|"
    r"dividends?|expenses?|fees?|shares outstanding|value|cost|common stocks?|issue|cash|"
    r"income fund|growth fund|developing world|participation fund|percentage|number of)\b", re.I)
NUM = re.compile(r"^\(?\$?\s*-?[\d,]+(\.\d+)?\s*%?\)?$")


def to_num(s):
    s = s.replace("$", "").replace(",", "").replace("%", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def doc_rows(path):
    html = open(path, encoding="latin-1").read()
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:
        return []
    out = []
    for t in tables:
        for r in t.values.tolist():
            cells = []
            for c in r:
                c = re.sub(r"\s+", " ", str(c)).strip()
                if c and c != "nan" and (not cells or cells[-1] != c):
                    cells.append(c)
            if cells:
                out.append(cells)
    return out


def parse_row(cells):
    """Return (kind, data). kind = 'holding', 'total' or None."""
    first = cells[0]
    nums_raw = [c for c in cells[1:] if NUM.match(c)]
    nums = [to_num(c) for c in nums_raw]
    nums = [n for n in nums if n is not None]
    if re.match(r"^total(\s+investments)?$", first, re.I) and nums:
        if len(nums) >= 2 and nums[-1] <= 100:
            return "total", {"value": nums[-2]}
        return "total", {"value": max(nums)}
    if NUM.match(first) or not re.search(r"[A-Za-z]", first) or NOT_A_COMPANY.search(first):
        return None, None
    if len(nums) < 3:
        return None, None
    pct = nums[-1]
    if not (0 <= pct <= 100):
        return None, None
    value, shares = nums[-2], nums[0]
    if value < 1000 or shares <= 0 or not float(shares).is_integer():
        return None, None
    name = re.sub(r"[¹²³⁴⁵⁶⁷⁸⁹*†‡]+$", "", first).strip()
    return "holding", {"name": name, "shares": shares, "value_usd": value, "pct": pct}


def parse_file(path):
    blocks, cur = [], []
    for cells in doc_rows(path):
        kind, d = parse_row(cells)
        if kind == "holding":
            cur.append(d)
        elif kind == "total":
            blocks.append((cur, d["value"]))
            cur = []
    return blocks   # rows after the last total are dropped (not part of a schedule)


def main():
    lst = pd.read_csv(os.path.join(RAW, "filings_list.csv"))
    lst["amend"] = lst["form"].str.endswith("/A")
    rows, checks = [], []
    for date, g in lst.sort_values(["date", "amend"]).groupby("date"):
        chosen = None
        for _, f in g.iterrows():                      # originals first, amendments as fallback
            blocks = parse_file(os.path.join(RAW, f["file"]))
            if len(blocks) >= 2:
                chosen = (f, blocks)
                break
        if chosen is None:
            checks.append({"date": date, "fund": "-", "status": "no schedules found"})
            continue
        f, blocks = chosen
        for fund, (hold, total) in zip(FUND_ORDER, blocks):
            if fund not in ("AMANX", "AMAGX"):
                continue
            s = sum(h["value_usd"] for h in hold)
            diff = (s - total) / total * 100 if total else float("nan")
            checks.append({"date": date, "fund": fund, "file": f["file"], "filing_date": f["filingDate"],
                           "holdings": len(hold), "sum_value_musd": round(s / 1e6, 2),
                           "total_line_musd": round(total / 1e6, 2), "diff_%": round(diff, 2),
                           "status": "ok" if abs(diff) <= 2 else "CHECK"})
            for h in hold:
                rows.append(dict(h, fund=fund, report_date=date, filing_date=f["filingDate"],
                                 form=f["form"], total_investments=total))

    ck = pd.DataFrame(checks)
    ck.to_csv(os.path.join("data", "old_parse_check.csv"), index=False)
    df = pd.DataFrame(rows)
    for fund in ("AMANX", "AMAGX"):
        df[df["fund"] == fund].to_csv(os.path.join("data", "holdings_old_{}.csv".format(fund)), index=False)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 400)
    print(ck.to_string(index=False))
    print("\nStatus counts:", ck["status"].value_counts().to_dict())


if __name__ == "__main__":
    main()
