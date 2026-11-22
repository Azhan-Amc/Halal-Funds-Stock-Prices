"""
Step 3 - Give every stock a ticker and download its daily price history.

N-PORT identifies stocks by CUSIP; prices need a ticker. For every stock that
appears in data/events.csv:
  1. use the ticker from the N-PORT filing if there is one,
  2. otherwise look the CUSIP up on OpenFIGI (free, no account needed),
  3. a manual fix can be added in data/ticker_overrides.csv (columns: sec_id,ticker).

Then it downloads daily prices (adjusted for splits and dividends) from Yahoo
for every ticker plus the benchmarks SPY, HLAL and SPUS.

Output:
    data/ticker_map.csv
    data/prices/<TICKER>.csv
    output/03_price_coverage.txt

Everything is cached: running it again only fetches what is missing.
Run:  python3 03_match_tickers_and_download_prices.py
"""

import os
import sys
import time

import pandas as pd
import requests

try:
    import yfinance as yf
except ImportError:
    sys.exit("yfinance is missing. Install it with:  pip3 install yfinance")

EVENTS_FILE = os.path.join("data", "events.csv")
MAP_FILE = os.path.join("data", "ticker_map.csv")
OVERRIDES_FILE = os.path.join("data", "ticker_overrides.csv")
PRICE_DIR = os.path.join("data", "prices")
OUT_DIR = "output"

BENCHMARKS = ["SPY", "HLAL", "SPUS"]
PRICE_START = "2019-01-01"        # one year before the first holdings report
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_BATCH = 10               # jobs per request allowed without an API key
OPENFIGI_PAUSE = 2.6              # seconds between requests (limit: 25 per minute)


# ----------------------------------------------------------------------------
# 1. Tickers
# ----------------------------------------------------------------------------
def clean_ticker(t):
    """Yahoo writes share classes with a dash: BRK.B -> BRK-B."""
    t = str(t or "").strip().upper()
    if t in ("", "NAN", "N/A", "NONE"):
        return ""
    return t.replace(".", "-").replace("/", "-").replace(" ", "-")


def openfigi_lookup(cusips):
    """CUSIP -> ticker on the US composite exchange. Returns dict."""
    found = {}
    for i in range(0, len(cusips), OPENFIGI_BATCH):
        batch = cusips[i:i + OPENFIGI_BATCH]
        jobs = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in batch]
        for attempt in range(5):
            try:
                r = requests.post(OPENFIGI_URL, json=jobs, timeout=30)
            except requests.RequestException:
                time.sleep(5)
                continue
            if r.status_code == 429:          # too many requests: wait and retry
                time.sleep(20)
                continue
            break
        else:
            print("   OpenFIGI not reachable, skipping this batch")
            continue
        if r.status_code != 200:
            print(f"   OpenFIGI answered {r.status_code}, skipping this batch")
            time.sleep(OPENFIGI_PAUSE)
            continue
        for cusip, res in zip(batch, r.json()):
            rows = res.get("data") or []
            # prefer common stock, else the first result
            pick = next((x for x in rows if x.get("securityType") in ("Common Stock", "REIT", "ADR")), None)
            pick = pick or (rows[0] if rows else None)
            if pick and pick.get("ticker"):
                found[cusip] = pick["ticker"]
        print(f"   OpenFIGI: {min(i + OPENFIGI_BATCH, len(cusips))}/{len(cusips)} looked up")
        time.sleep(OPENFIGI_PAUSE)
    return found


def build_ticker_map(events):
    stocks = (events.sort_values("report_date")
                    .groupby("sec_id", as_index=False)
                    .agg(name=("name", "last"), cusip=("cusip", "last"),
                         nport_ticker=("ticker", lambda s: next((x for x in s[::-1] if clean_ticker(x)), ""))))
    old = pd.read_csv(MAP_FILE, dtype=str).fillna("") if os.path.exists(MAP_FILE) else pd.DataFrame()

    tickers, sources = {}, {}
    if not old.empty:                      # reuse earlier lookups
        for _, r in old.iterrows():
            if r["ticker"]:
                tickers[r["sec_id"]], sources[r["sec_id"]] = r["ticker"], r["source"]

    for _, r in stocks.iterrows():
        if r["sec_id"] not in tickers and clean_ticker(r["nport_ticker"]):
            tickers[r["sec_id"]], sources[r["sec_id"]] = clean_ticker(r["nport_ticker"]), "nport"

    if os.path.exists(OVERRIDES_FILE):     # manual fixes always win
        for _, r in pd.read_csv(OVERRIDES_FILE, dtype=str).fillna("").iterrows():
            if r["ticker"]:
                tickers[r["sec_id"]], sources[r["sec_id"]] = clean_ticker(r["ticker"]), "manual"

    todo = [r["cusip"] for _, r in stocks.iterrows()
            if r["sec_id"] not in tickers and len(str(r["cusip"])) == 9]
    if todo:
        print(f"Looking up {len(todo)} CUSIPs on OpenFIGI (about {len(todo) // 10 * 3 // 60 + 1} min)...")
        figi = openfigi_lookup(todo)
        for _, r in stocks.iterrows():
            if r["sec_id"] not in tickers and r["cusip"] in figi:
                tickers[r["sec_id"]], sources[r["sec_id"]] = clean_ticker(figi[r["cusip"]]), "openfigi"

    stocks["ticker"] = stocks["sec_id"].map(tickers).fillna("")
    stocks["source"] = stocks["sec_id"].map(sources).fillna("")
    stocks.to_csv(MAP_FILE, index=False)
    return stocks


# ----------------------------------------------------------------------------
# 2. Prices
# ----------------------------------------------------------------------------
def download_prices(ticker):
    """Daily adjusted close. Returns number of rows saved (0 = no data)."""
    path = os.path.join(PRICE_DIR, f"{ticker}.csv")
    if os.path.exists(path):
        return len(pd.read_csv(path))
    try:
        hist = yf.Ticker(ticker).history(start=PRICE_START, auto_adjust=True, actions=False)
    except Exception:
        hist = None
    if hist is None or hist.empty or "Close" not in hist:
        open(path + ".missing", "w").close()      # remember the miss
        return 0
    out = pd.DataFrame({
        "date": pd.to_datetime(hist.index).tz_localize(None).date,
        "close": hist["Close"].values,
        "volume": hist["Volume"].values if "Volume" in hist else None,
    })
    out.to_csv(path, index=False)
    return len(out)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    if not os.path.exists(EVENTS_FILE):
        sys.exit(f"{EVENTS_FILE} not found. Run step 2 first.")
    os.makedirs(PRICE_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    events = pd.read_csv(EVENTS_FILE, dtype=str).fillna("")
    tmap = build_ticker_map(events)

    tickers = sorted(set(tmap.loc[tmap["ticker"] != "", "ticker"]) | set(BENCHMARKS))
    print(f"\nDownloading prices for {len(tickers)} tickers...")
    rows = {}
    for n, t in enumerate(tickers, 1):
        if os.path.exists(os.path.join(PRICE_DIR, f"{t}.csv.missing")):
            rows[t] = 0
        else:
            rows[t] = download_prices(t)
        if n % 50 == 0:
            print(f"   {n}/{len(tickers)}")
    tmap["price_rows"] = tmap["ticker"].map(rows).fillna(0).astype(int)
    tmap.to_csv(MAP_FILE, index=False)

    # ---------------- coverage report ----------------
    ev = events.merge(tmap[["sec_id", "ticker", "source", "price_rows"]], on="sec_id",
                      how="left", suffixes=("_nport", ""))
    ev["has_ticker"] = ev["ticker"].fillna("") != ""
    ev["has_prices"] = ev["price_rows"].fillna(0) > 0
    ev["candidate"] = (ev["event"] == "exit") & (ev["fund"] != "HLAL") & (ev.get("in_HLAL", "") == "True")

    def line(label, d):
        n = len(d)
        if n == 0:
            return f"{label:<34} {0:>6}"
        return (f"{label:<34} {n:>6} {d['has_ticker'].mean() * 100:>9.1f}% "
                f"{d['has_prices'].mean() * 100:>9.1f}%")

    lines = ["STEP 3 - TICKERS AND PRICES", ""]
    src = tmap["source"].replace("", "not found").value_counts()
    lines.append(f"Stocks: {len(tmap)}   ticker source: " + ", ".join(f"{k} {v}" for k, v in src.items()))
    lines.append("")
    lines.append(f"{'Events':<34} {'Count':>6} {'Ticker':>10} {'Prices':>10}")
    lines.append(line("All events", ev))
    for kind, label in (("entry", "entries"), ("exit", "exits")):
        lines.append(line(f"  {label}", ev[ev["event"] == kind]))
    lines.append(line("Candidate exits (still in HLAL)", ev[ev["candidate"]]))
    for fund in sorted(f for f in ev["fund"].unique() if f != "HLAL"):
        lines.append(line(f"  candidates from {fund}", ev[ev["candidate"] & (ev["fund"] == fund)]))

    bench = ", ".join(f"{b} {rows.get(b, 0)} days" for b in BENCHMARKS)
    lines += ["", f"Benchmarks: {bench}"]

    miss = ev[ev["candidate"] & ~ev["has_prices"]][["fund", "report_date", "name", "cusip", "ticker"]]
    if not miss.empty:
        lines += ["", "Candidate exits WITHOUT prices (often acquired/delisted - step 4 checks):"]
        lines += ["  " + " | ".join(str(v) for v in r) for r in miss.values]

    summary = "\n".join(lines)
    print("\n" + summary)
    with open(os.path.join(OUT_DIR, "03_price_coverage.txt"), "w") as fh:
        fh.write(summary + "\n")


if __name__ == "__main__":
    main()