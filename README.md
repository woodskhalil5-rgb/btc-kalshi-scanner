
# BLACKGOLD — BTC 15M / Kalshi V2

V2 keeps the live BTC/Kalshi scanner but adds:

- black + gold trading-terminal visual design
- static BTC candlestick "print" (no animation)
- automatic paper entries when the scanner rules trigger
- Supabase persistence instead of local SQLite
- automatic settlement checks for paper positions
- paper performance panel
- no live Kalshi order placement

## 1) Create Supabase

Create a Supabase project, then open **SQL Editor** and run the complete contents of `schema.sql`.

Supabase provides a full Postgres database and lets you create tables through its SQL Editor.

## 2) Get your project URL + publishable key

In Supabase open **Settings → API Keys**.

Use:
- `SUPABASE_URL` = your project URL
- `SUPABASE_KEY` = your **publishable** key (older projects may call this the `anon` key)

Do NOT put a secret/service-role key in the app.

## 3) Add Streamlit secrets

In Streamlit Community Cloud:

**Your app → Settings / Manage app → Secrets**

Paste:

```toml
SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
SUPABASE_KEY = "YOUR-PUBLISHABLE-KEY"
```

Save, then reboot/redeploy the app.

## 4) Replace the GitHub files

Upload:
- `app.py`
- `requirements.txt`
- `schema.sql`
- `.gitignore`
- `README.md`

Streamlit Community Cloud will rebuild the app from the committed GitHub version.

## 5) What V2 does automatically

When `AUTO PAPER TRADING` is ON:
1. It scans the active KXBTC15M contract.
2. It applies the edge, price and spread rules.
3. If a setup qualifies, it records a paper position in Supabase.
4. It will not repeatedly enter the same ticker/side while that paper position is open.
5. It checks open positions against the Kalshi market after settlement and records WIN/LOSS/P&L when a result is available.

No Kalshi order is sent.

## Important limitation

A Streamlit page only executes while the app is running. Community Cloud apps can hibernate when inactive. Therefore, V2 is excellent for dashboard-driven paper collection, but it is not yet a guaranteed 24/7 background collector.

The next infrastructure step can be a small worker/cron service that runs the same scanner independently and writes to Supabase. The phone dashboard can remain the front end.

## Research note

The probability model is a baseline lognormal approximation. It does not perfectly emulate Kalshi's settlement reference, fees, queue position, slippage or latency.
