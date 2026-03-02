import logging
import os
import sys
import datetime

# -------- LOGGING SETUP --------------------------------------------------
def logging_helper():
    BASE_DIR = os.path.dirname(__file__)
    LOG_DIR = os.path.join(BASE_DIR, "app_vol_profile_logs")
    os.makedirs(LOG_DIR, exist_ok=True) 

    today_str = datetime.datetime.now().strftime("%Y-%m-%d") 
    LOG_FILE = os.path.join(LOG_DIR, f"vol_profile_logs_{today_str}.log")

    for h in logging.root.handlers[:]:
        logging.root.removeHandler(h)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(threadName)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.__stdout__),  # logger -> terminal
        ],
    )
    logger = logging.getLogger(__name__)

    log_file_stream = open(LOG_FILE, "a", buffering=1)
    class TeeStdout:
        def write(self, data):
            sys.__stdout__.write(data)   # terminal
            log_file_stream.write(data)  # file
        def flush(self):
            sys.__stdout__.flush()
            log_file_stream.flush()

    class TeeStderr:
        def write(self, data):
            sys.__stderr__.write(data)
            log_file_stream.write(data)
        def flush(self):
            sys.__stderr__.flush()
            log_file_stream.flush()

    sys.stdout = TeeStdout()
    sys.stderr = TeeStderr()
    return logging.getLogger(__name__)
# -------- END LOGGING SETUP ----------------------------------------------




