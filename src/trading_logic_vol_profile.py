import pandas as pd
import numpy as np
import pandas_ta as ta
import datetime

# =====================================================
# Journey Capture
# =====================================================
def get_zone(live_data):
    cp = live_data["prices"][-1]  
    curr_vah = live_data.get("curr_vah")
    curr_val = live_data.get("curr_val")
    prv_vah = live_data.get("prv_vah")
    prv_val = live_data.get("prv_val")
    
    poc = live_data["curr_poc"] or live_data["prv_poc"]

    vah = curr_vah if curr_vah else prv_vah
    val = curr_val if curr_val else prv_val

    if not vah or not val or not poc:
        return None
    if "zone_history" not in live_data:
        live_data["zone_history"] = []
        
    if len(live_data["zone_history"]) > 20:
        live_data["zone_history"].pop(0)
    

    if cp > vah:
        live_data["zone_history"].append("above")
    elif cp < val:
        live_data["zone_history"].append("below")
    else:
        live_data["zone_history"].append("inside")

def detect_signal(live_data, executed_trades_global, para, logger):
    # =====================================================
    # 1) IB High and Low Building
    # =====================================================
    live_time_cutoff = datetime.datetime.fromtimestamp(int(live_data["live_time"][-1]))
    start_time_ib = datetime.time(9,15)
    end_time_ib = datetime.time(10,15)
    if "ib_high" not in live_data or "ib_low" not in live_data:
            live_data["ib_high"], live_data["ib_low"] = max(live_data["high_prices"]), min(live_data["low_prices"])
    if (start_time_ib <= live_time_cutoff.time() <= end_time_ib):
        live_data["ib_high"], live_data["ib_low"] = max(live_data["high_prices"][-60:]), min(live_data["low_prices"][-60:])    
    
    # =====================================================
    # EXTRACT
    # =====================================================
    cp = live_data["prices"][-1]
    lp = live_data["low_prices"][-1]
    hp = live_data["high_prices"][-1]
    op = live_data["open_prices"][-1]
    vol = live_data["volume"][-1]
    
    vol_len = min(len(live_data["volume"]), int(para["range_len"]))
    hp_lp = [abs(x - y) for x, y in zip(live_data["high_prices"][-50:], live_data["low_prices"][-50:])]
    avg_range =  pd.Series(hp_lp).rolling(window=int(para["range_len"])).mean().iloc[-1]
    avg_volume = pd.Series(live_data["volume"]).rolling(window=vol_len).mean().iloc[-1]
    df_h = pd.Series(live_data['high_prices'])
    df_l = pd.Series(live_data['low_prices'])
    df_c = pd.Series(live_data['prices'])
    atr = ta.atr(df_h, df_l, df_c, length=14, mamode="RMA").iloc[-1]

    curr_vah = live_data["curr_vah"]
    curr_val = live_data["curr_val"]
    prv_vah = live_data["prv_vah"]
    prv_val = live_data["prv_val"]
    poc = live_data["curr_poc"] or live_data["prv_poc"]

    vah = curr_vah if curr_vah else prv_vah
    val = curr_val if curr_val else prv_val

    if not vah or not val or not poc:
        logger.info(f"vah and val not in data")
        return None

    # =====================================================
    # JOURNEY ENGINE (NEW)
    # =====================================================
    if "zone_history" not in live_data:
        live_data["zone_history"] = []
    zh = live_data["zone_history"]

    if len(zh) > 5:
        if all(z == "below" for z in zh[-6:-1]):
            journey = "from_below"
        elif all(z == "above" for z in zh[-6:-1]):
            journey = "from_above"
        elif all(z == "inside" for z in zh[-6:-1]):
            journey = "from_inside"
        else:
            journey = "mixed"
    else:
        journey = "unknown"

    migrating_up = zh.count("below") > 3 and zh[-1] in ["inside", "above"]
    migrating_down = zh.count("above") > 3 and zh[-1] in ["inside", "below"]

    reclaim_up = len(zh) > 3 and zh[-3] == "below" and zh[-2] == "above"
    reclaim_down = len(zh) > 3 and zh[-3] == "above" and zh[-2] == "below"

    # =====================================================
    # HELPERS
    # =====================================================
    def accepted_above(level, bars=3):
        return len(live_data["prices"]) >= bars and all(c > level for c in live_data["prices"][-bars:])

    def accepted_below(level, bars=3):
        return len(live_data["prices"]) >= bars and all(c < level for c in live_data["prices"][-bars:])

    def impulse():
        return (hp_lp[-1] > avg_range * para["range_m"] and vol > avg_volume * para["vol_m"])

    def bullish_rejection():
        lower_wick = (op - lp) if cp > op else (cp - lp)
        body = abs(cp - op)
        return lower_wick > (body * 1.5) and cp > op

    def bearish_rejection():
        upper_wick = (hp - cp) if cp < op else (hp - op)
        body = abs(cp - op)
        return upper_wick > (body * 1.5) and cp < op
    
    def is_near(price, level, tolerance_atr_multiplier=0.3):
        # Checks if the price is within a strict distance (e.g., 0.3x ATR) of the level
        return abs(price - level) <= (atr * tolerance_atr_multiplier)

    def was_near(level, mode="low", bars=3):
        # We need the 'mode' parameter to know whether to check Highs or Lows
        prices = live_data["low_prices"] if mode == "low" else live_data["high_prices"]
        return any(abs(p - level) <= (atr * 0.5) for p in prices[-bars:])
      
    # =====================================================
    # REGIME
    # =====================================================
    ib_high, ib_low = live_data["ib_high"], live_data["ib_low"]

    ib_mid = (ib_high + ib_low) / 2
    current_time = datetime.datetime.fromtimestamp(int(live_data["live_time"][-1])).time()

    # 1. Morning Session Override
    if current_time < datetime.time(10, 0):
        vah, val, poc = prv_vah, prv_val, live_data["prv_poc"]
        regime = "normal"
        imp = (hp_lp[-1] > avg_range * 1.0) # Lowered impulse requirement
    else:
        # 2. Directional Regimes
        if (ib_high - ib_low) > atr * para["trend_atr_m"]:
            regime = "trend_up" if cp > ib_mid else "trend_down"
        elif abs(cp - ib_mid) < atr * para["bal_atr_m"]:
            regime = "balance"
        else:
            regime = "normal"
        imp = impulse()


    # =====================================================
    # ENTRY SEARCH (UPGRADED)
    # =====================================================
    acc_above = accepted_above(vah)
    acc_below = accepted_below(val)
    imp = impulse()
        
    entering_pdva_high = cp > curr_vah and cp < prv_vah and accepted_above(curr_vah, 2)
    entering_pdva_low  = cp < curr_val and cp > prv_val and accepted_below(curr_val, 2)

        # Micro-Trend Filter
    micro_trend_up = len(live_data["prices"]) > 3 and cp > live_data["prices"][-4]
    micro_trend_down = len(live_data["prices"]) > 3 and cp < live_data["prices"][-4]

    #poc_retest_sell = regime != "trend_down" and hp >= sell_retest_zone and cp < poc and bearish_rejection() and not micro_trend_up
    #poc_retest_buy = regime != "trend_up" and lp <= buy_retest_zone and cp > poc and bullish_rejection() and not micro_trend_down

    poc_retest_buy = regime != "trend_down" and is_near(lp, poc) and cp > poc and bullish_rejection() and not micro_trend_down
    poc_retest_sell = regime != "trend_up" and is_near(hp, poc) and cp < poc and bearish_rejection() and not micro_trend_up

    lookback = 15
    if len(live_data["prices"]) > lookback:
        recent_prices = live_data["prices"][-lookback:-1]
        was_outside_below = max(recent_prices) < val 
        was_outside_above = min(recent_prices) > vah
    else:
        was_outside_below = op < val
        was_outside_above = op > vah

    entered_va_from_below = was_outside_below and cp > val
    entered_va_from_above = was_outside_above and cp < vah

    decision = "wait"

    # PRIORITY 1 → RECLAIM
    if reclaim_up and accepted_above(vah, 1):
        decision = "breakout_buy"
    elif reclaim_down and accepted_below(val, 1):
        decision = "breakout_sell"

    # PRIORITY 2 → MIGRATION
    elif migrating_up and acc_above:
        decision = "breakout_buy"
    elif migrating_down and acc_below:
        decision = "breakout_sell"

    # PRIORITY 3 → FADES (Proximity Locked: Must touch VAH/VAL and close inside)
    elif not migrating_up and not imp and (is_near(hp, vah) or was_near(vah, "high")) and cp < vah and bearish_rejection():
        decision = "fade_from_vah_sell"
    elif not migrating_down and not imp and (is_near(lp, val) or was_near(val, "low")) and cp > val and bullish_rejection():
        decision = "fade_from_val_buy"

    # PRIORITY 4 → REVERSALS & FILLS (Reordered & Proximity Locked)
    elif entered_va_from_below and accepted_above(val, 2):
        decision = "va_fill_buy"
    elif entered_va_from_above and accepted_below(vah, 2):
        decision = "va_fill_sell"
        
    # PD Levels MUST be physically touched by the wick
    elif entering_pdva_low and (is_near(hp, prv_val) or was_near(prv_val, "high")) and cp < prv_val and bearish_rejection():
        decision = "pd_val_resistance"
    elif entering_pdva_high and (is_near(lp, prv_vah) or was_near(prv_vah, "low")) and cp > prv_vah and bullish_rejection():
        decision = "pd_vah_support"
        
    # POC Retests (Safe to run now that PD levels are locked)
    elif poc_retest_buy or (regime != "trend_down" and was_near(poc, "low") and cp > poc and bullish_rejection()):
        decision = "poc_retest_buy"
    elif poc_retest_sell or (regime != "trend_up" and was_near(poc, "high") and cp < poc and bearish_rejection()):
        decision = "poc_retest_sell"

    '''if decision == "wait":
        return None'''
    
    # =====================================================
    # Print statements
    # =====================================================
    logger.info(f"""
    --- Decision Logic Debug ----------------------------------------------------------------------------------------------------------------------------
    [Context] CP: {cp} | HP: {hp} | LP: {lp} | VAH: {vah} | VAL: {val} | POC: {poc} | Regime {regime}
    [Prev Levels] PrvVAH: {prv_vah} | PrvVAL: {prv_val}
    [State] MigUp: {migrating_up} | MigDn: {migrating_down} | RecUp: {reclaim_up} | RecDn: {reclaim_down}
    [State] Imp: {imp} | AccAbove: {acc_above} | AccBelow: {acc_below}
    [Entries] Ent_PD_H: {entering_pdva_high} | Ent_PD_L: {entering_pdva_low} | VA_Fill_Up: {entered_va_from_below} | VA_Fill_Dn: {entered_va_from_above}
    [Retest] POC_Ret_B: {poc_retest_buy} | POC_Ret_S: {poc_retest_sell}
    [Candle] BullRej: {bullish_rejection()} | BearRej: {bearish_rejection()}
    [decision] decision: {decision}""")

    # =====================================================
    # CONFLICT RESOLUTION
    # =====================================================
    # 1. Kill Fades during Migration
    if "fade" in decision and (migrating_up or migrating_down):
        logger.info(f"returned from killing the fade")
        return None

    if "breakout" in decision and (live_time_cutoff.time() < datetime.time(9, 45)):
        logger.info(f"returned from killing the breakout")
        return None

    # 2. Time Acceptance for Quiet Breakouts
    if "breakout" in decision and journey == "from_inside":
        if not imp:
            is_strong_buy  = (decision == "breakout_buy" and accepted_above(vah, 3))
            is_strong_sell = (decision == "breakout_sell" and accepted_below(val, 3))
            if not is_strong_buy and not is_strong_sell:
                return None

    # 3. Macro Trend Protection
    if regime == "trend_up" and "sell" in decision and "fill" not in decision:
        logger.info(f"Macro trend protection")
        return None
    if regime == "trend_down" and "buy" in decision and "fill" not in decision:
        logger.info(f"Macro trend protection")
        return None

    # =====================================================
    # SCORING
    # =====================================================
    score = 0
    if imp: score += 2
    if bullish_rejection() or bearish_rejection(): score += 2

    # Strategy Base Scores
    if "breakout" in decision: 
        score += 3
    if "pd_" in decision:          # Covers pd_vah_support & pd_val_resistance
        score += 3
    if "retest" in decision: 
        score += 2
    if "fill" in decision:         # Covers va_fill_buy & va_fill_sell
        score += 2
    if "fade" in decision:         # Covers fade_from_vah_sell & fade_from_val_buy
        score += 2

    logger.info(f"""[score] score: {score}
                        ------------------------------------------------------------------------------""")

    # =====================================================
    # 1) Trading window and cooling period
    # =====================================================
    if not live_data["trade_allowed"]:
        logger.info(f"market out of trading window")
        return None
    
    if len(live_data['live_time']) > 0 and live_data['live_time'][-1] <= live_data['trade_exit_time'] + 60 * para["cooldown"]:
        logger.info(f"cooling period on - for 5 minutes")
        return None
    
    # =====================================================
    # DAILY GUARD
    # =====================================================
    if executed_trades_global:
        if sum(trade["pnl"] for trade in executed_trades_global) <= -para["max_loss"]:
            return None
        if sum(trade["pnl"] for trade in executed_trades_global) >= para["max_profit"]:
            return None
        if len(executed_trades_global) >= 3 and all(trade["sl_hit"] == "yes" for trade in executed_trades_global[-3:]):
            logger.info(f"Trading Stopped as 3 Stop Losses Hit")
            return None

    # =====================================================
    # SL & TARGET and Min Score
    # =====================================================
    min_score = 4 if regime == "balance" else 5

    if score < min_score:
        return None


    entry = live_data["live_price"]

    buy_signals = ["breakout_buy", "poc_retest_buy", "fade_from_val_buy", "pd_vah_support", "va_fill_buy"]
    
    if decision in buy_signals:
        side = "buy"
        if decision == "breakout_buy": 
            sl = vah - (atr * para["break_sl_m"])
        elif decision == "va_fill_buy": 
            sl = val - (atr * para["fade_sl_m"])
        else: 
            sl = lp - (atr * para["fade_sl_m"])
    else:
        side = "sell"
        if decision == "breakout_sell": 
            sl = val + (atr * para["break_sl_m"])
        elif decision == "va_fill_sell": 
            sl = vah + (atr * para["fade_sl_m"])
        else: 
            sl = hp + (atr * para["fade_sl_m"])

    risk = abs(entry - sl)
    min_risk = entry * 0.003 
    if risk < min_risk:
        risk = min_risk
        sl = entry - risk if side == "buy" else entry + risk
    
    if decision in ["pd_val_resistance", "va_fill_sell"]:
        target = (prv_val - risk * 2) if "pd_" in decision else poc
    elif decision in ["pd_vah_support", "va_fill_buy"]:
        target = (prv_vah + risk * 2) if "pd_" in decision else poc
    else:
        target = entry + risk * (2 + score * 0.2) if side == "buy" else entry - risk * (2 + score * 0.2)

    if abs(target - entry) > 2.5 * risk:
        target = entry + 2.5 * risk if side == "buy" else entry - 2.5 * risk

    return {"side": side, "entry": entry, "sl": sl, "target": target, "score": score, "strategy": decision, "regime": regime, "journey": journey}

#===============================================================
#check stop and book profit live_data, trade_info, para, executed_trades_global
#===============================================================
def check_stop(live_data, trade_info, para, executed_trades, logger):

    live_price = live_data["live_price"]
    side   = trade_info["signal_type"]
    stop   = trade_info["stop_price"]
    target = trade_info["target_price"]
    entry  = trade_info["entry_price"]
    # --- NEW ---
    partial_done = trade_info.get("partial_done", False)

    exit_time = trade_info["entry_time"] + 60 * para["max_hold_min"]
    current_time = live_data["live_time"][-1] if len(live_data["live_time"]) > 0 else 0
    
    #======================== Exit based on max loss and max profit ====================
    executed_trades[-1]["pnl"] = (live_price - entry) if side == "buy" else (entry - live_price)
    if sum(trade["pnl"] for trade in executed_trades) <= -para["max_loss"]:
        return True
    if sum(trade["pnl"] for trade in executed_trades) >= para["max_profit"]:
        return True

    # ======================== Trade Management (Breakeven & Trail) ====================
    point_captured = (live_price - entry) if side == "buy" else (entry - live_price)
    point_targted = (target - entry) if side == "buy" else (entry - target)
    if point_targted > 0:
        ratio = point_captured / point_targted

        if ratio >= 0.85:
            if side == "buy":
                new_stop = entry + (point_targted * 0.7)
                if new_stop > stop:
                    trade_info["stop_price"] = new_stop
            else:
                new_stop = entry - (point_targted * 0.7)
                if new_stop < stop:
                    trade_info["stop_price"] = new_stop  
                
            logger.info(f"Tier 3 Trail 80 : Locked profit at {trade_info['stop_price']:.2f}")

        if 0.85 > ratio >= 0.7:
            if side == "buy":
                new_stop = entry + (point_targted * 0.5)
                if new_stop > stop:
                    trade_info["stop_price"] = new_stop
                trade_info["target_price"] = target + (point_targted * 0.1)
                
            else:
                new_stop = entry - (point_targted * 0.5)
                if new_stop < stop:
                    trade_info["stop_price"] = new_stop  
                trade_info["target_price"] = target - (point_targted * 0.1)
                
            logger.info(f"Tier 2 Trail: Locked profit at {trade_info['stop_price']:.2f}. Target pushed to {trade_info['target_price']:.2f}")

        # --- TIER 1: 40% Reached (Move to Breakeven) ---
        elif ratio >= 0.4 and not trade_info.get("trail_40_done", False):
            new_stop = entry
            if side == "buy" and new_stop > stop:
                trade_info["stop_price"] = new_stop
                trade_info["trail_40_done"] = True
            
            if side == "sell" and new_stop < stop:
                trade_info["stop_price"] = new_stop
                trade_info["trail_40_done"] = True
            
            logger.info(f"Tier 1 Trail: Stop moved to exact Entry ({entry}). Trade is now Risk-Free.")

    stop = trade_info["stop_price"]
    target = trade_info["target_price"]

    # ================= STOP LOSS =================
    if side == "buy" and live_price <= stop:
        executed_trades[-1]["sl_hit"] = "yes"
        executed_trades[-1]["pnl"] = live_price - entry
        return True

    if side == "sell" and live_price >= stop:
        executed_trades[-1]["sl_hit"] = "yes"
        executed_trades[-1]["pnl"] = entry - live_price
        return True

    # ================= TARGET =================
    if side == "buy" and live_price >= target:
        executed_trades[-1]["pnl"] = live_price - entry
        return True

    if side == "sell" and live_price <= target:
        executed_trades[-1]["pnl"] = entry - live_price
        return True

    # ================= TIME EXIT =================
    market_cutoff = datetime.datetime.fromtimestamp(int(current_time))
    squareoff = (market_cutoff.time() >= datetime.time(15,13)) or (current_time >= exit_time)
    if squareoff:
        executed_trades[-1]["sl_hit"] = "time_exit"
        return True

    return None
    
#-------------------------------------------------------------------------------------------
#function to build Volumne Profile
#-------------------------------------------------------------------------------------------
def get_volume_profile_live(df, va_pct=0.70):

    if df is None or df.empty:
        return {"POC": None, "VAH": None, "VAL": None}

    price_col = "prices"
    vol_col = "volume"

    profile = (
        df.groupby(price_col)[vol_col]
        .sum()
        .sort_index(ascending=False)
        .to_frame(name="volume")
    )

    if len(profile) == 1:
        p = profile.index[0]
        return {"POC": p, "VAH": p, "VAL": p}

    total_volume = profile["volume"].sum()
    target_volume = total_volume * va_pct

    poc_price = profile["volume"].idxmax()
    poc_idx = profile.index.get_loc(poc_price)

    current_va_vol = profile.iloc[poc_idx]["volume"]

    up_idx = poc_idx - 1
    down_idx = poc_idx + 1

    while current_va_vol < target_volume:
        can_move_up = up_idx >= 0
        can_move_down = down_idx < len(profile)

        if not can_move_up and not can_move_down:
            break

        if can_move_up and can_move_down:
            up_vol = profile.iloc[up_idx]["volume"]
            down_vol = profile.iloc[down_idx]["volume"]

            if up_vol >= down_vol:
                current_va_vol += up_vol
                up_idx -= 1
            else:
                current_va_vol += down_vol
                down_idx += 1

        elif can_move_up:
            current_va_vol += profile.iloc[up_idx]["volume"]
            up_idx -= 1
        else:
            current_va_vol += profile.iloc[down_idx]["volume"]
            down_idx += 1

    # clamp boundaries
    vah = profile.index[max(0, up_idx + 1)]
    val = profile.index[min(len(profile) - 1, down_idx - 1)]

    return {"POC": poc_price, "VAH": vah, "VAL": val}


def get_volume_profile_stats(df, va_pct=0.70, bin_size=0.05):
    """
    Calculates POC, VAH, and VAL from tick-level data.
    Uses price compression via bin_size.
    """

    price_col = "prices"
    vol_col = "volume"

    # Work on a copy to avoid modifying original df
    data = df[[price_col, vol_col]].copy()

    # ---- PRICE BINNING (critical) ----
    data["price_bin"] = ((data[price_col] / bin_size).round() * bin_size).round(2)

    # Build volume profile (descending like your original)
    profile = (
        data.groupby("price_bin")[vol_col]
        .sum()
        .sort_index(ascending=False)
        .to_frame(name="volume")
    )

    total_volume = profile["volume"].sum()
    target_volume = total_volume * va_pct

    # ---- POC ----
    poc_price = profile["volume"].idxmax()
    poc_idx = profile.index.get_loc(poc_price)

    # ---- VALUE AREA ----
    current_va_vol = profile.iloc[poc_idx]["volume"]

    up_idx = poc_idx - 1
    down_idx = poc_idx + 1

    while current_va_vol < target_volume:
        can_move_up = up_idx >= 0
        can_move_down = down_idx < len(profile)

        if can_move_up and can_move_down:
            up_vol = profile.iloc[up_idx]["volume"]
            down_vol = profile.iloc[down_idx]["volume"]

            if up_vol >= down_vol:
                current_va_vol += up_vol
                up_idx -= 1
            else:
                current_va_vol += down_vol
                down_idx += 1

        elif can_move_up:
            current_va_vol += profile.iloc[up_idx]["volume"]
            up_idx -= 1

        elif can_move_down:
            current_va_vol += profile.iloc[down_idx]["volume"]
            down_idx += 1
        else:
            break

    vah = profile.index[up_idx + 1]
    val = profile.index[down_idx - 1]

    return {
        "POC": poc_price,
        "VAH": vah,
        "VAL": val,
    }

