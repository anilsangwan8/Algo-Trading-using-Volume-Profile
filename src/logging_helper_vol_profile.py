import logging
import os
import sys
import datetime

# --def logging_helper(ticker):
def logging_helper(ticker):
    BASE_DIR = os.path.dirname(__file__)
    LOG_DIR = os.path.join(BASE_DIR, "app_kama_logs")
    os.makedirs(LOG_DIR, exist_ok=True) 

    today_str = datetime.datetime.now().strftime("%Y-%m-%d") 
    # Clean ticker name for filename
    safe_ticker = ticker.replace(":", "_").replace("-", "_")
    LOG_FILE = os.path.join(LOG_DIR, f"Log_{safe_ticker}_{today_str}.log")

    # Create a unique logger for this ticker name
    logger = logging.getLogger(ticker) 
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers if script reruns
    if not logger.handlers:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        stream_handler = logging.StreamHandler(sys.__stdout__)
        
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        stream_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)

    return logger