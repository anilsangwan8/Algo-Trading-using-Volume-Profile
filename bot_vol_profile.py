import time
import os
import datetime
import threading
import pytz
import pandas as pd
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws
import user_config
from config import STRATEGIES
from src.logging_helper_vol_profile import logging_helper
from src.fyers_client_vol_profile import get_access_token, subscribe_to_live_data, place_order
from src.trading_logic_vol_profile import  check_stop, detect_signal, get_volume_profile_stats, get_volume_profile_live, get_zone

ist = pytz.timezone('Asia/Kolkata')


# --- SESSION MANAGEMENT ---
def get_valid_fyers_client():
    # Using the Access Token from your config
    AUTH_DIR = r"F:\Trading Bot\Auth_Token"
    file_path = os.path.join(AUTH_DIR, "access_token.txt")
    with open(file_path, "r") as f:
            access_token = f.read().strip()
    client = fyersModel.FyersModel(
        client_id=user_config.CLIENT_ID, 
        token=access_token,
        is_async  = False,
        log_path=""
    )
    return client, access_token

class VolProfBotInstance:
    def __init__(self, config, fyers_client):
        self.cfg = config
        self.fyers = fyers_client
        self.ticker = config['ticker']
        self.side = config['side']
        self.logger = logging_helper(self.ticker)
        # --- PRESERVING YOUR EXACT GLOBALS PER INSTANCE ---
        self.live_data_lock = threading.Lock()
        self.executed_trades_lock = threading.Lock()
        self.open_positions_lock = threading.Lock()
        self.live_vol_profile_lock = threading.Lock()
        self.live_data = { "ticker":None,
            "live_price": 0,    "candle_time_start": [], "candle_time_end" :[] , "open_prices":[],    "high_prices": [],    "low_prices": [],    "prices": [],    "live_time":[], 
            "live_candle" : [], "first_print_done": False, "volume":[], "delta_candle":[], "live_delta":0,
            "last_ltp": 0, "cvd":[], "live_volume": 0, "pv_sum" : 0, "total_volume" : 0, "vwap" :[], "current_vwap":0, "sq_pv_sum":0, "vwap_std": 0, "trade_exit_time":0,
            "volume_traded_previous_tick":0, "vwap_std_series" : [], "prv_poc": None, "prv_vah": None, "prv_val":None, "curr_poc": None, "curr_vah": None, "curr_val":None }
                    
        self.current_candle_ts = None
        self.open_positions_global = {}
        self.executed_trades_global = []
        self.live_vol_profile = {}
        self.bot_running = True

    def seed_data(self):
        """Replaces your Start Bot historical fetch"""
        to_date = datetime.datetime.now(ist).date()
        from_date = to_date - datetime.timedelta(days=5)
        data = {"symbol": self.ticker, "resolution": self.cfg['timeframe'], "date_format": "1", 
                "range_from": str(from_date), "range_to": str(to_date), "cont_flag": "1"}
        hist = self.fyers.history(data=data)
        if hist.get("s") == "ok":
            c = hist.get("candles", [])
            with self.live_data_lock:
                self.live_data["ticker"] = self.ticker
                self.live_data["prices"] = [x[4] for x in c][-375:]
                self.live_data["open_prices"] = [x[1] for x in c][-375:]
                self.live_data["high_prices"] = [x[2] for x in c][-375:]
                self.live_data["low_prices"] = [x[3] for x in c][-375:]
                self.live_data["volume"] = [x[5] for x in c][-375:]
                self.live_data["candle_time_start"] = [x[0] for x in c][-375:]
            print(f"{self.ticker}: Seeded {len(c)} candles.")
       
       ### generate previous day VPF 
        data_vpf = {"symbol": self.ticker, "resolution": "5S", "date_format": "1", 
                "range_from": str(from_date), "range_to": str(to_date), "cont_flag": "1"}
        historical_data_poc = self.fyers.history(data=data_vpf)
        if historical_data_poc.get("s") == "ok":
            candles_vpf = historical_data_poc.get("candles", []) 
            df_vpf = pd.DataFrame(candles_vpf, columns=["Time", "Open", "High", "Low", "Close", "volume"])
            df_vpf["Time"] = pd.to_datetime(df_vpf["Time"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
            today = datetime.datetime.now().date()#- datetime.timedelta(days=2)
            df_today = df_vpf.copy()
            df_vpf = df_vpf[df_vpf["Time"].dt.date < today]
            df_vpf["prices"] = df_vpf[["High", "Low", "Close"]].mean(axis = 1).round(2)
            df_vpf = df_vpf[["prices", "volume"]][-4500:]
            raw_bin = df_vpf["prices"].iloc[-1] * 0.0002
            if raw_bin >= 1:
                bin_size = float(round(raw_bin))
            else:
                bin_size = round(max(0.05, round(raw_bin / 0.1) * 0.1),1)

            prv_vpf = get_volume_profile_stats(df_vpf, bin_size=bin_size)
            with self.live_data_lock:
                self.live_data["prv_poc"] = prv_vpf["POC"]
                self.live_data["prv_vah"] =prv_vpf["VAH"]
                self.live_data["prv_val"] = prv_vpf["VAL"]
        
        ### generate today's day VPF 
            today = datetime.datetime.now().date()#- datetime.timedelta(days=2)
            df_today = df_today[df_today["Time"].dt.date == today]
            df_today["prices"] = df_today[["High", "Low", "Close"]].mean(axis = 1).round(2)
            df_today = df_today[["prices", "volume"]]
            if not df_today.empty:
                today_vpf = get_volume_profile_stats(df_today, bin_size=bin_size)
                with self.live_data_lock, self.live_vol_profile_lock:
                    self.live_data["curr_poc"] = today_vpf["POC"]
                    self.live_data["curr_vah"] =today_vpf["VAH"]
                    self.live_data["curr_val"] = today_vpf["VAL"]

                    for price, vol in zip(today_vpf["prices"], today_vpf["volume"]):
                        price_b = round(round(price / bin_size) * bin_size, 2)
                        self.live_vol_profile[price_b] = self.live_vol_profile.get(price_b, 0) + vol      
        else:
            print(f"{self.ticker}: History Fetch Failed! Error: {hist.get('message')}")

    def on_tick(self, msg):
        if not self.bot_running: return
        logging_time = str(datetime.datetime.now(tz=ist).replace(microsecond=0))
        
        try:
            if msg.get("type") in ("cn", "ful", "sub"):
                return

            with self.live_data_lock:
                live_price = msg.get("ltp")
                live_time = msg.get("exch_feed_time")
                self.logger.info(f"{msg}")
                if live_price is None or live_time is None: 
                    print("No live data feed from exchange at this time")
                    return

                # --- MARKET TIMING LOGIC (IST AUTO-ADJUST) ---
                live_time_cutoff = datetime.datetime.fromtimestamp(int(live_time), tz=pytz.utc).astimezone(ist)
                live_market = datetime.time(9,15,00) <= live_time_cutoff.time() <= datetime.time(15,29,59)
                trade_allowed = datetime.time(9,15,0) <= live_time_cutoff.time() <= datetime.time(15,5,0)
                live_market = True
                trade_allowed = True

                self.live_data["trade_allowed"] = trade_allowed
                self.live_data["live_price"] = live_price

                if not live_market:
                    self.logger.info(f"Current TIme -  {live_time_cutoff} Out of the Trading Window - 9:15:00 to 15:29:59")
                    return
                last_qty = msg.get("vol_traded_today") - self.live_data['volume_traded_previous_tick']
                self.live_data['volume_traded_previous_tick'] =  msg.get("vol_traded_today")

                ##---------------------Create Current Vol Profile--------------------------------------
                raw_bin = live_price * 0.0002
                if raw_bin >= 1:
                    bin_size = float(round(raw_bin))
                else:
                    bin_size = round(max(0.1, round(raw_bin / 0.1) * 0.1),1)

                BIN = bin_size
                price_b = round(round(live_price / BIN) * BIN, 1)
                self.live_vol_profile[price_b] = self.live_vol_profile.get(price_b, 0) + last_qty

                price_bin = self.live_vol_profile.keys()
                vol_sum = self.live_vol_profile.values()
                df_pf = pd.DataFrame({"prices":price_bin, "volume":vol_sum})
                vpf = get_volume_profile_live(df_pf)
                self.live_data["curr_poc"] = vpf["POC"]
                self.live_data["curr_vah"] = vpf["VAH"]
                self.live_data["curr_val"] = vpf["VAL"]
                ##---------------------Create Current Vol Profile-end-------------------------------------

                # --- CANDLE FORMATION LOGIC (EXACT COPY) ---
                tf_seconds = int(self.cfg['timeframe']) * 60
                this_candle_id = (live_time // tf_seconds) * tf_seconds
                if self.current_candle_ts is None: self.current_candle_ts = this_candle_id

                if this_candle_id != self.current_candle_ts and len(self.live_data["live_candle"]) > 0:
                    self.live_data["open_prices"].append(self.live_data["live_candle"][0])
                    self.live_data["high_prices"].append(max(self.live_data["live_candle"]))
                    self.live_data["low_prices"].append(min(self.live_data["live_candle"]))
                    self.live_data["prices"].append(self.live_data["live_candle"][-1])
                    self.live_data["candle_time_start"].append(self.current_candle_ts)
                    self.live_data["candle_time_end"].append(self.live_data["live_time"][-1])
                    self.live_data["volume"].append(self.live_data["live_volume"])
                    get_zone(live_data)
                    # Keep 375
                    if len(self.live_data["prices"]) > 375:
                        for key in ["open_prices", "high_prices", "low_prices", "prices", "volume", "candle_time_start","candle_time_end"]:
                            self.live_data[key] = self.live_data[key][-1500:]
                    self.current_candle_ts = this_candle_id
                    self.live_data["live_volume"] = 0
                    self.live_data["live_candle"].clear()
                    self.live_data["live_time"].clear()
                    
                    print_live = {k: v[-10:] if isinstance(v, list) else v for k, v in self.live_data.items()}
                    self.logger.info(f"{print_live}")

                self.live_data["live_candle"].append(live_price)
                self.live_data["live_time"].append(live_time)
                self.live_data["live_volume"] += last_qty
                self.logger.info(f"Open Positions: {self.open_positions_global}")
                self.logger.info(f"Executed Traded: {self.executed_trades_global}")


            # --- EXIT LOGIC ---
            with self.open_positions_lock, self.executed_trades_lock:
                for trade_symbol, trade_info in list(self.open_positions_global.items()):
                    if check_stop(self.live_data, trade_info,  self.cfg, self.executed_trades_global):
                        place_order(self.fyers, trade_symbol, trade_info["qty"], 
                                    "sell" if trade_info["side"]=="buy" else "buy", "market")
                        del self.open_positions_global[trade_symbol]
                        self.live_data['trade_exit_time'] = live_time
                        self.logger.info(f"{logging_time} | {self.ticker} | EXIT TRIGGERED")

            # --- ENTRY LOGIC ---
            with self.executed_trades_lock, self.open_positions_lock:
                signal_dict = detect_signal(self.live_data, self.executed_trades_global, self.cfg)
                self.logger.info(f"Signal_Dic : {signal_dict}")
                signal = signal_dict["side"] if signal_dict is not None else None

                if signal and len(self.executed_trades_global) < self.cfg['max_trades'] and not self.open_positions_global:
                    
                    # --- SYMBOL CONSTRUCTION (EXACT COPY) ---
                    sell_or_buy = self.side
                    ticker_local = self.ticker
                    
                    if ticker_local == "NSE:NIFTY50-INDEX": ticker_local = "NSE:NIFTY-INDEX"
                    if ticker_local == "NSE:NIFTYBANK-INDEX": ticker_local = "NSE:BANKNIFTY-INDEX"

                    if self.cfg['trade_type'] == "Options":
                        strike_price = round(live_price) - (round(live_price) % self.cfg['option_step'])
                        if signal == "sell" : 
                            option_type = "Put"
                        else : option_type = "Call"
                        
                        if option_type == "Put":
                            strike_price = round(live_price) + (self.cfg['option_step'] - (round(live_price) % self.cfg['option_step']))
                        
                        expiry = datetime.datetime.strptime(self.cfg['expiry_str'], "%Y-%m-%d")
                        base_ticker = ticker_local.split(":")[1].split("-")[0]
                        if self.cfg['expiry_type'] == "Monthly":
                            symbol_to_trade = f"NSE:{base_ticker}{expiry.strftime('%y%b').upper()}{strike_price}{option_type[0].upper()}E"
                        else:
                            year_2digit = expiry.strftime("%y")
                            month_str = str(expiry.month)
                            date_2digit = expiry.strftime("%d")
                            expiry1 = year_2digit+month_str+date_2digit
                            symbol_to_trade = f"NSE:{base_ticker}{expiry1.upper()}{strike_price}{option_type[0].upper()}E"
                    else:
                        symbol_to_trade = ticker_local
                        sell_or_buy = signal

                    # --- EXECUTION ---
                    self.logger.info(f"symbol_to_trade - {symbol_to_trade} | sell_or_buy - {sell_or_buy} | Signal - {signal}")
                    response = place_order(self.fyers, symbol_to_trade, self.cfg['quantity'], sell_or_buy, "market")
                    if response.get("s") == "ok":
                        order_book = self.fyers.orderbook({"id": response["id"]})
                        fill_price = order_book["orderBook"][0]["tradedPrice"] if order_book.get("s")=="ok" else live_price
                        
                        trade = {
                            "ticker": symbol_to_trade, 
                            "buying_price": live_price,
                            "executed_price": fill_price,
                            "executed": "Yes",
                            "sl_hit": "No",
                            "exit_type" : None,
                            "pnl": None,
                        }
                        self.executed_trades_global.append(trade)
                        
                        self.open_positions_global[symbol_to_trade] = {
                            "qty": self.cfg['quantity'], 
                            "side": sell_or_buy,
                            "signal_type": signal,
                            "executed_price":fill_price,
                            "spot_price": signal_dict["entry"],
                            "entry_price" : signal_dict["entry"],
                            "stop_price" : signal_dict["sl"],
                            "target_price" : signal_dict["target"],
                            "entry_time" : live_time,
                            "strategy" : signal_dict["strategy"],
                            "regime" : signal_dict["regime"],
                            "score" : signal_dict["score"],
                            "partial_done" : False, 
                            "journey": signal_dict["journey"],                 
                        }

                        self.logger.info(f"{logging_time} | {self.ticker} | ENTRY SUCCESS: {symbol_to_trade} at {fill_price}")

        except Exception as e:
            self.logger.info(f"Error in {self.ticker}: {e}")

# --- GLOBAL RUNNER ---
# MAINTAIN SESSION
fyers_client, access_token = get_valid_fyers_client()

bot_map = {s['ticker']: VolProfBotInstance(s, fyers_client) for s in STRATEGIES}

for bot in bot_map.values(): bot.seed_data()

def on_message(msg):
    symbol = msg.get('symbol')
    if symbol in bot_map: bot_map[symbol].on_tick(msg)

# WebSocket Setup
access_token_for_ws = f"{user_config.CLIENT_ID}:{access_token}"
threading.Thread(
                target=subscribe_to_live_data,
                args=(access_token_for_ws, [s['ticker'] for s in STRATEGIES], on_message),
                daemon=True,
            ).start() 
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[!] Shutdown signal received. Closing Bot...")
    for bot in bot_map.values():
        bot.bot_running = False