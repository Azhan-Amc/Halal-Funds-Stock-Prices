# Results log: Shariah Index Reconstitution

## Step 1: Ground truth from SEC N-PORT filings (run 2026-10-30)

| Fund | Type | Snapshots | First | Last | Additions | Removals | ID changes | Median forced buy per add ($M) | Mean ($M) | Max ($M) |
|---|---|---|---|---|---|---|---|---|---|---|
| SPUS | passive ETF | 26 | 2020-05-31 | 2026-08-31 | 185 | 146 | 19 | (not in paste) | | |
| HLAL | passive ETF | 26 | 2020-05-31 | 2026-08-31 | 302 | 311 | 25 | 0.28 | 1.49 | 120.89 |
| MNZL | passive ETF | 3 | 2026-01-30 | 2026-07-31 | 73 | 42 | 3 | 0.01 | 0.01 | 0.14 |
| SPTE | passive ETF | 11 | 2024-01-31 | 2026-07-31 | 29 | 20 | 5 | 0.26 | 0.50 | 3.17 |
| SPRE | passive ETF | 23 | 2021-02-28 | 2026-08-31 | 65 | 74 | 19 | 0.09 | 1.05 | 18.58 |
| KWIN | passive ETF | 3 | 2025-12-31 | 2026-06-30 | 5 | 1 | 0 | 0.29 | 0.31 | 0.60 |
| AMAGX | active mutual fund | 28 | 2019-11-30 | 2026-08-31 | 36 | 38 | 1 | 39.41 | 48.63 | 110.76 |
| AMANX | active mutual fund | 28 | 2019-11-30 | 2026-08-31 | 20 | 33 | 3 | 7.97 | 13.36 | 47.13 |

Snapshot months differ by fund: SPUS/HLAL/SPRE/AMAGX/AMANX = Feb, May, Aug, Nov;
MNZL/SPTE = Jan, Apr, Jul (Oct); KWIN = Mar, Jun, Sep, Dec.

### Waves (stocks added by 2+ funds), raw output of 03

| Funds that added | Stocks |
|---|---|
| 1 | 346 |
| 2 | 106 |
| 3 | 17 |
| 4 | 6 (UPS, MRVL, AVGO, SNDK, CIEN, COHR) |

Gap first → last fund: median 366 days, mean 580. Combined forced buy per wave stock: median $1.11M, max $231.64M (NVDA, mostly Amana).

### Data problems found (must be cleaned before Step 2)

1. **Corporate actions counted as additions:** spin-offs the funds received rather than bought
   (SOLS, RAL, VSTS, KLG, PHIN, FTRE, MBC, RXO, Q, FDXF, VLTO, KVUE, GEHC, SNDK...).
2. **Corporate actions counted as removals:** acquired companies (SPLK, VMW, HZNP, PXD, MRO, HES,
   ANSS, JNPR, CTLT, WRK, AGR...).
3. **Missed ID changes:** XOM shows as removed (Exxon Mobil Corp) and added (ExxonMobil Holdings Corp)
   in Aug 2026; the name rule didn't match. Same company split in two rows in the waves table:
   CRH (two CUSIPs), SMCI (two CUSIPs).
4. **Fake waves:** AMAGX ↔ AMANX are the same manager; SPUS ↔ SPRE/SPTE use the same S&P Shariah screen;
   MNZL "adds" of stocks HLAL added in 2020 only reflect MNZL launching in 2025 (BIO, ZBH, LBRDA, LEN/B: 2,000+ day gaps).
5. **Junk rows:** share-class lines (LEN/B, LBRDA, UAA/UA), "TPG Inc 2602335D" at 0.00.
6. Missing tickers: SPRE before 2023 and KWIN have ticker = None (CUSIP still works for matching).

### First reading

- Passive halal ETFs buy very little per new stock: about $0.01–0.3M median. That's tiny next to
  large-cap daily volume, so a price-pressure edge from them alone looks unlikely. Step 2 will confirm this with real volume numbers.
- Amana is where the size is: median $39M per new Growth position, up to $110M.
- HLAL churns a lot (302 adds / 311 removes on ~200 holdings) and flips big names in and out
  (IBM 3 times, LLY, KO, XOM). FTSE divides debt by **total assets** (book values), so these flips
  should be predictable from 10-Q/10-K filings weeks before the quarterly review, and they don't come from price moves.
- The 2026 waves are concentrated in AI networking and optical stocks (CIEN, COHR, LITE, MRVL, SNDK) after big
  rallies. With a market-cap denominator that fits the momentum confound: they became compliant because they went up.

## Step 1d: Cleaning (04_clean_index_changes.py, run 2026-10-30)

1,530 raw rows → 1,222 usable events (US-listed, real changes).
Fixed: 164 ID changes (incl. XOM Aug 2026), 10 second share classes, 28 tiny rows, 168 non-US/unknown tickers; 140 missing tickers filled from CUSIP.

| Fund | Usable adds | Usable removes | Median add ($M) | Mean ($M) | Max ($M) | Median add at today's AUM ($M) | AUM now ($M) |
|---|---|---|---|---|---|---|---|
| SPUS | 178 | 139 | 0.38 | 1.37 | 32.66 | 3.64 | 3,136 |
| HLAL | 291 | 302 | 0.28 | 1.46 | 120.89 | 1.23 | 945 |
| MNZL | 65 | 38 | 0.01 | 0.02 | 0.14 | 0.01 | 24 |
| SPTE | 22 | 18 | 0.25 | 0.49 | 3.16 | 0.48 | 211 |
| SPRE | 23 | 28 | 0.78 | 2.43 | 18.58 | 3.90 | 212 |
| KWIN | 5 | 1 | 0.29 | 0.31 | 0.60 | 0.29 | 56 |
| AMAGX | 29 | 36 | 35.49 | 45.69 | 110.76 | 66.37 | 6,685 |
| AMANX | 15 | 32 | 5.81 | 9.80 | 40.31 | 7.76 | 2,364 |

Rule-change batch flagged: SPUS May 2024, 63 events, $96.7M (53 adds incl. AMZN, ABBV, ACN, MCK, COR, CAH: consistent with S&P dropping the receivables screen; inferred).

Waves by independent screen family (fund must exist when the wave starts):

| Families | Stocks |
|---|---|
| 1 | 294 |
| 2 | 94 |
| 3 | 8 (UPS, AVGO, KVUE, FERG, CRH, CIEN, COHR, FDXF) |

Gap first → last family: median 274 days. Forced (passive) buy per wave stock: median $1.19M.
Still contaminated (fixed in Step 2): KVUE and FDXF are spin-offs, FERG is a listing change, CRH's SPUS add is its S&P 500 entry,
and MNZL's July 2026 adds are mostly the Russell reconstitution.

## Step 2: Forced trading vs daily volume (05_flow_vs_volume.py, run 2026-10-30)

Not-a-flip events removed: spin-offs/IPOs, delisted/no Yahoo data (mostly mergers; FI is a ticker change to FISV),
MNZL Russell reconstitution (48 adds, 23 removes), SPUS May 2024 rule-change batch.
S&P 500 membership flags did NOT run (Wikipedia table not found); doesn't change the verdict below.

Median forced trade as % of one day's average dollar volume (clean flips only):

| Fund | Adds | Removes | Adds: back then | Adds: at today's size | Adds p90, today | Removes: at today's size | Median stock ADV ($M) |
|---|---|---|---|---|---|---|---|
| SPUS | 113 | 105 | 0.09% | 1.65% | 3.80% | 1.40% | 278 |
| HLAL | 245 | 252 | 0.16% | 0.67% | 1.35% | 0.58% | 245 |
| MNZL | 16 | 12 | 0.004% | 0.007% | 0.01% | 0.007% | 138 |
| SPTE | 21 | 15 | 0.04% | 0.08% | 1.70% | 0.16% | 749 |
| SPRE | 17 | 21 | 1.18% | 8.90% | 22.8% | 9.31% | 68 |
| KWIN | 5 | 0 | 0.03% | 0.03% | 0.07% | — | 1,068 |
| AMAGX (active) | 29 | 35 | 6.37% | 10.94% | 29.0% | 12.53% | 647 |
| AMANX (active) | 13 | 31 | 0.83% | 1.03% | 11.1% | 6.78% | 639 |

### Verdict on H1/H3 (price pressure from forced buying)

**Rejected at current fund sizes for the US equity ETFs.** SPUS, the biggest, trades a median 1.7% of one day's
volume when it adds a stock at today's size (max 5.7%). HLAL is under 1.5% for 90% of adds. That's within normal daily noise.
Combined waves are not bigger. Size needed for SPUS's median add to reach 10% of a day's volume: ~$19B (it's $3.1B now).
For HLAL: ~$14B.

Where flows are big:
- SPRE (global REITs, low-volume names): median ~9% of a day's volume at today's size. Niche, mostly non-US.
- Amana (AMAGX): median ~11%, up to 82% for removals, but it's active, so the timing is unknown, and there's no daily data (H4 on hold).

Outliers to ignore: SW (Smurfit WestRock) 421% is a pre-merger ticker artifact.

## Step 3: Returns around additions (06_event_returns.py, run 2026-10-30)

Return minus SPY, mean % (t-stat), hit rate = % of events beating SPY.
"During" = quarter the fund bought (not tradeable). "After" = from public day (quarter end + 60 days), tradeable.

| Fund | n | During | After 20d | After 60d | After 120d | Hit rate after 60d |
|---|---|---|---|---|---|---|
| AMAGX | 29 / 26 | +2.64 (0.83) | +1.61 (0.84) | +3.32 (1.33) | +2.66 (0.82) | 65.4% |
| SPRE | 17 / 17 | −5.40 (−1.74) | −1.87 (−1.07) | −4.35 (−0.95) | −0.19 (−0.07) | 52.9% |
| SPUS | 113 / 105 | +3.94 (1.13) | −0.64 (−0.66) | −0.70 (−0.38) | −0.52 (−0.16) | 44.8% |
| HLAL | 245 / 237 | +1.79 (1.34) | +0.67 (0.83) | −0.24 (−0.21) | **−2.76 (−1.94)** | 46.4% |
| AMANX | 13 / 13 | +2.92 (1.10) | −2.11 (−1.08) | −3.72 (−1.04) | **−8.55 (−1.96)** | 46.2% |

SPRE vs VNQ (REIT market): during −3.23 (−1.14); after 120d +3.61 (1.96), hit 75%.

Confluence (focus funds AMAGX + SPRE): with = 5 events (only 3 with after-returns), no = 41.
With: after 120d +10.0% (3 of 3 beat SPY). Without: +0.9%. **Too few events to mean anything.**

Amana follow-through (next quarter's shares vs first appearance): AMAGX 42% kept buying, median +0%;
AMANX 77% kept buying, median +66.7%, 8% sold out.

### Verdict on Step 3

- **No tradeable edge is proven.** No "after" result reaches |t| ≥ 2. With ~30 cells tested, one or two near 2 are expected by luck.
  Events also overlap in time, so the real t-stats are a bit lower than shown.
- AMAGX "after" is the only consistently positive line (+1.6% to +3.3%, beats SPY 61–65% of the time), but with n = 26 it would need
  several times more events to be convincing.
- The opposite pattern shows up more strongly: stocks newly added by HLAL (−2.8%, t −1.94) and AMANX (−8.6%, t −1.96)
  **lag the market over the following 6 months.** That fits the momentum story: stocks become compliant after rising, then cool off.
  It can't be traded halal (no shorting, and removed stocks aren't halal to buy), but it matters for a halal portfolio:
  don't chase stocks that just became compliant.
- Confluence: 5 events is far too few to test.

## Step 3b: Amana 2004–2019 holdings from old filings (run 2026-10-30)

80 filings downloaded (N-Q, N-CSR, N-CSRS, amendments). 118 fund snapshots parsed (59 per fund, May 2004 → Nov 2019);
**every one adds up to the filing's "Total investments" line within 1%.** 5 quarters have no holdings table
(2003 ×2, Feb 2005, Aug 2012, Feb 2013); those become 6-month windows.

501 name spellings → ~250 companies, matched by hand to current tickers (`amana_name_map.csv`).
Companies that no longer trade (Wyeth, Black & Decker, Burlington Northern, Xilinx, Celgene...) get no ticker,
so a reused ticker can never pull in the wrong company. 78% of holding rows (89% of the money) have a ticker.

| Fund | Additions 2004–2019 | With ticker | Removals | With ticker |
|---|---|---|---|---|
| AMAGX | 91 | 59 | 121 | 62 |
| AMANX | 102 | 72 | 100 | 55 |

Survivorship caveat: 35% of Growth additions and 29% of Income additions are companies that no longer trade, mostly because they were acquired.
They drop out of the return test. Acquired companies often went up before the deal, so this probably makes the test a bit harsher, not easier.

Follow-through 2004–2019 (shares one snapshot later vs first appearance):
AMAGX 51% kept buying (median +18%), 8% sold out next; AMANX 45% kept buying (median 0%), 8% sold out next.
