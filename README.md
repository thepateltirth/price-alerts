# Telegram price alerts

A price-alert bot that runs on **GitHub Actions** — no server, no credit card, and nothing depending on your laptop being awake. GitHub runs the checker on a cron; when a price crosses a level you set, your bot messages you.

Covers gold (XAU/USD), Bitcoin, Nifty 50, Sensex, and any NSE/BSE stock, all from one free keyless data source.

---

## Files

| File | What it is |
|---|---|
| `alerts.json` | Your alert levels. **This is the only file you normally edit.** |
| `check_prices.py` | The checker. Pure Python stdlib — no `pip install`. |
| `get_chat_id.py` | One-time helper to find your Telegram chat ID. |
| `state.json` | Remembers what already fired, so you get one message per crossing, not one every 10 minutes. |
| `.github/workflows/price-alerts.yml` | The cron that runs it. |

---

## Step 1 — get your chat ID

You have the bot token already. Now:

1. Open Telegram, find your bot, press **START**, send it any message (`hi` is fine).
2. Then, **in a terminal on your computer — not in the Telegram chat window** — run:

**Windows (PowerShell):**

```powershell
$env:TELEGRAM_BOT_TOKEN="123456:AAxxxxxxxx"
python get_chat_id.py
```

**macOS / Linux:**

```bash
TELEGRAM_BOT_TOKEN=123456:AAxxxxxxxx python3 get_chat_id.py
```

It prints your chat ID and sends a test message back to confirm the round trip works.

> **No script needed at all:** send your bot a message, then paste
> `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` into a browser and read `message.chat.id`.
> If it shows `{"ok":true,"result":[]}`, send the bot another message and reload — Telegram
> only buffers updates for 24 hours.

> **The bot will not reply to you on its own.** A Telegram bot has no logic of its own; it
> only speaks when code somewhere calls `sendMessage`. Until you finish Step 4 below, sending
> it messages will always be met with silence. That's normal, not a fault.

---

## Step 2 — put it on GitHub

```bash
cd telegram-price-alerts
git init && git add . && git commit -m "price alerts"
gh repo create price-alerts --public --source=. --push
```

(Or create the repo in the web UI and push to it — same thing.)

**Make it public.** Public repos get unlimited free Actions minutes; private repos get 2,000 minutes/month and GitHub bills every run rounded up to a full minute, so a 10-minute cron (~4,300 runs/month) would blow through the quota in about two weeks. The repo only contains your alert levels — your bot token never goes in it.

If you'd rather keep it private, change the cron to `"*/30 * * * *"` (~1,440 runs/month, fits the free quota).

---

## Step 3 — add your secrets

In the repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token from @BotFather |
| `TELEGRAM_CHAT_ID` | what step 1 printed |

These are encrypted and are not visible in the repo or in logs, even on a public repo.

---

## Step 4 — run it once by hand

**Actions** tab → **price-alerts** → **Run workflow**.

Open the run log. It prints every current price:

```
[ok]   GC=F             3,412.4000  (yahoo/query1)
[ok]   BTC-USD        104,880.0000  (yahoo/query1)
[ok]   ^NSEI           25,394.9500  (yahoo/query1)
```

Use those numbers to set realistic levels in `alerts.json`, commit, and you're done. From then on it runs every 10 minutes on its own.

> First-run note: if a level in the shipped `alerts.json` is already breached, that alert fires immediately on the first run. That's the design working — it's telling you the condition is true right now. Edit the levels and it settles down.

---

## Editing `alerts.json`

Each alert needs a `symbol` and **exactly one** of `above` or `below`. Want both sides of a range? Write two entries.

```json
{
  "name": "Gold (XAU/USD)",
  "symbol": "GC=F",
  "above": 3600,
  "cooldown_minutes": 120,
  "note": "trim position here",
  "enabled": true
}
```

| Field | Required | What it does |
|---|---|---|
| `symbol` | yes | Yahoo Finance ticker (table below) |
| `above` / `below` | one of | The level to watch |
| `name` | no | Label in the message; defaults to the symbol |
| `cooldown_minutes` | no | Minimum gap between messages for this alert |
| `note` | no | Free text appended to the message |
| `enabled` | no | `false` to park an alert without deleting it |
| `once` | no | `true` = fire once ever, then never again |

### Symbols

| What | Symbol |
|---|---|
| Gold, COMEX futures | `GC=F` |
| Gold, spot XAU/USD | `XAUUSD=X` |
| Silver | `SI=F` |
| Bitcoin | `BTC-USD` |
| Ethereum | `ETH-USD` |
| Nifty 50 | `^NSEI` |
| Sensex | `^BSESN` |
| Bank Nifty | `^NSEBANK` |
| NSE stock | `RELIANCE.NS`, `TCS.NS`, `INFY.NS` … |
| BSE stock | `RELIANCE.BO` |
| USD/INR | `INR=X` |

Anything with a Yahoo Finance page works — the ticker in the URL is the symbol.

### How the anti-spam works

Each alert is **edge-triggered**. It fires on the crossing, then goes quiet. It re-arms only after the price moves back to the other side of your level. So gold crossing $3,600 messages you once — not 144 times a day while it sits above.

---

## Things worth knowing

- **5 minutes is GitHub's floor** for cron, and the schedule is best-effort — runs get delayed by a few minutes when GitHub is busy. Fine for swing levels, not for scalping.
- **Indian markets trade 9:15–15:30 IST.** Outside that, Yahoo returns the last traded price. The message says `Market closed — last known price` when that happens. Gold and crypto run nearly 24/7.
- **GitHub pauses cron on repos with 60 days of no activity.** The checker writes a heartbeat into `state.json` every 20 days and the workflow commits it, which keeps the repo active automatically.
- **Data source:** Yahoo Finance's public chart endpoint, with CoinGecko as an automatic fallback for crypto. Both keyless. If Yahoo ever changes, only `fetch_yahoo()` needs touching.
- **Cost:** ₹0. Public repo = unlimited Actions minutes.

## Running it somewhere else

Nothing here is GitHub-specific — it's one script that exits. On any box with Python 3.9+:

```bash
*/10 * * * * cd /path/to/telegram-price-alerts && \
  TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... /usr/bin/python3 check_prices.py >> alerts.log 2>&1
```

Same on Render/Railway/Fly as a cron job. `DRY_RUN=1` prints messages instead of sending them.

## Testing the logic offline

```bash
python3 test_local.py
```

Runs seven scenarios against fake prices — crossings, repeats, re-arming, disabled alerts, rupee formatting — without touching the network or Telegram.
