"""
Run Step 1 for every fund marked include=yes in halal_funds.csv:
  01_download_etf_holdings.py  ->  02_find_index_changes.py  for each fund,
then 03_combine_all_funds.py once at the end.

Usage:
    python3 run_step1_all_funds.py

If one fund fails (for example, not found at the SEC, or too new to have
two filings), it is reported and the others still run.
To skip a fund, set its "include" column to "no" in halal_funds.csv.
"""

import os
import subprocess
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))


def run(script, *args):
    """Run one of the project scripts. Returns (ok, last lines of output)."""
    p = subprocess.run([sys.executable, os.path.join(HERE, script)] + list(args),
                       cwd=HERE, capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip()
    return p.returncode == 0, out


def main():
    funds = pd.read_csv(os.path.join(HERE, "halal_funds.csv"))
    funds = funds[funds["include"].str.strip().str.lower() == "yes"]

    status = []
    for t in funds["ticker"]:
        print("=" * 70)
        print(t)
        ok, out = run("01_download_etf_holdings.py", t)
        print(out.splitlines()[-1] if out else "")
        if not ok:
            status.append((t, "download failed", out.splitlines()[-1] if out else ""))
            continue
        snaps = [l for l in out.splitlines() if l.startswith("Snapshots:")]
        ok, out2 = run("02_find_index_changes.py", t)
        if not ok:
            status.append((t, "changes failed", out2.splitlines()[-1] if out2 else ""))
            continue
        tot = [l for l in out2.splitlines() if l.startswith("Totals:")]
        status.append((t, "ok", (snaps[0] if snaps else "") + " | " + (tot[0] if tot else "")))
        print(out2)

    print("\n" + "=" * 70)
    print("STATUS PER FUND")
    print("=" * 70)
    for t, s, msg in status:
        print("{:<6} {:<16} {}".format(t, s, msg))

    print("\n" + "=" * 70)
    print("ALL FUNDS COMBINED")
    print("=" * 70)
    ok, out = run("03_combine_all_funds.py")
    print(out)


if __name__ == "__main__":
    main()