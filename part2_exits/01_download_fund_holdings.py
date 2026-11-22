"""
Step 1 - Download the quarterly holdings history of halal funds from SEC EDGAR.

Every US fund files form N-PORT each quarter with its full list of holdings.
This script finds those filings for each fund below, reads the holdings,
and saves them in one table:

    data/holdings_quarterly.csv
    output/01_holdings_summary.txt

Raw filings are cached in data/nport_raw/, so running it again is fast.

Before running: put your name and email in SEC_CONTACT (SEC requires it).
Run:  python3 01_download_fund_holdings.py
"""

import json
import os
import sys
import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
SEC_CONTACT = "Your Name your-email@example.com"   # <-- edit this line

FUNDS = {
    # ticker : what it is / how it screens debt (to verify in step 2)
    "SPUS": "SP Funds S&P 500 Sharia Industry Exclusions ETF (S&P, market-cap screen)",
    "HLAL": "Wahed FTSE USA Shariah ETF (FTSE, total-assets screen)",
    "MNZL": "Manzil Russell Halal USA Broad Market ETF",
    "AMAGX": "Amana Growth Fund (Saturna)",
    "AMANX": "Amana Income Fund (Saturna)",
}

DATA_DIR = "data"
RAW_DIR = os.path.join(DATA_DIR, "nport_raw")
OUT_DIR = "output"
PAUSE = 0.15          # seconds between SEC requests (SEC limit is 10 per second)

session = requests.Session()


# ----------------------------------------------------------------------------
# SEC access
# ----------------------------------------------------------------------------
def sec_get(url, stream=False):
    """GET with SEC headers, polite pause and a few retries."""
    for attempt in range(5):
        time.sleep(PAUSE)
        try:
            r = session.get(url, headers={"User-Agent": SEC_CONTACT}, timeout=30, stream=stream)
        except requests.RequestException as e:
            print(f"   network error ({e}), retrying...")
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r
        if r.status_code in (429, 500, 502, 503):
            time.sleep(2 * (attempt + 1))
            continue
        return r            # 404 etc.: let the caller decide
    return None


def find_series(tickers):
    """Map each fund ticker to (trust CIK, series ID) using SEC's fund ticker list."""
    r = sec_get("https://www.sec.gov/files/company_tickers_mf.json")
    if r is None or r.status_code != 200:
        sys.exit("Could not download SEC fund ticker list. Check SEC_CONTACT and your internet.")
    table = r.json()
    cols = table["fields"]
    rows = [dict(zip(cols, row)) for row in table["data"]]
    found = {}
    for t in tickers:
        match = [row for row in rows if str(row["symbol"]).upper() == t]
        if match:
            found[t] = (int(match[0]["cik"]), match[0]["seriesId"])
    return found


def list_nport_filings(cik):
    """All NPORT-P filings of a trust (recent list + older pages)."""
    r = sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    if r is None or r.status_code != 200:
        return []
    sub = r.json()
    blocks = [sub["filings"]["recent"]]
    for page in sub["filings"].get("files", []):
        rp = sec_get(f"https://data.sec.gov/submissions/{page['name']}")
        if rp is not None and rp.status_code == 200:
            blocks.append(rp.json())

    filings = []
    for b in blocks:
        for i, form in enumerate(b["form"]):
            if form == "NPORT-P":
                filings.append({
                    "accession": b["accessionNumber"][i],
                    "filing_date": b["filingDate"][i],
                    "report_date": b["reportDate"][i],
                    "doc": os.path.basename(b["primaryDocument"][i]) or "primary_doc.xml",
                })
    return filings


def series_of_filing(cik, f):
    """Read only the top of a filing to learn which fund (series) it belongs to.
    A trust files one N-PORT per fund, so most filings of a trust are other funds."""
    acc = f["accession"].replace("-", "")
    cache = os.path.join(RAW_DIR, f"{cik}_{acc}.series")
    if os.path.exists(cache):
        return open(cache).read().strip()

    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{f['doc']}"
    r = sec_get(url, stream=True)
    if r is None or r.status_code != 200:
        return ""
    head = b""
    for chunk in r.iter_content(4096):
        head += chunk
        if b"</seriesId>" in head or len(head) > 200_000:
            break
    r.close()
    text = head.decode("utf-8", errors="ignore")
    series = ""
    if "<seriesId>" in text and "</seriesId>" in text:
        series = text.split("<seriesId>", 1)[1].split("</seriesId>", 1)[0].strip()
    with open(cache, "w") as fh:
        fh.write(series)
    return series


def download_filing(cik, f):
    """Full N-PORT XML of one filing (cached)."""
    acc = f["accession"].replace("-", "")
    path = os.path.join(RAW_DIR, f"{cik}_{acc}.xml")
    if os.path.exists(path):
        return open(path, "rb").read()
    r = sec_get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{f['doc']}")
    if r is None or r.status_code != 200:
        return None
    with open(path, "wb") as fh:
        fh.write(r.content)
    return r.content


# ----------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------
def strip_ns(tag):
    return tag.split("}", 1)[-1]


def child(el, name):
    for c in el:
        if strip_ns(c.tag) == name:
            return c
    return None


def text_of(el, name):
    c = child(el, name)
    return c.text.strip() if c is not None and c.text else ""


def parse_holdings(xml_bytes):
    """Return (report_date, list of holdings) from an N-PORT XML."""
    root = ET.fromstring(xml_bytes)
    report_date = ""
    holdings = []
    for el in root.iter():
        tag = strip_ns(el.tag)
        if tag == "repPdDate" and el.text:
            report_date = el.text.strip()
        elif tag == "invstOrSec":
            isin, ticker = "", ""
            ids = child(el, "identifiers")
            if ids is not None:
                for i in ids:
                    t = strip_ns(i.tag)
                    if t == "isin":
                        isin = i.get("value", "")
                    elif t == "ticker":
                        ticker = i.get("value", "")
            holdings.append({
                "name": text_of(el, "name"),
                "title": text_of(el, "title"),
                "cusip": text_of(el, "cusip"),
                "isin": isin,
                "ticker": ticker,
                "balance": text_of(el, "balance"),
                "units": text_of(el, "units"),
                "value_usd": text_of(el, "valUSD"),
                "pct_value": text_of(el, "pctVal"),
                "asset_cat": text_of(el, "assetCat"),
                "country": text_of(el, "invCountry"),
            })
    return report_date, holdings


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    if "your_email@example.com" in SEC_CONTACT:
        sys.exit("Edit SEC_CONTACT at the top of the script (your name and email) first.")
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    print("Looking up funds in SEC ticker list...")
    series_map = find_series(list(FUNDS))
    log = []

    all_rows = []
    for ticker in FUNDS:
        if ticker not in series_map:
            msg = f"{ticker}: NOT FOUND in SEC fund list (may not file N-PORT, e.g. non-US fund)"
            print(msg)
            log.append(msg)
            continue
        cik, series_id = series_map[ticker]
        print(f"\n{ticker}: trust CIK {cik}, series {series_id}")
        filings = list_nport_filings(cik)
        print(f"   trust has {len(filings)} N-PORT filings in total; finding the ones for {ticker}...")

        mine = []
        for n, f in enumerate(filings, 1):
            if series_of_filing(cik, f) == series_id:
                mine.append(f)
            if n % 200 == 0:
                print(f"   checked {n}/{len(filings)}")
        print(f"   {len(mine)} filings belong to {ticker}")

        for f in mine:
            xml_bytes = download_filing(cik, f)
            if xml_bytes is None:
                log.append(f"{ticker}: failed to download {f['accession']}")
                continue
            try:
                rep_date, holdings = parse_holdings(xml_bytes)
            except ET.ParseError:
                log.append(f"{ticker}: could not read {f['accession']}")
                continue
            for h in holdings:
                h.update({
                    "fund": ticker,
                    "series_id": series_id,
                    "report_date": rep_date or f["report_date"],
                    "filing_date": f["filing_date"],
                    "accession": f["accession"],
                })
                all_rows.append(h)

    if not all_rows:
        sys.exit("No holdings downloaded. See messages above.")

    df = pd.DataFrame(all_rows)
    # If a fund filed the same quarter twice, keep only the latest filing
    latest = (df.groupby(["fund", "report_date"])["filing_date"].transform("max"))
    dup_quarters = df.loc[df["filing_date"] != latest, ["fund", "report_date"]].drop_duplicates()
    for _, d in dup_quarters.iterrows():
        log.append(f"{d['fund']}: {d['report_date']} was filed twice, kept the latest filing")
    df = df[df["filing_date"] == latest]
    df = df[df["accession"] == df.groupby(["fund", "report_date"])["accession"].transform("max")]

    first =["fund", "report_date", "filing_date", "accession", "series_id"]
    df = df[first + [c for c in df.columns if c not in first]]
    df = df.sort_values(["fund", "report_date", "name"])
    out_csv = os.path.join(DATA_DIR, "holdings_quarterly.csv")
    df.to_csv(out_csv, index=False)

    # Summary per fund
    lines = ["STEP 1 - FUND HOLDINGS DOWNLOADED FROM SEC N-PORT", ""]
    lines.append(f"{'Fund':<6} {'Reports':>7} {'First report':>13} {'Last report':>12} "
                 f"{'Avg holdings':>13} {'Equity %':>9}")
    for fund, g in df.groupby("fund"):
        per_report = g.groupby("report_date").size()
        equity_share = (g["asset_cat"] == "EC").mean() * 100
        lines.append(f"{fund:<6} {per_report.size:>7} {per_report.index.min():>13} "
                     f"{per_report.index.max():>12} {per_report.mean():>13.0f} {equity_share:>8.1f}%")
    lines += ["", f"Rows saved: {len(df):,}  ->  {out_csv}"]
    if log:
        lines += ["", "Notes:"] + ["  " + m for m in log]
    summary = "\n".join(lines)
    print("\n" + summary)
    with open(os.path.join(OUT_DIR, "01_holdings_summary.txt"), "w") as fh:
        fh.write(summary + "\n")


if __name__ == "__main__":
    main()