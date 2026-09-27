
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import streamlit as st
from scipy.stats import norm

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
COINBASE_BASE = "https://api.exchange.coinbase.com"

DB = Path("paper_trades.sqlite3")

st.set_page_config(page_title="BTC 15M Kalshi Edge Scanner", page_icon="₿", layout="wide")

# ---------- Data ----------
@st.cache_data(ttl=2)
def kalshi_markets():
    url = f"{KALSHI_BASE}/markets"
    r = requests.get(url, params={
        "series_ticker": "KXBTC15M",
        "status": "open",
        "limit": 1000,
    }, timeout=10)
    r.raise_for_status()
    return r.json().get("markets", [])

@st.cache_data(ttl=3)
def coinbase_spot():
    r = requests.get(f"{COINBASE_BASE}/products/BTC-USD/ticker", timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])

@st.cache_data(ttl=30)
def coinbase_1m_vol():
    # Coinbase public candles: [time, low, high, open, close, volume]
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(hours=6)
    r = requests.get(
        f"{COINBASE_BASE}/products/BTC-USD/candles",
        params={
            "granularity": 60,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        timeout=10,
    )
    r.raise_for_status()
    rows = r.json()
    if len(rows) < 30:
        return 0.70
    df = pd.DataFrame(rows, columns=["ts","low","high","open","close","volume"])
    df = df.sort_values("ts")
    close = pd.to_numeric(df["close"], errors="coerce")
    ret = np.log(close / close.shift(1)).dropna()
    # Annualized realized vol from 1-minute returns.
    ann = float(ret.std(ddof=1) * math.sqrt(365 * 24 * 60))
    return float(np.clip(ann, 0.20, 2.50))

def iso_seconds(ts):
    if ts is None:
        return None
    return pd.Timestamp(ts).tz_convert("UTC").timestamp()

def model_probability(spot, strike, seconds_left, ann_vol):
    """
    Research model:
    P(BTC close >= strike) under a driftless lognormal approximation.
    KXBTC15M settlement uses Kalshi's reference methodology, including
    the final-minute average; this model is therefore intentionally an
    approximation and is not a settlement emulator.
    """
    if seconds_left <= 0:
        return 0.5
    T = seconds_left / (365 * 24 * 3600)
    sigma = max(ann_vol, 0.05)
    z = (math.log(strike / spot) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return float(np.clip(1.0 - norm.cdf(z), 0.001, 0.999))

def dollar(x):
    return f"${x:,.2f}"

def pct(x):
    return f"{100*x:.1f}%"

def cents(x):
    return f"{100*x:.1f}¢"

# ---------- Journal ----------
def init_db():
    con = sqlite3.connect(DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            entry REAL NOT NULL,
            model_prob REAL NOT NULL,
            market_prob REAL NOT NULL,
            edge REAL NOT NULL,
            contracts INTEGER NOT NULL,
            stake REAL NOT NULL,
            notes TEXT
        )
    """)
    con.commit()
    con.close()

def add_trade(ticker, side, entry, model_p, market_p, edge, contracts, notes):
    con = sqlite3.connect(DB)
    con.execute("""
        INSERT INTO paper_trades
        (created_at,ticker,side,entry,model_prob,market_prob,edge,contracts,stake,notes)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        datetime.now(timezone.utc).isoformat(),
        ticker, side, entry, model_p, market_p, edge,
        contracts, entry * contracts, notes
    ))
    con.commit()
    con.close()

def get_trades():
    con = sqlite3.connect(DB)
    df = pd.read_sql_query("SELECT * FROM paper_trades ORDER BY id DESC", con)
    con.close()
    return df

init_db()

# ---------- UI ----------
st.title("₿ BTC 15M • Kalshi Edge Scanner")
st.caption("Read-only research + paper trading. It does not place live Kalshi orders.")

with st.sidebar:
    st.header("Scanner rules")
    min_edge = st.slider("Minimum edge", 0.01, 0.25, 0.08, 0.01)
    max_price = st.slider("Max entry price", 0.50, 0.95, 0.75, 0.01)
    max_spread = st.slider("Max spread", 0.01, 0.10, 0.03, 0.01)
    bankroll = st.number_input("Paper bankroll ($)", min_value=50.0, value=500.0, step=50.0)
    risk_per_trade = st.number_input("Paper risk/trade ($)", min_value=1.0, value=10.0, step=1.0)
    refresh = st.number_input("Refresh seconds", min_value=2, max_value=60, value=5, step=1)

    st.divider()
    st.markdown("**Model note**")
    st.write(
        "The model is a baseline probability estimate using live BTC spot, "
        "realized 1-minute volatility, strike distance and time remaining. "
        "It is not a guarantee and should be validated out-of-sample."
    )

try:
    markets = kalshi_markets()
    spot = coinbase_spot()
    ann_vol = coinbase_1m_vol()
except Exception as e:
    st.error(f"Live data connection failed: {e}")
    st.info("If deployed, check that outbound HTTPS requests are allowed.")
    st.stop()

now = datetime.now(timezone.utc).timestamp()
active = []
for m in markets:
    close_ts = iso_seconds(m.get("close_time"))
    open_ts = iso_seconds(m.get("open_time"))
    if not close_ts or close_ts <= now:
        continue
    strike = m.get("floor_strike")
    if strike is None:
        strike = m.get("strike")
    if strike is None:
        continue
    try:
        strike = float(strike)
    except Exception:
        continue
    yes_bid = float(m.get("yes_bid_dollars") or m.get("yes_bid") or 0)
    yes_ask = float(m.get("yes_ask_dollars") or m.get("yes_ask") or 0)
    last = float(m.get("last_price_dollars") or m.get("last_price") or 0)
    spread = max(0.0, yes_ask - yes_bid)
    mid = (yes_bid + yes_ask) / 2 if yes_bid and yes_ask else last
    seconds_left = close_ts - now
    model_p = model_probability(spot, strike, seconds_left, ann_vol)
    edge = model_p - mid
    active.append({
        "ticker": m.get("ticker",""),
        "close_time": pd.to_datetime(m.get("close_time")),
        "strike": strike,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "mid": mid,
        "spread": spread,
        "volume": float(m.get("volume") or 0),
        "oi": float(m.get("open_interest") or 0),
        "seconds_left": seconds_left,
        "model_p": model_p,
        "edge": edge,
    })

if not active:
    st.warning("No open KXBTC15M contract was returned by the public API.")
    st.stop()

df = pd.DataFrame(active).sort_values("close_time")
best = df.iloc[0].to_dict()

# Header metrics
c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("BTC spot", dollar(spot))
c2.metric("Next target", dollar(best["strike"]))
c3.metric("Time left", f"{int(best['seconds_left']//60)}m {int(best['seconds_left']%60):02d}s")
c4.metric("1m realized vol", pct(ann_vol))
c5.metric("Model YES", pct(best["model_p"]))

st.divider()

# Main signal
entry_yes = best["yes_ask"]
entry_no = 1.0 - best["yes_bid"] if best["yes_bid"] else None
yes_edge = best["model_p"] - entry_yes if entry_yes else -1
no_model = 1.0 - best["model_p"]
no_edge = no_model - entry_no if entry_no else -1

yes_ok = entry_yes > 0 and entry_yes <= max_price and best["spread"] <= max_spread and yes_edge >= min_edge
no_ok = entry_no is not None and entry_no <= max_price and best["spread"] <= max_spread and no_edge >= min_edge

if yes_ok and yes_edge >= no_edge:
    signal, signal_edge, signal_price, signal_side, signal_prob = "🟢 YES SETUP", yes_edge, entry_yes, "YES", best["model_p"]
elif no_ok:
    signal, signal_edge, signal_price, signal_side, signal_prob = "🟢 NO SETUP", no_edge, entry_no, "NO", no_model
else:
    signal, signal_edge, signal_price, signal_side, signal_prob = "⚪ PASS / WATCH", max(yes_edge,no_edge), None, "PASS", max(best["model_p"],no_model)

a,b,c,d = st.columns(4)
a.metric("Signal", signal)
b.metric("YES ask", cents(entry_yes))
c.metric("YES model edge", f"{100*yes_edge:+.1f}%")
d.metric("Spread", cents(best["spread"]))

st.subheader("Next contract")
left,right = st.columns([1.4,1])
with left:
    st.dataframe(
        pd.DataFrame([{
            "Ticker": best["ticker"],
            "Target": dollar(best["strike"]),
            "YES bid": cents(best["yes_bid"]),
            "YES ask": cents(best["yes_ask"]),
            "Model YES": pct(best["model_p"]),
            "YES edge @ ask": f"{100*yes_edge:+.1f}%",
            "Model NO": pct(no_model),
            "NO edge @ implied ask": f"{100*no_edge:+.1f}%",
            "24h/total volume": f"{best['volume']:,.0f}",
            "Open interest": f"{best['oi']:,.0f}",
        }]),
        use_container_width=True,
        hide_index=True,
    )
with right:
    st.markdown("### Decision logic")
    st.write(f"**BTC:** {dollar(spot)}")
    st.write(f"**Strike:** {dollar(best['strike'])}")
    st.write(f"**Distance:** {100*(spot/best['strike']-1):+.3f}%")
    st.write(f"**Annualized 1m vol:** {pct(ann_vol)}")
    st.write(f"**Model:** {pct(best['model_p'])} YES")
    st.write(f"**Minimum required edge:** {100*min_edge:.1f}%")
    if signal_side != "PASS":
        st.success(f"{signal_side} candidate at about {cents(signal_price)}")
    else:
        st.info("No contract currently clears every filter.")

st.subheader("Upcoming KXBTC15M contracts")
view = df.copy()
view["close_time"] = view["close_time"].dt.strftime("%H:%M:%S UTC")
view["strike"] = view["strike"].map(dollar)
view["yes_bid"] = view["yes_bid"].map(cents)
view["yes_ask"] = view["yes_ask"].map(cents)
view["model_p"] = view["model_p"].map(pct)
view["edge"] = view["edge"].map(lambda x: f"{100*x:+.1f}%")
view["spread"] = view["spread"].map(cents)
view["minutes"] = view["seconds_left"].map(lambda x: f"{int(x//60)}:{int(x%60):02d}")
st.dataframe(
    view[["ticker","close_time","strike","minutes","yes_bid","yes_ask","spread","model_p","edge","volume","oi"]],
    use_container_width=True, hide_index=True
)

# Paper trade
st.subheader("Paper trade")
if signal_side != "PASS":
    max_contracts = max(1, int(risk_per_trade / max(signal_price, 0.01)))
    contracts = st.number_input("Contracts", min_value=1, max_value=max(1, max_contracts*10), value=max_contracts, step=1)
    notes = st.text_input("Notes", value=f"Scanner signal: {signal}. Edge={100*signal_edge:.1f}%")
    if st.button(f"Log PAPER {signal_side} @ {cents(signal_price)}", type="primary"):
        add_trade(best["ticker"], signal_side, signal_price, signal_prob,
                  signal_prob if signal_side == "YES" else 1-signal_prob,
                  signal_edge, int(contracts), notes)
        st.success("Paper trade logged. No Kalshi order was sent.")
else:
    st.info("No paper trade offered because the current market does not meet the configured edge filters.")

st.divider()
trades = get_trades()
st.subheader("Paper journal")
if len(trades):
    st.dataframe(trades, use_container_width=True, hide_index=True)
    total_stake = trades["stake"].sum()
    st.caption(f"{len(trades)} paper entries • total notional logged: ${total_stake:,.2f}")
else:
    st.caption("No paper trades logged yet.")

st.caption(
    "Important: this is a research scanner, not financial advice. "
    "The baseline model can be wrong, especially during sudden BTC moves, "
    "and it does not fully model Kalshi's final-minute reference averaging, "
    "fees, queue position, slippage or latency."
)

# Simple auto-refresh using browser meta refresh.
st.markdown(
    f'<meta http-equiv="refresh" content="{int(refresh)}">',
    unsafe_allow_html=True
)
