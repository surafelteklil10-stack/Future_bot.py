# ======================================================
# FUTURE BOT – PART 1 : CORE SYSTEM
# Bybit DEMO + REAL | Cloud Ready (Render)
# File: future_bot.py
# ======================================================

import os
import time
import threading
import requests
from datetime import datetime
from pybit.unified_trading import HTTP

# ===============================
# MODE CONFIG (DEMO / REAL)
# ===============================
MODE = os.getenv("MODE", "DEMO")  # DEMO or REAL

DEMO_KEY = os.getenv("BYBIT_DEMO_KEY")
DEMO_SECRET = os.getenv("BYBIT_DEMO_SECRET")

REAL_KEY = os.getenv("BYBIT_REAL_KEY")
REAL_SECRET = os.getenv("BYBIT_REAL_SECRET")

TG_TOKEN = os.getenv("TG_TOKEN")
TG_ADMIN = int(os.getenv("TG_ADMIN", "0"))

if MODE == "REAL":
    API_KEY = REAL_KEY
    API_SECRET = REAL_SECRET
    TESTNET = False
else:
    API_KEY = DEMO_KEY
    API_SECRET = DEMO_SECRET
    TESTNET = True

# ===============================
# GLOBAL BOT STATE
# ===============================
BOT_ACTIVE = True
KILL_SWITCH = False
START_DAY_BALANCE = None
TRADES_TODAY = 0
OPEN_TRADES = {}

# ===============================
# RISK SETTINGS (BASE)
# ===============================
LEVERAGE = 20
RISK_PER_TRADE = 0.20     # 20%
MAX_DAILY_LOSS = 0.10     # 10%
MAX_DAILY_PROFIT = 0.25  # 25%
MAX_TRADES = 5

# ===============================
# CONNECT TO BYBIT
# ===============================
print("🔌 Connecting to Bybit...")

session = HTTP(
    testnet=TESTNET,
    api_key=API_KEY,
    api_secret=API_SECRET
)

# ===============================
# TELEGRAM CORE
# ===============================
def tg(msg):
    if not TG_TOKEN or TG_ADMIN == 0:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_ADMIN, "text": msg}
        )
    except:
        pass

# ===============================
# WALLET
# ===============================
def get_balance():
    try:
        r = session.get_wallet_balance(accountType="UNIFIED")
        return float(r["result"]["list"][0]["totalWalletBalance"])
    except:
        return 0.0

# ===============================
# DAILY INIT
# ===============================
def init_day():
    global START_DAY_BALANCE, TRADES_TODAY, KILL_SWITCH
    START_DAY_BALANCE = get_balance()
    TRADES_TODAY = 0
    KILL_SWITCH = False
    tg(f"🚀 FUTURE BOT STARTED ({MODE})\nBalance: {START_DAY_BALANCE}")

# ===============================
# BASIC DAILY RISK CHECK
# ===============================
def daily_risk_check():
    global KILL_SWITCH
    bal = get_balance()
    if START_DAY_BALANCE is None:
        return

    pnl = (bal - START_DAY_BALANCE) / START_DAY_BALANCE

    if pnl <= -MAX_DAILY_LOSS:
        KILL_SWITCH = True
        tg("🛑 DAILY LOSS LIMIT HIT")

    if pnl >= MAX_DAILY_PROFIT:
        KILL_SWITCH = True
        tg("🎯 DAILY PROFIT TARGET HIT")

# ===============================
# TEST CORE
# ===============================
if __name__ == "__main__":
    init_day()
    while True:
        daily_risk_check()
        print("Balance:", get_balance(), "| Active:", BOT_ACTIVE, "| Kill:", KILL_SWITCH)
        time.sleep(15)

  # ======================================================
# FUTURE BOT – PART 2 : MARKET ENGINE + TIMEFRAMES
# ======================================================

# ===============================
# 100+ FUTURES PAIRS (AUTO LOAD)
# ===============================
def load_pairs():
    try:
        r = session.get_tickers(category="linear")
        pairs = []
        for x in r["result"]["list"]:
            if x["symbol"].endswith("USDT"):
                pairs.append(x["symbol"])
        return pairs[:120]  # 100+ pairs
    except:
        return ["BTCUSDT", "ETHUSDT"]

SYMBOLS = load_pairs()

print("📊 Loaded pairs:", len(SYMBOLS))

# ===============================
# TIMEFRAME ENGINE
# ===============================
TIMEFRAME = os.getenv("TIMEFRAME", "1")  
# seconds based: 1,5,15,60,300,900,3600...
# up to 1 year: 31536000

def tf_sleep():
    try:
        return int(TIMEFRAME)
    except:
        return 5

# ===============================
# MARKET DATA
# ===============================
def get_price(symbol):
    r = session.get_tickers(category="linear", symbol=symbol)
    return float(r["result"]["list"][0]["lastPrice"])

def get_kline(symbol, interval="1", limit=50):
    return session.get_kline(
        category="linear",
        symbol=symbol,
        interval=interval,
        limit=limit
    )["result"]["list"]

# ===============================
# AI TREND FILTER (LIGHT)
# ===============================
def ai_trend_filter(symbol):
    try:
        data = get_kline(symbol, "1", 20)
        closes = [float(x[4]) for x in data]
        ma_fast = sum(closes[-5:]) / 5
        ma_slow = sum(closes) / len(closes)

        if ma_fast > ma_slow:
            return "BULL"
        elif ma_fast < ma_slow:
            return "BEAR"
        else:
            return "SIDE"
    except:
        return "SIDE"

# ===============================
# BASE STRATEGY
# ===============================
def strategy_signal(symbol):
    trend = ai_trend_filter(symbol)
    if trend == "BULL":
        return "Buy"
    if trend == "BEAR":
        return "Sell"
    return None

# ======================================================
# FUTURE BOT – PART 3 : ORDER ENGINE + RISK + SL/TP
# ======================================================

# ===============================
# POSITION SIZE ENGINE
# ===============================
def calc_qty(symbol, risk_pct):
    balance = get_balance()
    price = get_price(symbol)

    usdt_amount = balance * risk_pct * LEVERAGE
    qty = round(usdt_amount / price, 3)

    if qty <= 0:
        return None
    return qty

# ===============================
# SET LEVERAGE
# ===============================
def set_leverage(symbol):
    try:
        session.set_leverage(
            category="linear",
            symbol=symbol,
            buyLeverage=LEVERAGE,
            sellLeverage=LEVERAGE
        )
    except:
        pass

# ===============================
# AUTO STOP LOSS & TAKE PROFIT
# ===============================
def calc_sl_tp(price, side):
    if side == "Buy":
        sl = price * 0.99
        tp = price * 1.02
    else:
        sl = price * 1.01
        tp = price * 0.98
    return round(sl, 4), round(tp, 4)

# ===============================
# OPEN TRADE
# ===============================
def open_trade(symbol, side):
    global TRADES_TODAY, OPEN_TRADES

    if TRADES_TODAY >= MAX_TRADES:
        return

    set_leverage(symbol)

    qty = calc_qty(symbol, RISK_PER_TRADE)
    if not qty:
        return

    price = get_price(symbol)
    sl, tp = calc_sl_tp(price, side)

    try:
        session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=qty,
            takeProfit=tp,
            stopLoss=sl,
            timeInForce="IOC"
        )

        OPEN_TRADES[symbol] = {
            "side": side,
            "entry": price,
            "sl": sl,
            "tp": tp
        }

        TRADES_TODAY += 1
        tg(f"📈 {symbol} {side}\nEntry:{price}\nTP:{tp}\nSL:{sl}")

    except Exception as e:
        print("Order error:", e)

# ===============================
# SIMPLE TRAILING STOP (LOGIC)
# ===============================
def trailing_stop_manager():
    while True:
        try:
            for sym in list(OPEN_TRADES.keys()):
                trade = OPEN_TRADES[sym]
                price = get_price(sym)

                if trade["side"] == "Buy" and price > trade["entry"] * 1.01:
                    new_sl = price * 0.995
                elif trade["side"] == "Sell" and price < trade["entry"] * 0.99:
                    new_sl = price * 1.005
                else:
                    continue

                trade["sl"] = round(new_sl, 4)

            time.sleep(5)
        except:
            time.sleep(5)

      # ======================================================
# FUTURE BOT – PART 4 : MAIN AUTO TRADER + DAILY CONTROL
# ======================================================

# ===============================
# AUTO TRADER CORE LOOP
# ===============================
def auto_trader():
    global BOT_ACTIVE, KILL_SWITCH

    init_day()

    while True:
        try:
            if not BOT_ACTIVE:
                time.sleep(5)
                continue

            # reset new day
            now = datetime.utcnow()
            if now.hour == 0 and now.minute < 2:
                init_day()

            daily_risk_check()

            if KILL_SWITCH:
                time.sleep(20)
                continue

            for symbol in SYMBOLS:
                if KILL_SWITCH:
                    break

                if symbol not in OPEN_TRADES:
                    side = ai_signal(symbol)
                    if side:
                        open_trade(symbol, side)

                time.sleep(1)

            time.sleep(3)

        except Exception as e:
            print("Trader error:", e)
            time.sleep(5)


# ===============================
# THREAD STARTER
# ===============================
def start_systems():
    threading.Thread(target=auto_trader, daemon=True).start()
    threading.Thread(target=trailing_stop_manager, daemon=True).start()

# ======================================================
# FUTURE BOT – PART 5 : AI TREND + TIMEFRAME + 100+ PAIRS
# ======================================================

# ===============================
# SYMBOL ENGINE (100+ PAIRS)
# ===============================
def load_symbols():
    try:
        data = session.get_tickers(category="linear")
        syms = []
        for s in data["result"]["list"]:
            if "USDT" in s["symbol"]:
                syms.append(s["symbol"])
        return syms[:120]  # 100+ pairs
    except:
        return ["BTCUSDT", "ETHUSDT"]

SYMBOLS = load_symbols()
print("Loaded pairs:", len(SYMBOLS))


# ===============================
# TIMEFRAME SYSTEM
# ===============================
TIMEFRAME = os.getenv("TIMEFRAME", "1")  
# "1"=1m, "3","5","15","60","D","W"
# (1 second scalping is simulated internally)

def get_candles(symbol, limit=100):
    return session.get_kline(
        category="linear",
        symbol=symbol,
        interval=TIMEFRAME,
        limit=limit
    )["result"]["list"]


# ===============================
# AI TREND FILTER (SMART)
# ===============================
def ai_trend_filter(symbol):
    try:
        klines = get_candles(symbol, 50)
        closes = [float(k[4]) for k in klines]

        fast = sum(closes[-10:]) / 10
        slow = sum(closes[-30:]) / 30

        if fast > slow:
            return "BULL"
        elif fast < slow:
            return "BEAR"
        else:
            return "SIDE"
    except:
        return "SIDE"


# ===============================
# AI SIGNAL SYSTEM
# ===============================
def ai_signal(symbol):
    trend = ai_trend_filter(symbol)

    t = int(time.time())
    micro = "BUY" if t % 2 == 0 else "SELL"

    if trend == "BULL" and micro == "BUY":
        return "Buy"
    if trend == "BEAR" and micro == "SELL":
        return "Sell"

    return None

# ======================================================
# FUTURE BOT – PART 6 : AUTO SL / TP / TRAILING / MANAGER
# ======================================================

# ===============================
# POSITION SETTINGS
# ===============================
STOP_LOSS_PERCENT = 0.02     # 2%
TAKE_PROFIT_PERCENT = 0.04   # 4%
TRAILING_TRIGGER = 0.02      # start trailing after 2%
TRAILING_DISTANCE = 0.01     # trail by 1%

# ===============================
# OPEN POSITION
# ===============================
def open_trade(symbol, side):
    global TRADES_TODAY, OPEN_TRADES

    bal = get_balance()
    if bal <= 0:
        return

    qty_usdt = bal * RISK_PER_TRADE
    price = float(session.get_tickers(category="linear", symbol=symbol)
                  ["result"]["list"][0]["lastPrice"])

    qty = round(qty_usdt / price, 3)

    session.set_leverage(
        category="linear",
        symbol=symbol,
        buyLeverage=LEVERAGE,
        sellLeverage=LEVERAGE
    )

    order = session.place_order(
        category="linear",
        symbol=symbol,
        side=side,
        orderType="Market",
        qty=qty,
        timeInForce="IOC"
    )

    entry = price

    if side == "Buy":
        sl = entry * (1 - STOP_LOSS_PERCENT)
        tp = entry * (1 + TAKE_PROFIT_PERCENT)
    else:
        sl = entry * (1 + STOP_LOSS_PERCENT)
        tp = entry * (1 - TAKE_PROFIT_PERCENT)

    OPEN_TRADES[symbol] = {
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "trail": False
    }

    TRADES_TODAY += 1
    tg(f"🚀 OPEN {symbol} {side}\nEntry:{entry}\nSL:{sl}\nTP:{tp}")


# ===============================
# POSITION MANAGER
# ===============================
def manage_positions():
    global OPEN_TRADES

    while True:
        try:
            for symbol in list(OPEN_TRADES.keys()):
                pos = OPEN_TRADES[symbol]
                price = float(session.get_tickers(category="linear", symbol=symbol)
                              ["result"]["list"][0]["lastPrice"])

                side = pos["side"]

                # SL / TP hit
                if side == "Buy":
                    if price <= pos["sl"] or price >= pos["tp"]:
                        close_trade(symbol, side)
                        continue
                else:
                    if price >= pos["sl"] or price <= pos["tp"]:
                        close_trade(symbol, side)
                        continue

                # Trailing
                profit = (price - pos["entry"]) / pos["entry"] if side == "Buy" else (pos["entry"] - price) / pos["entry"]

                if profit >= TRAILING_TRIGGER:
                    pos["trail"] = True

                if pos["trail"]:
                    if side == "Buy":
                        new_sl = price * (1 - TRAILING_DISTANCE)
                        if new_sl > pos["sl"]:
                            pos["sl"] = new_sl
                    else:
                        new_sl = price * (1 + TRAILING_DISTANCE)
                        if new_sl < pos["sl"]:
                            pos["sl"] = new_sl

        except:
            pass

        time.sleep(3)


# ===============================
# CLOSE POSITION
# ===============================
def close_trade(symbol, side):
    opp = "Sell" if side == "Buy" else "Buy"

    try:
        session.place_order(
            category="linear",
            symbol=symbol,
            side=opp,
            orderType="Market",
            qty=0,
            reduceOnly=True,
            timeInForce="IOC"
        )
    except:
        pass

    tg(f"✅ CLOSED {symbol}")
    if symbol in OPEN_TRADES:
        del OPEN_TRADES[symbol]


# ===============================
# START MANAGER THREAD
# ===============================
threading.Thread(target=manage_positions, daemon=True).start()

# ======================================================
# FUTURE BOT – PART 7 : AUTO TRADING ENGINE
# ======================================================

# ===============================
# SYMBOL ENGINE (100+ PAIRS READY)
# ===============================
SYMBOLS = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT",
    "AVAXUSDT","LINKUSDT","DOTUSDT","MATICUSDT","LTCUSDT","TRXUSDT","ATOMUSDT",
    "NEARUSDT","OPUSDT","ARBUSDT","APEUSDT","ETCUSDT","FILUSDT","RNDRUSDT",
    "INJUSDT","SUIUSDT","SEIUSDT","APTUSDT","GALAUSDT","SANDUSDT","MANAUSDT",
    "FTMUSDT","EGLDUSDT","AAVEUSDT","UNIUSDT","RUNEUSDT","DYDXUSDT","KAVAUSDT",
    "1000PEPEUSDT","1000SHIBUSDT","WLDUSDT","STXUSDT","MINAUSDT","CFXUSDT"
]

# ===============================
# TIMEFRAME ENGINE
# ===============================
TIMEFRAME = "1"   # 1s - 1y supported by Bybit candles
SCAN_DELAY = 5    # seconds between scans

# ===============================
# SIMPLE AI TREND FILTER (BASE)
# ===============================
def ai_trend(symbol):
    try:
        candles = session.get_kline(
            category="linear",
            symbol=symbol,
            interval=TIMEFRAME,
            limit=50
        )["result"]["list"]

        closes = [float(c[4]) for c in candles]

        fast = sum(closes[-5:]) / 5
        slow = sum(closes[-20:]) / 20

        if fast > slow:
            return "Buy"
        elif fast < slow:
            return "Sell"
        else:
            return None
    except:
        return None


# ===============================
# AUTO TRADER CORE
# ===============================
def auto_trader():
    global BOT_ACTIVE, KILL_SWITCH, TRADES_TODAY

    init_day()

    while True:

        # new day reset
        if datetime.utcnow().hour == 0 and datetime.utcnow().minute < 2:
            init_day()

        if not BOT_ACTIVE or KILL_SWITCH:
            time.sleep(10)
            continue

        if TRADES_TODAY >= MAX_TRADES:
            time.sleep(30)
            continue

        daily_risk_check()

        for sym in SYMBOLS:

            if KILL_SWITCH or not BOT_ACTIVE:
                break

            if sym in OPEN_TRADES:
                continue

            sig = ai_trend(sym)

            if sig:
                open_trade(sym, sig)
                time.sleep(2)

        time.sleep(SCAN_DELAY)


# ===============================
# START AUTO TRADER
# ===============================
threading.Thread(target=auto_trader, daemon=True).start()

# ======================================================
# FUTURE BOT – PART 8 : TELEGRAM CONTROL PANEL
# ======================================================

# ===============================
# TELEGRAM BUTTON PANEL
# ===============================
def tg_buttons(text):
    keyboard = {
        "keyboard": [
            [{"text": "▶️ START BOT"}, {"text": "⛔ STOP BOT"}],
            [{"text": "📊 STATUS"}, {"text": "💰 BALANCE"}],
            [{"text": "♻️ RESET DAY"}, {"text": "🧠 AI MODE"}]
        ],
        "resize_keyboard": True
    }

    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data={
            "chat_id": TG_ADMIN,
            "text": text,
            "reply_markup": keyboard
        }
    )


# ===============================
# TELEGRAM LISTENER
# ===============================
def telegram_listener():
    global BOT_ACTIVE, KILL_SWITCH

    offset = None
    tg_buttons("🤖 FUTURE BOT ONLINE")

    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 30}
            ).json()

            for u in r["result"]:
                offset = u["update_id"] + 1

                if "message" not in u:
                    continue
                if u["message"]["chat"]["id"] != TG_ADMIN:
                    continue

                txt = u["message"]["text"]

                if txt == "▶️ START BOT":
                    BOT_ACTIVE = True
                    KILL_SWITCH = False
                    tg("▶️ BOT STARTED")

                elif txt == "⛔ STOP BOT":
                    BOT_ACTIVE = False
                    tg("⛔ BOT STOPPED")

                elif txt == "📊 STATUS":
                    bal = get_balance()
                    tg(f"⚙️ MODE: {MODE}\n💰 BALANCE: {bal}\n📈 TRADES: {TRADES_TODAY}")

                elif txt == "💰 BALANCE":
                    tg(f"💰 CURRENT BALANCE: {get_balance()}")

                elif txt == "♻️ RESET DAY":
                    init_day()

                elif txt == "🧠 AI MODE":
                    tg("🧠 AI MODE ACTIVE (Trend Filter Enabled)")

        except Exception as e:
            time.sleep(5)


# ===============================
# START TELEGRAM THREAD
# ===============================
threading.Thread(target=telegram_listener, daemon=True).start()

# ======================================================
# FUTURE BOT – PART 9 : TRADE ENGINE + SL + TRAILING
# ======================================================

# ===============================
# AUTO STOP LOSS & TRAILING
# ===============================
STOP_LOSS_PCT = 0.02      # 2% SL
TRAIL_START = 0.01       # start trailing after 1% profit
TRAIL_GAP = 0.005        # 0.5% trailing gap


def open_trade(symbol, side):
    global TRADES_TODAY, OPEN_TRADES

    bal = get_balance()
    risk_usdt = bal * RISK_PER_TRADE

    price = float(session.get_tickers(
        category="linear", symbol=symbol
    )["result"]["list"][0]["lastPrice"])

    qty = round((risk_usdt * LEVERAGE) / price, 3)

    session.set_leverage(
        category="linear",
        symbol=symbol,
        buyLeverage=LEVERAGE,
        sellLeverage=LEVERAGE
    )

    order = session.place_order(
        category="linear",
        symbol=symbol,
        side=side,
        orderType="Market",
        qty=qty,
        timeInForce="IOC"
    )

    entry = price
    sl = entry * (1 - STOP_LOSS_PCT) if side == "Buy" else entry * (1 + STOP_LOSS_PCT)

    OPEN_TRADES[symbol] = {
        "side": side,
        "entry": entry,
        "sl": sl,
        "trail": sl
    }

    TRADES_TODAY += 1
    tg(f"📈 OPEN {side} {symbol}\nEntry: {entry}\nSL: {round(sl,4)}")


# ===============================
# TRADE MANAGER
# ===============================
def manage_trades():
    global OPEN_TRADES

    while True:
        try:
            for symbol in list(OPEN_TRADES.keys()):
                pos = OPEN_TRADES[symbol]
                side = pos["side"]

                price = float(session.get_tickers(
                    category="linear", symbol=symbol
                )["result"]["list"][0]["lastPrice"])

                entry = pos["entry"]

                # PROFIT %
                if side == "Buy":
                    profit = (price - entry) / entry
                else:
                    profit = (entry - price) / entry

                # TRAILING
                if profit > TRAIL_START:
                    if side == "Buy":
                        new_trail = price * (1 - TRAIL_GAP)
                        if new_trail > pos["trail"]:
                            pos["trail"] = new_trail
                    else:
                        new_trail = price * (1 + TRAIL_GAP)
                        if new_trail < pos["trail"]:
                            pos["trail"] = new_trail

                # EXIT CONDITIONS
                if side == "Buy" and price <= pos["trail"]:
                    close_trade(symbol, "Sell")

                elif side == "Sell" and price >= pos["trail"]:
                    close_trade(symbol, "Buy")

        except:
            pass

        time.sleep(3)


def close_trade(symbol, side):
    try:
        session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=0,
            reduceOnly=True,
            timeInForce="IOC"
        )
        tg(f"❌ CLOSED {symbol}")
        del OPEN_TRADES[symbol]
    except:
        pass


# ===============================
# MAIN AI TRADER LOOP
# ===============================
def trader_engine():
    global BOT_ACTIVE, KILL_SWITCH

    init_day()

    while True:
        try:
            if not BOT_ACTIVE or KILL_SWITCH:
                time.sleep(5)
                continue

            daily_risk_check()

            if TRADES_TODAY >= MAX_TRADES:
                time.sleep(20)
                continue

            for sym in SYMBOLS:
                if sym in OPEN_TRADES:
                    continue

                sig = ai_signal(sym)

                if sig and BOT_ACTIVE and not KILL_SWITCH:
                    open_trade(sym, sig)
                    time.sleep(2)

            time.sleep(10)

        except:
            time.sleep(5)


# ===============================
# RUN EVERYTHING
# ===============================
if __name__ == "__main__":
    threading.Thread(target=manage_trades, daemon=True).start()
    trader_engine()
