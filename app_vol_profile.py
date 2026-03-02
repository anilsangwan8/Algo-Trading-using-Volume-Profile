from src.logging_helper_vol_profile import logging_helper
import streamlit as st
import pandas as pd
from fyers_apiv3 import fyersModel
from src.fyers_client_vol_profile import get_access_token, subscribe_to_live_data, place_order
from src.trading_logic_vol_profile import  check_stop, detect_signal, get_volume_profile_stats, get_volume_profile_live, para, get_zone
import threading
import datetime
import pytz
ist=pytz.timezone('Asia/Kolkata')
logger = logging_helper()

# ================= MODULE-LEVEL GLOBALS FOR LIVE DATA =================

live_data_lock = threading.Lock()
live_data = {
    "live_price": 0,    "candle_time_start": [], "candle_time_end" :[] , "open_prices":[],    "high_prices": [],    "low_prices": [],    "prices": [],    "live_time":[], 
    "live_candle" : [], "first_print_done": False, "volume":[], "delta_candle":[], "live_delta":0,
     "last_ltp": 0, "cvd":[], "live_volume": 0, "pv_sum" : 0, "total_volume" : 0, "vwap" :[], "current_vwap":0, "sq_pv_sum":0, "vwap_std": 0, "trade_exit_time":0,
     "volume_traded_previous_tick":0, "vwap_std_series" : [], "prv_poc": None, "prv_vah": None, "prv_val":None, "curr_poc": None, "curr_vah": None, "curr_val":None }

current_candle_ts = None

# Global open positions and trades for use in WS thread
open_positions_lock = threading.Lock()
open_positions_global = {}

executed_trades_lock = threading.Lock()
executed_trades_global = []

live_vol_profile_lock = threading.Lock()
live_vol_profile = {}

# Global fyers client for WS thread
fyers_client = None
bot_running = False

# --------------- BASIC SETUP ---------------
st.set_page_config("Volume Profile Trading Bot", layout="wide")
st.subheader("Volume Profile Trading Bot")


# --------------- SESSION STATE INIT ---------------
if 'client_id' not in st.session_state:
    st.session_state.client_id = "F436AH37O2-100"
if 'secret_key' not in st.session_state:
    st.session_state.secret_key = "9F241B61PS"
if 'redirect_uri' not in st.session_state:
    st.session_state.redirect_uri = "https://trade.fyers.in/api-login/redirect-uri/index.html"
if 'access_token' not in st.session_state:
    st.session_state.access_token = None
if 'fyers' not in st.session_state:
    st.session_state.fyers = None

if 'executed_trades' not in st.session_state:
    st.session_state.executed_trades = []
if 'open_positions' not in st.session_state:
    st.session_state.open_positions = {}

if 'ws_started' not in st.session_state:
    st.session_state.ws_started = False

# sync session_state views from globals for display
with open_positions_lock:
    st.session_state.open_positions = dict(open_positions_global)
with executed_trades_lock:
    st.session_state.executed_trades = list(executed_trades_global)


# --------------- AUTH SECTION ---------------
if st.session_state.access_token is None:
    st.subheader("Authentication")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.session_state.client_id = st.text_input("Client ID", st.session_state.client_id)
    with col2:
        st.session_state.secret_key = st.text_input("Secret Key", st.session_state.secret_key, type="password")
    with col3:
        st.session_state.redirect_uri = st.text_input("Redirect URI", st.session_state.redirect_uri)

    session = fyersModel.SessionModel(
        client_id=st.session_state.client_id,
        secret_key=st.session_state.secret_key,
        redirect_uri=st.session_state.redirect_uri,
        response_type="code",
        grant_type="authorization_code"
    )
    auth_code_url = session.generate_authcode()
    with col4:
        st.markdown(
            f"<a href='{auth_code_url}' target='_blank'>Click here to generate auth code</a>",
            unsafe_allow_html=True
        )

    auth_code = st.text_input("Auth Code")

    if st.button("Generate Access Token"):
        if all([st.session_state.client_id, st.session_state.secret_key, st.session_state.redirect_uri, auth_code]):
            try:
                st.session_state.access_token = get_access_token(
                    st.session_state.client_id,
                    st.session_state.secret_key,
                    st.session_state.redirect_uri,
                    auth_code
                )
                st.rerun()
            except Exception as e:
                st.error(f"Failed to generate access token: {e}")
        else:
            st.error("Please fill in all the fields.")


# --------------- MAIN APP ---------------
else:

    if st.session_state.fyers is None:
        st.session_state.fyers = fyersModel.FyersModel(
            client_id=st.session_state.client_id,
            token=st.session_state.access_token,
            log_path=""
        )
    # expose fyers client to WS thread

    fyers_client = st.session_state.fyers

    #st.success("Successfully authenticated!")
   
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        ticker = st.text_input("Ticker", "NSE:TMPV-EQ")
        if ticker.lower().split(":",1)[1].split("-",1)[0] in "NIFTY50BANKNIFTYFINNIFTY".lower():
            trade_type = st.selectbox("Trade Type", ["Options", "Equity"])
        else : trade_type = st.selectbox("Trade Type", ["Equity", "Options"])
        expiry_str = st.text_input(
            "Expiry (YYYY-MM-DD)",
            datetime.date.today().strftime("%Y-%m-%d"))

    with col2:
        volum_multiplier = st.number_input("Volume Multiple", value= 1.08)
        if ticker.lower().split(":",1)[1].split("-",1)[0] in "NIFTY50BANKNIFTYFINNIFTY".lower():
            option_step = st.number_input("Strike Price Increments", value= 100)
        else : option_step = st.number_input("Strike Price Increments", value= 10)
        max_trades = st.number_input("Max Trades", value=10)        
        
    with col3:
        risk_reward = st.number_input("Ris to Reward", value= 2.5)
        if ticker.lower().split(":",1)[1].split("-",1)[0] in "NIFTY50BANKNIFTYFINNIFTY".lower():
            expiry_type = st.selectbox("Expiry Type", ["Weekly", "Monthly"])
        else: expiry_type = st.selectbox("Expiry Type", ["Monthly", "Weekly"])
        side = st.selectbox("Side for Options Only", ["buy"])

    with col4:
        no_tarde_zone_multi = st.number_input("No Trade Zone Multiplier", value= 0.2)
        cooldown_minutes = st.number_input("Minutes Gap Btwn SL and New Entry", value=2)
        quantity = st.number_input("Quantity", value=1)
        
    with col5:
        exit_trade_time = st.number_input("Exit Trade After Minutes",value= 23)
        timeframe_options = {
            "1 minute": "1",
            "3 minute": "2",
            "3 minute": "3",
            "5 minutes": "5",
            "10 minutes": "10",
            "15 minutes": "15",
            "30 minutes": "30",
            "45 minutes": "45"
        }
        timeframe_display = st.selectbox("Timeframe", list(timeframe_options.keys()))
        timeframe = timeframe_options[timeframe_display]
        cvd_shift_input  = st.number_input("CVD Shift",value= 2)
        

        
    # --------------- WEBSOCKET CALLBACK USING ONLY GLOBALS ---------------
    def on_message(msg: dict):
        global current_candle_ts
        logging_time = str(datetime.datetime.now(tz=ist).replace(microsecond=0))
        global bot_running
        if not bot_running: 
            return
        
        """
        Runs in WebSocket thread. Uses only module-level globals; no st.session_state
        mutation inside the thread.
        """
        try:
            # ignore control messages (cn, ful, sub etc.)
            if msg.get("type") in ("cn", "ful", "sub"):
                return

# ============================================================================================================================================================
            with live_data_lock, live_vol_profile_lock:
                if not live_data["first_print_done"]:
                    #print("WS first message in app.py:", msg)
                    live_data["first_print_done"] = True
                live_price = msg.get("ltp")
                live_time = msg.get("exch_feed_time")
                print(msg)
                
                if live_price is None or live_time is None:
                    print("No live data feed from exchange at this time")
                    return

                live_time_cutoff = datetime.datetime.fromtimestamp(int(live_time))

                live_market = datetime.time(9,15,00) <= live_time_cutoff.time() <= datetime.time(15,29,59)
                trade_allowed = datetime.time(9,20) <= live_time_cutoff.time() <= datetime.time(15,5)
                '''live_market = True
                trade_allowed = True'''

                if trade_allowed:
                    live_data["trade_allowed"] = True

                if not live_market:
                    print("Current TIme - ", live_time_cutoff, "Out of the Trading Window - 9:15:00 to 15:29:59")
                    return

                last_qty = msg.get("vol_traded_today") - live_data['volume_traded_previous_tick']
                live_data['volume_traded_previous_tick'] =  msg.get("vol_traded_today")
                ##---------------------Create Current Vol Profile--------------------------------------
                raw_bin = live_price * 0.0002
                if raw_bin >= 1:
                    # If >= 1, round to the nearest whole number (e.g., 4.4 -> 4.0)
                    bin_size = float(round(raw_bin))
                else:
                    # If < 1, round to the nearest 0.05 (e.g., 0.12 -> 0.10)
                    bin_size = round(max(0.1, round(raw_bin / 0.1) * 0.1),1)

                BIN = bin_size
                price_b = round(round(live_price / BIN) * BIN, 1)
                live_vol_profile[price_b] = live_vol_profile.get(price_b, 0) + last_qty

                price_bin = live_vol_profile.keys()
                vol_sum = live_vol_profile.values()
                df_pf = pd.DataFrame({"prices":price_bin, "volume":vol_sum})
                vpf = get_volume_profile_live(df_pf)
                live_data["curr_poc"] = vpf["POC"]
                live_data["curr_vah"] = vpf["VAH"]
                live_data["curr_val"] = vpf["VAL"]

                ##---------------------Create Current Vol Profile---End--------------------------------------

                #last_qty = msg.get('last_traded_qty')
                bid_price = msg.get('bid_price')
                ask_price = msg.get('ask_price')
                delta = 0
                
                if ask_price is None or bid_price is None:
                    ask_price = 0
                    bid_price = 0
                if (live_price >= ask_price and ask_price != 0) or live_price > live_data['last_ltp']:
                    delta = last_qty
                elif (live_price <= bid_price and bid_price !=0) or live_price < live_data['last_ltp']:
                    delta = -last_qty

                #---------VWAP Band------------------------------------------------------------------------
            # 2. UPDATE RUNNING TOTALS (EVERY TICK) - PLACE IT HERE
                running_pv_sum = live_data["pv_sum"]+(live_price * last_qty)
                running_sq_pv_sum = live_data["sq_pv_sum"] + (live_price**2 * last_qty)
                running_total_volume = live_data["total_volume"] + last_qty
                live_data["sq_pv_sum"] = running_sq_pv_sum

                # 3. CALCULATE BANDS (EVERY TICK)
                if running_total_volume > 0:
                    current_vwap = running_pv_sum / running_total_volume
                    mean_sq = running_sq_pv_sum / running_total_volume
                    variance = max(0, mean_sq - (current_vwap**2))
                    vwap_std = variance**0.5
                else:
                    current_vwap = live_price
                    vwap_std = 0

                live_data["current_vwap"] = current_vwap
                live_data["vwap_std"] = vwap_std

                #---------VWAP Band logic end--------------------------------------------------------------

                minutes_tf = int(timeframe)
                live_data["live_price"] = live_price

                tf_seconds = minutes_tf * 60
                this_candle_id = (live_time // tf_seconds) * tf_seconds

                # initialise first candle
                if current_candle_ts is None:
                    current_candle_ts = this_candle_id

                # if candle id changed => close previous candle and start a new one
                if this_candle_id != current_candle_ts and len(live_data["live_candle"]) > 0:
                    open_price = live_data["live_candle"][0]
                    high_price = max(live_data["live_candle"])
                    low_price = min(live_data["live_candle"])
                    close_price = live_data["live_candle"][-1]


                    live_data["open_prices"].append(open_price)
                    live_data["high_prices"].append(high_price)
                    live_data["low_prices"].append(low_price)
                    live_data["prices"].append(close_price)
                    live_data["candle_time_start"].append(current_candle_ts)
                    live_data["candle_time_end"].append(live_data["live_time"][-1])
                    live_data["delta_candle"].append(live_data["live_delta"])
                    if len(live_data["cvd"]) > 0 :
                        live_data["cvd"].append(live_data["cvd"][-1]+live_data["live_delta"])
                    else : live_data["cvd"].append(live_data["live_delta"])
                    live_data["volume"].append(live_data["live_volume"])
                    if live_data["total_volume"] != 0 :
                        live_data["vwap"].append(live_data["pv_sum"] / live_data["total_volume"])
                    #live_data["vwap_std_series"].append(vwap_std)
                    #==append jpurney history
                    get_zone(live_data)

                    print(f"{logging_time} | CLOSED Candle: {datetime.datetime.fromtimestamp(this_candle_id)}","\n", live_data)

                    # keep last 375 candles
                    if len(live_data["prices"]) > 375:
                        for key in ["open_prices", "high_prices", "low_prices",
                                    "prices", "candle_time_start", "candle_time_end","delta_candle", "cvd", "volume", "vwap" ]:
                            live_data[key] = live_data[key][-375:]

                    # start new candle
                    current_candle_ts = this_candle_id
                    live_data["live_volume"] = 0
                    live_data["live_delta"]  = 0
                    live_data["live_candle"].clear()
                    live_data["live_time"].clear()

                # update current (forming) candle with this tick
                live_data["live_candle"].append(live_price)
                live_data["live_time"].append(live_time)
                live_data["live_volume"] += last_qty
                live_data["live_delta"]  += delta
                live_data["last_ltp"] = live_price
                live_data["pv_sum"] += live_price * last_qty
                live_data["total_volume"] += last_qty
                live_data["current_vwap"] = live_data["pv_sum"] / live_data["total_volume"] if live_data["total_volume"] > 0 else live_price
                print(f"{logging_time} | open positions - {open_positions_global}")
                print(f"{logging_time} | executed trades - {executed_trades_global}")
            
#============================================================================================================================================================================
# ---------- trading logic preserved, but uses globals ----------
            # Stop-loss on open positions 
            with open_positions_lock:
   
                for trade_symbol, trade_info in list(open_positions_global.items()): 
                    if  check_stop(live_data, trade_info, para, executed_trades_global):
                        place_order(
                            fyers_client,
                            trade_symbol,
                            trade_info["qty"],
                            "sell" if trade_info["side"] == "buy" else "buy",
                            "market"
                        )
                        
                        del open_positions_global[trade_symbol]
                        live_data['trade_exit_time'] = live_time
            

            # Entry logic
            with executed_trades_lock, open_positions_lock:
                signal = None
                signal_dict = detect_signal(live_data, open_positions_global, executed_trades_global, para)
                print(logging_time, ":Signal_Dic ", signal_dict)

                if len(executed_trades_global) < max_trades and len(list(open_positions_global.items())) == 0:
                    signal = signal_dict["side"] if signal_dict is not None else None

                if signal:
                        sell_or_buy = side
                        ticker_local = ticker
                        if ticker_local == "NSE:NIFTY50-INDEX":
                            ticker_local = "NSE:NIFTY-INDEX"
                        if ticker_local == "NSE:NIFTYBANK-INDEX":
                            ticker_local = "NSE:BANKNIFTY-INDEX"
                        if trade_type == "Options" and expiry_type == "Monthly":
                            strike_price = round(live_data["live_price"]) - (round(live_data["live_price"]) % option_step)
                            if signal == "sell" : 
                                option_type = "Put"
                            else : option_type = "Call"
                            if option_type == "Put":
                                strike_price = round(live_data["live_price"]) + (option_step - (round(live_data["live_price"]) % option_step))
                                
                            expiry = datetime.datetime.strptime(expiry_str, "%Y-%m-%d")
                            base_ticker = ticker_local.split(":")[1].split("-")[0]
                            symbol_to_trade = (
                                f"NSE:{base_ticker}{expiry.strftime('%y%b').upper()}"
                                f"{strike_price}{option_type[0].upper()}E"
                            )
                     
                    
                        elif trade_type == "Options" and expiry_type == "Weekly":
                            strike_price = round(live_data["live_price"]) - (round(live_data["live_price"]) % option_step)
                            if signal == "sell" : 
                                option_type = "Put"
                            else : option_type = "Call"
                            if option_type == "Put":
                                strike_price = round(live_data["live_price"]) + (option_step - (round(live_data["live_price"]) % option_step))
                                
                            expiry = datetime.datetime.strptime(expiry_str, "%Y-%m-%d")
                            month_str = str(expiry.month)  # "1" not "01"
                            year_2digit = expiry.strftime("%y")  # "26"
                            date_2digit = expiry.strftime("%d")
                            expiry1 = year_2digit+month_str+date_2digit
                            base_ticker = ticker_local.split(":")[1].split("-")[0]
                            symbol_to_trade = (
                                f"NSE:{base_ticker}{expiry1.upper()}"
                                f"{strike_price}{option_type[0].upper()}E"
                            )
                        
                        else:
                            symbol_to_trade = ticker_local
                            sell_or_buy = signal

                        print(logging_time,"symbol_to_trade -", symbol_to_trade, "| sell_or_buy -",sell_or_buy, "| Signal (side) -", signal )
                           
                        response = place_order(
                            fyers_client,
                            symbol_to_trade,
                            quantity,
                            sell_or_buy,
                            "market"
                        )


                        if response.get("s") == "ok":
                            order_id = response["id"]
                            order_book = fyers_client.orderbook({"id": order_id})
                            print(logging_time, "order book", order_book)
                            fill_price = (
                                order_book["orderBook"][0]["tradedPrice"]
                                if order_book.get("s") == "ok"
                                else live_data["live_price"]
                            )


                            trade = {
                                "ticker": symbol_to_trade,
                                "buying_price": live_data["live_price"],
                                "executed_price": fill_price,
                                "executed": "yes",
                                "sl_hit" : "no",
                                "pnl":None,
                            }
                            executed_trades_global.append(trade)

                            open_positions_global[symbol_to_trade] = {
                                "qty": quantity,
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
                        else:
                            print(f"Order placement failed: {response}")
            print("."*150,"\n")

        except Exception as e:
            print("on_message error:", e)


    # --------------- HISTORICAL DATA ---------------
    def fetch_data(_fyers, _ticker, _timeframe):
        to_date = datetime.datetime.now().date()
        from_date = to_date - datetime.timedelta(days=5)

        data = {
            "symbol": _ticker,
            "resolution": _timeframe,
            "date_format": "1",
            "range_from": str(from_date),
            "range_to": str(to_date),
            "cont_flag": "1"
        }
        return _fyers.history(data=data)


    # --------------- START BOT BUTTON ---------------
    col1,col2, col3, col4, col5 = st.columns(5)
    with col1:
        if st.button("🟢 Start Bot") and not st.session_state.ws_started:
            st.session_state.ws_started = True
            bot_running = True
            st.write("Bot started...")

            # seed close prices so MA has history
            historical_data = fetch_data(fyers_client, ticker, timeframe)
            if historical_data.get("s") == "ok":
                candles = historical_data.get("candles", [])
                close_prices = [c[4] for c in candles]
                open_prices = [c[1] for c in candles]
                high_prices = [c[2] for c in candles]
                low_prices = [c[3] for c in candles]
                volume_pp = [c[5] for c in candles]
                candle_time_start = [c[0] for c in candles]
                            
            # close_prices = [val for val in close_prices1 for _ in range(5)]
                with live_data_lock:
                    live_data["prices"] = close_prices[-375:]
                    live_data["open_prices"] = open_prices[-375:]
                    live_data["high_prices"] = high_prices[-375:]
                    live_data["low_prices"] = low_prices[-375:]
                    live_data["volume"] = volume_pp[-375:]
                    live_data["candle_time_start"] = candle_time_start[-375:]
            ####previous day Volume profile----------------------------------------------------------------------------------
            historical_data_poc = fetch_data(fyers_client, ticker, "5S")
            if historical_data_poc.get("s") == "ok":
                candles_vpf = historical_data_poc.get("candles", [])
                df_vpf = pd.DataFrame(candles_vpf, columns=["Time", "Open", "High", "Low", "Close", "volume"])
                df_vpf["Time"] = pd.to_datetime(df_vpf["Time"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
                today = datetime.datetime.now().date()#- datetime.timedelta(days=2)
                df_vpf = df_vpf[df_vpf["Time"].dt.date < today]
                df_vpf["prices"] = df_vpf[["High", "Low", "Close"]].mean(axis = 1).round(2)
                df_vpf = df_vpf[["prices", "volume"]][-4500:]
                raw_bin = df_vpf["prices"].iloc[-1] * 0.0002
                if raw_bin >= 1:
                    bin_size = float(round(raw_bin))
                else:
                    bin_size = round(max(0.05, round(raw_bin / 0.05) * 0.05),2)

                prv_vpf = get_volume_profile_stats(df_vpf, bin_size=bin_size)

            # close_prices = [val for val in close_prices1 for _ in range(5)]
                with live_data_lock:
                    live_data["prv_poc"] = prv_vpf["POC"]
                    live_data["prv_vah"] =prv_vpf["VAH"]
                    live_data["prv_val"] = prv_vpf["VAL"]

            ####today day Volume profile----------------------------------------------------------------------------------
            historical_data_poc = fetch_data(fyers_client, ticker, "5S")
            if historical_data_poc.get("s") == "ok":
                candles_vpf = historical_data_poc.get("candles", [])
                df_vpf = pd.DataFrame(candles_vpf, columns=["Time", "Open", "High", "Low", "Close", "volume"])
                df_vpf["Time"] = pd.to_datetime(df_vpf["Time"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
                today = datetime.datetime.now().date()
                df_vpf = df_vpf[df_vpf["Time"].dt.date == today]
                df_vpf["prices"] = df_vpf[["High", "Low", "Close"]].mean(axis = 1).round(2)
                df_vpf = df_vpf[["prices", "volume"]]
                if not df_vpf.empty:
                    prv_vpf = get_volume_profile_stats(df_vpf, bin_size=bin_size)
                    with live_data_lock, live_vol_profile_lock:
                        live_data["curr_poc"] = prv_vpf["POC"]
                        live_data["curr_vah"] =prv_vpf["VAH"]
                        live_data["curr_val"] = prv_vpf["VAL"]

                        for price, vol in zip(df_vpf["prices"], df_vpf["volume"]):
                            price_b = round(round(price / bin_size) * bin_size, 2)
                            live_vol_profile[price_b] = live_vol_profile.get(price_b, 0) + vol         


            else:
                st.error(f"Failed to fetch historical data: {historical_data.get('message', 'Unknown error')}") 
            # subscribe via existing helper in a background thread
            #current_candle_ts = live_data["candle_time_start"][-1]
            access_token_for_ws = f"{st.session_state.client_id}:{st.session_state.access_token}"
            threading.Thread(
                target=subscribe_to_live_data,
                args=(access_token_for_ws, [ticker], on_message),
                daemon=True,
            ).start()
  
    with col5:
        if st.button("🔴 Stop Bot") and st.session_state.ws_started:
            bot_running = False
            st.session_state.ws_started = False
            st.success("✅ Bot stopped safely")

