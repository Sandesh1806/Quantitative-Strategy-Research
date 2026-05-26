import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import warnings
from dotenv import load_dotenv
import os
warnings.filterwarnings('ignore')

# ================ MT5 CONNECTION ================
load_dotenv()

login = int(os.getenv("MT5_LOGIN"))
password = os.getenv("MT5_PASSWORD")
server = os.getenv("MT5_SERVER")

def initialize_mt5():
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return False
    
    if not mt5.login(login, password, server):
        print("Failed to login to MT5")
        return False
    
    print("✅ MT5 initialized successfully")
    return True

# ================ STRATEGY PARAMETERS ================
SYMBOL = "BTCUSDT"
TIMEFRAME_M5 = mt5.TIMEFRAME_M5
TIMEFRAME_M1 = mt5.TIMEFRAME_M1
REFERENCE_TIME = "19:40"
STRATEGY_NAME = "Baseline_QMO_Strategy"

# Risk Management
RISK_REWARD_RATIO = 1.0  # 1:1
LOT_SIZE = 0.1  # Fixed lot size (change manually)
MAX_TRADES_AT_A_TIME = 1  # Only one trade at a time
BUFFER_POINTS = 10  # Buffer for trade entry

# Indicators Parameters
BASELINE_PERIOD = 26  # Kijun-sen period
QMO_SHORT_EMA = 20
QMO_LONG_EMA = 55
QMO_REGRESSION_LENGTH = 20

# Trading State - GLOBAL VARIABLES
trading_enabled = False
active_trades = []
pending_buy_signal = None
pending_sell_signal = None
last_candle_checked = None
current_trade_direction = None
trade_mode = "LIVE"
last_trade_outcome = None
last_position_ticket = None
position_just_closed = False
last_swing_calculation_time = None
baseline_touched_after_trade = False
signal_candle_data = None  # Store signal candle data
is_first_trade_after_start = True  # NEW: Track if this is first trade after start
is_trade_after_sl_tp = False  # NEW: Track if trade is after SL/TP hit

# ================ NEW: DYNAMIC DECIMAL PLACES ================
def get_decimal_places():
    """Get the number of decimal places for the current symbol"""
    symbol_info = mt5.symbol_info(SYMBOL)
    if symbol_info:
        # Digits property gives the number of decimal places
        digits = symbol_info.digits
        return digits
    return 5  # Default for most forex pairs

# ================ NEW QMO HELPER FUNCTIONS ================

def create_custom_timeframe(df_1m, minutes=2):
    """Create custom timeframe candles from 1-minute data - NO VOLUME NEEDED for QMO"""
    if df_1m is None or len(df_1m) < minutes:
        return None
    
    # Group every 'minutes' rows
    resampled_data = []
    
    for i in range(0, len(df_1m), minutes):
        if i + minutes <= len(df_1m):
            chunk = df_1m.iloc[i:i+minutes]
            
            # QMO only needs OHLC, not volume
            custom_candle = {
                'time': chunk.index[0],
                'open': chunk.iloc[0]['open'],
                'high': chunk['high'].max(),
                'low': chunk['low'].min(),
                'close': chunk.iloc[-1]['close']
            }
            resampled_data.append(custom_candle)
    
    df_custom = pd.DataFrame(resampled_data)
    df_custom.set_index('time', inplace=True)
    return df_custom

def tradingview_linreg(source_series, length, offset=0):
    """EXACT TradingView ta.linreg() implementation"""
    if len(source_series) < length:
        return pd.Series([np.nan] * len(source_series), index=source_series.index)
    
    result = pd.Series(index=source_series.index, dtype=float)
    
    for i in range(len(source_series)):
        if i < length - 1 + offset:
            result.iloc[i] = np.nan
            continue
        
        start_idx = i - length + 1 - offset
        end_idx = i - offset + 1
        
        if start_idx < 0:
            result.iloc[i] = np.nan
            continue
        
        window = source_series.iloc[start_idx:end_idx].values
        
        if len(window) != length or np.any(np.isnan(window)):
            result.iloc[i] = np.nan
            continue
        
        # TradingView linear regression calculation
        sum_x = 0.0
        sum_y = 0.0
        sum_xy = 0.0
        sum_xx = 0.0
        
        for j in range(length):
            x = float(j)
            y = window[j]
            sum_x += x
            sum_y += y
            sum_xy += x * y
            sum_xx += x * x
        
        denominator = length * sum_xx - sum_x * sum_x
        
        if abs(denominator) < 1e-10:
            result.iloc[i] = window[-1]
            continue
        
        m = (length * sum_xy - sum_x * sum_y) / denominator
        b = (sum_y - m * sum_x) / length
        
        # TradingView formula: b + m * (length - 1 - offset)
        result.iloc[i] = b + m * (length - 1 - offset)
    
    return result

def tradingview_ema(series, period):
    """EXACT TradingView EMA calculation"""
    if len(series) == 0:
        return pd.Series(dtype=float)
    
    alpha = 2.0 / (period + 1)
    ema_values = np.zeros(len(series))
    
    for i in range(len(series)):
        if np.isnan(series.iloc[i]):
            ema_values[i] = np.nan
        elif i == 0 or np.isnan(ema_values[i-1]):
            ema_values[i] = series.iloc[i]
        else:
            ema_values[i] = series.iloc[i] * alpha + ema_values[i-1] * (1 - alpha)
    
    return pd.Series(ema_values, index=series.index)

def align_to_timeframe(source_series, target_timestamps, timeframe='5m'):
    """Align data from different timeframes to current chart timeframe"""
    aligned_series = pd.Series(index=target_timestamps, dtype=float)
    
    for i, ts in enumerate(target_timestamps):
        # Find the closest timestamp <= current timestamp
        valid_timestamps = source_series.index[source_series.index <= ts]
        if len(valid_timestamps) > 0:
            last_valid_ts = valid_timestamps[-1]
            aligned_series.iloc[i] = source_series[last_valid_ts]
    
    # Forward fill any remaining NaNs
    aligned_series = aligned_series.ffill()
    return aligned_series

# ================ INDICATORS FUNCTIONS ================

def get_previous_candle_data():
    """Get ONLY previous completed candle (no current candle)"""
    time.sleep(3)
    
    
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME_M5, 1, 1)
    
    if rates is None or len(rates) < 1:
        return None
    
    # Now rates[0] is the previous completed candle
    candle = rates[0]
    candle_time = datetime.fromtimestamp(candle['time'])
    candle_open = candle['open']
    candle_high = candle['high']
    candle_low = candle['low']
    candle_close = candle['close']
    
    return candle_time, candle_open, candle_high, candle_low, candle_close

def get_current_candle_data():
    """Get current forming candle data"""
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME_M5, 0, 1)  
    if rates is None or len(rates) < 1:
        return None
    
    # Current forming candle is the latest one
    candle = rates[0]
    candle_time = datetime.fromtimestamp(candle['time'])
    candle_open = candle['open']
    candle_high = candle['high']
    candle_low = candle['low']
    candle_close = candle['close']
    
    return candle_time, candle_open, candle_high, candle_low, candle_close

def get_price_data(symbol, timeframe, count=100):
    """Get price data from MT5 - FIXED for MT5 column names"""
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            return None
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        
        # MT5 returns different column names - adjust if needed
        if 'tick_volume' in df.columns and 'volume' not in df.columns:
            # Rename tick_volume to volume for consistency
            df = df.rename(columns={'tick_volume': 'volume'})
        
        # Ensure we have required columns for QMO
        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_cols):
            print(f"⚠️ Missing required columns in data: {df.columns.tolist()}")
            return None
            
        return df
    except Exception as e:
        print(f"⚠️ Error getting price data: {str(e)}")
        return None

def calculate_baseline(df, period=26):
    """Calculate Baseline (Kijun-sen) indicator - EXACTLY like TradingView"""
    if df is None or len(df) < period:
        return None
    
    recent_df = df.tail(period)
    highest_high = recent_df['high'].max()
    lowest_low = recent_df['low'].min()
    baseline = (highest_high + lowest_low) / 2
    
    return baseline

def check_price_touches_baseline(baseline_value):
    """Check if PREVIOUS CANDLE touches baseline - EXACT TOUCH like TradingView"""
    if baseline_value is None:
        return False
    
    # Get previous completed candle data
    candle_data = get_previous_candle_data()
    if candle_data is None:
        return False
    
    _, _, candle_high, candle_low, _ = candle_data
    
    # EXACT TOUCH CHECK: Baseline between candle high and low
    # This matches TradingView visualization exactly
    candle_touches_baseline = (candle_low <= baseline_value <= candle_high)
    
    if candle_touches_baseline:
        decimal_places = get_decimal_places()
        print(f"✅ Previous Candle touches baseline: High=${candle_high:.{decimal_places}f}, Low=${candle_low:.{decimal_places}f}, Baseline=${baseline_value:.{decimal_places}f}")
    
    return candle_touches_baseline

def check_candle_position_relative_to_baseline(baseline_value, candle_data, position='above'):
    """Check if candle close is above or below baseline"""
    if baseline_value is None or candle_data is None:
        return False
    
    candle_close = candle_data['close']
    
    if position == 'above':
        return candle_close > baseline_value
    else:  # 'below'
        return candle_close < baseline_value

# ================ ULTRA SIMPLE QMO VERSION (EXACTLY AS YOU REQUESTED) ================

def calculate_qmo_oscillator_exact():
    """Calculate Quantum Motion Oscillator - ULTRA SIMPLE VERSION 1"""
    try:
        print("🔍 Starting QMO calculation (Version: Ultra Simple)...")
        
        # Get 5-minute data ONLY - Forget about 1m data issues
        df = get_price_data(SYMBOL, TIMEFRAME_M5, 200)
        if df is None or len(df) < 150:
            print("⚠️ Not enough 5-minute data for QMO calculation")
            return None, None, None
        
        # Use the SAME close prices for all timeframes
        # This is how TradingView's request.security() works internally
        close_prices = df['close']
        
        # Step 1: Calculate SMAs with different windows
        # TradingView QMO uses 50-period SMA for ALL timeframes
        trend_1m = close_prices.rolling(window=50).mean()  # 1-minute equivalent
        trend_2m = close_prices.rolling(window=50).mean()  # 2-minute equivalent  
        trend_3m = close_prices.rolling(window=50).mean()  # 3-minute equivalent
        trend_5m = close_prices.rolling(window=50).mean()  # 5-minute (actual)
        
        # Step 2: Weighted average
        trend_strength = (
            trend_1m * 0.4 +  # 40%
            trend_2m * 0.3 +  # 30%
            trend_3m * 0.2 +  # 20%
            trend_5m * 0.1    # 10%
        )
        
        # Step 3: Current price
        current_price = close_prices
        
        # Step 4: Linear regression
        current_minus_trend = current_price - trend_strength
        linreg_result = tradingview_linreg(current_minus_trend, 20, 0)
        predicted_trend = linreg_result + trend_strength
        
        # Step 5: Dynamic range
        highest_50 = predicted_trend.rolling(window=50).max()
        lowest_50 = predicted_trend.rolling(window=50).min()
        trend_strength_range = highest_50 - lowest_50
        
        # Avoid division by zero
        trend_strength_range = trend_strength_range.replace(0, 0.000001)
        
        # Step 6: Scale the trend
        predicted_diff = predicted_trend - predicted_trend.shift(1)
        scaled_trend_strength = predicted_diff / trend_strength_range * 100
        scaled_trend_strength = scaled_trend_strength.fillna(0)
        
        # Step 7: EMA smoothing
        smoothed_trend_strength = tradingview_ema(scaled_trend_strength, 10)
        
        # Step 8: Calculate EMAs
        short_ema = tradingview_ema(smoothed_trend_strength, 20)
        long_ema = tradingview_ema(smoothed_trend_strength, 55)
        
        # Get latest values
        latest_smoothed = smoothed_trend_strength.iloc[-1]
        latest_short = short_ema.iloc[-1] if len(short_ema) > 0 else 0
        latest_long = long_ema.iloc[-1] if len(long_ema) > 0 else 0
        
        # Color determination
        qmo_color = 'green' if latest_smoothed > 0 else 'red'
        
        print(f"\n✅ QMO CALCULATION COMPLETE:")
        print(f"   Smoothed Value (HISTOGRAM): {latest_smoothed:.6f}")
        print(f"   Short EMA (20): {latest_short:.6f}")
        print(f"   Long EMA (55): {latest_long:.6f}")
        print(f"   QMO COLOR: {qmo_color.upper()}")
        
        return qmo_color, latest_short, latest_long
        
    except Exception as e:
        print(f"⚠️ Error in QMO calculation: {str(e)}")
        return None, None, None

def get_correct_swing_points():
    """Get ONE swing high and ONE swing low from last 15 completed candles - FIXED to calculate EVERY TIME"""
    # Get enough data to ensure we have at least 15 complete candles
    df = get_price_data(SYMBOL, TIMEFRAME_M5, 20)  # Get 20 candles to be safe
    if df is None or len(df) < 17:
        print("⚠️ Not enough data for swing point calculation")
        return None, None
    
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None, None
    
    current_price = tick.bid
    current_time = datetime.now()
    
    # Use the last 15 completed candles (excluding current forming candle)
    if len(df) < 17:
        print("⚠️ Not enough candles for swing analysis")
        return None, None
    
    # Get the last 15 completed candles (skip current forming candle at index 0)
    analysis_df = df.iloc[1:16].copy()  # indices 1 to 15 = 15 candles
    
    decimal_places = get_decimal_places()
    
    print(f"\n🔍 SWING POINT ANALYSIS (Time: {current_time.strftime('%H:%M:%S')})")
    print(f"   Analyzing last 15 completed candles (from {analysis_df.index[0].strftime('%H:%M')} to {analysis_df.index[-1].strftime('%H:%M')})")
    print(f"   Current Price: ${current_price:.{decimal_places}f}")
    
    # Find swing high - look for peaks with 2 candles on each side
    swing_high = None
    swing_high_time = None
    swing_low = None
    swing_low_time = None
    
    # Create arrays for highs and lows
    highs = analysis_df['high'].values
    lows = analysis_df['low'].values
    
    # Check each candle (skip first 2 and last 2 to have 2 candles on each side)
    valid_candles = len(highs)
    
    # Find swing high (looking for peak)
    for i in range(2, valid_candles - 2):
        current_high = highs[i]
        
        # Check if current high is higher than 2 candles before and after
        higher_than_left = current_high > highs[i-2] and current_high > highs[i-1]
        higher_than_right = current_high > highs[i+1] and current_high > highs[i+2]
        
        if higher_than_left and higher_than_right:
            if swing_high is None or current_high > swing_high:
                swing_high = current_high
                swing_high_time = analysis_df.index[i]
    
    # Find swing low (looking for valley)
    for i in range(2, valid_candles - 2):
        current_low = lows[i]
        
        # Check if current low is lower than 2 candles before and after
        lower_than_left = current_low < lows[i-2] and current_low < lows[i-1]
        lower_than_right = current_low < lows[i+1] and current_low < lows[i+2]
        
        if lower_than_left and lower_than_right:
            if swing_low is None or current_low < swing_low:
                swing_low = current_low
                swing_low_time = analysis_df.index[i]
    
    # If no swing high found with strict conditions, use highest high in the range
    if swing_high is None:
        swing_high = highs.max()
        swing_high_idx = np.argmax(highs)
        swing_high_time = analysis_df.index[swing_high_idx]
        print(f"   ⚠️ No strict swing high found, using highest: ${swing_high:.{decimal_places}f}")
    else:
        print(f"   📈 Swing High: ${swing_high:.{decimal_places}f} at {swing_high_time.strftime('%H:%M')}")
    
    # If no swing low found with strict conditions, use lowest low in the range
    if swing_low is None:
        swing_low = lows.min()
        swing_low_idx = np.argmin(lows)
        swing_low_time = analysis_df.index[swing_low_idx]
        print(f"   ⚠️ No strict swing low found, using lowest: ${swing_low:.{decimal_places}f}")
    else:
        print(f"   📉 Swing Low: ${swing_low:.{decimal_places}f} at {swing_low_time.strftime('%H:%M')}")
    
    print(f"   ✅ Final Levels:")
    print(f"      - Swing High: ${swing_high:.{decimal_places}f} {'(ABOVE current)' if swing_high > current_price else '(BELOW current)'}")
    print(f"      - Swing Low: ${swing_low:.{decimal_places}f} {'(BELOW current)' if swing_low < current_price else '(ABOVE current)'}")
    
    return swing_high, swing_low

def analyze_candle():
    """Analyze latest completed candle - FIXED for proper candle color detection"""
    candle_data = get_previous_candle_data()
    if candle_data is None:
        return None, None, None, None
    
    candle_time, candle_open, candle_high, candle_low, candle_close = candle_data
    
    # FIXED: Proper candle color detection (close vs open)
    candle_color = 'green' if candle_close > candle_open else 'red'
    
    df = get_price_data(SYMBOL, TIMEFRAME_M5, 100)
    if df is None:
        return candle_color, None, None, {
            'time': candle_time,
            'open': candle_open,
            'high': candle_high,
            'low': candle_low,
            'close': candle_close,
            'color': candle_color
        }
    
    baseline = calculate_baseline(df, BASELINE_PERIOD)
    if baseline is None:
        return candle_color, None, None, {
            'time': candle_time,
            'open': candle_open,
            'high': candle_high,
            'low': candle_low,
            'close': candle_close,
            'color': candle_color
        }
    
    # Check if candle is near baseline (touches or is within range)
    baseline_range = baseline * 0.005
    candle_touches_baseline = (candle_low <= baseline + baseline_range and 
                              candle_high >= baseline - baseline_range)
    
    # Also check if candle open or close is near baseline
    open_near_baseline = abs(candle_open - baseline) <= baseline_range
    close_near_baseline = abs(candle_close - baseline) <= baseline_range
    high_near_baseline = abs(candle_high - baseline) <= baseline_range
    low_near_baseline = abs(candle_low - baseline) <= baseline_range
    
    is_near_baseline = (candle_touches_baseline or open_near_baseline or 
                       close_near_baseline or high_near_baseline or low_near_baseline)
    
    return candle_color, baseline, is_near_baseline, {
        'time': candle_time,
        'open': candle_open,
        'high': candle_high,
        'low': candle_low,
        'close': candle_close,
        'color': candle_color
    }

# ================ TRADING FUNCTIONS ================

def close_all_positions():
    """Close all open positions"""
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions:
        print(f"🔄 Closing {len(positions)} positions...")
        for position in positions:
            close_position(position)
        return True
    return False

def close_position(position):
    """Close a single position"""
    tick = mt5.symbol_info_tick(SYMBOL)
    
    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": position.volume,
        "type": order_type,
        "position": position.ticket,
        "price": price,
        "deviation": 20,
        "magic": 100,
        "comment": "Close by strategy",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    return result

def place_trade(order_type, sl_price, entry_price):
    """Place a market order with SL and TP - WITH BUFFER"""
    tick = mt5.symbol_info_tick(SYMBOL)
    
    if order_type == 'buy':
        trade_type = mt5.ORDER_TYPE_BUY
        price = tick.ask + BUFFER_POINTS  # ADD BUFFER FOR BUY
    else:
        trade_type = mt5.ORDER_TYPE_SELL
        price = tick.bid - BUFFER_POINTS  # SUBTRACT BUFFER FOR SELL
    
    if order_type == 'buy':
        risk = price - sl_price
        tp_price = price + risk
    else:
        risk = sl_price - price
        tp_price = price - risk
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": LOT_SIZE,
        "type": trade_type,
        "price": price,
        "sl": sl_price,
        "tp": tp_price,
        "deviation": 20,
        "magic": 100,
        "comment": STRATEGY_NAME,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    return result

def check_pending_buy_breakout(current_price, signal_candle_high):
    """Check if NEXT candle breaks the high of signal candle"""
    # Get current candle data
    current_candle = get_current_candle_data()
    if current_candle is None:
        return False
    
    current_candle_time, current_candle_open, current_candle_high, current_candle_low, current_candle_close = current_candle
    
    # Check if current price > signal candle high
    if current_price > signal_candle_high:
        decimal_places = get_decimal_places()
        print(f"✅ NEXT CANDLE Breakout: Current Price ${current_price:.{decimal_places}f} > Signal High ${signal_candle_high:.{decimal_places}f}")
        return True
    
    return False

def check_pending_sell_breakout(current_price, signal_candle_low):
    """Check if NEXT candle breaks the low of signal candle"""
    # Get current candle data
    current_candle = get_current_candle_data()
    if current_candle is None:
        return False
    
    current_candle_time, current_candle_open, current_candle_high, current_candle_low, current_candle_close = current_candle
    
    # Check if current price < signal candle low
    if current_price < signal_candle_low:
        decimal_places = get_decimal_places()
        print(f"✅ NEXT CANDLE Breakout: Current Price ${current_price:.{decimal_places}f} < Signal Low ${signal_candle_low:.{decimal_places}f}")
        return True
    
    return False


def check_entry_signals():
    """Check for buy/sell entry signals - store pending signals - FIXED TIMING"""
    global pending_buy_signal, pending_sell_signal, last_candle_checked, current_trade_direction
    global baseline_touched_after_trade, last_trade_outcome, signal_candle_data
    global is_first_trade_after_start, is_trade_after_sl_tp  # NEW
    
    current_time = datetime.now()
    current_minute = current_time.minute
    
    # Check at 2-4 seconds AFTER the new candle starts
    # This ensures we analyze the PREVIOUS completed candle
    if current_minute % 5 == 0 and 2 <= current_time.second <= 4:
        current_candle_time = current_time.replace(second=0, microsecond=0)
        
        if last_candle_checked == current_candle_time:
            return None
        
        last_candle_checked = current_candle_time
        
        # Clear old pending signals
        if pending_buy_signal is not None:
            print(f"🔄 Clearing old BUY signal - New candle started")
            pending_buy_signal = None
        
        if pending_sell_signal is not None:
            print(f"🔄 Clearing old SELL signal - New candle started")
            pending_sell_signal = None
        
        # Check baseline touch requirement for first trade or after trade closed
        positions = mt5.positions_get(symbol=SYMBOL)
        
        # Check if we already have a trade and what type it is
        has_buy_position = any(p.type == mt5.POSITION_TYPE_BUY for p in positions) if positions else False
        has_sell_position = any(p.type == mt5.POSITION_TYPE_SELL for p in positions) if positions else False
        
        # Determine if we need special conditions (first trade or after SL/TP)
        need_special_conditions = False
        
        if len(positions) == 0:
            if is_first_trade_after_start:
                # This is the first trade after bot started
                need_special_conditions = True
                print(f"🔍 First trade after strategy start - applying SPECIAL conditions")
            elif last_trade_outcome in ["TP", "SL", "MANUAL_CLOSE"]:
                # Trade was closed via TP, SL, or manually
                need_special_conditions = True
                is_trade_after_sl_tp = True
                print(f"🔍 Trade after {last_trade_outcome} - applying SPECIAL conditions")
        
        # ===== CHECK BASELINE TOUCH WHEN WE NEED SPECIAL CONDITIONS =====
        if need_special_conditions and not baseline_touched_after_trade:
            # Need to check baseline touch (only once for special conditions)
            df = get_price_data(SYMBOL, TIMEFRAME_M5, 100)
            if df is None:
                return None
            
            baseline_value = calculate_baseline(df, BASELINE_PERIOD)
            if baseline_value is None:
                return None
            
            if check_price_touches_baseline(baseline_value):
                baseline_touched_after_trade = True
                print(f"✅ Baseline touched, ready for new signals")
            else:
                print(f"⏳ Waiting for price to touch baseline before checking signals...")
                return None
        # ===== END CHECK =====
        
        # If we need special conditions but baseline hasn't been touched yet, return
        if need_special_conditions and not baseline_touched_after_trade:
            return None
        
        # Analyze latest completed candle (the one that just closed)
        candle_color, baseline_value, is_near_baseline, candle_data = analyze_candle()
        if None in [candle_color, baseline_value]:
            return None
        
        # Get QMO color
        qmo_color, short_ema, long_ema = calculate_qmo_oscillator_exact()
        if qmo_color is None:
            return None
        
        # Get swing points
        swing_high, swing_low = get_correct_swing_points()
        
        if swing_high is None or swing_low is None:
            print("⚠️ Cannot get swing points")
            return None
        
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return None
        
        current_price = tick.bid
        signal_candle_high = candle_data['high']
        signal_candle_low = candle_data['low']
        signal_candle_time = candle_data['time']
        
        decimal_places = get_decimal_places()
        
        print(f"\n📊 SIGNAL CHECK at {current_time.strftime('%H:%M:%S')}")
        print(f"   Previous Candle ({signal_candle_time.strftime('%H:%M')}):")
        print(f"   Color: {candle_color.upper()}, Open: ${candle_data['open']:.{decimal_places}f}, Close: ${candle_data['close']:.{decimal_places}f}")
        print(f"   High: ${signal_candle_high:.{decimal_places}f}, Low: ${signal_candle_low:.{decimal_places}f}")
        print(f"   Baseline: ${baseline_value:.{decimal_places}f}")
        print(f"   QMO Color: {qmo_color}")
        
        # Store signal candle data
        signal_candle_data = candle_data
        
        # ===== CHECK IF WE ALREADY HAVE A TRADE AND IGNORE SAME-DIRECTION SIGNALS =====
        if has_buy_position and candle_color == 'green' and qmo_color == 'green':
            print(f"🚫 IGNORING BUY SIGNAL - Already have a BUY position")
            return None
        
        if has_sell_position and candle_color == 'red' and qmo_color == 'red':
            print(f"🚫 IGNORING SELL SIGNAL - Already have a SELL position")
            return None
        
        # ===== MODIFIED: Check if we need special conditions =====
        if need_special_conditions and baseline_touched_after_trade:
            print(f"\n🔍 Checking with SPECIAL conditions (First trade or after SL/TP):")
            
            # Check for BUY signal with SPECIAL conditions
            if (candle_color == 'green' and 
                qmo_color == 'green' and
                check_candle_position_relative_to_baseline(baseline_value, candle_data, 'above')):
                
                print(f"\n🔍 Checking BUY conditions (SPECIAL):")
                print(f"   Candle Green: ✓")
                print(f"   Candle Close ABOVE Baseline: ✓ (${candle_data['close']:.{decimal_places}f} > ${baseline_value:.{decimal_places}f})")
                print(f"   QMO Green: ✓")
                
                if swing_low is not None:
                    if swing_low < current_price:
                        print(f"\n✅ BUY SIGNAL DETECTED (SPECIAL CONDITIONS)!")
                        print(f"   Waiting for NEXT candle to break above: ${signal_candle_high:.{decimal_places}f}")
                        print(f"   SL (Previous Swing Low): ${swing_low:.{decimal_places}f}")
                        
                        positions = mt5.positions_get(symbol=SYMBOL)
                        has_sell_positions = any(p.type == mt5.POSITION_TYPE_SELL for p in positions)
                        
                        if has_sell_positions:
                            print(f"⚠️ SELL trade running - Will close for BUY entry")
                        
                        pending_buy_signal = {
                            'type': 'buy',
                            'signal_price': current_price,
                            'signal_candle_high': signal_candle_high,
                            'signal_candle_low': signal_candle_low,
                            'sl': swing_low,
                            'baseline': baseline_value,
                            'qmo_color': qmo_color,
                            'signal_time': datetime.now(),
                            'candle_time': signal_candle_time,
                            'is_special_condition': True  # Track that this is a special condition signal
                        }
                        pending_sell_signal = None
                    else:
                        print(f"❌ Invalid BUY signal - Swing Low (${swing_low:.{decimal_places}f}) not below current price (${current_price:.{decimal_places}f})")
                else:
                    print(f"❌ No swing low found for BUY signal")
            
            # Check for SELL signal with SPECIAL conditions
            elif (candle_color == 'red' and 
                  qmo_color == 'red' and
                  check_candle_position_relative_to_baseline(baseline_value, candle_data, 'below')):
                
                print(f"\n🔍 Checking SELL conditions (SPECIAL):")
                print(f"   Candle Red: ✓")
                print(f"   Candle Close BELOW Baseline: ✓ (${candle_data['close']:.{decimal_places}f} < ${baseline_value:.{decimal_places}f})")
                print(f"   QMO Red: ✓")
                
                if swing_high is not None:
                    if swing_high > current_price:
                        print(f"\n✅ SELL SIGNAL DETECTED (SPECIAL CONDITIONS)!")
                        print(f"   Waiting for NEXT candle to break below: ${signal_candle_low:.{decimal_places}f}")
                        print(f"   SL (Previous Swing High): ${swing_high:.{decimal_places}f}")
                        
                        positions = mt5.positions_get(symbol=SYMBOL)
                        has_buy_positions = any(p.type == mt5.POSITION_TYPE_BUY for p in positions)
                        
                        if has_buy_positions:
                            print(f"⚠️ BUY trade running - Will close for SELL entry")
                        
                        pending_sell_signal = {
                            'type': 'sell',
                            'signal_price': current_price,
                            'signal_candle_high': signal_candle_high,
                            'signal_candle_low': signal_candle_low,
                            'sl': swing_high,
                            'baseline': baseline_value,
                            'qmo_color': qmo_color,
                            'signal_time': datetime.now(),
                            'candle_time': signal_candle_time,
                            'is_special_condition': True  # Track that this is a special condition signal
                        }
                        pending_buy_signal = None
                    else:
                        print(f"❌ Invalid SELL signal - Swing High (${swing_high:.{decimal_places}f}) not above current price (${current_price:.{decimal_places}f})")
                else:
                    print(f"❌ No swing high found for SELL signal")
            else:
                # Show why special conditions failed
                if candle_color != 'green' and candle_color != 'red':
                    print(f"❌ No special signal: Invalid candle color")
                elif (candle_color == 'green' and qmo_color != 'green'):
                    print(f"❌ No special BUY signal: Candle is green but QMO is {qmo_color}")
                elif (candle_color == 'red' and qmo_color != 'red'):
                    print(f"❌ No special SELL signal: Candle is red but QMO is {qmo_color}")
                elif (candle_color == 'green' and not check_candle_position_relative_to_baseline(baseline_value, candle_data, 'above')):
                    print(f"❌ No special BUY signal: Candle close (${candle_data['close']:.{decimal_places}f}) not ABOVE baseline (${baseline_value:.{decimal_places}f})")
                elif (candle_color == 'red' and not check_candle_position_relative_to_baseline(baseline_value, candle_data, 'below')):
                    print(f"❌ No special SELL signal: Candle close (${candle_data['close']:.{decimal_places}f}) not BELOW baseline (${baseline_value:.{decimal_places}f})")
        
        else:
            # ===== FIXED: For reversal trades (STRICT above/below - NO "near baseline") =====
            # Check for BUY signal conditions (REVERSAL - STRICT ABOVE baseline)
            if (candle_color == 'green' and 
                check_candle_position_relative_to_baseline(baseline_value, candle_data, 'above') and
                qmo_color == 'green'):
                
                print(f"\n🔍 Checking BUY conditions (REVERSAL):")
                print(f"   Candle Green: ✓")
                print(f"   Candle Close STRICTLY ABOVE Baseline: ✓ (${candle_data['close']:.{decimal_places}f} > ${baseline_value:.{decimal_places}f})")
                print(f"   QMO Green: ✓")
                
                if swing_low is not None:
                    if swing_low < current_price:
                        print(f"\n✅ BUY SIGNAL DETECTED (REVERSAL)!")
                        print(f"   Waiting for NEXT candle to break above: ${signal_candle_high:.{decimal_places}f}")
                        print(f"   SL (Previous Swing Low): ${swing_low:.{decimal_places}f}")
                        
                        positions = mt5.positions_get(symbol=SYMBOL)
                        has_sell_positions = any(p.type == mt5.POSITION_TYPE_SELL for p in positions)
                        
                        if has_sell_positions:
                            print(f"⚠️ SELL trade running - Will close for BUY entry")
                        
                        pending_buy_signal = {
                            'type': 'buy',
                            'signal_price': current_price,
                            'signal_candle_high': signal_candle_high,
                            'signal_candle_low': signal_candle_low,
                            'sl': swing_low,
                            'baseline': baseline_value,
                            'qmo_color': qmo_color,
                            'signal_time': datetime.now(),
                            'candle_time': signal_candle_time,
                            'is_special_condition': False  # This is a reversal trade
                        }
                        pending_sell_signal = None
                    else:
                        print(f"❌ Invalid BUY signal - Swing Low (${swing_low:.{decimal_places}f}) not below current price (${current_price:.{decimal_places}f})")
                else:
                    print(f"❌ No swing low found for BUY signal")
            
            # Check for SELL signal conditions (REVERSAL - STRICT BELOW baseline)
            elif (candle_color == 'red' and 
                  check_candle_position_relative_to_baseline(baseline_value, candle_data, 'below') and
                  qmo_color == 'red'):
                
                print(f"\n🔍 Checking SELL conditions (REVERSAL):")
                print(f"   Candle Red: ✓")
                print(f"   Candle Close STRICTLY BELOW Baseline: ✓ (${candle_data['close']:.{decimal_places}f} < ${baseline_value:.{decimal_places}f})")
                print(f"   QMO Red: ✓")
                
                if swing_high is not None:
                    if swing_high > current_price:
                        print(f"\n✅ SELL SIGNAL DETECTED (REVERSAL)!")
                        print(f"   Waiting for NEXT candle to break below: ${signal_candle_low:.{decimal_places}f}")
                        print(f"   SL (Previous Swing High): ${swing_high:.{decimal_places}f}")
                        
                        positions = mt5.positions_get(symbol=SYMBOL)
                        has_buy_positions = any(p.type == mt5.POSITION_TYPE_BUY for p in positions)
                        
                        if has_buy_positions:
                            print(f"⚠️ BUY trade running - Will close for SELL entry")
                        
                        pending_sell_signal = {
                            'type': 'sell',
                            'signal_price': current_price,
                            'signal_candle_high': signal_candle_high,
                            'signal_candle_low': signal_candle_low,
                            'sl': swing_high,
                            'baseline': baseline_value,
                            'qmo_color': qmo_color,
                            'signal_time': datetime.now(),
                            'candle_time': signal_candle_time,
                            'is_special_condition': False  # This is a reversal trade
                        }
                        pending_buy_signal = None
                    else:
                        print(f"❌ Invalid SELL signal - Swing High (${swing_high:.{decimal_places}f}) not above current price (${current_price:.{decimal_places}f})")
                else:
                    print(f"❌ No swing high found for SELL signal")
            
            # If no signal, show why - FIXED MESSAGES
            else:
                if candle_color != 'green' and candle_color != 'red':
                    print(f"❌ No reversal signal: Invalid candle color")
                elif (candle_color == 'green' and not check_candle_position_relative_to_baseline(baseline_value, candle_data, 'above')):
                    print(f"❌ No reversal BUY signal: Candle close (${candle_data['close']:.{decimal_places}f}) not STRICTLY ABOVE baseline (${baseline_value:.{decimal_places}f})")
                elif (candle_color == 'red' and not check_candle_position_relative_to_baseline(baseline_value, candle_data, 'below')):
                    print(f"❌ No reversal SELL signal: Candle close (${candle_data['close']:.{decimal_places}f}) not STRICTLY BELOW baseline (${baseline_value:.{decimal_places}f})")
                elif (candle_color == 'green' and qmo_color != 'green'):
                    print(f"❌ No reversal BUY signal: Candle is green but QMO is {qmo_color}")
                elif (candle_color == 'red' and qmo_color != 'red'):
                    print(f"❌ No reversal SELL signal: Candle is red but QMO is {qmo_color}")
    
    return None

def process_pending_signals():
    """Process pending buy/sell signals waiting for breakout"""
    global pending_buy_signal, pending_sell_signal, current_trade_direction
    global baseline_touched_after_trade, last_trade_outcome, signal_candle_data
    global is_first_trade_after_start, is_trade_after_sl_tp  # NEW
    
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return
    
    current_price = tick.bid
    current_ask = tick.ask
    
    # Process pending BUY signal (GREEN candle, QMO GREEN, wait for NEXT candle to break high)
    if pending_buy_signal is not None:
        if check_pending_buy_breakout(current_price, pending_buy_signal['signal_candle_high']):
            decimal_places = get_decimal_places()
            print(f"\n🎯 BUY BREAKOUT CONFIRMED - NEXT candle broke above signal high")
            print(f"   Signal was from candle at: {pending_buy_signal['candle_time'].strftime('%H:%M')}")
            
            # Check that we're still in the NEXT candle (not a later one)
            current_time = datetime.now()
            if current_time.minute // 5 != pending_buy_signal['candle_time'].minute // 5 + 1:
                print(f"⚠️ Too late for breakout - This is not the immediate next candle")
                pending_buy_signal = None
                return
            
            positions = mt5.positions_get(symbol=SYMBOL)
            has_sell_positions = any(p.type == mt5.POSITION_TYPE_SELL for p in positions)
            
            if has_sell_positions:
                print(f"🔄 Cutting SELL trade for BUY entry...")
                close_all_positions()
                time.sleep(2)
            
            positions = mt5.positions_get(symbol=SYMBOL)
            if len(positions) < MAX_TRADES_AT_A_TIME:
                
                signal = pending_buy_signal
                
                # Re-check QMO before placing trade
                qmo_color, _, _ = calculate_qmo_oscillator_exact()
                if qmo_color != 'green':
                    print(f"⚠️ QMO changed to {qmo_color} - Canceling BUY trade")
                    pending_buy_signal = None
                    return
                
                result = place_trade(signal['type'], signal['sl'], current_ask)
                
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    current_trade_direction = 'buy'
                    
                    # Reset special condition flags after successful trade
                    if signal.get('is_special_condition', False):
                        is_first_trade_after_start = False
                        is_trade_after_sl_tp = False
                        print(f"\n🎯 BUY TRADE EXECUTED (LIVE - SPECIAL CONDITIONS)")
                    else:
                        print(f"\n🎯 BUY TRADE EXECUTED (LIVE - REVERSAL)")
                    
                    print(f"   Entry (with buffer): ${result.price:.{decimal_places}f}")
                    print(f"   SL: ${signal['sl']:.{decimal_places}f}")
                    
                    tp_price = result.price + (result.price - signal['sl'])
                    print(f"   TP: ${tp_price:.{decimal_places}f}")
                    print(f"   Risk: ${abs(result.price - signal['sl']):.{decimal_places}f}")
                    print(f"   Reward: ${abs(tp_price - result.price):.{decimal_places}f}")
                    print(f"   Buffer used: {BUFFER_POINTS} points")
                else:
                    print(f"❌ Failed to place BUY trade: {result.comment}")
                
                pending_buy_signal = None
                baseline_touched_after_trade = False
            else:
                print(f"⚠️ Cannot place BUY trade - Max trades ({MAX_TRADES_AT_A_TIME}) already reached")
                pending_buy_signal = None  # Clear the signal since we can't place it
    
    # Process pending SELL signal (RED candle, QMO RED, wait for NEXT candle to break low)
    if pending_sell_signal is not None:
        if check_pending_sell_breakout(current_price, pending_sell_signal['signal_candle_low']):
            decimal_places = get_decimal_places()
            print(f"\n🎯 SELL BREAKOUT CONFIRMED - NEXT candle broke below signal low")
            print(f"   Signal was from candle at: {pending_sell_signal['candle_time'].strftime('%H:%M')}")
            
            # Check that we're still in the NEXT candle (not a later one)
            current_time = datetime.now()
            if current_time.minute // 5 != pending_sell_signal['candle_time'].minute // 5 + 1:
                print(f"⚠️ Too late for breakout - This is not the immediate next candle")
                pending_sell_signal = None
                return
            
            positions = mt5.positions_get(symbol=SYMBOL)
            has_buy_positions = any(p.type == mt5.POSITION_TYPE_BUY for p in positions)
            
            if has_buy_positions:
                print(f"🔄 Cutting BUY trade for SELL entry...")
                close_all_positions()
                time.sleep(2)
            
            positions = mt5.positions_get(symbol=SYMBOL)
            if len(positions) < MAX_TRADES_AT_A_TIME:
                
                signal = pending_sell_signal
                
                # Re-check QMO before placing trade
                qmo_color, _, _ = calculate_qmo_oscillator_exact()
                if qmo_color != 'red':
                    print(f"⚠️ QMO changed to {qmo_color} - Canceling SELL trade")
                    pending_sell_signal = None
                    return
                
                result = place_trade(signal['type'], signal['sl'], current_price)
                
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    current_trade_direction = 'sell'
                    
                    # Reset special condition flags after successful trade
                    if signal.get('is_special_condition', False):
                        is_first_trade_after_start = False
                        is_trade_after_sl_tp = False
                        print(f"\n🎯 SELL TRADE EXECUTED (LIVE - SPECIAL CONDITIONS)")
                    else:
                        print(f"\n🎯 SELL TRADE EXECUTED (LIVE - REVERSAL)")
                    
                    print(f"   Entry (with buffer): ${result.price:.{decimal_places}f}")
                    print(f"   SL: ${signal['sl']:.{decimal_places}f}")
                    
                    tp_price = result.price - (signal['sl'] - result.price)
                    print(f"   TP: ${tp_price:.{decimal_places}f}")
                    print(f"   Risk: ${abs(signal['sl'] - result.price):.{decimal_places}f}")
                    print(f"   Reward: ${abs(result.price - tp_price):.{decimal_places}f}")
                    print(f"   Buffer used: {BUFFER_POINTS} points")
                else:
                    print(f"❌ Failed to place SELL trade: {result.comment}")
                
                pending_sell_signal = None
                baseline_touched_after_trade = False
            else:
                print(f"⚠️ Cannot place SELL trade - Max trades ({MAX_TRADES_AT_A_TIME}) already reached")
                pending_sell_signal = None  # Clear the signal since we can't place it
    
    # Clear old pending signals (if breakout doesn't happen within 1 candle)
    current_time = datetime.now()
    
    if pending_buy_signal is not None:
        # Check if we're past the NEXT candle
        expected_breakout_candle_minute = (pending_buy_signal['candle_time'].minute // 5 + 1) * 5
        current_candle_minute = (current_time.minute // 5) * 5
        
        if current_candle_minute > expected_breakout_candle_minute:
            print(f"🔄 Clearing BUY signal - No breakout in next candle")
            pending_buy_signal = None
    
    if pending_sell_signal is not None:
        # Check if we're past the NEXT candle
        expected_breakout_candle_minute = (pending_sell_signal['candle_time'].minute // 5 + 1) * 5
        current_candle_minute = (current_time.minute // 5) * 5
        
        if current_candle_minute > expected_breakout_candle_minute:
            print(f"🔄 Clearing SELL signal - No breakout in next candle")
            pending_sell_signal = None

def update_active_trades():
    """Update list of active trades and check trade outcomes"""
    global active_trades, current_trade_direction, last_position_ticket, position_just_closed
    global pending_buy_signal, pending_sell_signal, last_trade_outcome, baseline_touched_after_trade
    global is_trade_after_sl_tp  # NEW
    
    positions = mt5.positions_get(symbol=SYMBOL)
    current_position_tickets = [pos.ticket for pos in positions] if positions else []
    active_trades = current_position_tickets
    
    if positions:
        if positions[0].type == mt5.POSITION_TYPE_BUY:
            current_trade_direction = 'buy'
        else:
            current_trade_direction = 'sell'
        
        if len(positions) > 0:
            last_position_ticket = positions[0].ticket
            position_just_closed = False
    else:
        current_trade_direction = None
        
        if last_position_ticket is not None and not position_just_closed:
            position_just_closed = True
            print(f"🔍 Position {last_position_ticket} was closed")
            
            # Try to get deal history with a wider time window
            end_time = datetime.now()
            start_time = end_time - timedelta(minutes=10)  # Increased from 5 to 10 minutes
            
            try:
                # First try to get deals for today
                deals = mt5.history_deals_get(start_time, end_time)
                
                if not deals or len(deals) == 0:
                    # If no deals found, try to get all deals from today
                    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    deals = mt5.history_deals_get(today_start, end_time)
                
                if deals:
                    position_deals = []
                    for deal in deals:
                        # Try different ways to match the deal with position
                        if (hasattr(deal, 'position_id') and deal.position_id == last_position_ticket) or \
                           (hasattr(deal, 'ticket') and deal.ticket == last_position_ticket) or \
                           (hasattr(deal, 'order') and deal.order == last_position_ticket):
                            position_deals.append(deal)
                    
                    if position_deals:
                        # Sort deals by time (most recent first)
                        position_deals.sort(key=lambda x: x.time if hasattr(x, 'time') else 0, reverse=True)
                        last_deal = position_deals[0]
                        
                        if hasattr(last_deal, 'profit'):
                            decimal_places = get_decimal_places()
                            profit = last_deal.profit
                            
                            # Check if this is a closing deal (type 0 for buy, 1 for sell)
                            if hasattr(last_deal, 'type'):
                                deal_type = last_deal.type
                                # Type 0 = Buy, Type 1 = Sell, Type 2 = Balance, Type 3 = Credit, etc.
                                # We're only interested in buy/sell deals (0 or 1)
                                if deal_type in [0, 1]:
                                    if profit > 0:
                                        last_trade_outcome = "TP"
                                        print(f"💎 TP HIT on position {last_position_ticket} - Profit: ${profit:.{decimal_places}f}")
                                    elif profit < 0:
                                        last_trade_outcome = "SL"
                                        print(f"🛑 SL HIT on position {last_position_ticket} - Loss: ${abs(profit):.{decimal_places}f}")
                                    else:
                                        last_trade_outcome = "BREAK_EVEN"
                                        print(f"⚖️ Break even on position {last_position_ticket}")
                                else:
                                    # If it's not a buy/sell deal, check the entry field
                                    if hasattr(last_deal, 'entry'):
                                        entry_type = last_deal.entry
                                        # Entry 0 = In, Entry 1 = Out, Entry 2 = In/Out
                                        if entry_type in [1, 2]:  # Out or In/Out means closing
                                            if profit > 0:
                                                last_trade_outcome = "TP"
                                                print(f"💎 TP HIT on position {last_position_ticket} - Profit: ${profit:.{decimal_places}f}")
                                            elif profit < 0:
                                                last_trade_outcome = "SL"
                                                print(f"🛑 SL HIT on position {last_position_ticket} - Loss: ${abs(profit):.{decimal_places}f}")
                                            else:
                                                last_trade_outcome = "BREAK_EVEN"
                                                print(f"⚖️ Break even on position {last_position_ticket}")
                                        else:
                                            print(f"⚠️ Deal found but not a closing deal for position {last_position_ticket}")
                                    else:
                                        print(f"⚠️ Deal found but cannot determine type for position {last_position_ticket}")
                            else:
                                # If no type attribute, just check profit
                                if profit > 0:
                                    last_trade_outcome = "TP"
                                    print(f"💎 TP HIT on position {last_position_ticket} - Profit: ${profit:.{decimal_places}f}")
                                elif profit < 0:
                                    last_trade_outcome = "SL"
                                    print(f"🛑 SL HIT on position {last_position_ticket} - Loss: ${abs(profit):.{decimal_places}f}")
                                else:
                                    last_trade_outcome = "BREAK_EVEN"
                                    print(f"⚖️ Break even on position {last_position_ticket}")
                        else:
                            print(f"⚠️ Deal found for position {last_position_ticket} but no profit attribute")
                    else:
                        print(f"⚠️ No matching deals found for position {last_position_ticket}")
                        print(f"   Total deals found: {len(deals)}")
                        # Try alternative method: check if position was manually closed
                        print(f"   Assuming position was manually closed or stopped out")
                        last_trade_outcome = "MANUAL_CLOSE"
                else:
                    print(f"⚠️ No deal history found for position {last_position_ticket}")
                    print(f"   Time range: {start_time} to {end_time}")
                    # Assume it was manually closed
                    last_trade_outcome = "MANUAL_CLOSE"
                    
            except Exception as e:
                print(f"⚠️ Error checking deal history: {str(e)}")
                import traceback
                traceback.print_exc()
                last_trade_outcome = "UNKNOWN"
            
            # CRITICAL FIX: Clear pending signals when trade closes
            if pending_buy_signal is not None:
                print(f"🔄 Clearing pending BUY signal - Trade just closed")
                pending_buy_signal = None
            if pending_sell_signal is not None:
                print(f"🔄 Clearing pending SELL signal - Trade just closed")
                pending_sell_signal = None
            
            # Reset baseline touch flag after trade closes
            baseline_touched_after_trade = False
            print(f"⏳ Waiting for price to touch baseline before next signal...")
            
            # Set flag for next trade after SL/TP
            if last_trade_outcome in ["TP", "SL"]:
                is_trade_after_sl_tp = True
                print(f"📝 Trade closed via {last_trade_outcome} - Will wait for baseline touch")
            elif last_trade_outcome == "MANUAL_CLOSE":
                print(f"📝 Trade manually closed - Will wait for baseline touch")
                is_trade_after_sl_tp = True  # Also wait for baseline touch after manual close
            
            last_position_ticket = None

# ================ MAIN STRATEGY LOOP ================
def main():
    global trading_enabled, pending_buy_signal, pending_sell_signal, last_candle_checked, current_trade_direction, last_swing_calculation_time
    global is_first_trade_after_start  # NEW
    
    if not initialize_mt5():
        return
    
    current_time_str = datetime.now().strftime("%Y-%m-d %H:%M:%S")
    print(f"\n⏰ CURRENT TIME: {current_time_str}")
    print("="*50)
    print("BASELINE + QMO SWING STRATEGY")
    print("="*50)
    print(f"Symbol: {SYMBOL}")
    print(f"Reference Time: {REFERENCE_TIME}")
    print(f"Lot Size: {LOT_SIZE}")
    print(f"Max Trades at a Time: {MAX_TRADES_AT_A_TIME}")
    print(f"Risk Reward: {RISK_REWARD_RATIO}:1")
    print(f"Buffer Points: {BUFFER_POINTS}")
    print(f"Initial Trade Mode: LIVE")
    print("="*50)
    
    # Get and display decimal places for the symbol
    decimal_places = get_decimal_places()
    print(f"📊 Symbol Decimal Places: {decimal_places}")
    print("="*50)
    
    print(f"⏳ Waiting for reference time: {REFERENCE_TIME}")
    
    last_candle_checked = None
    current_trade_direction = None
    last_swing_calculation_time = None
    is_first_trade_after_start = True  # NEW: Initialize flag
    
    while True:
        try:
            current_time = datetime.now()
            current_time_str = current_time.strftime("%H:%M")
            current_second = current_time.second
            
            if current_time_str == REFERENCE_TIME and not trading_enabled:
                print(f"\n🎯 STARTING STRATEGY AT {REFERENCE_TIME}")
                trading_enabled = True
            
            if trading_enabled:
                update_active_trades()
                
                if current_second % 30 == 0:
                    tick = mt5.symbol_info_tick(SYMBOL)
                    if tick:
                        decimal_places = get_decimal_places()
                        current_price = tick.bid
                        print(f"\n📊 {current_time.strftime('%H:%M:%S')} - Price: ${current_price:.{decimal_places}f}")
                        if current_trade_direction:
                            print(f"   Current Trade Direction: {current_trade_direction.upper()}")
                
                check_entry_signals()
                process_pending_signals()
                
                if pending_buy_signal is not None:
                    decimal_places = get_decimal_places()
                    current_price = mt5.symbol_info_tick(SYMBOL).bid
                    condition_type = "SPECIAL" if pending_buy_signal.get('is_special_condition', False) else "REVERSAL"
                    print(f"   ⏳ Pending BUY ({condition_type}) - Need price > ${pending_buy_signal['signal_candle_high']:.{decimal_places}f} (Current: ${current_price:.{decimal_places}f})")
                if pending_sell_signal is not None:
                    decimal_places = get_decimal_places()
                    current_price = mt5.symbol_info_tick(SYMBOL).bid
                    condition_type = "SPECIAL" if pending_sell_signal.get('is_special_condition', False) else "REVERSAL"
                    print(f"   ⏳ Pending SELL ({condition_type}) - Need price < ${pending_sell_signal['signal_candle_low']:.{decimal_places}f} (Current: ${current_price:.{decimal_places}f})")
                
                positions = mt5.positions_get(symbol=SYMBOL)
                if positions:
                    position_count = len(positions)
                    print(f"   📈 Active Positions: {position_count}")
            
            time.sleep(1)
            
            if current_time_str == "00:00":
                print("\n🔄 Midnight reset - continuing strategy...")
                pending_buy_signal = None
                pending_sell_signal = None
                last_candle_checked = None
                current_trade_direction = None
                last_swing_calculation_time = None
                is_first_trade_after_start = True  # NEW: Reset for new day
            
        except KeyboardInterrupt:
            print("\n\n🛑 Strategy stopped by user")
            break
        except Exception as e:
            print(f"\n⚠️ Error in main loop: {str(e)}")
            time.sleep(5)
    
    mt5.shutdown()
    print("Strategy terminated.")

# ================ RUN STRATEGY ================
if __name__ == "__main__":
    main()