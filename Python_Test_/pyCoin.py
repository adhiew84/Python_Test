import requests
import threading
import base64
import pickle
import os
import sqlite3

from tabulate import tabulate
from datetime import datetime
from time import sleep

requests.packages.urllib3.disable_warnings()

class Thread(threading.Thread):
    def __init__(self, url, cryptos, currencies, key):
        threading.Thread.__init__(self, target=update_ticker, 
                                  args=(url, cryptos, currencies, key))
        self.start()

class Crypto(object):
    def __init__(self, data: dict) -> None:
        self.id = data["id"]
        self.name = data["name"]
        self.symbol = data["symbol"].upper()
        self.supply = None
        self.currencies = None

    def set_ticker(self, ticker: dict, currencies: str) -> None:
        # TODO: Add price change 7d for custom cryptos
        self.rank = ticker["market_cap_rank"]
        if "percent_change_7d" in ticker:
            data = ticker

            if self.currencies:
                self.currencies[currencies.upper()] = data
            else:
                self.currencies = {currencies.upper(): data}
        else:
            keys = ["price", "volume_24h", "percent_change_24h",
                    "percent_change_7d"]
            cgecko_keys = ["current_price", "total_volume",
                           "price_change_percentage_24h_in_currency", 
                           "price_change_percentage_7d_in_currency"]

            for currency in currencies.split(","):
                data = {}
                for key, cg_key in zip(keys, cgecko_keys):
                    data[key] = ticker[cg_key][currency.lower()]

                if self.currencies:
                    self.currencies[currency.upper()] = data
                else:
                    self.currencies = {currency.upper(): data}
        if "supply" in ticker:
            self.supply = Supply(ticker["supply"]).obj


color_not_supported = os.name == 'nt'

class bcolors:
    WHITE = '\033[97m'
    CYAN = '\033[36m'
    MAGENTA = '\033[35m'
    BLUE = '\033[94m'
    GREEN = '\033[32m'
    YELLOW = '\033[93m'
    RED = '\033[31m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    CLEAR = '\033[H\033[J'

class Supply(object):
    def __init__(self, data: dict) -> None:
        self._total = data["total"]
        self._max = data["max"]
        self._circulating = data["circulating"]
    
    def __init__(self, data: str) -> None:
        self.obj = pickle.loads(data)

def bold(text):
    return bcolors.BOLD + str(text) + bcolors.ENDC


def color(text, color):
    if color_not_supported:
        return str(text)
    colors = {"m": bcolors.MAGENTA, "b": bcolors.BLUE, "y": bcolors.YELLOW,
              "w": bcolors.WHITE, "c": bcolors.CYAN, "r": bcolors.RED,
              "g": bcolors.GREEN}
    return colors[color] + str(text) + bcolors.ENDC


def color_percent(value):
    if value == "N/A":
        return color(value, "r")
    elif value < 0:
        return color(value / 100, "r")
    else:
        return color(value / 100, "g")


def load_cgecko_cryptos(symbols: str) -> tuple:
    # Get the JSON file from CoinGecko API
    url = "https://api.coingecko.com/api/v3/coins/list"
    try:
        r = requests.get(url, timeout=10)
    except Exception as e:
        return {}, str(e)

    if r.status_code == 200:
        data = r.json()

        # Parse the JSON into a dict of Crypto objects
        cryptos, errors = {}, []
        cgecko_symbs = [d["symbol"] for d in data]
        for s in symbols.split(","):
            if s.lower() in cgecko_symbs:
                cryptos[s.upper()] = Crypto(data[cgecko_symbs.index(s.lower())])
            else:
                errors.append(color(f"Couldn't find '{s.upper()}' " \
                                    "on CoinGecko.com", 'm'))
        return cryptos, "\n".join(errors)

    else:
        raise ConnectionError(f"{url} [{r.status_code}]")

def get_supplies(cryptos):
    url = "https://coin-cheap.com/api/v3/supply"
    try:
        r = requests.get(url, timeout=30, verify=False)
    except:
        return {}

    if r.status_code == 200:
        data = r.json()

        supplies = {}

        for c in cryptos:
            if c in data:
                base64_bytes = data[c].encode("ascii")
                supplies[c] = base64.b64decode(base64_bytes)

        return supplies
    else:
        return {}

def update_ticker(url: str, cryptos: dict, currencies: str, key: str) -> None:
    key_url = url.format(cryptos[key].id)
    try:
        r = requests.get(key_url, timeout=10)
    except:
        return

    if r.status_code == 200:
        with lock:
            cryptos[key].set_ticker(r.json()["market_data"], currencies)
    else:
        raise ConnectionError(f"{key_url} [{r.status_code}]")


def update_tickers(cryptos: dict, currencies: str) -> None:
    # Get and set all tickers for each crypto selected
    url = "https://api.coingecko.com/api/v3/coins/{}?" \
          "localization=false&tickers=false&community_data=false" \
          "&developer_data=false&sparkline=false"

    threads = [Thread(url, cryptos, currencies, key) for key in cryptos]
    [t.join() for t in threads]  # Wait until all threads are done to continue


def get_top_10(convert: str="USD") -> dict:
    url = "https://api.coingecko.com/api/v3/coins/?per_page=10"
    try:
        r = requests.get(url, timeout=10)
    except:
        return {}

    if r.status_code == 200:
        # Parse the JSON and update the Crypto objects
        data = r.json()

        cryptos = {d["symbol"].upper(): Crypto(d) for d in data}

        supplies = get_supplies(cryptos)         

        for conv in [c.lower() for c in convert.split(",")]:
            for d in data:
                pc24 = 'price_change_percentage_24h_in_currency'
                pc7 = 'price_change_percentage_7d_in_currency'
                ticker = {
                    "market_cap_rank": d['market_data']['market_cap_rank'],
                    "price": d['market_data']['current_price'][conv],
                    "volume_24h": d['market_data']['total_volume'][conv],
                    "percent_change_24h": d['market_data'][pc24][conv],
                    "percent_change_7d": d['market_data'][pc7][conv]
                }
                if d["symbol"].upper() in supplies:
                    ticker["supply"] = supplies[d["symbol"].upper()]
                cryptos[d["symbol"].upper()].set_ticker(ticker, conv)

    else:
        raise ConnectionError(f"{url} [{r.status_code}]")

    return cryptos


def sort_selection(selection, sort_value, curr):
    cases = {"rank": lambda x: x.rank,
             "price": lambda x: x.currencies[curr]["price"],
             "change_24h": lambda x: x.currencies[curr]["percent_change_24h"],
             "change_7d": lambda x: x.currencies[curr]["percent_change_7d"],
             "volume": lambda x: x.currencies[curr]["volume_24h"]}

    return sorted(selection, key=cases[sort_value.replace("-", "")],
                  reverse="-" not in sort_value)


def print_selection_multitab(selection, sort_value):
    for currency in selection[0].currencies:
        # Generate a list of lists containing the data to print
        to_print = []

        # Sort the selection
        selection = sort_selection(selection, sort_value, currency)

        for item in selection:
            currs = item.currencies
            price = currs[currency]['price']
            volume = currs[currency]['volume_24h']
            percent_24h = color_percent(currs[currency]['percent_change_24h'])
            percent_7d = color_percent(currs[currency]['percent_change_7d'])
            circulating = 0
            if item.supply:
                circulating = item.supply._circulating
            data = [bold(item.rank), item.symbol, item.name,
                    price, percent_24h, percent_7d, volume, circulating]
            to_print.append(data)

        headers = ["Rank", "Symbol", "Name", f"Price ({currency})",
                   f"24h-Change ({currency})", f"7d-Change ({currency})",
                   f"24h-Volume ({currency})", "Circulating Supply"]
        headers = [bold(h) for h in headers]

        floatfmt = ["", "", "", f"{'.8f' if currency == 'BTC' else '.4f'}",
                    ".2%", ".2%", f"{'.4f' if currency == 'BTC' else ',.0f'}"]

        print(color(bold("\n> " + currency), "y"))
        print(tabulate(to_print, headers=headers, floatfmt=floatfmt))
    # Print the source and timestamp
    print(f"\nSource: {color('https://www.coingecko.com', 'w')} - "
          f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def main(currencies, cryptos, sort_value, clear_scr):
    if cryptos:
        # Load the crypto ids from CoinGecko
        update_tickers(cryptos, currencies)
    else:
        # Get the tickers of the top 10 cryptos
        cryptos = get_top_10(currencies)

    selection = [cryptos[key] for key in cryptos]

    save_to_databases(cryptos,currencies)

    # Clear the screen if needed
    if clear_scr:
        if color_not_supported:
            os.system("cls")
        else:
            print(bcolors.CLEAR)

    # Print the selection if any
    if selection:
        print_selection_multitab(selection, sort_value)


lock = threading.Lock()

# Initialize the database
def initialize_database():
    conn = sqlite3.connect('crypto_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cryptocurrency (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rank INTEGER,
            symbol TEXT,
            name TEXT,
            price REAL,
            percent_change_24h REAL,
            percent_change_7d REAL,
            volume_24h REAL,
            circulating_supply REAL,
            currencies TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_to_databases(cryptos,currencies):
    # Save data to the database
    conn = sqlite3.connect('crypto_data.db')
    cursor = conn.cursor()

    for key in cryptos:
        crypto = cryptos[key]
        for currency in currencies.split(","):
            currs = crypto.currencies[currency]
            circulating_supply = crypto.supply._circulating if crypto.supply else 0

            # Use the check_and_save function to save data
            check_and_save(crypto, currs, circulating_supply, currency, cursor)

    conn.commit()
    conn.close()

def check_and_save(crypto, currs, circulating_supply, currencies, cursor):
    # Check if there is any data in the database for the given symbol and currencies
    cursor.execute('''
        SELECT *
        FROM cryptocurrency
        WHERE symbol = ? AND currencies = ?
    ''', (crypto.symbol, currencies))
    existing_data = cursor.fetchone()

    if existing_data is None:
        # No existing data found, insert the new data
        cursor.execute('''
            INSERT INTO cryptocurrency
            (rank, symbol, name, price, percent_change_24h, percent_change_7d, volume_24h, circulating_supply, currencies)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            crypto.rank, crypto.symbol, crypto.name, currs['price'],
            currs['percent_change_24h'], currs['percent_change_7d'],
            currs['volume_24h'], circulating_supply, currencies
        ))
    else:
        # Compare each field separately with the existing data
        rank_changed = crypto.rank != existing_data[1]
        name_changed = crypto.name != existing_data[3]
        price_changed = abs(currs['price'] - existing_data[4]) > 0.000001  # Adjust tolerance as needed
        percent_change_24h_changed = abs(currs['percent_change_24h'] - existing_data[5]) > 0.000001
        percent_change_7d_changed = abs(currs['percent_change_7d'] - existing_data[6]) > 0.000001
        volume_24h_changed = abs(currs['volume_24h'] - existing_data[7]) > 0.000001
        circulating_supply_changed = circulating_supply != existing_data[8]

        # If any field has changed, insert the new data
        if (
            rank_changed or name_changed or price_changed or
            percent_change_24h_changed or percent_change_7d_changed or
            volume_24h_changed or circulating_supply_changed
        ):
            cursor.execute('''
                INSERT INTO cryptocurrency
                (rank, symbol, name, price, percent_change_24h, percent_change_7d, volume_24h, circulating_supply, currencies)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                crypto.rank, crypto.symbol, crypto.name, currs['price'],
                currs['percent_change_24h'], currs['percent_change_7d'],
                currs['volume_24h'], circulating_supply, currencies
            ))


if __name__ == '__main__':
    import argparse
    
    # Initialize the database
    initialize_database()

    supported_currencies = ['AED', 'ARS', 'AUD', 'BCH', 'BDT', 'BHD', 'BMD', 
                            'BNB', 'BRL', 'BTC', 'CAD', 'CHF', 'CLP', 'CNY', 
                            'CZK', 'DKK', 'EOS', 'ETH', 'EUR', 'GBP', 'HKD', 
                            'HUF', 'IDR', 'ILS', 'INR', 'JPY', 'KRW', 'KWD', 
                            'LKR', 'LTC', 'MMK', 'MXN', 'MYR', 'NOK', 'NZD', 
                            'PHP', 'PKR', 'PLN', 'RUB', 'SAR', 'SEK', 'SGD', 
                            'THB', 'TRY', 'TWD', 'USD', 'VEF', 'XAG', 'XAU', 
                            'XDR', 'XLM', 'XRP', 'ZAR']
    sorts = ["rank", "rank-", "price", "price-", "change_24h", "change_24h-",
             "change_7d", "change_7d-", "volume", "volume-"]

    parser = argparse.ArgumentParser(description='Displays cryptocurrencies '
                                     'data from CMC in the terminal')
    parser.add_argument('--curr', default='USD', type=str,
                        help='Currency used for the price and volume '
                        '(for more than one, separate them with a comma : '
                        'USD,BTC). Valid currencies: '
                        f'{bold(", ".join(supported_currencies))}, '
                        '(default USD)')
    parser.add_argument('--crypto', default=None, type=str,
                        help='Symbols of the cryptocurrencies to display '
                        '(default top10).')
    parser.add_argument('--sort', default='rank-', type=str, choices=sorts,
                        help='How to sort cryptos (default rank-)')
    parser.add_argument('-d', '--delay', default=10, type=int,
                        help='Autorefresh delay in seconds '
                        '(default 10s)')

    args = parser.parse_args()

    args.curr = args.curr.upper()
    args.sort = args.sort.lower()

    # Check if the currency is supported by CoinGecko, if not use 'USD'
    for curr in args.curr.split(","):
        if curr not in supported_currencies:
            print(color(f"'{args.curr}' is not a valid currency value, "
                        "using 'USD'", 'm'))
            args.curr = "USD"
            break

    cryptos = {}
    if args.crypto:
        args.crypto = args.crypto.upper().replace(" ", "")
        cryptos, errors = load_cgecko_cryptos(args.crypto)

        if errors:
            print(errors)

    while True:
        try:
            main(args.curr, cryptos, args.sort, args.delay > 0)
            if args.delay > 0:
                sleep(args.delay)
            else:
                break
        except KeyboardInterrupt:
            break
