# config_range.py
STRATEGIES = [
    {
        "ticker": "NSE:TMPV-EQ",
        "timeframe": "1",
        "quantity": 1,
        "trade_type": "Equity", #"Equity", # or "Options"
        "expiry_str": "2026-03-10",
        "expiry_type": "Weekly", # or "Weekly" "Monthly"
        "option_step": 10,
        "side": "buy",
        "max_trades": 10,
        "max_loss": 100, 
        "max_profit":100, 
        "range_len":20, 
        "trend_atr_m":1.5, 
        "bal_atr_m":0.5, 
        "range_m":1.2, 
        "vol_m":1.3,
        "break_sl_m":1.5, 
        "fade_sl_m":1.0, 
        "max_hold_min":90,
        "cooldown" : 5},
]