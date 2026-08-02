#!/usr/bin/env python3
"""Offline test of the alert logic — fake prices, no network, no Telegram."""
import json, os, shutil, tempfile

tmp = tempfile.mkdtemp()
shutil.copy("alerts.json", os.path.join(tmp, "alerts.json"))
os.environ.update(DRY_RUN="1",
                  ALERTS_CONFIG=os.path.join(tmp, "alerts.json"),
                  ALERTS_STATE=os.path.join(tmp, "state.json"))

import check_prices as cp

PRICES = {}
cp.get_price = lambda sym, src="auto": {
    "price": PRICES[sym], "prev_close": PRICES[sym] * 0.988,
    "currency": "INR" if cp.RUPEE_RE.search(sym) else "USD",
    "market_state": "REGULAR", "source": "fake",
}


def run(label, prices):
    global PRICES
    PRICES = prices
    print(f"\n{'='*68}\n{label}\n{'='*68}")
    cp.main()


base = {"GC=F": 3400.0, "BTC-USD": 105000.0, "^NSEI": 25500.0,
        "^BSESN": 84000.0, "RELIANCE.NS": 1480.0, "TCS.NS": 3450.0,
        "HDFCBANK.NS": 1950.0}

run("1. Everything mid-range — expect ZERO messages", base)
run("2. Gold spikes past 3600, Nifty drops under 24000 — expect 2 messages",
    {**base, "GC=F": 3655.20, "^NSEI": 23880.15})
run("3. Same elevated prices again — expect ZERO (no spam on repeat)",
    {**base, "GC=F": 3661.00, "^NSEI": 23805.00})
run("4. Prices come back to normal — expect ZERO, alerts re-arm", base)
run("5. Gold spikes AGAIN — expect 1 message (re-armed and fired)",
    {**base, "GC=F": 3702.00})
run("6. Disabled alert (HDFCBANK above 2000) is breached — expect ZERO",
    {**base, "HDFCBANK.NS": 2150.0})
run("7. Rupee formatting check: Reliance above 1600 — expect 1 message in ₹",
    {**base, "RELIANCE.NS": 1642.35})

print(f"\n{'='*68}\nfinal state.json\n{'='*68}")
with open(os.environ["ALERTS_STATE"]) as fh:
    st = json.load(fh)
for k, v in sorted(st["alerts"].items()):
    print(f"  {k:<30} armed={str(v['armed']):<6} fired={v.get('fired_count', 0)}")
