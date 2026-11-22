"""
Step 3b (part 1): Download Amana's quarterly holdings filings from before N-PORT existed (2004-2019).

Amana Mutual Funds Trust (Growth + Income funds) filed:
    N-Q    : holdings at the 1st and 3rd fiscal quarter (Aug and Feb)
    N-CSR  : annual report, holdings at fiscal year end (May)
    N-CSRS : semi-annual report, holdings at Nov
They list company names (no tickers), so the files are parsed in a later step.

Usage:
    python3 07_download_amana_old_filings.py

Output:
    data/raw_amana_old/<report date>_<form>_<accession>.<ext>   one raw file per filing
    data/raw_amana_old/filings_list.csv                          what was downloaded
    data/company_tickers.json                                    SEC list of company names -> tickers
Already-downloaded files are skipped, so it is safe to run again.
"""

import json
import os
import sys
import time

import pandas as pd
import requests

USER_AGENT = "Your Name your-email@example.com"
CIK = 766285
FORMS = {"N-Q", "N-CSR", "N-CSRS", "N-Q/A", "N-CSR/A", "N-CSRS/A"}
FIRST, LAST = "2003-01-01", "2019-12-31"
OUT = os.path.join("data", "raw_amana_old")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def fetch(url, binary=False):
    time.sleep(0.2)
    r = SESSION.get(url, timeout=60)
    if r.status_code != 200:
        raise RuntimeError("HTTP {} for {}".format(r.status_code, url))
    return r.content if binary else r.text


def filings_table(block):
    keys = ["accessionNumber", "filingDate", "reportDate", "form", "primaryDocument"]
    return pd.DataFrame({k: block.get(k, []) for k in keys})


def list_filings():
    sub = json.loads(fetch("https://data.sec.gov/submissions/CIK{:010d}.json".format(CIK)))
    parts = [filings_table(sub["filings"]["recent"])]
    for f in sub["filings"].get("files", []):
        older = json.loads(fetch("https://data.sec.gov/submissions/" + f["name"]))
        parts.append(filings_table(older))
    df = pd.concat(parts, ignore_index=True)
    df = df[df["form"].isin(FORMS)]
    date = df["reportDate"].where(df["reportDate"].astype(str).str.len() == 10, df["filingDate"])
    df = df.assign(date=date)
    df = df[(df["date"] >= FIRST) & (df["date"] <= LAST)]
    return df.sort_values("date").reset_index(drop=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    print("Listing Amana filings at the SEC...")
    df = list_filings()
    print("Found {} N-Q / N-CSR / N-CSRS filings ({} to {})".format(len(df), df["date"].min(), df["date"].max()))
    if df.empty:
        sys.exit("ERROR: nothing found")

    saved = []
    for i, r in df.iterrows():
        acc = r["accessionNumber"]
        doc = os.path.basename(str(r["primaryDocument"]))
        ext = os.path.splitext(doc)[1] or ".txt"
        name = "{}_{}_{}{}".format(r["date"], r["form"].replace("/", "-"), acc, ext)
        path = os.path.join(OUT, name)
        if not os.path.exists(path):
            url = "https://www.sec.gov/Archives/edgar/data/{}/{}/{}".format(CIK, acc.replace("-", ""), doc)
            try:
                data = fetch(url, binary=True)
            except Exception as e:
                print("  FAILED {}: {}".format(name, e))
                continue
            with open(path, "wb") as f:
                f.write(data)
        print("  {:>3}/{}  {}".format(i + 1, len(df), name))
        saved.append(dict(r, file=name))
    pd.DataFrame(saved).to_csv(os.path.join(OUT, "filings_list.csv"), index=False)

    tick = fetch("https://www.sec.gov/files/company_tickers.json")
    with open(os.path.join("data", "company_tickers.json"), "w") as f:
        f.write(tick)

    print("\nSaved {} filings in {}".format(len(saved), OUT))
    print("Saved data/company_tickers.json")
    print("\nNext: zip and upload them:")
    print("  zip -r amana_old.zip data/raw_amana_old data/company_tickers.json")


if __name__ == "__main__":
    main()