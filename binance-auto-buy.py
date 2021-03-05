import time
import json
import requests
import hmac
import hashlib
from getpass import getpass


g_binance_api_base_url = "https://api.binance.com/api/v3"


def get_binance_endpoint_json(endpoint, payload={}, headers={}):
    full_endpoint_url = g_binance_api_base_url + endpoint
    result = requests.get(full_endpoint_url, params=payload, headers=headers)
    if result.status_code != 200:
        print(f"Probably something went wrong: binance endpoint {full_endpoint_url} returned status code {result.status_code}") 
        print(result.text)
    return result.json()


def post_binance_endpoint_json(endpoint, body_data, headers):
    full_endpoint_url = g_binance_api_base_url + endpoint
    result = requests.post(full_endpoint_url, data=body_data, headers=headers)
    return result.json()


def get_available_tickers():
    tickers = []
    exchange_info_json = get_binance_endpoint_json("/exchangeInfo")
    for symbol in exchange_info_json["symbols"]:
        tickers.append(symbol["symbol"])
    return sorted(tickers)


def get_exchange_info_json():
    full_endpoint_url = g_binance_api_base_url + "/exchangeInfo"
    result = requests.get(full_endpoint_url)
    return result.json()


def get_max_amount_symbol(symbol_to_check):
    exchange_info_json = get_exchange_info_json()
    for symbol in exchange_info_json["symbols"]:
        if symbol["symbol"] == symbol_to_check:
            for filter_ in symbol["filters"]:
                if filter_["filterType"] == "LOT_SIZE":
                    return float(filter_["maxQty"])


def get_min_amount_symbol(symbol_to_check):
    exchange_info_json = get_exchange_info_json()
    for symbol in exchange_info_json["symbols"]:
        if symbol["symbol"] == symbol_to_check:
            for filter_ in symbol["filters"]:
                if filter_["filterType"] == "LOT_SIZE":
                    return float(filter_["minQty"])


def get_amount_step_size(symbol_to_check):
    exchange_info_json = get_exchange_info_json()
    for symbol in exchange_info_json["symbols"]:
        if symbol["symbol"] == symbol_to_check:
            for filter_ in symbol["filters"]:
                if filter_["filterType"] == "LOT_SIZE":
                    return float(filter_["stepSize"])


def exit_on_ticker_setup_issue(tickers_setup, tickers_available):
    error_message = ""
    for ticker in tickers_setup:
        # Set variables for cleanliness:
        symbol = ticker["symbol"]
        buy_or_sell = ticker["buy_or_sell"]
        transaction_amount = ticker["transaction_amount"]
        time_interval_seconds = ticker["time_interval_seconds"]
        last_purchase_time = ticker["last_purchase_time"]
        min_purchase = get_min_amount_symbol(symbol)
        max_purchase = get_max_amount_symbol(symbol)

        # Check that the ticker is available on Binance:
        if type(symbol) != str:
            error_message += f"Error on ticker {symbol}. Ticker symbol should be a string.\n"
        if symbol not in tickers_available:
            error_message += f"Error on ticker {symbol}. Ticker symbol {symbol} is not available on binance.\n"
        # Check that either "BUY" or "SELL" is set:
        if buy_or_sell not in ("BUY", "SELL"):
            error_message += f"Error on ticker {symbol}. Transaction type {buy_or_sell} is not allowed. Please set to 'BUY' or 'SELL'.\n"
        # Check that transaction_amount is positive (if it's not text):
        if type(transaction_amount) == int:
            if transaction_amount < 0:
                error_message += f"Error on ticker {symbol}. Purchase amount cannot be negative.\n"
        # Check that, if the transaction_amount is of type string, that it's equal to 'MAX'
        elif type(transaction_amount) == str:
            if transaction_amount != "MAX":
                error_message += f"Error on ticker {symbol}. Only allowed string value is 'MAX'.\n"
        elif type(transaction_amount) != int and type(transaction_amount) != str:
            error_message += f"Error on ticker {symbol}. Value for `buy_or_sell` should be an integer or 'MAX'.\n"
        # Other checks:
        if type(time_interval_seconds) != int:
            error_message += f"Error on ticker {symbol}. Time interval must be an integer value.\n"
        elif time_interval_seconds < 0:
            error_message += f"Error on ticker {symbol}. Time interval must have a positive value.\n"
        if type(last_purchase_time) != float:
            error_message += f"Error on ticker {symbol}. Last purchase time must be a number (epoch time).\n"
    if error_message:
        raise Exception(error_message)


def update_json_file(ticker_to_update, timestamp_epoch):
    tickers_json = {}
    with open("auto_buy_tickers.json", 'r') as tickers_json_file:
        tickers_json = json.load(tickers_json_file)
    # Find the right ticker:
    for ticker in tickers_json["tickers"]:
        if ticker["symbol"] == ticker_to_update:
            ticker["last_purchase_time"] = timestamp_epoch
    with open("auto_buy_tickers.json", 'w') as tickers_json_file:
        json.dump(tickers_json, tickers_json_file, indent=4)


def get_data_signature(data, api_secret_key):
    string_to_hash = ""
    for key, value in data.items():
        string_to_hash += f"{key}={value}&"
    string_to_hash = string_to_hash[:-1] # Remove excess ampersand
    signature = hmac.new(
            bytes(api_secret_key , 'latin-1'), 
            msg = bytes(string_to_hash, 'latin-1'), 
            digestmod = hashlib.sha256
        ).hexdigest()
    return signature


def get_account_info_json(api_key, api_secret_key):
    timestamp_now = int(time.time() * 1000)
    payload = {"timestamp": timestamp_now}
    signature = get_data_signature(payload, api_secret_key)
    payload.update({"signature": signature})
    headers = {"X-MBX-APIKEY": api_key}
    account_info = get_binance_endpoint_json("/account", payload, headers)
    return account_info


def get_available_funds(symbol, buy_or_sell, api_key, api_secret_key):
    account_info_json = get_account_info_json(api_key, api_secret_key)
    for balance in account_info_json["balances"]:
        if buy_or_sell == "BUY" and symbol.endswith(balance["asset"]):
            amount_str = balance["free"]
            return float(amount_str)
        elif buy_or_sell == "SELL" and symbol.startswith(balance["asset"]):
            amount_str = balance["free"]
            return float(amount_str)


def get_adjusted_transaction_amount(symbol, buy_or_sell, transaction_amount, api_key, api_secret_key):
    adjusted_amount = 0
    if type(transaction_amount) == int:
        adjusted_amount = transaction_amount
    elif type(transaction_amount) == str and transaction_amount == "MAX":
        adjusted_amount = get_available_funds(symbol, buy_or_sell, api_key, api_secret_key)
    excess_decimals = adjusted_amount % get_amount_step_size(symbol)
    adjusted_amount = adjusted_amount - excess_decimals
    return adjusted_amount


def do_transaction(symbol, buy_or_sell, transaction_amount, api_key, api_secret_key):
    adjusted_transaction_amount = get_adjusted_transaction_amount(symbol, buy_or_sell, transaction_amount, api_key, api_secret_key)
    # Check that the user has enough funds:
    symbol_available_funds = get_available_funds(symbol, buy_or_sell, api_key, api_secret_key)
    if symbol_available_funds < adjusted_transaction_amount:
        return f"!ERROR! Not enough funds to {buy_or_sell} on ticker {symbol}. \n" \
             + f"Transaction amount is set to {transaction_amount}, but you" \
             + f" only have {symbol_available_funds} available within your account."
    timestamp_now = int(time.time() * 1000)
    data = {
        "symbol": symbol,
        "side": buy_or_sell,
        "type": "MARKET",
        "timestamp": timestamp_now,
    }
    if buy_or_sell == "SELL":
        data.update({"quantity": adjusted_transaction_amount})
    elif buy_or_sell == "BUY":
        data.update({"quoteOrderQty": adjusted_transaction_amount})

    signature = get_data_signature(data, api_secret_key)
    data.update({"signature": signature})
    headers = {"X-MBX-APIKEY": api_key}
    print(f"Attempting transaction {buy_or_sell} of symbol {symbol} | amount: {adjusted_transaction_amount} | timestamp: {timestamp_now}")
    buy_result_json = post_binance_endpoint_json("/order", data, headers=headers)
    return buy_result_json


def is_transaction_successful(transaction_result_json):
    # If the result (which should be a dict/json object) is not a dict, something went wrong.
    # The response form binance is always in JSON format.
    if type(transaction_result_json) != dict:
        return False
    # Check that the key `status` exists:
    elif "status" in transaction_result_json: 
        # If the key exists, check that the order was completely filled:
        if transaction_result_json["status"] == "FILLED": 
            return True
    return False


def main():
    
    # # Check for connection with the api
    result = requests.get("https://api.binance.com/api/v3/ping")
    print(f"Ping result: {result}")

    # Get the API key and Secret key discreetly:
    api_key = getpass("API Key: ")
    api_secret_key = getpass("API Secret key: ")

    # Get all the tickers that should be bought, and check if their 
    # attribute values are reasonable
    tickers_to_buy = {}
    with open("auto_buy_tickers.json", 'r') as tickers_json:
        tickers_to_buy = json.load(tickers_json)["tickers"]

    available_tickers = get_available_tickers()
    exit_on_ticker_setup_issue(tickers_to_buy, available_tickers)

    while True:
        # Buy loop:
        for ticker in tickers_to_buy:
            symbol = ticker["symbol"]
            current_time_epoch = time.time()
            seconds_since_last_buy = current_time_epoch - ticker["last_purchase_time"]
            if seconds_since_last_buy > ticker["time_interval_seconds"]:
                transaction_result_json = do_transaction(symbol, 
                    ticker["buy_or_sell"], 
                    ticker["transaction_amount"], 
                    api_key, api_secret_key
                    )
                if is_transaction_successful(transaction_result_json):
                    ticker["last_purchase_time"] = current_time_epoch
                    update_json_file(symbol, current_time_epoch)
                    print(f"Successfully bought {symbol}.")
                else:
                    print(f"Something went wrong purchasing symbol {symbol}: ")
                    print(transaction_result_json)
        # Sleep for a second
        time.sleep(10)


if __name__ == "__main__":
    main()
