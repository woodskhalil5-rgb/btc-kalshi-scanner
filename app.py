import math
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from supabase import create_client

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
COINBASE_BASE = "https://api.exchange.coinbase.com"
CF_BASE = "https://www.cfbenchmarks.com/api/v1"

st.set_page_config(page_title="BLACKGOLD V5 • BTC 15M", page_icon="₿", layout="wide", initial_sidebar_state="collapsed")

st.markdown(r'''<style>
:root{--bg:#050505;--panel:#0c0c0c;--panel2:#111;--gold:#d4af37;--gold2:#f5df78;--muted:#8a8a8a;--green:#56d364;--red:#ff6b6b}
html,body,[data-testid="stAppViewContainer"]{background:var(--bg);color:#f4f4f4}
[data-testid="stHeader"]{background:rgba(5,5,5,.96)}
.block-container{max-width:1600px;padding-top:1rem}
[data-testid="stMetric"]{background:linear-gradient(145deg,#101010,#080808);border:1px solid #252525;border-radius:14px;padding:11px 14px}
[data-testid="stMetricLabel"]{color:#929292!important}[data-testid="stMetricValue"]{color:var(--gold2)!important}
.stButton>button{background:linear-gradient(180deg,#e7cb62,#b78e1c);color:#050505;border:0;font-weight:900;border-radius:10px}
[data-testid="stDataFrame"]{border:1px solid #242424;border-radius:12px}
.goldline{height:2px;background:linear-gradient(90deg,transparent,#d4af37,transparent);margin:5px 0 18px}
.hero{border:1px solid #2b2b2b;border-radius:20px;padding:20px 22px;background:radial-gradient(circle at 82% 8%,rgba(212,175,55,.16),transparent 30%),linear-gradient(145deg,#111,#070707);box-shadow:0 12px 40px rgba(0,0,0,.28)}
.brand{letter-spacing:.2em;font-size:.75rem;color:#bdbdbd;font-weight:800}.hero h1{margin:2px 0 0;font-size:2.15rem}.hero p{color:#888;margin:5px 0 0}
.section{color:var(--gold2);letter-spacing:.1em;font-size:.75rem;font-weight:900;text-transform:uppercase;margin:17px 0 8px}
.signal{border:1px solid #6a571d;border-radius:18px;background:radial-gradient(circle at 90% 15%,rgba(212,175,55,.12),transparent 35%),linear-gradient(145deg,#16140b,#090909);padding:22px;box-shadow:0 8px 30px rgba(212,175,55,.05)}
.signal h2{color:var(--gold2);margin:0;font-size:2rem}.small{color:#888;font-size:.82rem}.tag{display:inline-block;border:1px solid #333;border-radius:999px;padding:3px 8px;margin:2px;color:#bcbcbc;font-size:.72rem}.ok{color:var(--green)}.bad{color:var(--red)}
.bigscore{font-size:3rem;font-weight:900;color:var(--gold2);line-height:1}.scorelabel{color:#888;text-transform:uppercase;font-size:.72rem;letter-spacing:.1em}
</style>''', unsafe_allow_html=True)

# Streamlit compatibility: older deployments may not expose st.fragment.
if not hasattr(st, "fragment"):
    def _fragment_fallback(**kwargs):
        def deco(fn):
            return fn
        return deco
    st.fragment=_fragment_fallback

@st.cache_resource
def supabase_client(): return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
try: sb=supabase_client()
except Exception:
    st.error("Supabase is not connected."); st.code('SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"\nSUPABASE_KEY = "YOUR-PUBLISHABLE-KEY"'); st.stop()

# ---------- DATA ----------
@st.cache_data(ttl=2)
def kalshi_markets():
    r=requests.get(f"{KALSHI_BASE}/markets",params={"series_ticker":"KXBTC15M","status":"open","limit":1000},timeout=10); r.raise_for_status(); return r.json().get("markets",[])

@st.cache_data(ttl=2)
def coinbase_spot():
    r=requests.get(f"{COINBASE_BASE}/products/BTC-USD/ticker",timeout=10); r.raise_for_status(); return float(r.json()["price"])

@st.cache_data(ttl=30)
def coinbase_candles(hours=24):
    # Coinbase Exchange candles caps each request at 300 candles.
    # Fetch 4-hour chunks (240 one-minute candles) to build the 24h window.
    end=pd.Timestamp.now(tz="UTC")
    start=end-pd.Timedelta(hours=hours)
    chunks=[]
    cur=start
    while cur < end:
        chunk_end=min(cur+pd.Timedelta(minutes=240),end)
        r=requests.get(
            f"{COINBASE_BASE}/products/BTC-USD/candles",
            params={"granularity":60,"start":cur.isoformat(),"end":chunk_end.isoformat()},
            timeout=10
        )
        r.raise_for_status()
        rows=r.json()
        if rows:
            chunks.extend(rows)
        cur=chunk_end
    if not chunks:
        return pd.DataFrame()
    df=pd.DataFrame(chunks,columns=["ts","low","high","open","close","volume"])
    df["ts"]=pd.to_datetime(df["ts"],unit="s",utc=True)
    for c in ["low","high","open","close","volume"]:
        df[c]=pd.to_numeric(df[c],errors="coerce")
    return df.drop_duplicates("ts").sort_values("ts").dropna()

@st.cache_data(ttl=1)
def cfb_brti():
    # Optional licensed feed. Credentials belong in Streamlit secrets; never hard-code them.
    user=st.secrets.get("CFB_USERNAME",""); key=st.secrets.get("CFB_API_KEY","")
    if not user or not key:return None
    r=requests.get(f"{CF_BASE}/values",params={"id":"BRTI","maxResolution":"PER_SECOND"},headers={"Accept":"application/json"},auth=(user,key),timeout=8); r.raise_for_status()
    p=r.json().get("payload") or []
    if not p:return None
    row=p[-1]; return {"price":float(row["value"]),"time":pd.to_datetime(row["time"],unit="ms",utc=True)}

def underlying():
    try:
        c=cfb_brti()
        if c:return c["price"],"CFB BRTI",c["time"]
    except Exception:pass
    return coinbase_spot(),"COINBASE FALLBACK",pd.Timestamp.now(tz="UTC")

def ts_seconds(v):
    if not v:return None
    try:return pd.Timestamp(v).tz_convert("UTC").timestamp()
    except Exception:return None

def realized_vol(df,window=720):
    if len(df)<30:return .70
    r=np.log(df["close"]/df["close"].shift(1)).dropna().tail(window)
    return float(np.clip(float(r.std(ddof=1)*math.sqrt(365*24*60)),.20,2.50))

def features(df):
    if len(df)<30:return {"ret1":0,"ret3":0,"ret5":0,"ret15":0,"ema_slope":0,"rsi":50,"vol_ratio":1,"atr_pct":0,"regime":"UNKNOWN"}
    c=df["close"].astype(float); r=np.log(c/c.shift(1)).dropna()
    ret=lambda n: float(c.iloc[-1]/c.iloc[-1-n]-1) if len(c)>n else 0
    short=float(r.tail(15).std()); long=float(r.tail(240).std()) if len(r)>=30 else short
    vr=short/long if long else 1
    ema12=c.ewm(span=12).mean(); ema48=c.ewm(span=48).mean(); slope=float((ema12.iloc[-1]/ema12.iloc[-6]-1)*10000)
    d=c.diff(); gain=d.clip(lower=0).rolling(14).mean(); loss=(-d.clip(upper=0)).rolling(14).mean(); rs=gain/(loss.replace(0,np.nan)); rsi=float((100-100/(1+rs)).iloc[-1]) if pd.notna(rs.iloc[-1]) else 50
    tr=pd.concat([df["high"]-df["low"],(df["high"]-c.shift()).abs(),(df["low"]-c.shift()).abs()],axis=1).max(axis=1); atr=float((tr.rolling(14).mean().iloc[-1]/c.iloc[-1])*100)
    if vr>1.7:reg="VOL EXPANSION"
    elif vr<.65:reg="VOL COMPRESSION"
    elif abs(ret(15))>.002:reg="TRENDING"
    elif rsi>65:reg="MOMENTUM UP"
    elif rsi<35:reg="MOMENTUM DOWN"
    else:reg="CHOP"
    return {"ret1":ret(1),"ret3":ret(3),"ret5":ret(5),"ret15":ret(15),"ema_slope":slope,"rsi":rsi,"vol_ratio":vr,"atr_pct":atr,"regime":reg}

def base_probability(spot,strike,seconds,sigma):
    if seconds<=0:return .5
    T=seconds/(365*24*3600); s=max(float(sigma),.05); z=(math.log(strike/spot)+.5*s*s*T)/(s*math.sqrt(T)); return float(np.clip(.5*(1-math.erf(z/math.sqrt(2))),.001,.999))

def expected_move(spot,seconds,sigma):
    return float(spot*sigma*math.sqrt(max(seconds,1)/(365*24*3600)))

# ---------- DB ----------
def recent_trades(limit=2000):
    try:return pd.DataFrame(sb.table("paper_trades").select("*").order("created_at",desc=True).limit(limit).execute().data or [])
    except Exception:return pd.DataFrame()
def open_trades():
    try:return pd.DataFrame(sb.table("paper_trades").select("*").eq("status","OPEN").order("created_at",desc=True).execute().data or [])
    except Exception:return pd.DataFrame()
def journal(limit=5000):
    try:return pd.DataFrame(sb.table("signal_journal").select("*").order("observed_at",desc=True).limit(limit).execute().data or [])
    except Exception:return pd.DataFrame()
def has_open(key):
    try:return bool(sb.table("paper_trades").select("id").eq("trade_key",key).eq("status","OPEN").limit(1).execute().data)
    except Exception:return False

def insert_trade(ticker,side,price,prob,edge,contracts,seconds,regime,score):
    key=f"{ticker}:{side}"
    if has_open(key):return False
    row={"trade_key":key,"created_at":datetime.now(timezone.utc).isoformat(),"ticker":ticker,"side":side,"entry_price":float(price),"model_prob":float(prob),"edge":float(edge),"contracts":int(contracts),"stake":float(price*contracts),"seconds_left":float(seconds),"regime":regime,"signal_score":float(score),"status":"OPEN","notes":"AUTO PAPER — BLACKGOLD V5"}
    try:sb.table("paper_trades").insert(row).execute();return True
    except Exception:return False

def resolve_trades():
    df=open_trades(); n=0
    for _,row in df.iterrows():
        try:
            m=requests.get(f"{KALSHI_BASE}/markets/{row['ticker']}",timeout=8).json().get("market",{})
            result=str(m.get("result") or "").lower(); sv=m.get("settlement_value_dollars")
            if not result and sv is not None:result="yes" if float(sv)>=.5 else "no"
            if result not in ("yes","no"):continue
            won=str(row["side"]).lower()==result; p=float(row["entry_price"]); k=int(row["contracts"]); pnl=k*(1-p) if won else -k*p
            sb.table("paper_trades").update({"status":"RESOLVED","resolved_at":datetime.now(timezone.utc).isoformat(),"outcome":"WIN" if won else "LOSS","pnl":float(pnl)}).eq("id",row["id"]).execute(); n+=1
        except Exception:pass
    return n

def log_snapshot(rec):
    key=f"{rec['ticker']}:{int(time.time()//30)}"
    rec={**rec,"signal_key":key,"observed_at":datetime.now(timezone.utc).isoformat()}
    try:
        if sb.table("signal_journal").select("id").eq("signal_key",key).limit(1).execute().data:return False
        sb.table("signal_journal").insert(rec).execute();return True
    except Exception:return False

def resolve_journal():
    sj=journal(5000)
    if sj.empty or "outcome" not in sj:return
    p=sj[sj["outcome"].isna()]
    for ticker in p["ticker"].dropna().unique():
        try:
            m=requests.get(f"{KALSHI_BASE}/markets/{ticker}",timeout=8).json().get("market",{}); result=str(m.get("result") or "").lower();sv=m.get("settlement_value_dollars")
            if not result and sv is not None:result="yes" if float(sv)>=.5 else "no"
            if result not in ("yes","no"):continue
            for _,r in p[p["ticker"]==ticker].iterrows():
                side=str(r.get("side") or "PASS").lower(); actual=(result=="yes") if side=="pass" else side==result
                sb.table("signal_journal").update({"outcome":"WIN" if actual else "LOSS","resolved_at":datetime.now(timezone.utc).isoformat()}).eq("id",r["id"]).execute()
        except Exception:pass

# ---------- MODEL ----------
def historical_prob(side,price,seconds,regime):
    sj=journal(5000)
    if sj.empty or "outcome" not in sj:return None,0
    d=sj.dropna(subset=["outcome","entry_price","seconds_left"]).copy()
    if d.empty:return None,0
    for c in ["entry_price","seconds_left"]:d[c]=pd.to_numeric(d[c],errors="coerce")
    d=d[(d["side"]==side)&(d["regime"]==regime)]
    d=d[(abs(d["entry_price"]-price)<=.075)&(abs(d["seconds_left"]-seconds)<=180)]
    if len(d)<30:return None,len(d)
    y=(d["outcome"]=="WIN").astype(float); return float((y.sum()+3)/(len(y)+6)),len(y)

def calibrated_probability(raw, side, price, seconds, regime):
    # Side-aware shrinkage. It cannot manufacture evidence; it only calibrates when >=30 comparable observations exist.
    h,n=historical_prob(side,price,seconds,regime)
    if h is None:return raw,h,n
    w=min(.50,n/400); return float(np.clip((1-w)*raw+w*h,.001,.999)),h,n

def score_signal(prob,market,edge,spread,seconds,feat,hist_n):
    components=[]
    components.append(np.clip(abs(edge)/.20,0,1))
    components.append(np.clip(1-spread/.08,0,1))
    components.append(np.clip(seconds/600,0,1))
    components.append(np.clip(abs(feat["ret5"])/.002,0,1))
    components.append(np.clip(1-abs(prob-market)/.5,0,1))
    if hist_n:components.append(np.clip(hist_n/200,0,1))
    else:components.append(.45)
    return float(100*np.mean(components))

def metrics(tr):
    if tr.empty:return {}
    r=tr[tr["status"]=="RESOLVED"].copy()
    if r.empty:return {"resolved":0,"winrate":0,"pnl":0,"expectancy":0,"pf":0,"dd":0,"edge":0}
    p=pd.to_numeric(r["pnl"],errors="coerce").fillna(0); wins=(r["outcome"]=="WIN").sum(); gp=p[p>0].sum();gl=-p[p<0].sum();eq=p.cumsum();dd=eq-eq.cummax()
    return {"resolved":len(r),"winrate":wins/len(r),"pnl":float(p.sum()),"expectancy":float(p.mean()),"pf":float(gp/gl) if gl else float("inf"),"dd":float(dd.min()),"edge":float(pd.to_numeric(r["edge"],errors="coerce").mean())}

def render_research(tr):
    if tr.empty:return
    r=tr[tr["status"]=="RESOLVED"].copy()
    if r.empty:return
    m=metrics(tr); st.markdown('<div class="section">Performance command center</div>',unsafe_allow_html=True)
    a,b,c,d,e,f=st.columns(6);a.metric("RESOLVED",m["resolved"]);b.metric("WIN RATE",f'{m["winrate"]*100:.1f}%');c.metric("P&L",f'${m["pnl"]:,.2f}');d.metric("EXPECTANCY",f'${m["expectancy"]:,.2f}');e.metric("PROFIT FACTOR","∞" if math.isinf(m["pf"]) else f'{m["pf"]:.2f}');f.metric("MAX DD",f'${m["dd"]:,.2f}')
    for c in ["model_prob","entry_price","edge","pnl"]:r[c]=pd.to_numeric(r[c],errors="coerce")
    r["actual"]=(r["outcome"]=="WIN").astype(float); r["bucket"]=pd.cut(r["model_prob"],bins=[0,.2,.4,.6,.8,1],include_lowest=True)
    cal=r.groupby("bucket",observed=False).agg(n=("actual","size"),predicted=("model_prob","mean"),actual=("actual","mean")).reset_index();cal["error"]=cal["actual"]-cal["predicted"]
    st.markdown("**Calibration** — negative error means the model was overconfident. Positive means underconfident.");st.dataframe(cal,use_container_width=True,hide_index=True)
    for title,col in [("Entry price","entry_price"),("Edge","edge"),("Side","side"),("Regime","regime")]:
        if col in r:
            g=r.groupby(col,dropna=False).agg(trades=("pnl","size"),win_rate=("outcome",lambda s:(s=="WIN").mean()),expectancy=("pnl","mean"),total_pnl=("pnl","sum")).reset_index()
            if col in ("entry_price","edge"):g[col]=g[col].map(lambda x:f'{x*100:.1f}¢' if col=="entry_price" else f'{x*100:.1f}%')
            g["win_rate"]=g["win_rate"].map(lambda x:f'{x*100:.1f}%');g["expectancy"]=g["expectancy"].map(lambda x:f'${x:,.2f}');g["total_pnl"]=g["total_pnl"].map(lambda x:f'${x:,.2f}')
            st.markdown(f"**By {title}**");st.dataframe(g,use_container_width=True,hide_index=True)
    r=r.sort_values("created_at");r["equity"]=r["pnl"].cumsum();fig=go.Figure(go.Scatter(x=np.arange(1,len(r)+1),y=r["equity"],mode="lines",name="equity"));fig.update_layout(height=280,margin=dict(l=0,r=0,t=10,b=0),paper_bgcolor="#050505",plot_bgcolor="#050505",font=dict(color="#ccc"),xaxis_title="Resolved trade",yaxis_title="Cumulative P&L",showlegend=False);st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})

# ---------- LIVE ----------
def live_state():
    spot,source,source_time=underlying(); candles=coinbase_candles(24); sigma=realized_vol(candles); feat=features(candles); now=time.time(); rows=[]
    for m in kalshi_markets():
        close=ts_seconds(m.get("close_time")); strike=m.get("floor_strike",m.get("strike"))
        if not close or close<=now or strike is None:continue
        try:
            strike=float(strike);yb=float(m.get("yes_bid_dollars") or m.get("yes_bid") or 0);ya=float(m.get("yes_ask_dollars") or m.get("yes_ask") or 0);last=float(m.get("last_price_dollars") or m.get("last_price") or 0)
        except Exception:continue
        sp=max(0,ya-yb); sec=close-now; bp=base_probability(spot,strike,sec,sigma); rows.append({"ticker":m.get("ticker",""),"close_time":pd.to_datetime(m.get("close_time")),"strike":strike,"yes_bid":yb,"yes_ask":ya,"no_price":1-yb,"spread":sp,"seconds_left":sec,"base_yes":bp,"volume":float(m.get("volume") or 0),"oi":float(m.get("open_interest") or 0)})
    return spot,source,source_time,candles,sigma,feat,pd.DataFrame(rows)

with st.sidebar:
    st.markdown("## BLACKGOLD V5 controls")
    min_edge=st.slider("Minimum net edge",.01,.30,.08,.01)
    max_price=st.slider("Max entry price",.50,.95,.75,.01)
    max_spread=st.slider("Max spread",.01,.10,.03,.01)
    min_score=st.slider("Minimum signal score",50,95,70,1)
    risk=st.number_input("Paper risk / trade",1.0,100.0,10.0,1.0)
    auto=st.toggle("AUTO PAPER",True)
    st.caption("Paper-only. BRTI is used when licensed CFB credentials are configured; otherwise Coinbase is explicitly labeled as fallback.")

if "last_resolve" not in st.session_state:st.session_state.last_resolve=0.0

@st.fragment(run_every="1s")
def dashboard():
    try:spot,source,source_time,candles,sigma,feat,df=live_state()
    except Exception as e:st.error(f"Live data error: {e}");return
    if df.empty:st.warning("No open KXBTC15M contracts returned.");return
    # Evaluate every active contract and both sides. No first-row shortcut.
    candidates=[]
    for _,r in df.iterrows():
        move=expected_move(spot,r.seconds_left,sigma); dist=(r.strike-spot)/max(move,1e-9)
        for side,price in [("YES",r.yes_ask),("NO",r.no_price)]:
            if price<=0:continue
            raw_yes=base_probability(spot,r.strike,r.seconds_left,sigma)
            raw=raw_yes if side=="YES" else 1-raw_yes
            # Momentum adjustment is deliberately small and signed by direction.
            mom=(feat["ret1"]*350+feat["ret3"]*130+feat["ret5"]*70+feat["ret15"]*35)
            time_w=np.clip(300/max(r.seconds_left,20),0,1)
            signed=mom if side=="YES" else -mom
            enhanced=float(np.clip(raw+.025*np.tanh(signed)*time_w,.001,.999))
            cal,h,n=calibrated_probability(enhanced,side,float(price),float(r.seconds_left),feat["regime"])
            edge=cal-float(price); score=score_signal(cal,float(price),edge,float(r.spread),float(r.seconds_left),feat,n)
            qualifies=price<=max_price and r.spread<=max_spread and edge>=min_edge and score>=min_score
            candidates.append({**r.to_dict(),"side":side,"price":float(price),"raw_prob":raw,"prob":cal,"hist":h,"hist_n":n,"edge":edge,"score":score,"expected_move":move,"distance_sigma":dist,"qualifies":qualifies})
    cdf=pd.DataFrame(candidates); qualified=cdf[cdf.qualifies].sort_values(["score","edge"],ascending=False); best=(qualified.iloc[0] if not qualified.empty else cdf.sort_values(["edge","score"],ascending=False).iloc[0])
    decision="SIGNAL" if bool(best.qualifies) else "PASS"; display=best.side if decision=="SIGNAL" else "PASS / WATCH"
    why=(f"{best.side} clears edge, price, spread and score filters. Fair {best.prob*100:.1f}% vs {best.price*100:.1f}¢; +{best.edge*100:.1f}¢ edge; score {best.score:.0f}; {best.seconds_left/60:.1f}m remaining; {feat['regime']}." if decision=="SIGNAL" else f"Best available setup is {best.side} at {best.price*100:.1f}¢ with {best.edge*100:+.1f}¢ edge and score {best.score:.0f}; at least one configured filter blocks entry.")
    log_snapshot({"ticker":best.ticker,"decision":decision,"side":best.side if decision=="SIGNAL" else "PASS","entry_price":best.price,"model_prob":best.prob,"market_prob":best.price,"edge":best.edge,"seconds_left":best.seconds_left,"spread":best.spread,"strike":best.strike,"spot":spot,"ann_vol":sigma,"regime":feat["regime"],"ret1":feat["ret1"],"ret3":feat["ret3"],"ret5":feat["ret5"],"ret15":feat["ret15"],"rsi":feat["rsi"],"vol_ratio":feat["vol_ratio"],"expected_move":best.expected_move,"distance_sigma":best.distance_sigma,"signal_score":best.score,"outcome":None,"reason":why})
    logged=False
    if auto and decision=="SIGNAL":
        contracts=max(1,int(risk/max(best.price,.01))); logged=insert_trade(best.ticker,best.side,best.price,best.prob,best.edge,contracts,best.seconds_left,feat["regime"],best.score)
    if time.time()-st.session_state.last_resolve>=5:resolve_trades();resolve_journal();st.session_state.last_resolve=time.time()

    st.markdown(f'<div class="hero"><div class="brand">BLACKGOLD • QUANT CORE V5</div><h1>₿ BTC 15M / KALSHI INTELLIGENCE TERMINAL</h1><p>Calibrated probability • full-contract selection • expected move • regime • research journal</p></div><div class="goldline"></div>',unsafe_allow_html=True)
    a,b,c,d,e,f=st.columns(6);a.metric("BTC",f"${spot:,.2f}");b.metric("REFERENCE",source);c.metric("TARGET",f"${best.strike:,.2f}");d.metric("TIME",f"{int(best.seconds_left//60)}:{int(best.seconds_left%60):02d}");e.metric("REGIME",feat["regime"]);f.metric("BRTI / SOURCE",source)
    st.markdown('<div class="section">Primary signal</div>',unsafe_allow_html=True)
    l,r=st.columns([1.7,1])
    with l: st.markdown(f'<div class="signal"><div class="small">DECISION</div><h2>{display} {"• "+str(round(best.price*100,1))+"¢" if decision=="SIGNAL" else ""}</h2><p class="small">{why}</p><span class="tag">FAIR {best.prob*100:.1f}%</span><span class="tag">MARKET {best.price*100:.1f}¢</span><span class="tag">EDGE {best.edge*100:+.1f}¢</span><span class="tag">SCORE {best.score:.0f}</span></div>',unsafe_allow_html=True)
    with r:
        x,y,z=st.columns(3);x.metric("EDGE",f"{best.edge*100:+.1f}%");y.metric("SCORE",f"{best.score:.0f}/100");z.metric("EXP MOVE",f"${best.expected_move:,.0f}")
        st.markdown(f'<div class="small">Strike distance: <b>{best.distance_sigma:+.2f}σ</b> • RSI {feat["rsi"]:.0f} • Vol ratio {feat["vol_ratio"]:.2f}</div>',unsafe_allow_html=True)
    st.markdown('<div class="section">Probability stack</div>',unsafe_allow_html=True)
    q1,q2,q3,q4,q5=st.columns(5);q1.metric("BASE",f'{best.raw_prob*100:.1f}%');q2.metric("CALIBRATED",f'{best.prob*100:.1f}%');q3.metric("HIST N",str(best.hist_n));q4.metric("MOMENTUM",f'{feat["ret5"]*100:+.3f}%');q5.metric("RSI",f'{feat["rsi"]:.0f}')
    hist_val=best["hist"]; hist_n=best["hist_n"]
    if hist_val is not None:st.caption(f"Comparable historical setups: {hist_n}. Empirical probability {hist_val*100:.1f}% is blended conservatively into the final probability.")
    else:st.caption("Calibration layer is waiting for enough comparable resolved observations; no fabricated historical edge is added.")
    st.markdown('<div class="section">All opportunities</div>',unsafe_allow_html=True)
    view=cdf.sort_values(["qualifies","score","edge"],ascending=[False,False,False]).copy();view["strike"]=view["strike"].map(lambda x:f"${x:,.2f}");view["price"]=view["price"].map(lambda x:f"{x*100:.1f}¢");view["prob"]=view["prob"].map(lambda x:f"{x*100:.1f}%");view["edge"]=view["edge"].map(lambda x:f"{x*100:+.1f}%");view["score"]=view["score"].map(lambda x:f"{x:.0f}");view["time"]=view["seconds_left"].map(lambda x:f"{int(x//60)}:{int(x%60):02d}");view["dist"]=view["distance_sigma"].map(lambda x:f"{x:+.2f}σ");st.dataframe(view[["ticker","side","strike","time","price","prob","edge","score","dist","spread","volume","oi"]],use_container_width=True,hide_index=True)
    st.markdown('<div class="section">BTC structure</div>',unsafe_allow_html=True)
    if len(candles):
        p=candles.tail(180);fig=go.Figure(go.Candlestick(x=p.ts,open=p.open,high=p.high,low=p.low,close=p.close,increasing_line_color="#d4af37",decreasing_line_color="#777",increasing_fillcolor="#d4af37",decreasing_fillcolor="#222"));fig.update_layout(height=370,margin=dict(l=0,r=0,t=10,b=0),paper_bgcolor="#050505",plot_bgcolor="#050505",font=dict(color="#ccc"),xaxis=dict(showgrid=False,rangeslider=dict(visible=False)),yaxis=dict(showgrid=True,gridcolor="#181818",side="right"),showlegend=False);st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})
    tr=recent_trades(2000); render_research(tr)
    st.markdown('<div class="section">Signal journal / calibration feed</div>',unsafe_allow_html=True);sj=journal(1500)
    if sj.empty:st.info("Run schema_v5.sql once in Supabase. Every evaluated setup is recorded, including PASS.")
    else:
        st.caption(f"Journal observations: {len(sj)} • resolved labels allow calibration without using paper-trade selection alone.");cols=[c for c in ["observed_at","decision","side","ticker","entry_price","model_prob","edge","seconds_left","regime","signal_score","outcome","reason"] if c in sj.columns];st.dataframe(sj[cols],use_container_width=True,hide_index=True)
    st.markdown('<div class="small"><b>Research / paper mode:</b> No live Kalshi orders. BRTI requires licensed CF Benchmarks credentials. Coinbase is labeled fallback. Paper P&L is not execution-adjusted for fees, queue position or slippage.</div>',unsafe_allow_html=True)

dashboard()
