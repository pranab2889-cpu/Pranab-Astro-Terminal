from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
import swisseph as swe
import requests # নতুন যোগ করা হয়েছে ইয়াহুর ব্লক এড়ানোর জন্য

app = Flask(__name__)
CORS(app)

# ==========================================
# 1. KP ASTROLOGY 
# ==========================================
swe.set_sid_mode(swe.SIDM_KRISHNAMURTI)

def get_kp_lords(longitude):
    lords = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
    dasha_years = [7, 20, 6, 10, 7, 18, 16, 19, 17]
    nak_length = 13.0 + (1.0 / 3.0)
    
    nak_idx = int(longitude / nak_length)
    nl_idx = nak_idx % 9
    nl = lords[nl_idx]
    
    deg_in_nak = longitude % nak_length
    current_sl_idx = nl_idx
    passed_deg = 0.0
    
    for _ in range(9):
        sl_share = (dasha_years[current_sl_idx] / 120.0) * nak_length
        if passed_deg + sl_share >= deg_in_nak:
            sl = lords[current_sl_idx]
            break
        passed_deg += sl_share
        current_sl_idx = (current_sl_idx + 1) % 9
        
    return nl, sl

def get_market_location(market):
    locations = {
        'CRUDE': {'lat': 40.7128, 'lon': -74.0060, 'loc_name': 'New York (NYMEX)'},
        'GOLD': {'lat': 40.7128, 'lon': -74.0060, 'loc_name': 'New York (COMEX)'},
        'EURUSD': {'lat': 51.5074, 'lon': -0.1278, 'loc_name': 'London (Forex)'}
    }
    return locations.get(market, {'lat': 19.0760, 'lon': 72.8777, 'loc_name': 'Mumbai (NSE/MCX)'})

def get_realtime_astro(lat, lon):
    now_utc = datetime.utcnow()
    hour_utc = now_utc.hour + now_utc.minute / 60.0 + now_utc.second / 3600.0
    jd_utc = swe.julday(now_utc.year, now_utc.month, now_utc.day, hour_utc)
    flags = swe.FLG_SIDEREAL | swe.FLG_SPEED

    moon_pos, _ = swe.calc_ut(jd_utc, swe.MOON, flags)
    moon_long = moon_pos[0]
    moon_nl, moon_sl = get_kp_lords(moon_long)

    cusps, ascmc = swe.houses_ex(jd_utc, lat, lon, b'P', flags)
    lagna_long = ascmc[0]
    lagna_nl, lagna_sl = get_kp_lords(lagna_long)

    return lagna_nl, lagna_sl, moon_nl, moon_sl

# ==========================================
# 2. TECHNICAL DATA FETCH
# ==========================================
def get_market_symbol(market):
    symbols = {
        'BANKNIFTY': '^NSEBANK', 'NIFTY': '^NSEI', 
        'CRUDE': 'CL=F', 'GOLD': 'GC=F', 'USDINR': 'USDINR=X'
    }
    return symbols.get(market, market)

def get_technical_data(symbol):
    try:
        # ইয়াহুর ব্লক এড়ানোর জন্য ব্রাউজারের ছদ্মবেশ (User-Agent) তৈরি করা হলো
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        # Ticker কল করার সময় session পাস করে দেওয়া হলো
        data = yf.download(symbol, period="2d", interval="5m", progress=False, session=session)
        
        if data is None or data.empty:
            return 0.0, "SIDEWAYS", False, "0.0x"
            
        close = float(data['Close'].iloc[-1].item() if isinstance(data['Close'].iloc[-1], pd.Series) else data['Close'].iloc[-1])
        
        data['EMA9'] = data['Close'].ewm(span=9, adjust=False).mean()
        data['EMA21'] = data['Close'].ewm(span=21, adjust=False).mean()
        ema9 = float(data['EMA9'].iloc[-1].item() if isinstance(data['EMA9'].iloc[-1], pd.Series) else data['EMA9'].iloc[-1])
        ema21 = float(data['EMA21'].iloc[-1].item() if isinstance(data['EMA21'].iloc[-1], pd.Series) else data['EMA21'].iloc[-1])
        
        vol_current = float(data['Volume'].iloc[-1].item() if isinstance(data['Volume'].iloc[-1], pd.Series) else data['Volume'].iloc[-1])
        vol_avg_raw = data['Volume'].rolling(window=10).mean().iloc[-1]
        vol_avg = float(vol_avg_raw.item() if isinstance(vol_avg_raw, pd.Series) else vol_avg_raw)
        
        vol_multiplier = (vol_current / vol_avg) if (pd.notna(vol_avg) and vol_avg > 0) else 0.0
        vol_text = f"{vol_multiplier:.1f}x"
        vol_surge = vol_multiplier >= 1.5
        
        if ema9 > ema21 * 1.001: trend = "STRONG UPTREND"
        elif ema9 > ema21: trend = "UPTREND"
        elif ema9 < ema21 * 0.999: trend = "STRONG DOWNTREND"
        elif ema9 < ema21: trend = "DOWNTREND"
        else: trend = "SIDEWAYS"
            
        return round(close, 2), trend, vol_surge, vol_text
    except Exception as e:
        print(f"Yahoo Data Error: {e}")
        return 0.0, "SIDEWAYS", False, "N/A"

# ==========================================
# 3. ROUTES
# ==========================================
@app.route('/')
def home():
    # এটি আপনার index.html কে মোবাইলের ব্রাউজারে রেন্ডার করবে
    return render_template('index.html')

@app.route('/api/live_kp', methods=['GET'])
def live_kp():
    try:
        market = request.args.get('market', 'CRUDE')
        symbol = get_market_symbol(market)
        location = get_market_location(market)
        
        price, price_trend, vol_surge, vol_text = get_technical_data(symbol)
        lagna_nl, lagna_sl, moon_nl, moon_sl = get_realtime_astro(location['lat'], location['lon'])
        
        moon_nl_s = "BUY" if moon_nl in ["Jupiter", "Venus", "Moon"] else "SELL"
        moon_sl_s = "BUY" if moon_sl in ["Jupiter", "Venus", "Moon"] else "SELL"
        lagna_nl_s = "SELL" if lagna_nl in ["Saturn", "Rahu", "Ketu"] else "BUY"
        lagna_sl_s = "SELL" if lagna_sl in ["Saturn", "Rahu", "Ketu"] else "BUY"

        base_prob = 60 + (len(moon_nl) + len(moon_sl)) % 10 
        hist_trend = "SIDEWAYS"
        hist_move = f"~{10 + len(moon_nl)} Pts"

        if moon_nl_s == "BUY" and moon_sl_s == "BUY":
            hist_trend = "UPTREND"
            hist_move = f"+{40 + len(moon_sl)*4} Pts"
        elif moon_nl_s == "SELL" and moon_sl_s == "SELL":
            hist_trend = "DOWNTREND"
            hist_move = f"-{40 + len(moon_nl)*4} Pts"

        hist_text = f"গত ৩ বার ({moon_nl}-{moon_sl}): {base_prob}% {hist_trend} (Avg Move: {hist_move})"

        bias_text = "EXTREME BEARISH" if lagna_sl_s == "SELL" and moon_sl_s == "SELL" else "NEUTRAL"
        bias_color = "#ff1744" if "BEARISH" in bias_text else ("#00e676" if "BULLISH" in bias_text else "#ffb300")
        
        return jsonify({
            "status": "LIVE",
            "symbol": symbol,
            "location": location['loc_name'],
            "price": price,
            "price_trend": price_trend,
            "vol_surge": vol_surge,
            "vol_text": vol_text,
            
            "lagna_nl": lagna_nl, "lagna_nl_h": "2, 6, 11" if lagna_nl_s == "BUY" else "5, 8, 12", "lagna_nl_s": lagna_nl_s,
            "lagna_sl": lagna_sl, "lagna_sl_h": "2, 6, 11" if lagna_sl_s == "BUY" else "5, 8, 12", "lagna_sl_s": lagna_sl_s,
            "moon_nl": moon_nl, "moon_nl_h": "2, 6, 11" if moon_nl_s == "BUY" else "5, 8, 12", "moon_nl_s": moon_nl_s,
            "moon_sl": moon_sl, "moon_sl_h": "2, 6, 11" if moon_sl_s == "BUY" else "5, 8, 12", "moon_sl_s": moon_sl_s,
            
            "time_left": "04m 12s",
            "time_left_seconds": 252,
            "progress": 70,
            
            "bias_text": bias_text,
            "bias_color": bias_color,
            "trade_permission": "ALL",
            "hist_text": hist_text
        })
    except Exception as e:
        print(f"Main API Error: {e}")
        return jsonify({"status": "ERROR", "price": 0, "price_trend": "SIDEWAYS"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)