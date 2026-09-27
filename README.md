
# BTC 15M Kalshi Edge Scanner

A read-only/paper-trading dashboard for Kalshi's KXBTC15M markets.

## What it does

- Pulls open KXBTC15M contracts from Kalshi's public Trade API.
- Pulls BTC-USD spot and 1-minute candles from Coinbase Exchange's public API.
- Estimates a baseline probability that BTC finishes above the Kalshi strike.
- Compares model probability with the live YES ask.
- Filters for edge, spread and entry price.
- Shows the next active contract and upcoming contracts.
- Logs paper trades to a local SQLite database.
- NEVER places a live Kalshi order.

## Run locally

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows:
# .venv\Scripts\activate

pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL Streamlit prints.

## Deploy

Streamlit Community Cloud can deploy this repo/app. The entry file is `app.py`.

## Data / architecture

Kalshi market data is public. The app uses:
`https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXBTC15M&status=open`

The scanner uses `floor_strike`, `open_time`, `close_time`, and v2 dollar price fields where available.

The probability model is intentionally a baseline research model:
driftless lognormal approximation using current BTC spot, realized 1-minute volatility and time remaining.

It is NOT a claim of profitability.

## Important

KXBTC15M settlement uses Kalshi's reference methodology, including the final-minute averaging procedure. The simple model in this first version does not fully reproduce that settlement process.

The correct development path is:

1. Run the scanner in paper mode.
2. Collect at least 100-300 signals.
3. Compare predicted probabilities to actual resolutions.
4. Calibrate the model.
5. Add realistic fees/spread/slippage/latency.
6. Only after positive out-of-sample results consider any live execution layer.

Do not put Kalshi private API keys into this first version.
