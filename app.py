
import math
import time
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

def insert_paper_trade(ticker, side, entry, model_p, edge, contracts, seconds_left=None):
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
        "seconds_left": float(seconds_left) if seconds_left is not None else None,
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



# -------------------- SIGNAL JOURNAL --------------------
def signal_journal_recent(limit=1000):
    try:
        res = (
            sb.table("signal_journal")
            .select("*")
            .order("observed_at", desc=True)
            .limit(limit)
            .execute()
        )
        return pd.DataFrame(res.data or [])
    except Exception:
        # V3 remains runnable if the optional signal_journal table has not
        # been created yet. The setup banner below tells the user what to do.
        return pd.DataFrame()


def log_signal_snapshot(ticker, decision, side, entry_price, model_prob, edge,
                        seconds_left, spread, strike, spot, ann_vol, reason):
    # One observation per ticker/decision/30-second bucket keeps the journal useful
    # without flooding the database every second.
    bucket = int(time.time() // 30)
    key = f"{ticker}:{bucket}"
    try:
        exists = (
            sb.table("signal_journal")
            .select("id")
            .eq("signal_key", key)
            .limit(1)
            .execute()
        )
        if exists.data:
            return False
        row = {
            "signal_key": key,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "decision": decision,
            "side": side,
            "entry_price": float(entry_price) if entry_price is not None else None,
            "model_prob": float(model_prob),
            "market_prob": float(entry_price) if entry_price is not None else None,
            "edge": float(edge),
            "seconds_left": float(seconds_left),
            "spread": float(spread),
            "strike": float(strike),
            "spot": float(spot),
            "ann_vol": float(ann_vol),
            "reason": reason,
        }
        sb.table("signal_journal").insert(row).execute()
        return True
    except Exception:
        return False


def why_signal(side, edge, price, spread, seconds_left, min_edge, max_price, max_spread):
    if side != "PASS":
        reasons = [
            f"{side} shows {edge*100:+.1f}% model-vs-market edge",
            f"entry is {price*100:.1f}¢ within the {max_price*100:.0f}¢ price limit",
            f"spread is {spread*100:.1f}¢ within the {max_spread*100:.1f}¢ limit",
            f"{int(seconds_left//60)}:{int(seconds_left%60):02d} remains before close",
        ]
        return " • ".join(reasons)
    failures = []
    if price is None:
        failures.append(f"best edge {edge*100:+.1f}% is below the {min_edge*100:.1f}% threshold")
    else:
        if edge < min_edge:
            failures.append(f"edge {edge*100:+.1f}% is below {min_edge*100:.1f}%")
        if price > max_price:
            failures.append(f"entry {price*100:.1f}¢ exceeds {max_price*100:.0f}¢")
        if spread > max_spread:
            failures.append(f"spread {spread*100:.1f}¢ exceeds {max_spread*100:.1f}¢")
    return "PASS because " + "; ".join(failures or ["no configured filter is cleared"]) + "."


def bucket_label(value, edges, labels):
    try:
        return pd.cut(pd.Series([float(value)]), bins=edges, labels=labels, include_lowest=True)[0]
    except Exception:
        return None


def performance_metrics(trades):
    if trades.empty:
        return {}
    resolved = trades[trades["status"] == "RESOLVED"].copy()
    if resolved.empty:
        return {"resolved": 0, "wins": 0, "losses": 0, "winrate": 0.0, "pnl": 0.0}
    pnl_s = pd.to_numeric(resolved["pnl"], errors="coerce").fillna(0.0)
    wins = int((resolved["outcome"] == "WIN").sum())
    losses = int((resolved["outcome"] == "LOSS").sum())
    gross_profit = float(pnl_s[pnl_s > 0].sum())
    gross_loss = float(-pnl_s[pnl_s < 0].sum())
    return {
        "resolved": wins + losses,
        "wins": wins,
        "losses": losses,
        "winrate": wins / (wins + losses) if wins + losses else 0.0,
        "pnl": float(pnl_s.sum()),
        "avg_pnl": float(pnl_s.mean()),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": gross_profit / gross_loss if gross_loss else float("inf") if gross_profit else 0.0,
        "max_drawdown": float((pnl_s.cumsum() - pnl_s.cumsum().cummax()).min()) if len(pnl_s) else 0.0,
        "avg_edge": float(pd.to_numeric(resolved["edge"], errors="coerce").mean()),
        "avg_stake": float(pd.to_numeric(resolved["stake"], errors="coerce").mean()),
    }


def render_analytics(trades):
    st.markdown('<div class="section">Research analytics</div>', unsafe_allow_html=True)
    if trades.empty:
        st.info("Analytics will populate as paper positions resolve.")
        return
    resolved = trades[trades["status"] == "RESOLVED"].copy()
    if resolved.empty:
        st.info("Waiting for the first resolved paper positions.")
        return

    for c in ["pnl", "edge", "entry_price", "stake", "model_prob", "contracts"]:
        if c in resolved.columns:
            resolved[c] = pd.to_numeric(resolved[c], errors="coerce")
    resolved["pnl"] = resolved["pnl"].fillna(0)
    m = performance_metrics(trades)
    a,b,c,d,e = st.columns(5)
    a.metric("AVG EDGE", pct(m["avg_edge"]))
    b.metric("EXPECTANCY / TRADE", money(m["avg_pnl"]))
    c.metric("PROFIT FACTOR", "∞" if math.isinf(m["profit_factor"]) else f"{m['profit_factor']:.2f}")
    d.metric("MAX DRAWDOWN", money(m["max_drawdown"]))
    e.metric("100 / 250 / 500", f"{m['resolved']} / 250 / 500")

    # Calibration on resolved paper trades: predicted probability versus realized outcome.
    cal = resolved.dropna(subset=["model_prob"]).copy()
    if not cal.empty:
        cal["model_prob"] = cal["model_prob"].clip(0,1)
        cal["actual"] = (cal["outcome"] == "WIN").astype(float)
        cal["cal_bucket"] = pd.cut(cal["model_prob"], bins=[0,.2,.4,.6,.8,1], include_lowest=True)
        caltab = cal.groupby("cal_bucket", observed=False).agg(
            signals=("actual","size"),
            predicted=("model_prob","mean"),
            actual=("actual","mean"),
        ).reset_index()
        caltab["predicted"] = caltab["predicted"].map(lambda x: f"{x*100:.1f}%")
        caltab["actual"] = caltab["actual"].map(lambda x: f"{x*100:.1f}%")
        st.markdown("**Model calibration** — resolved paper trades grouped by predicted probability.")
        st.dataframe(caltab, use_container_width=True, hide_index=True)

    # Entry/edge/time buckets.
    resolved["price_bucket"] = pd.cut(resolved["entry_price"], bins=[0,.25,.5,.65,.75,1], include_lowest=True)
    resolved["edge_bucket"] = pd.cut(resolved["edge"], bins=[-1,.05,.08,.12,.20,1], include_lowest=True)
    # Paper journal does not yet store seconds_left; use the optional field if a future schema adds it.
    if "seconds_left" in resolved.columns:
        resolved["time_bucket"] = pd.cut(resolved["seconds_left"], bins=[-1,60,180,300,600,900,999999], include_lowest=True)
    else:
        resolved["time_bucket"] = "not captured in legacy trades"

    for title, col in [("Entry price", "price_bucket"), ("Edge", "edge_bucket"), ("Time remaining", "time_bucket")]:
        g = resolved.groupby(col, observed=False).agg(
            trades=("pnl","size"),
            win_rate=("outcome", lambda s: (s == "WIN").mean()),
            avg_pnl=("pnl","mean"),
            total_pnl=("pnl","sum"),
        ).reset_index()
        g["win_rate"] = g["win_rate"].map(lambda x: f"{x*100:.1f}%")
        g["avg_pnl"] = g["avg_pnl"].map(money)
        g["total_pnl"] = g["total_pnl"].map(money)
        st.markdown(f"**Results by {title.lower()}**")
        st.dataframe(g, use_container_width=True, hide_index=True)

    # Equity curve.
    eq = resolved.sort_values("created_at").copy()
    eq["pnl"] = pd.to_numeric(eq["pnl"], errors="coerce").fillna(0)
    eq["equity"] = eq["pnl"].cumsum()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(range(1, len(eq)+1)), y=eq["equity"], mode="lines", name="Paper equity"))
    fig.update_layout(height=280, margin=dict(l=0,r=0,t=10,b=0), paper_bgcolor="#050505", plot_bgcolor="#050505", font=dict(color="#cfcfcf"), xaxis_title="Resolved trade", yaxis_title="Cumulative P&L", showlegend=False)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def fetch_live_state():
    markets = kalshi_markets()
    spot = coinbase_spot()
    candles = coinbase_candles()
    ann_vol = realized_vol(candles)
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
            "ticker": m.get("ticker", ""), "close_time": pd.to_datetime(m.get("close_time")),
            "close_ts": close_ts, "strike": strike, "yes_bid": yes_bid, "yes_ask": yes_ask,
            "mid": mid, "spread": spread, "volume": float(m.get("volume") or m.get("volume_24h") or 0),
            "oi": float(m.get("open_interest") or 0), "seconds_left": seconds_left, "model_p": mp,
        })
    return spot, candles, ann_vol, pd.DataFrame(active).sort_values("close_time") if active else pd.DataFrame()

# -------------------- CONTROLS --------------------
with st.sidebar:
    st.markdown("## BLACKGOLD controls")
    min_edge = st.slider("Minimum edge", 0.01, 0.25, 0.08, 0.01)
    max_price = st.slider("Max entry price", 0.50, 0.95, 0.75, 0.01)
    max_spread = st.slider("Max spread", 0.01, 0.10, 0.03, 0.01)
    risk_per_trade = st.number_input("Paper risk / trade", 1.0, 100.0, 10.0, 1.0)
    auto_paper = st.toggle("AUTO PAPER TRADING", value=True)
    st.caption("Gold = signal layer. Black = execution journal. No live Kalshi orders.")

# Session state keeps the latest market close available to the 1-second countdown fragment.
if "best_close_ts" not in st.session_state:
    st.session_state["best_close_ts"] = None
if "best_ticker" not in st.session_state:
    st.session_state["best_ticker"] = ""
if "last_resolve" not in st.session_state:
    st.session_state["last_resolve"] = 0.0

# -------------------- CONTINUOUS COUNTDOWN --------------------
# The dashboard fragment reruns every second. Market endpoints are independently
# cached for a few seconds, so the countdown can move every second without
# hammering the external APIs every second.

# -------------------- LIVE DASHBOARD --------------------
@st.fragment(run_every="1s")
def live_dashboard():
    try:
        spot, candles, ann_vol, df = fetch_live_state()
    except Exception as e:
        st.error(f"Live data connection failed: {e}")
        return
    if df.empty:
        st.warning("No open KXBTC15M contract was returned.")
        return

    df["yes_edge"] = df["model_p"] - df["yes_ask"]
    df["no_price"] = 1.0 - df["yes_bid"]
    df["no_model"] = 1.0 - df["model_p"]
    df["no_edge"] = df["no_model"] - df["no_price"]
    best = df.iloc[0]
    st.session_state["best_close_ts"] = float(best["close_ts"])
    st.session_state["best_ticker"] = str(best["ticker"])

    yes_ok = best["yes_ask"] > 0 and best["yes_ask"] <= max_price and best["spread"] <= max_spread and best["yes_edge"] >= min_edge
    no_ok = best["no_price"] > 0 and best["no_price"] <= max_price and best["spread"] <= max_spread and best["no_edge"] >= min_edge
    if yes_ok and best["yes_edge"] >= best["no_edge"]:
        signal_side, signal_edge, signal_price, signal_prob = "YES", float(best["yes_edge"]), float(best["yes_ask"]), float(best["model_p"])
    elif no_ok:
        signal_side, signal_edge, signal_price, signal_prob = "NO", float(best["no_edge"]), float(best["no_price"]), float(best["no_model"])
    else:
        signal_side, signal_edge, signal_price, signal_prob = "PASS", float(max(best["yes_edge"], best["no_edge"])), None, float(best["model_p"])

    why = why_signal(signal_side, signal_edge, signal_price, float(best["spread"]), float(best["seconds_left"]), min_edge, max_price, max_spread)
    log_signal_snapshot(best["ticker"], "SIGNAL" if signal_side != "PASS" else "PASS", signal_side, signal_price, signal_prob, signal_edge, best["seconds_left"], best["spread"], best["strike"], spot, ann_vol, why)

    auto_logged = False
    if auto_paper and signal_side != "PASS":
        contracts = max(1, int(risk_per_trade / max(signal_price, 0.01)))
        try:
            auto_logged = insert_paper_trade(best["ticker"], signal_side, signal_price, signal_prob, signal_edge, contracts, best["seconds_left"])
        except Exception:
            auto_logged = False

    resolved_count = 0
    if time.time() - st.session_state["last_resolve"] >= 5:
        resolved_count = resolve_open_trades()
        st.session_state["last_resolve"] = time.time()

    st.markdown("""
    <div class="hero">
      <div class="brand">BLACKGOLD • MARKET INTELLIGENCE</div>
      <h1>₿ BTC 15M / KALSHI EDGE SCANNER</h1>
      <p>Live BTC structure • Kalshi pricing • model edge • automatic paper journal</p>
    </div><div class="goldline"></div>
    """, unsafe_allow_html=True)
    status_msgs = []
    if auto_logged: status_msgs.append("AUTO PAPER ENTRY LOGGED")
    if resolved_count: status_msgs.append(f"{resolved_count} PAPER POSITION(S) RESOLVED")
    if status_msgs:
        st.markdown('<div class="small" style="border:1px solid #5d4b17;border-radius:10px;padding:8px 12px;margin:8px 0;background:#0d0d0d;color:#d4af37;">' + " &nbsp;•&nbsp; ".join(status_msgs) + '</div>', unsafe_allow_html=True)

    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("BTC SPOT", money(spot)); c2.metric("NEXT STRIKE", money(float(best["strike"])))
    c3.metric("TIME LEFT", f"{int(max(0, best['seconds_left'])//60)}:{int(max(0, best['seconds_left'])%60):02d}")
    c4.metric("1M REALIZED VOL", pct(ann_vol)); c5.metric("MODEL YES", pct(float(best["model_p"])))

    st.markdown('<div class="section">Signal engine</div>', unsafe_allow_html=True)
    left, right = st.columns([1.4,1])
    with left:
        if signal_side == "PASS":
            st.markdown(f'<div class="signal"><div class="small">CURRENT DECISION</div><h2>PASS / WATCH</h2><p class="small">{why}</p></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="signal"><div class="small">AUTO PAPER SIGNAL</div><h2>{signal_side} • {cents(signal_price)}</h2><p class="small">Estimated edge: {100*signal_edge:+.1f}% • model probability: {pct(signal_prob)}</p><p class="small"><b>WHY THIS TRADE:</b> {why}</p></div>', unsafe_allow_html=True)
    with right:
        x,y,z = st.columns(3); x.metric("YES ASK", cents(float(best["yes_ask"]))); y.metric("YES EDGE", f"{100*best['yes_edge']:+.1f}%"); z.metric("SPREAD", cents(float(best["spread"])))

    st.markdown('<div class="section">BTC structure print</div>', unsafe_allow_html=True)
    if len(candles):
        plot_df = candles.tail(120).copy()
        fig = go.Figure(data=[go.Candlestick(x=plot_df["ts"],open=plot_df["open"],high=plot_df["high"],low=plot_df["low"],close=plot_df["close"],increasing_line_color="#d4af37",decreasing_line_color="#6f6f6f",increasing_fillcolor="#d4af37",decreasing_fillcolor="#202020",name="BTC")])
        fig.update_layout(height=360,margin=dict(l=0,r=0,t=10,b=0),paper_bgcolor="#050505",plot_bgcolor="#050505",font=dict(color="#cfcfcf"),xaxis=dict(showgrid=False,rangeslider=dict(visible=False)),yaxis=dict(showgrid=True,gridcolor="#181818",side="right"),showlegend=False)
        st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})

    st.markdown('<div class="section">KXBTC15M board</div>', unsafe_allow_html=True)
    view=df.copy(); view["close_time"]=view["close_time"].dt.strftime("%H:%M:%S UTC"); view["strike"]=view["strike"].map(money); view["yes_bid"]=view["yes_bid"].map(cents); view["yes_ask"]=view["yes_ask"].map(cents); view["no_price"]=view["no_price"].map(cents); view["model_p"]=view["model_p"].map(pct); view["yes_edge"]=view["yes_edge"].map(lambda x:f"{100*x:+.1f}%"); view["no_edge"]=view["no_edge"].map(lambda x:f"{100*x:+.1f}%"); view["spread"]=view["spread"].map(cents); view["minutes"]=view["seconds_left"].map(lambda x:f"{int(x//60)}:{int(x%60):02d}")
    st.dataframe(view[["ticker","close_time","strike","minutes","yes_bid","yes_ask","no_price","spread","model_p","yes_edge","no_edge","volume","oi"]],use_container_width=True,hide_index=True)

    st.markdown('<div class="section">Paper performance</div>', unsafe_allow_html=True)
    trades=recent_trades(500)
    if not trades.empty:
        m=performance_metrics(trades); a,b,c,d,e=st.columns(5); a.metric("RESOLVED",str(m.get("resolved",0))); b.metric("WIN RATE",pct(m.get("winrate",0))); c.metric("PAPER P&L",money(m.get("pnl",0))); d.metric("OPEN",str(int((trades["status"]=="OPEN").sum()))); e.metric("AVG EDGE",pct(m.get("avg_edge",0)))
        show=trades.copy(); show["created_at"]=pd.to_datetime(show["created_at"]).dt.strftime("%m-%d %H:%M:%S"); cols=[c for c in ["created_at","ticker","side","entry_price","model_prob","edge","contracts","stake","status","outcome","pnl"] if c in show.columns]; st.dataframe(show[cols],use_container_width=True,hide_index=True)
        render_analytics(trades)
    else:
        st.info("No paper trades yet. Auto-paper mode will log a qualifying setup once the filters are met.")

    st.markdown('<div class="section">Signal journal</div>', unsafe_allow_html=True)
    sj=signal_journal_recent(500)
    if sj.empty:
        st.caption("Signal journal table is not available yet. Run schema_v3.sql in Supabase once to enable PASS/signal history.")
    if not sj.empty:
        st.dataframe(sj[[c for c in ["observed_at","ticker","decision","side","entry_price","model_prob","edge","seconds_left","spread","reason"] if c in sj.columns]],use_container_width=True,hide_index=True)
    else:
        st.info("Signal journal is waiting for its first snapshot.")

    st.markdown("""
    <div class="small"><b>Research mode:</b> This build never sends a live Kalshi order. The probability model is a baseline lognormal approximation and does not fully reproduce Kalshi's settlement methodology, fees, queue position, slippage or latency. Paper results are for validation, not a guarantee of future performance.</div>
    """, unsafe_allow_html=True)

live_dashboard()
