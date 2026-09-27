
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from scipy.stats import norm
from supabase import create_client

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
COINBASE_BASE = "https://api.exchange.coinbase.com"

st.set_page_config(
    page_title="BLACKGOLD • BTC 15M",
    page_icon="₿",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# -------------------- STYLE --------------------
st.markdown("""
<style>
:root {
    --bg: #050505;
    --panel: #0d0d0d;
    --panel2: #111111;
    --gold: #d4af37;
    --gold2: #f0d77a;
    --muted: #8d8d8d;
    --line: #242424;
}
html, body, [data-testid="stAppViewContainer"] {
    background: var(--bg);
    color: #f4f4f4;
}
[data-testid="stHeader"] { background: rgba(5,5,5,.95); }
.block-container { max-width: 1450px; padding-top: 1.2rem; }
[data-testid="stMetric"] {
    background: linear-gradient(145deg, #0d0d0d, #090909);
    border: 1px solid #262626;
    border-radius: 14px;
    padding: 12px 14px;
}
[data-testid="stMetricLabel"] { color: #9a9a9a !important; }
[data-testid="stMetricValue"] { color: #f1d46a !important; }
.stButton > button {
    background: linear-gradient(180deg, #e3c55a, #b58b18);
    color: #050505;
    border: 0;
    font-weight: 800;
    border-radius: 10px;
}
.stButton > button:hover { filter: brightness(1.08); }
[data-testid="stDataFrame"] {
    border: 1px solid #252525;
    border-radius: 12px;
}
.goldline {
    height: 2px;
    background: linear-gradient(90deg, transparent, #d4af37, transparent);
    margin: 4px 0 18px;
}
.brand {
    letter-spacing: .18em;
    font-size: .78rem;
    color: #c6c6c6;
    font-weight: 700;
}
.hero {
    border: 1px solid #292929;
    border-radius: 18px;
    padding: 18px 20px;
    background:
      radial-gradient(circle at 80% 10%, rgba(212,175,55,.12), transparent 28%),
      linear-gradient(145deg, #101010, #070707);
}
.hero h1 { margin: 0; font-size: 2.1rem; }
.hero p { color: #8f8f8f; margin: 5px 0 0; }
.section {
    color: #e3c55a;
    letter-spacing: .08em;
    font-size: .78rem;
    font-weight: 800;
    text-transform: uppercase;
    margin: 14px 0 7px;
}
.signal {
    border: 1px solid #5d4b17;
    border-radius: 16px;
    background: linear-gradient(145deg, #15130b, #0b0b0b);
    padding: 18px;
}
.signal h2 { color: #f0d77a; margin: 0; }
.small { color: #888; font-size: .82rem; }
</style>
""", unsafe_allow_html=True)

# -------------------- CONNECTION --------------------
@st.cache_resource
def supabase_client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

try:
    sb = supabase_client()
    db_ok = True
except Exception as e:
    db_ok = False
    sb = None
    st.error("Supabase is not connected yet.")
    st.code('SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"\nSUPABASE_KEY = "YOUR-PUBLISHABLE-KEY"')
    st.stop()

# -------------------- DATA --------------------
@st.cache_data(ttl=2)
def kalshi_markets():
    r = requests.get(
        f"{KALSHI_BASE}/markets",
        params={"series_ticker": "KXBTC15M", "status": "open", "limit": 1000},
        timeout=10,
    )
    r.raise_for_status()
    return r.json().get("markets", [])

@st.cache_data(ttl=2)
def coinbase_spot():
    r = requests.get(f"{COINBASE_BASE}/products/BTC-USD/ticker", timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])

@st.cache_data(ttl=30)
def coinbase_candles():
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(hours=4)
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
    df = pd.DataFrame(rows, columns=["ts","low","high","open","close","volume"])
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    for c in ["low","high","open","close","volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("ts").dropna()

def realized_vol(df):
    if len(df) < 30:
        return 0.70
    ret = np.log(df["close"] / df["close"].shift(1)).dropna()
    ann = float(ret.std(ddof=1) * math.sqrt(365 * 24 * 60))
    return float(np.clip(ann, 0.20, 2.50))

def model_probability(spot, strike, seconds_left, ann_vol):
    if seconds_left <= 0:
        return 0.5
    T = seconds_left / (365 * 24 * 3600)
    sigma = max(ann_vol, 0.05)
    z = (
        math.log(strike / spot) + 0.5 * sigma * sigma * T
    ) / (sigma * math.sqrt(T))
    return float(np.clip(1.0 - norm.cdf(z), 0.001, 0.999))

def ts_seconds(value):
    if not value:
        return None
    try:
        return pd.Timestamp(value).tz_convert("UTC").timestamp()
    except Exception:
        return None

def money(x): return f"${x:,.2f}"
def cents(x): return f"{100*x:.1f}¢"
def pct(x): return f"{100*x:.1f}%"

# -------------------- SUPABASE PAPER JOURNAL --------------------
def open_trades():
    res = (
        sb.table("paper_trades")
        .select("*")
        .eq("status", "OPEN")
        .order("created_at", desc=True)
        .execute()
    )
    return pd.DataFrame(res.data or [])

def recent_trades(limit=100):
    res = (
        sb.table("paper_trades")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return pd.DataFrame(res.data or [])

def has_open_trade(trade_key):
    res = (
        sb.table("paper_trades")
        .select("id")
        .eq("trade_key", trade_key)
        .eq("status", "OPEN")
        .limit(1)
        .execute()
    )
    return bool(res.data)

def insert_paper_trade(ticker, side, entry, model_p, edge, contracts):
    key = f"{ticker}:{side}"
    if has_open_trade(key):
        return False
    row = {
        "trade_key": key,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "side": side,
        "entry_price": float(entry),
        "model_prob": float(model_p),
        "edge": float(edge),
        "contracts": int(contracts),
        "stake": float(entry * contracts),
        "status": "OPEN",
        "notes": "AUTO PAPER — scanner rules",
    }
    sb.table("paper_trades").insert(row).execute()
    return True

def resolve_trade(row):
    ticker = row["ticker"]
    r = requests.get(f"{KALSHI_BASE}/markets/{ticker}", timeout=10)
    r.raise_for_status()
    market = r.json().get("market", r.json())
    result = str(market.get("result") or "").lower()
    settlement = market.get("settlement_value_dollars")
    if not result and settlement is not None:
        try:
            result = "yes" if float(settlement) >= 0.5 else "no"
        except Exception:
            pass
    if result not in ("yes", "no"):
        return False

    side = str(row["side"]).lower()
    won = side == result
    entry = float(row["entry_price"])
    contracts = int(row["contracts"])
    pnl = (contracts * (1.0 - entry)) if won else (-contracts * entry)

    sb.table("paper_trades").update({
        "status": "RESOLVED",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "outcome": "WIN" if won else "LOSS",
        "pnl": float(pnl),
    }).eq("id", row["id"]).execute()
    return True

def resolve_open_trades():
    df = open_trades()
    if df.empty:
        return 0
    count = 0
    for _, row in df.iterrows():
        try:
            if resolve_trade(row):
                count += 1
        except Exception:
            pass
    return count

# -------------------- LOAD LIVE STATE --------------------
try:
    markets = kalshi_markets()
    spot = coinbase_spot()
    candles = coinbase_candles()
    ann_vol = realized_vol(candles)
except Exception as e:
    st.error(f"Live data connection failed: {e}")
    st.stop()

now = datetime.now(timezone.utc).timestamp()
active = []

for m in markets:
    close_ts = ts_seconds(m.get("close_time"))
    if not close_ts or close_ts <= now:
        continue
    strike = m.get("floor_strike", m.get("strike"))
    if strike is None:
        continue
    try:
        strike = float(strike)
        yes_bid = float(m.get("yes_bid_dollars") or m.get("yes_bid") or 0)
        yes_ask = float(m.get("yes_ask_dollars") or m.get("yes_ask") or 0)
        last = float(m.get("last_price_dollars") or m.get("last_price") or 0)
    except Exception:
        continue

    spread = max(0.0, yes_ask - yes_bid)
    mid = (yes_bid + yes_ask) / 2 if yes_bid and yes_ask else last
    seconds_left = close_ts - now
    mp = model_probability(spot, strike, seconds_left, ann_vol)

    active.append({
        "ticker": m.get("ticker", ""),
        "close_time": pd.to_datetime(m.get("close_time")),
        "strike": strike,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "mid": mid,
        "spread": spread,
        "volume": float(m.get("volume") or m.get("volume_24h") or 0),
        "oi": float(m.get("open_interest") or 0),
        "seconds_left": seconds_left,
        "model_p": mp,
    })

if not active:
    st.warning("No open KXBTC15M contract was returned.")
    st.stop()

df = pd.DataFrame(active).sort_values("close_time")
df["yes_edge"] = df["model_p"] - df["yes_ask"]
df["no_price"] = 1.0 - df["yes_bid"]
df["no_model"] = 1.0 - df["model_p"]
df["no_edge"] = df["no_model"] - df["no_price"]

# -------------------- CONTROLS --------------------
with st.sidebar:
    st.markdown("## BLACKGOLD controls")
    min_edge = st.slider("Minimum edge", 0.01, 0.25, 0.08, 0.01)
    max_price = st.slider("Max entry price", 0.50, 0.95, 0.75, 0.01)
    max_spread = st.slider("Max spread", 0.01, 0.10, 0.03, 0.01)
    risk_per_trade = st.number_input("Paper risk / trade", 1.0, 100.0, 10.0, 1.0)
    refresh = st.number_input("Refresh seconds", 3, 60, 5, 1)
    auto_paper = st.toggle("AUTO PAPER TRADING", value=True)
    st.caption("Gold = signal layer. Black = execution journal. No live Kalshi orders.")

best = df.iloc[0]
yes_ok = (
    best["yes_ask"] > 0 and
    best["yes_ask"] <= max_price and
    best["spread"] <= max_spread and
    best["yes_edge"] >= min_edge
)
no_ok = (
    best["no_price"] > 0 and
    best["no_price"] <= max_price and
    best["spread"] <= max_spread and
    best["no_edge"] >= min_edge
)

if yes_ok and best["yes_edge"] >= best["no_edge"]:
    signal_side = "YES"
    signal_edge = float(best["yes_edge"])
    signal_price = float(best["yes_ask"])
    signal_prob = float(best["model_p"])
elif no_ok:
    signal_side = "NO"
    signal_edge = float(best["no_edge"])
    signal_price = float(best["no_price"])
    signal_prob = float(best["no_model"])
else:
    signal_side = "PASS"
    signal_edge = float(max(best["yes_edge"], best["no_edge"]))
    signal_price = None
    signal_prob = float(best["model_p"])

# Auto-paper entry on qualifying signal.
auto_logged = False
if auto_paper and signal_side != "PASS":
    contracts = max(1, int(risk_per_trade / max(signal_price, 0.01)))
    try:
        auto_logged = insert_paper_trade(
            best["ticker"], signal_side, signal_price,
            signal_prob, signal_edge, contracts
        )
    except Exception:
        auto_logged = False

# Resolve any trades whose market has settled.
resolved_count = resolve_open_trades()

# -------------------- HEADER --------------------
st.markdown("""
<div class="hero">
  <div class="brand">BLACKGOLD • MARKET INTELLIGENCE</div>
  <h1>₿ BTC 15M / KALSHI EDGE SCANNER</h1>
  <p>Live BTC structure • Kalshi pricing • model edge • automatic paper journal</p>
</div>
<div class="goldline"></div>
""", unsafe_allow_html=True)

if auto_logged:
    st.toast("AUTO PAPER ENTRY LOGGED", icon="🟡")

if resolved_count:
    st.toast(f"{resolved_count} paper position(s) resolved", icon="✓")

c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("BTC SPOT", money(spot))
c2.metric("NEXT STRIKE", money(float(best["strike"])))
c3.metric("TIME LEFT", f"{int(best['seconds_left']//60)}:{int(best['seconds_left']%60):02d}")
c4.metric("1M REALIZED VOL", pct(ann_vol))
c5.metric("MODEL YES", pct(float(best["model_p"])))

st.markdown('<div class="section">Signal engine</div>', unsafe_allow_html=True)
left, right = st.columns([1.4, 1])

with left:
    if signal_side == "PASS":
        st.markdown(f"""
        <div class="signal">
          <div class="small">CURRENT DECISION</div>
          <h2>PASS / WATCH</h2>
          <p class="small">No setup clears every configured filter.</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="signal">
          <div class="small">AUTO PAPER SIGNAL</div>
          <h2>{signal_side} • {cents(signal_price)}</h2>
          <p class="small">Estimated edge: {100*signal_edge:+.1f}% • model probability: {pct(signal_prob)}</p>
        </div>
        """, unsafe_allow_html=True)

with right:
    x,y,z = st.columns(3)
    x.metric("YES ASK", cents(float(best["yes_ask"])))
    y.metric("YES EDGE", f"{100*best['yes_edge']:+.1f}%")
    z.metric("SPREAD", cents(float(best["spread"])))

# -------------------- STATIC TRADING VISUAL --------------------
st.markdown('<div class="section">BTC structure print</div>', unsafe_allow_html=True)
if len(candles):
    plot_df = candles.tail(120).copy()
    fig = go.Figure(data=[go.Candlestick(
        x=plot_df["ts"],
        open=plot_df["open"],
        high=plot_df["high"],
        low=plot_df["low"],
        close=plot_df["close"],
        increasing_line_color="#d4af37",
        decreasing_line_color="#6f6f6f",
        increasing_fillcolor="#d4af37",
        decreasing_fillcolor="#202020",
        name="BTC"
    )])
    fig.update_layout(
        height=360,
        margin=dict(l=0,r=0,t=10,b=0),
        paper_bgcolor="#050505",
        plot_bgcolor="#050505",
        font=dict(color="#cfcfcf"),
        xaxis=dict(showgrid=False, rangeslider=dict(visible=False)),
        yaxis=dict(showgrid=True, gridcolor="#181818", side="right"),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# -------------------- MARKET TABLE --------------------
st.markdown('<div class="section">KXBTC15M board</div>', unsafe_allow_html=True)
view = df.copy()
view["close_time"] = view["close_time"].dt.strftime("%H:%M:%S UTC")
view["strike"] = view["strike"].map(money)
view["yes_bid"] = view["yes_bid"].map(cents)
view["yes_ask"] = view["yes_ask"].map(cents)
view["no_price"] = view["no_price"].map(cents)
view["model_p"] = view["model_p"].map(pct)
view["yes_edge"] = view["yes_edge"].map(lambda x: f"{100*x:+.1f}%")
view["no_edge"] = view["no_edge"].map(lambda x: f"{100*x:+.1f}%")
view["spread"] = view["spread"].map(cents)
view["minutes"] = view["seconds_left"].map(lambda x: f"{int(x//60)}:{int(x%60):02d}")
st.dataframe(
    view[[
        "ticker","close_time","strike","minutes","yes_bid","yes_ask",
        "no_price","spread","model_p","yes_edge","no_edge","volume","oi"
    ]],
    use_container_width=True,
    hide_index=True
)

# -------------------- JOURNAL / PERFORMANCE --------------------
st.markdown('<div class="section">Paper performance</div>', unsafe_allow_html=True)
trades = recent_trades(250)

if not trades.empty:
    resolved = trades[trades["status"] == "RESOLVED"].copy()
    wins = int((resolved["outcome"] == "WIN").sum()) if not resolved.empty else 0
    losses = int((resolved["outcome"] == "LOSS").sum()) if not resolved.empty else 0
    pnl = float(pd.to_numeric(resolved.get("pnl", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not resolved.empty else 0.0
    winrate = wins / (wins + losses) if wins + losses else 0.0

    a,b,c,d = st.columns(4)
    a.metric("RESOLVED", f"{wins+losses}")
    b.metric("WIN RATE", pct(winrate))
    c.metric("PAPER P&L", money(pnl))
    d.metric("OPEN", str(int((trades["status"] == "OPEN").sum())))

    show = trades.copy()
    show["created_at"] = pd.to_datetime(show["created_at"]).dt.strftime("%m-%d %H:%M")
    cols = [c for c in [
        "created_at","ticker","side","entry_price","model_prob","edge",
        "contracts","stake","status","outcome","pnl"
    ] if c in show.columns]
    st.dataframe(show[cols], use_container_width=True, hide_index=True)
else:
    st.info("No paper trades yet. Auto-paper mode will log a qualifying setup once the filters are met.")

st.markdown("""
<div class="small">
<b>Research mode:</b> This build never sends a live Kalshi order. The probability model is a baseline
lognormal approximation and does not fully reproduce Kalshi's settlement methodology, fees,
queue position, slippage or latency. Paper results are for validation, not a guarantee of future performance.
</div>
""", unsafe_allow_html=True)

# Simple refresh loop. The database keeps the journal persistent even when the app reruns.
st.markdown(f'<meta http-equiv="refresh" content="{int(refresh)}">', unsafe_allow_html=True)
