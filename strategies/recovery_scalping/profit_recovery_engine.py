#this is always take profit strategy in this we never stop until we get profit .
#After every few trades the volume is increased to recover previous loss 
#Our main goal is take atleast fix profit like ex - 1$


import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()

login = int(os.getenv("MT5_LOGIN"))
password = os.getenv("MT5_PASSWORD")
server = os.getenv("MT5_SERVER")


started = mt5.initialize()
loged_in = mt5.login(login, password, server)
print(started, loged_in)

symbol = "BTCUSDT"
timeframe = mt5.TIMEFRAME_M5
volume = 0.01
strategy_name = 'reversing_strategy'

# Strategy parameters
POINTS_DIFF = 100
RISK_REWARD_RATIO = 3
MAX_TRADES = 13  # Increased to allow for volume progression

# Trading state variables
reference_low = 0.0
upper_level = 0.0
lower_level = 0.0
trade_sequence = 0
current_direction = None
trade_active = False
tp_hit = False
last_trade_price = 0.0
last_sl_price = 0.0
last_tp_price = 0.0
reference_times = ["18:33", "20:15"]  # CHANGED FROM "19.50" to "19:50"
current_reference_index = 0
reference_time = reference_times[current_reference_index]

# Volume progression variables
current_volume = volume
volume_progression = [volume]  # Track volume for each trade
# Volume progression based on your photo - manual sequence
volume_sequence = [
    0.01,  # Trade 1
    0.01,  # Trade 2  
    0.01,  # Trade 3
    0.02,  # Trade 4
    0.02,  # Trade 5
    0.03,  # Trade 6
    0.04,  # Trade 7
    0.05,  # Trade 8
    0.07,  # Trade 9
    0.09,  # Trade 10
    0.12,  # Trade 11
    0.16,  # Trade 12
    0.22   # Trade 13
]

def calculate_next_volume(current_vol):
    """Get next volume from manual sequence based on trade sequence"""
    if trade_sequence < len(volume_sequence):
        return volume_sequence[trade_sequence]
    else:
        # If beyond sequence, use last volume or custom logic
        return volume_sequence[-1]  # Use last volume in sequence
    

def close_all_positions():
    if mt5.positions_total() > 0:
        positions = mt5.positions_get()
        for position in positions:
            close_position(position)

def close_position(position, deviation=20, magic=12345):
    order_type_dict = {
        0: mt5.ORDER_TYPE_SELL,
        1: mt5.ORDER_TYPE_BUY
    }
    price_dict = {
        0: mt5.symbol_info_tick(symbol).bid,
        1: mt5.symbol_info_tick(symbol).ask
    }
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": position.ticket,
        "symbol": symbol,
        "volume": position.volume,
        "type": order_type_dict[position.type],
        "price": price_dict[position.type],
        "deviation": deviation,
        "magic": magic,
        "comment": strategy_name,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    return mt5.order_send(request)

def market_order(symbol, volume, order_type, sl, tp, deviation=20, magic=12345):
    order_type_dict = {
        'buy': mt5.ORDER_TYPE_BUY,
        'sell': mt5.ORDER_TYPE_SELL
    }
    price_dict = {
        'buy': mt5.symbol_info_tick(symbol).ask,
        'sell': mt5.symbol_info_tick(symbol).bid
    }
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type_dict[order_type],
        "price": price_dict[order_type],
        "sl": sl,
        "tp": tp,
        "deviation": deviation,
        "magic": magic,
        "comment": strategy_name,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    return mt5.order_send(request)

def calculate_levels(low_price):
    return low_price + POINTS_DIFF, low_price - POINTS_DIFF

def analyze_trade_outcome_live(entry_price, direction, sl_price, tp_price, current_price):
    """
    Live market analysis to determine if TP or SL was hit
    Returns: 'tp_hit', 'sl_hit', or 'unknown'
    """
    if direction == 'buy':
        # For BUY: TP is above entry, SL is below entry
        if current_price >= tp_price:
            return 'tp_hit'
        elif current_price <= sl_price:
            return 'sl_hit'
    elif direction == 'sell':
        # For SELL: TP is below entry, SL is above entry
        if current_price <= tp_price:
            return 'tp_hit'
        elif current_price >= sl_price:
            return 'sl_hit'
    return 'unknown'

if __name__ == '__main__':
    is_initialized = mt5.initialize()
    print('initialize: ', is_initialized)
    is_logged_in = mt5.login(login, password, server)
    print('logged in: ', is_logged_in)
    print('\n')
    
    levels_set = False
    day_reset = False
    trading_enabled = False  # ADDED: Flag to enable trading only after reference time
    
    current_time = datetime.now().strftime('%H:%M')
    print(f"=== STRATEGY STARTED ===")
    print(f"Current Time (24h): {current_time}")
    print(f"Reference Time: {reference_time}")
    print(f"Symbol: {symbol}")
    print(f"Points Difference: {POINTS_DIFF}")
    print(f"Max Trades: {MAX_TRADES}")
    print(f"Initial Volume: {volume}")
    print(f"========================")
    
    while True:
        current_time = datetime.now().strftime('%H:%M')
        current_time_full = datetime.now().strftime('%H:%M:%S')
        current_bid = mt5.symbol_info_tick(symbol).bid
        current_ask = mt5.symbol_info_tick(symbol).ask
        
        # DEBUG: Print status every 10 seconds
        if int(datetime.now().strftime('%S')) % 10 == 0:
            print(f"[{current_time_full}] Current Price: {current_bid}, Levels Set: {levels_set}, Trading Enabled: {trading_enabled}, Sequence: {trade_sequence}, TP Hit: {tp_hit}, Current Volume: {current_volume}")
        
        # Set reference levels at specified time
        if (current_time == reference_time and not levels_set and not tp_hit and 
            trading_enabled == False):
            print(f"🎯 SETTING REFERENCE LEVELS at {reference_time}")
            time.sleep(2)
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 1, 1)
            if rates is not None and len(rates) > 0:
                reference_close = rates[0]['close']
                upper_level, lower_level = calculate_levels(reference_close)
                print(f"✅ REFERENCE LEVELS SET:")
                print(f"   Reference Low: {reference_close}")
                print(f"   Upper Level (+{POINTS_DIFF}): {upper_level}")
                print(f"   Lower Level (-{POINTS_DIFF}): {lower_level}")
                print(f"   TP Distance: {POINTS_DIFF * RISK_REWARD_RATIO} points")
                trade_sequence = 0
                current_direction = None
                trade_active = False
                tp_hit = False
                last_trade_price = 0.0
                levels_set = True
                trading_enabled = True  # ENABLE TRADING ONLY AFTER REFERENCE TIME
                day_reset = False
                # Reset volume to initial for new cycle
                current_volume = volume
                volume_progression = [volume]
                close_all_positions()
            else:
                print(f"❌ ERROR: Could not get price data for {symbol}")
        
        # Reset for next day
        if current_time == "00:00" and not day_reset:
            print(f"🔄 24-HOUR CYCLE RESET")
            current_reference_index = 0
            reference_time = reference_times[current_reference_index]
            levels_set = False
            trading_enabled = False  # DISABLE TRADING UNTIL NEXT REFERENCE TIME
            trade_sequence = 0
            current_direction = None
            trade_active = False
            day_reset = True
            tp_hit = False
            # Reset volume to initial for new day
            current_volume = volume
            volume_progression = [volume]
            
        if current_time == "00:01" and day_reset:
            day_reset = False
            
        if levels_set and (tp_hit or trade_sequence >= MAX_TRADES):
            if current_reference_index < len(reference_times) - 1:
                current_reference_index += 1
                reference_time = reference_times[current_reference_index]
                levels_set = False
                trading_enabled = False
                trade_sequence = 0
                current_direction = None
                trade_active = False
                tp_hit = False
                # Reset volume to initial for next reference time
                current_volume = volume
                volume_progression = [volume]
                print(f"🔄 ADVANCING TO NEXT REFERENCE TIME: {reference_time}")
            else:
                current_reference_index = 0
                reference_time = reference_times[current_reference_index]
                levels_set = False
                trading_enabled = False
                # Reset volume to initial for new cycle
                current_volume = volume
                volume_progression = [volume]
                print(f"🔄 CYCLE COMPLETE - RESTARTING WITH FIRST TIME: {reference_time}")
        
        # TRADING LOGIC - ONLY EXECUTE IF TRADING IS ENABLED
        if trading_enabled and levels_set and trade_sequence < MAX_TRADES and not tp_hit:
            # DEBUG: Print levels comparison
            if int(datetime.now().strftime('%S')) % 15 == 0:
                print(f"   📊 Price: {current_bid} | Upper: {upper_level} | Lower: {lower_level} | Ref Low: {reference_close}")
            
            # TRADE SEQUENCE 1: Initial breakout
            if trade_sequence == 0 and not trade_active:
                # BUY condition
                if current_bid >= upper_level and current_direction is None:
                    sl = current_ask - POINTS_DIFF 
                    tp = current_ask + (POINTS_DIFF * RISK_REWARD_RATIO)
                    print(f"🚀 BUY SIGNAL - Price {current_bid} >= Upper {upper_level}")
                    order_result = market_order(symbol, current_volume, 'buy', sl, tp)
                    if order_result.retcode == mt5.TRADE_RETCODE_DONE:
                        current_direction = 'buy'
                        trade_active = True
                        trade_sequence = 1
                        last_trade_price = current_ask
                        last_sl_price = sl
                        last_tp_price = tp
                        print(f"✅ Trade 1: BUY at {current_ask}, SL: {sl}, TP: {tp}, Volume: {current_volume}")
                    else:
                        print(f"❌ Trade 1 FAILED: {order_result.comment}")
                
                # SELL condition  
                elif current_bid <= lower_level and current_direction is None:
                    sl = current_bid + POINTS_DIFF
                    tp = current_bid - (POINTS_DIFF * RISK_REWARD_RATIO)
                    print(f"🚀 SELL SIGNAL - Price {current_bid} <= Lower {lower_level}")
                    order_result = market_order(symbol, current_volume, 'sell', sl, tp)
                    if order_result.retcode == mt5.TRADE_RETCODE_DONE:
                        current_direction = 'sell'
                        trade_active = True
                        trade_sequence = 1
                        last_trade_price = current_bid
                        last_sl_price = sl
                        last_tp_price = tp
                        print(f"✅ Trade 1: SELL at {current_bid}, SL: {sl}, TP: {tp}, Volume: {current_volume}")
                    else:
                        print(f"❌ Trade 1 FAILED: {order_result.comment}")
            
            # ULTRA-FAST POSITION CLOSURE DETECTION WITH LIVE ANALYSIS
            if trade_active:
                positions = mt5.positions_get(symbol=symbol)
                
                # If position closed, analyze using LIVE MARKET DATA
                if len(positions) == 0 and trade_active:
                    trade_active = False
                    print(f"🔄 POSITION CLOSED - Analyzing with live market data...")
                    
                    # LIVE MARKET ANALYSIS - Check if price reached TP level
                    outcome = analyze_trade_outcome_live(
                        last_trade_price, 
                        current_direction, 
                        last_sl_price, 
                        last_tp_price, 
                        current_bid
                    )
                    
                    if outcome == 'tp_hit':
                        print(f"🎯 TP HIT CONFIRMED - Price reached TP level")
                        print(f"   Entry: {last_trade_price}, Current: {current_bid}, TP Level: {last_tp_price}")
                        print(f"💎 TP HIT - STOPPING ALL TRADING")
                        trade_active = False
                        tp_hit = True
                        trade_sequence = MAX_TRADES
                        continue  # Stop immediately
                    
                    elif outcome == 'sl_hit':
                        print(f"🛑 SL HIT CONFIRMED - Price reached SL level")
                        print(f"   Entry: {last_trade_price}, Current: {current_bid}, SL Level: {last_sl_price}")
                        print(f"🔄 PLACING COUNTER-TRADE IMMEDIATELY")
                        
                        # CALCULATE NEXT VOLUME
                        current_volume = calculate_next_volume(current_volume)
                        volume_progression.append(current_volume)
                        print(f"📈 Volume increased to: {current_volume}")
                        
                        # IMMEDIATE COUNTER-TRADE PLACEMENT (REVERSE DIRECTION)
                        if current_direction == 'buy':  # SL hit on buy, now SELL
                            entry_price = current_bid
                            sl = entry_price + POINTS_DIFF
                            tp = entry_price - (POINTS_DIFF * RISK_REWARD_RATIO)
                            print(f"🔄 IMMEDIATE SELL at {entry_price}")
                            order_result = market_order(symbol, current_volume, 'sell', sl, tp)
                            if order_result.retcode == mt5.TRADE_RETCODE_DONE:
                                current_direction = 'sell'  # Reverse direction
                                trade_active = True
                                trade_sequence += 1
                                last_trade_price = entry_price
                                last_sl_price = sl
                                last_tp_price = tp
                                print(f"✅ Trade {trade_sequence}: SELL at {entry_price}, SL: {sl}, TP: {tp}, Volume: {current_volume}")
                            else:
                                print(f"❌ Trade {trade_sequence} FAILED: {order_result.comment}")
                                trade_active = False
                        
                        elif current_direction == 'sell':  # SL hit on sell, now BUY
                            entry_price = current_ask
                            sl = entry_price - POINTS_DIFF
                            tp = entry_price + (POINTS_DIFF * RISK_REWARD_RATIO)
                            print(f"🔄 IMMEDIATE BUY at {entry_price}")
                            order_result = market_order(symbol, current_volume, 'buy', sl, tp)
                            if order_result.retcode == mt5.TRADE_RETCODE_DONE:
                                current_direction = 'buy'  # Reverse direction
                                trade_active = True
                                trade_sequence += 1
                                last_trade_price = entry_price
                                last_sl_price = sl
                                last_tp_price = tp
                                print(f"✅ Trade {trade_sequence}: BUY at {entry_price}, SL: {sl}, TP: {tp}, Volume: {current_volume}")
                            else:
                                print(f"❌ Trade {trade_sequence} FAILED: {order_result.comment}")
                                trade_active = False
                    
                    else:
                        # If live analysis is uncertain, use deal history as backup
                        print(f"⚠️ UNCERTAIN OUTCOME - Checking deal history...")
                        end_time = datetime.now()
                        start_time = end_time - timedelta(seconds=10)
                        history = mt5.history_deals_get(start_time, end_time)
                        
                        tp_found = False
                        if history:
                            for deal in reversed(history):
                                if hasattr(deal, 'profit') and deal.profit > 0:
                                    print(f"🎯 TP HIT (Deal History) - Profit: {deal.profit}")
                                    trade_active = False
                                    tp_hit = True
                                    trade_sequence = MAX_TRADES
                                    tp_found = True
                                    break
                        
                        if not tp_found:
                            print(f"🛑 Assuming SL hit - Placing counter-trade")
                            
                            # CALCULATE NEXT VOLUME
                            current_volume = calculate_next_volume(current_volume)
                            volume_progression.append(current_volume)
                            print(f"📈 Volume increased to: {current_volume}")
                            
                            # Place counter-trade logic here (REVERSE DIRECTION)
                            if current_direction == 'buy':
                                entry_price = current_bid
                                sl = entry_price + POINTS_DIFF
                                tp = entry_price - (POINTS_DIFF * RISK_REWARD_RATIO)
                                print(f"🔄 IMMEDIATE SELL at {entry_price}")
                                order_result = market_order(symbol, current_volume, 'sell', sl, tp)
                                if order_result.retcode == mt5.TRADE_RETCODE_DONE:
                                    current_direction = 'sell'  # Reverse direction
                                    trade_active = True
                                    trade_sequence += 1
                                    last_trade_price = entry_price
                                    last_sl_price = sl
                                    last_tp_price = tp
                                    print(f"✅ Trade {trade_sequence}: SELL at {entry_price}, SL: {sl}, TP: {tp}, Volume: {current_volume}")
                                    
                            elif current_direction == 'sell':
                                entry_price = current_ask
                                sl = entry_price - POINTS_DIFF
                                tp = entry_price + (POINTS_DIFF * RISK_REWARD_RATIO)
                                print(f"🔄 IMMEDIATE BUY at {entry_price}")
                                order_result = market_order(symbol, current_volume, 'buy', sl, tp)
                                if order_result.retcode == mt5.TRADE_RETCODE_DONE:
                                    current_direction = 'buy'  # Reverse direction
                                    trade_active = True
                                    trade_sequence += 1
                                    last_trade_price = entry_price
                                    last_sl_price = sl
                                    last_tp_price = tp
                                    print(f"✅ Trade {trade_sequence}: BUY at {entry_price}, SL: {sl}, TP: {tp}, Volume: {current_volume}")

                                
        
        # Display TP hit status
        if tp_hit:
            print(f"💎 TP HIT - NO MORE TRADES FOR TODAY")
            print(f"📊 Volume Progression: {volume_progression}")
        
        time.sleep(0.1)  # Ultra-fast detection