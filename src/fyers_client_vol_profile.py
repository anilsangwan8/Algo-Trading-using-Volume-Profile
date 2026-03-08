from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws

def get_access_token(client_id, secret_key, redirect_uri, auth_code):
    session = fyersModel.SessionModel(
        client_id=client_id,
        secret_key=secret_key,
        redirect_uri=redirect_uri,
        response_type="code",
        grant_type="authorization_code"
    )
    session.set_token(auth_code)
    response = session.generate_token()
    return response.get("access_token")

def get_historical_data(fyers, symbol, resolution, date_format=0, range_from=None, range_to=None, cont_flag="1"):
    data = {
        "symbol": symbol,
        "resolution": resolution,
        "date_format": date_format,
        "range_from": range_from,
        "range_to": range_to,
        "cont_flag": cont_flag
    }
    return fyers.history(data=data)

# src/fyers_client.py
from fyers_apiv3.FyersWebsocket import data_ws

def subscribe_to_live_data(access_token, symbols, on_message):
    """
    access_token: 'APP_ID:ACCESS_TOKEN'
    symbols: ['NSE:SBIN-EQ']
    on_message: function(message: dict) -> None
    """
    def on_open():
        print("WebSocket connected")
        # SymbolUpdate gives full tick including ltp, volume etc. [web:12][web:39]
        fyers_ws.subscribe(symbols=symbols, data_type="SymbolUpdate")
        fyers_ws.keep_running()

    def on_close(msg):
        print(f"Connection closed: {msg}")

    def on_error(msg):
        print(f"Error: {msg}")

    fyers_ws = data_ws.FyersDataSocket(
        access_token=access_token,
        log_path="",
        litemode=False,          # keep False since you use full SymbolUpdate [web:13]
        write_to_file=False,
        reconnect=True,
        on_connect=on_open,
        on_close=on_close,
        on_error=on_error,
        on_message=on_message,   # MUST be def on_message(message)
    )
    fyers_ws.connect()


def place_order(fyers, symbol, qty, side, order_type, limit_price=0, stop_price=0, validity="DAY", disclosed_qty=0, offline_order=False, stop_loss=0, take_profit=0, order_Tag = "Trend"):
    data = {
        "symbol": symbol,
        "qty": qty,
        "type": 2 if order_type == "market" else 1,  # 2 for market order, 1 for limit order
        "side": 1 if side == "buy" else -1,  # 1 for buy, -1 for sell
        "productType": "INTRADAY",
        "limitPrice": limit_price,
        "stopPrice": stop_price,
        "validity": validity,
        "disclosedQty": disclosed_qty,
        "offlineOrder": offline_order,
        "stopLoss": stop_loss,
        "takeProfit": take_profit,
        "orderTag": order_Tag
    }
    return fyers.place_order(data=data)
