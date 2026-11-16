import os, time, threading, json, csv, math
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, jsonify, render_template, request, abort, make_response
import secrets
import requests

app = Flask(__name__)

@app.before_request
def protect_dashboard():
    # Set PAPER_PASSWORD in the hosting provider's environment settings.
    expected = os.environ.get("PAPER_PASSWORD")
    if os.environ.get("RENDER") and not expected:
        abort(503, description="서버 관리자가 PAPER_PASSWORD 환경변수를 설정해야 합니다.")
    if not expected:
        return  # convenient for local-only testing
    auth = request.authorization
    if not auth or not secrets.compare_digest(auth.password or "", expected):
        response = make_response("로그인이 필요합니다.", 401)
        response.headers["WWW-Authenticate"] = 'Basic realm="Paper Trading Dashboard"'
        return response
BASE = "https://api.bybit.com"
DATA = Path(os.environ.get("DATA_DIR", "."))
DATA.mkdir(exist_ok=True)
STATE_PATH = DATA / "state.json"
TRADES_PATH = DATA / "trades.csv"

START_BALANCE = 1000.0
BTC_LEV, ALT_LEV = 3.0, 5.0
RISK = 0.005
DAILY_STOP = 0.02
FEE = 0.00055
INTERVAL = "15"
POLL_SECONDS = 30
ALT_COUNT = 10
MIN_TURNOVER = 10_000_000
MAX_MARGIN_FRACTION = 0.20
ATR_STOP = 1.5
RR = 2.0

lock = threading.RLock()
worker = None
stop_event = threading.Event()

def default_state():
    return {
        "running": False, "balance": START_BALANCE, "starting_balance": START_BALANCE,
        "position": None, "trades": [], "closed_trades": 0, "wins": 0,
        "realized_pnl": 0.0, "day": None, "day_start": START_BALANCE,
        "last_signal": {}, "last_scan": None, "last_error": None,
        "watchlist": [], "prices": {}
    }

def load_state():
    if STATE_PATH.exists():
        try:
            s = json.loads(STATE_PATH.read_text())
            d = default_state()
            d.update(s)
            return d
        except Exception:
            pass
    return default_state()

state = load_state()

def persist():
    with lock:
        STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")

def api(path, params):
    r = requests.get(BASE + path, params=params, timeout=12)
    r.raise_for_status()
    j = r.json()
    if j.get("retCode") != 0:
        raise RuntimeError(j.get("retMsg", "Bybit API error"))
    return j["result"]

def get_universe():
    rows = api("/v5/market/tickers", {"category": "linear"}).get("list", [])
    alts = []
    for x in rows:
        sym = x.get("symbol", "")
        if not sym.endswith("USDT") or sym == "BTCUSDT":
            continue
        if any(t in sym for t in ("2LUSDT","2SUSDT","3LUSDT","3SUSDT","5LUSDT","5SUSDT")):
            continue
        try:
            turnover, price = float(x.get("turnover24h", 0)), float(x.get("lastPrice", 0))
        except Exception:
            continue
        if turnover >= MIN_TURNOVER and price > 0:
            alts.append((sym, turnover, price))
    alts.sort(key=lambda z: z[1], reverse=True)
    return [("BTCUSDT", next((float(x["lastPrice"]) for x in rows if x.get("symbol")=="BTCUSDT"), 0))] + [(a[0], a[2]) for a in alts[:ALT_COUNT]]

def candles(symbol):
    rows = api("/v5/market/kline", {"category":"linear","symbol":symbol,"interval":INTERVAL,"limit":200}).get("list", [])
    rows = list(reversed(rows))[:-1]  # exclude still-forming candle
    return [{"t":int(x[0]),"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in rows]

def ema(vals, n):
    if len(vals) < n: return [None]*len(vals)
    out=[None]*len(vals); v=sum(vals[:n])/n; out[n-1]=v; a=2/(n+1)
    for i in range(n,len(vals)):
        v=a*vals[i]+(1-a)*v; out[i]=v
    return out

def rsi(vals, n=14):
    if len(vals)<=n: return [None]*len(vals)
    changes=[vals[i]-vals[i-1] for i in range(1,len(vals))]
    gains=[max(x,0) for x in changes]; losses=[max(-x,0) for x in changes]
    ag=sum(gains[:n])/n; al=sum(losses[:n])/n
    out=[None]*n
    def calc(g,l): return 100 if l==0 else 100-100/(1+g/l)
    out.append(calc(ag,al))
    for i in range(n,len(changes)):
        ag=(ag*(n-1)+gains[i])/n; al=(al*(n-1)+losses[i])/n
        out.append(calc(ag,al))
    return out

def atr(cs,n=14):
    trs=[]
    for i,c in enumerate(cs):
        prev=cs[i-1]["c"] if i else c["c"]
        trs.append(max(c["h"]-c["l"],abs(c["h"]-prev),abs(c["l"]-prev)))
    if len(trs)<n: return None
    v=sum(trs[:n])/n
    for x in trs[n:]: v=(v*(n-1)+x)/n
    return v

def macd(vals):
    e12,e26=ema(vals,12),ema(vals,26)
    line=[(a-b if a is not None and b is not None else None) for a,b in zip(e12,e26)]
    valid=[x for x in line if x is not None]
    sigv=ema(valid,9)
    sig=[None]*(len(line)-len(valid))+sigv
    return line,sig

def signal_for(cs):
    if len(cs)<80: return None
    c=[x["c"] for x in cs]; v=[x["v"] for x in cs]
    e20,e50=ema(c,20),ema(c,50); rs=rsi(c); ml,ms=macd(c); a=atr(cs)
    i=len(c)-1
    if a is None or any(x[i] is None for x in (e20,e50,rs,ml,ms)): return None
    avg=sum(v[-21:-1])/20
    vol_ok=v[-1]>=avg
    long=c[i]>e20[i]>e50[i] and ml[i]>ms[i] and 50<=rs[i]<=68 and vol_ok
    short=c[i]<e20[i]<e50[i] and ml[i]<ms[i] and 32<=rs[i]<=50 and vol_ok
    return {"side":"LONG" if long else "SHORT" if short else None,
            "price":c[i],"atr":a,"rsi":rs[i],"candle":cs[-1]["t"]}

def add_trade(item):
    state["trades"].insert(0,item)
    state["trades"]=state["trades"][:100]
    if not TRADES_PATH.exists():
        with TRADES_PATH.open("w",newline="",encoding="utf-8-sig") as f:
            csv.writer(f).writerow(["time_utc","event","symbol","side","price","qty","leverage","pnl","balance","reason"])
    with TRADES_PATH.open("a",newline="",encoding="utf-8-sig") as f:
        csv.writer(f).writerow([item.get(k,"") for k in ["time","event","symbol","side","price","qty","leverage","pnl","balance","reason"]])

def open_pos(symbol, sig):
    lev=BTC_LEV if symbol=="BTCUSDT" else ALT_LEV
    price, a, side=sig["price"],sig["atr"],sig["side"]
    dist=max(a*ATR_STOP,price*0.002)
    qty=min((state["balance"]*RISK)/dist,(state["balance"]*MAX_MARGIN_FRACTION*lev)/price)
    if qty<=0: return
    stop=price-dist if side=="LONG" else price+dist
    target=price+dist*RR if side=="LONG" else price-dist*RR
    fee=qty*price*FEE
    state["balance"]-=fee
    state["position"]={"symbol":symbol,"side":side,"entry":price,"qty":qty,"leverage":lev,
                       "stop":stop,"target":target,"entry_fee":fee,"opened":datetime.now(timezone.utc).isoformat()}
    add_trade({"time":datetime.now(timezone.utc).isoformat(),"event":"OPEN","symbol":symbol,"side":side,
               "price":price,"qty":qty,"leverage":lev,"pnl":-fee,"balance":state["balance"],"reason":"strategy signal"})

def close_pos(price, reason):
    p=state["position"]
    if not p:return
    d=1 if p["side"]=="LONG" else -1
    gross=(price-p["entry"])*p["qty"]*d
    fee=price*p["qty"]*FEE
    net=gross-fee-p["entry_fee"]
    state["balance"]+=gross-fee
    state["realized_pnl"]+=net
    state["closed_trades"]+=1
    if net>0: state["wins"]+=1
    add_trade({"time":datetime.now(timezone.utc).isoformat(),"event":"CLOSE","symbol":p["symbol"],"side":p["side"],
               "price":price,"qty":p["qty"],"leverage":p["leverage"],"pnl":net,"balance":state["balance"],"reason":reason})
    state["position"]=None

def scan_loop():
    while not stop_event.is_set():
        try:
            with lock:
                today=datetime.now(timezone.utc).date().isoformat()
                if state.get("day")!=today:
                    state["day"]=today; state["day_start"]=state["balance"]
                if state["position"]:
                    p=state["position"]
                    cs=candles(p["symbol"])
                    if cs:
                        px=cs[-1]["c"]
                        state["prices"][p["symbol"]]=px
                        if p["side"]=="LONG":
                            if px<=p["stop"]: close_pos(p["stop"],"stop loss")
                            elif px>=p["target"]: close_pos(p["target"],"take profit")
                        else:
                            if px>=p["stop"]: close_pos(p["stop"],"stop loss")
                            elif px<=p["target"]: close_pos(p["target"],"take profit")
                daily_floor=state["day_start"]*(1-DAILY_STOP)
                if state["position"] is None and state["balance"]>daily_floor:
                    universe=get_universe()
                    state["watchlist"]=[s for s,_ in universe]
                    for symbol,px in universe:
                        state["prices"][symbol]=px
                    for symbol,_ in universe:
                        cs=candles(symbol)
                        if not cs: continue
                        sig=signal_for(cs)
                        if sig and sig["side"]:
                            key=str(sig["candle"])
                            if state["last_signal"].get(symbol)!=key:
                                state["last_signal"][symbol]=key
                                open_pos(symbol,sig)
                                break
                state["last_scan"]=datetime.now(timezone.utc).isoformat()
                state["last_error"]=None
                persist()
        except Exception as e:
            with lock:
                state["last_error"]=str(e)[:240]
                persist()
        stop_event.wait(POLL_SECONDS)
    with lock:
        state["running"]=False
        persist()

def start_worker():
    global worker
    with lock:
        if state["running"] and worker and worker.is_alive(): return
        stop_event.clear()
        state["running"]=True
        state["last_error"]=None
        worker=threading.Thread(target=scan_loop,daemon=True)
        worker.start()
        persist()

def stop_worker():
    stop_event.set()
    with lock:
        state["running"]=False
        persist()

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/status")
def status():
    with lock:
        p=state["position"]
        unreal=0.0
        if p:
            px=state["prices"].get(p["symbol"],p["entry"])
            d=1 if p["side"]=="LONG" else -1
            unreal=(px-p["entry"])*p["qty"]*d
        equity=state["balance"]+unreal
        winrate=(100*state["wins"]/state["closed_trades"]) if state["closed_trades"] else 0
        return jsonify({**state,"unrealized_pnl":unreal,"equity":equity,"win_rate":winrate,
                        "fee_assumption":FEE,"poll_seconds":POLL_SECONDS})

@app.post("/api/start")
def start():
    start_worker()
    return jsonify({"ok":True,"message":"모의매매를 시작했습니다."})

@app.post("/api/stop")
def stop():
    stop_worker()
    return jsonify({"ok":True,"message":"신규 스캔을 중지했습니다. 보유 포지션은 유지됩니다."})

@app.post("/api/reset")
def reset():
    if state.get("running"):
        return jsonify({"ok":False,"message":"먼저 자동매매를 중지하세요."}),400
    with lock:
        state.clear(); state.update(default_state()); persist()
    return jsonify({"ok":True,"message":"가상자금을 1,000 USDT로 초기화했습니다."})

if __name__ == "__main__":
    # Render and similar hosts provide PORT. Use one worker; in-memory loop is process-local.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), threaded=True)
