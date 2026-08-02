#!/usr/bin/env python3
"""
Telegram price alerts — one-shot checker.

Runs once per invocation:
  read alerts.json -> fetch prices -> evaluate -> send Telegram -> save state.json

Pure standard library. No pip install, nothing to keep running.
Designed to be driven by a GitHub Actions cron (or any cron).

Env vars:
  TELEGRAM_BOT_TOKEN   required
  TELEGRAM_CHAT_ID     required
  ALERTS_CONFIG        optional, default alerts.json
  ALERTS_STATE         optional, default state.json
  DRY_RUN=1            print messages instead of sending
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

CONFIG_PATH = os.environ.get("ALERTS_CONFIG", "alerts.json")
STATE_PATH = os.environ.get("ALERTS_STATE", "state.json")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
DRY_RUN = os.environ.get("DRY_RUN") == "1"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

IST = timezone(timedelta(hours=5, minutes=30))

# Symbols that should be shown with a rupee sign.
RUPEE_RE = re.compile(r"(\.NS$|\.BO$|^\^NSE|^\^BSE|^\^CNX)")

# Fallback price source for crypto if Yahoo is having a moment.
COINGECKO_IDS = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "XRP-USD": "ripple",
    "DOGE-USD": "dogecoin",
    "BNB-USD": "binancecoin",
}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def http_get_json(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------
# Price sources
# --------------------------------------------------------------------------
def fetch_yahoo(symbol: str) -> dict:
    """Yahoo Finance chart endpoint. Free, no API key. Covers gold futures,
    crypto, FX, NSE/BSE stocks and Indian indices."""
    path = urllib.parse.quote(symbol, safe="")
    last_err = None
    for host in ("query1", "query2"):
        url = (
            f"https://{host}.finance.yahoo.com/v8/finance/chart/{path}"
            "?interval=5m&range=1d"
        )
        try:
            data = http_get_json(url)
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            if price is None:
                raise ValueError("no regularMarketPrice in response")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            return {
                "price": float(price),
                "prev_close": float(prev) if prev else None,
                "currency": meta.get("currency") or "",
                "market_state": meta.get("marketState") or "",
                "source": f"yahoo/{host}",
            }
        except Exception as exc:  # noqa: BLE001 - try the next host
            last_err = exc
            time.sleep(1)
    raise RuntimeError(f"Yahoo failed for {symbol}: {last_err}")


def fetch_coingecko(symbol: str) -> dict:
    cg_id = COINGECKO_IDS.get(symbol.upper())
    if not cg_id:
        raise RuntimeError(f"no CoinGecko mapping for {symbol}")
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={cg_id}&vs_currencies=usd&include_24hr_change=true"
    )
    data = http_get_json(url)[cg_id]
    price = float(data["usd"])
    change = data.get("usd_24h_change")
    prev = price / (1 + change / 100) if change else None
    return {
        "price": price,
        "prev_close": prev,
        "currency": "USD",
        "market_state": "REGULAR",
        "source": "coingecko",
    }


def get_price(symbol: str, source: str = "auto") -> dict:
    """Fetch one symbol, with a fallback for crypto."""
    if source == "coingecko":
        return fetch_coingecko(symbol)
    try:
        return fetch_yahoo(symbol)
    except Exception:
        if symbol.upper() in COINGECKO_IDS:
            return fetch_coingecko(symbol)
        raise


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------
def money(symbol: str, value: float, currency: str = "") -> str:
    sign = "₹" if (RUPEE_RE.search(symbol) or currency == "INR") else "$"
    if abs(value) >= 1000:
        return f"{sign}{value:,.2f}"
    if abs(value) >= 1:
        return f"{sign}{value:,.4f}".rstrip("0").rstrip(".")
    return f"{sign}{value:.6f}"


def build_message(alert: dict, quote: dict) -> str:
    name = alert.get("name") or alert["symbol"]
    symbol = alert["symbol"]
    price = quote["price"]
    direction = "above" if alert.get("above") is not None else "below"
    target = alert.get("above") if direction == "above" else alert.get("below")
    arrow = "🟢 ▲" if direction == "above" else "🔴 ▼"

    lines = [
        f"{arrow} <b>{html.escape(str(name))}</b> is {direction} your level",
        "",
        f"Price:  <b>{money(symbol, price, quote['currency'])}</b>",
        f"Target: {direction} {money(symbol, float(target), quote['currency'])}",
    ]

    prev = quote.get("prev_close")
    if prev:
        pct = (price - prev) / prev * 100
        lines.append(f"Session: {pct:+.2f}%")

    if quote.get("market_state") and quote["market_state"] not in ("REGULAR", ""):
        lines.append(f"<i>Market {quote['market_state'].lower()} — last known price</i>")

    if alert.get("note"):
        lines.append("")
        lines.append(f"<i>{html.escape(str(alert['note']))}</i>")

    stamp = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    lines += ["", f"<code>{symbol}</code> · {stamp}"]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------
def send_telegram(text: str) -> None:
    if DRY_RUN:
        print("--- would send ---")
        print(re.sub(r"<[^>]+>", "", text))
        print("------------------")
        return
    if not BOT_TOKEN or not CHAT_ID:
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

    payload = urllib.parse.urlencode(
        {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=payload)
            with urllib.request.urlopen(req, timeout=20) as resp:
                json.loads(resp.read().decode())
            return
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            if exc.code in (400, 401, 403):  # bad token / chat id — retrying won't help
                raise SystemExit(f"Telegram rejected the message ({exc.code}): {body}")
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


# --------------------------------------------------------------------------
# Config + state
# --------------------------------------------------------------------------
def alert_id(alert: dict, index: int) -> str:
    if alert.get("id"):
        return str(alert["id"])
    side = "above" if alert.get("above") is not None else "below"
    level = alert.get("above") if side == "above" else alert.get("below")
    return f"{alert['symbol']}|{side}|{level}|{index}"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        cfg = json.load(fh)
    alerts = cfg.get("alerts", [])
    if not alerts:
        raise SystemExit(f"No alerts defined in {CONFIG_PATH}")
    for i, a in enumerate(alerts):
        if not a.get("symbol"):
            raise SystemExit(f"alerts[{i}] is missing 'symbol'")
        has_above = a.get("above") is not None
        has_below = a.get("below") is not None
        if has_above == has_below:
            raise SystemExit(
                f"alerts[{i}] ({a.get('symbol')}) needs exactly one of "
                f"'above' or 'below' — got {'both' if has_above else 'neither'}"
            )
    return cfg


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"alerts": {}, "heartbeat": None}


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write("\n")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> int:
    cfg = load_config()
    state = load_state()
    state.setdefault("alerts", {})
    alerts = cfg["alerts"]
    now = datetime.now(timezone.utc)

    # Fetch each distinct symbol once.
    symbols = {}
    for a in alerts:
        symbols.setdefault((a["symbol"], a.get("source", "auto")), None)

    quotes, failures = {}, {}
    for (sym, src) in symbols:
        try:
            quotes[sym] = get_price(sym, src)
            print(f"[ok]   {sym:<12} {quotes[sym]['price']:>14,.4f}  ({quotes[sym]['source']})")
        except Exception as exc:  # noqa: BLE001
            failures[sym] = str(exc)
            print(f"[fail] {sym:<12} {exc}", file=sys.stderr)

    fired = 0
    for i, alert in enumerate(alerts):
        if alert.get("enabled") is False:
            continue
        sym = alert["symbol"]
        if sym not in quotes:
            continue

        aid = alert_id(alert, i)
        st = state["alerts"].setdefault(aid, {"armed": True, "fired_count": 0})
        price = quotes[sym]["price"]

        if alert.get("above") is not None:
            hit = price >= float(alert["above"])
        else:
            hit = price <= float(alert["below"])

        st["last_price"] = round(price, 6)
        st["last_seen"] = now.isoformat(timespec="seconds")

        if not hit:
            # Condition cleared — re-arm so the next crossing alerts again.
            if not st.get("armed") and not alert.get("once"):
                st["armed"] = True
                print(f"[rearm] {aid}")
            continue

        if not st.get("armed"):
            continue  # already alerted on this crossing, staying quiet

        cooldown = alert.get("cooldown_minutes")
        if cooldown and st.get("last_fired"):
            last = datetime.fromisoformat(st["last_fired"])
            if now - last < timedelta(minutes=float(cooldown)):
                continue

        send_telegram(build_message(alert, quotes[sym]))
        st["armed"] = False
        st["last_fired"] = now.isoformat(timespec="seconds")
        st["fired_count"] = st.get("fired_count", 0) + 1
        fired += 1
        print(f"[FIRED] {aid} @ {price}")

    # Keep the repo looking active so GitHub doesn't pause the schedule,
    # without committing on every single run.
    hb = state.get("heartbeat")
    if not hb or (now - datetime.fromisoformat(hb)) > timedelta(days=20):
        state["heartbeat"] = now.isoformat(timespec="seconds")

    # Prune state for alerts that no longer exist in the config.
    live_ids = {alert_id(a, i) for i, a in enumerate(alerts)}
    for stale in set(state["alerts"]) - live_ids:
        del state["alerts"][stale]

    save_state(state)

    print(f"\nchecked {len(alerts)} alerts · {len(quotes)} symbols ok · {fired} sent")
    if failures and not quotes:
        print("every price lookup failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
