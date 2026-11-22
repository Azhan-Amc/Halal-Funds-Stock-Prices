"""
Step 1a: Download an ETF's holdings history from SEC N-PORT filings.

Usage:
    python3 01_download_etf_holdings.py SPUS
    python3 01_download_etf_holdings.py HLAL

Output:
    data/holdings_<TICKER>.csv   one row per (report date, stock held)
    data/raw/<TICKER>/            cached XML files (re-running does not re-download)

The SEC asks for a User-Agent with a real email. Edit USER_AGENT below if needed.
"""

import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests

USER_AGENT = "Your Name your-email@example.com"
PAUSE = 0.2  # seconds between SEC requests (SEC limit is 10 per second)

TICKERS_URL = "https://www.sec.gov/files/company_tickers_mf.json"
FILINGS_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
               "&CIK={series}&type=NPORT-P&dateb=&owner=include&count=100"
               "&start={start}&output=atom")
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/primary_doc.xml"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def fetch(url):
    """Download a URL and return its text. Stops with a clear message on error."""
    time.sleep(PAUSE)
    r = SESSION.get(url, timeout=60)
    if r.status_code != 200:
        sys.exit("ERROR: HTTP {} for {}".format(r.status_code, url))
    return r.text


def find_series(ticker):
    """Look up the fund's CIK and series ID from the SEC fund ticker list."""
    data = json.loads(fetch(TICKERS_URL))
    fields = data["fields"]
    for row in data["data"]:
        rec = dict(zip(fields, row))
        if str(rec["symbol"]).upper() == ticker:
            return int(rec["cik"]), rec["seriesId"]
    sys.exit("ERROR: ticker {} not found in SEC fund list".format(ticker))


def list_accessions(series):
    """Return all NPORT-P accession numbers filed for this series."""
    found = []
    start = 0
    while True:
        text = fetch(FILINGS_URL.format(series=series, start=start))
        accs = re.findall(r"\d{10}-\d{2}-\d{6}", text)
        new = [a for a in dict.fromkeys(accs) if a not in found]
        if not new:
            break
        found.extend(new)
        if len(new) < 100:
            break
        start += 100
    return found


def strip_ns(root):
    """Remove XML namespaces so tags can be found by plain name."""
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def text_of(el, path):
    found = el.find(path)
    return found.text.strip() if found is not None and found.text else None


def to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_nport(xml_text):
    """Return (info dict, list of holding dicts) from one N-PORT XML file."""
    root = strip_ns(ET.fromstring(xml_text))
    gen = root.find(".//genInfo")
    fund = root.find(".//fundInfo")
    info = {
        "series_id": text_of(gen, "seriesId"),
        "series_name": text_of(gen, "seriesName"),
        "report_date": text_of(gen, "repPdDate"),
        "net_assets": to_float(text_of(fund, "netAssets")),
    }
    rows = []
    for sec in root.iter("invstOrSec"):
        ticker_el = sec.find("identifiers/ticker")
        isin_el = sec.find("identifiers/isin")
        rows.append({
            "name": text_of(sec, "name"),
            "title": text_of(sec, "title"),
            "cusip": text_of(sec, "cusip"),
            "isin": isin_el.get("value") if isin_el is not None else None,
            "ticker": ticker_el.get("value") if ticker_el is not None else None,
            "asset_cat": text_of(sec, "assetCat"),
            "shares": to_float(text_of(sec, "balance")),
            "value_usd": to_float(text_of(sec, "valUSD")),
            "pct": to_float(text_of(sec, "pctVal")),
        })
    return info, rows


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 01_download_etf_holdings.py TICKER")
    ticker = sys.argv[1].upper()
    raw_dir = os.path.join("data", "raw", ticker)
    os.makedirs(raw_dir, exist_ok=True)

    cik, series = find_series(ticker)
    print("{}: CIK {}, series {}".format(ticker, cik, series))

    accessions = list_accessions(series)
    print("N-PORT filings found:", len(accessions))
    if not accessions:
        sys.exit("ERROR: no N-PORT filings found for this series")

    all_rows = []
    for i, acc in enumerate(accessions, 1):
        path = os.path.join(raw_dir, acc + ".xml")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                xml_text = f.read()
        else:
            url = DOC_URL.format(cik=cik, acc=acc.replace("-", ""))
            xml_text = fetch(url)
            with open(path, "w", encoding="utf-8") as f:
                f.write(xml_text)

        info, rows = parse_nport(xml_text)
        if info["series_id"] != series:
            print("  skip {}: belongs to {} ({})".format(
                acc, info["series_id"], info["series_name"]))
            continue
        print("  {:>2}/{}  {}  report date {}  holdings {}".format(
            i, len(accessions), acc, info["report_date"], len(rows)))
        for r in rows:
            r.update(info)
            r["accession"] = acc
            r["filing_rank"] = i  # SEC lists newest filings first, so 1 = newest
            all_rows.append(r)

    df = pd.DataFrame(all_rows)

    # If a month was filed twice (amendment), keep the newest filing only.
    newest = df.groupby("report_date")["filing_rank"].min()
    df = df[df["filing_rank"] == df["report_date"].map(newest)]
    df = df.drop(columns="filing_rank")

    df = df.sort_values(["report_date", "value_usd"], ascending=[True, False])
    out = os.path.join("data", "holdings_{}.csv".format(ticker))
    df.to_csv(out, index=False)

    dates = sorted(df["report_date"].unique())
    print()
    print("Saved", out)
    print("Snapshots: {}  (first {}, last {})".format(len(dates), dates[0], dates[-1]))
    print("Series name:", df["series_name"].iloc[-1])


if __name__ == "__main__":
    main()