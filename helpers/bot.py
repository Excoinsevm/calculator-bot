import logging
import os
import time
from telegram import Bot, Update
from flask import Flask, Blueprint, request, jsonify
from telegram.ext import Dispatcher, CommandHandler
from web3 import Web3
import requests

# Set up logging
logger = logging.getLogger(__name__)

# Telegram Bot and Flask App Initialization
app = Flask(__name__)
api = Blueprint("serverless_handler", __name__)
bot = Bot(os.environ["7804006973:AAEbG0b-LGj2Toay58o_agO_6XTqMKOiMOA"])
app.config["tg_bot"] = bot
dispatcher = Dispatcher(bot, None, workers=0)

# Bitrock RPC and DEX Info
BITROCK_RPC = "https://connect.bit-rock.io"
FACTORY_ADDRESSES = {
    "PopSwap": "0x195b605fa7c6f379fd27ddeec89cfae6caabfae9",
    "RockSwap": "0x02c73ecb9b82e545e32665edc42ae903f8aa86a9",
}
FACTORY_ABI = [
    "event PairCreated(address indexed token0, address indexed token1, address pair, uint)"
]

# Initialize Web3
web3 = Web3(Web3.HTTPProvider(BITROCK_RPC))

# Track known pairs
known_pairs = set()

# Start Command Handler
def start_handler(update, context):
    update.message.reply_text("Monitoring new pairs on Bitrock DEXs...")

dispatcher.add_handler(CommandHandler("start", start_handler))


# Function to get token symbols
def get_token_symbol(token_address):
    abi = ["function symbol() view returns (string)"]
    contract = web3.eth.contract(address=Web3.toChecksumAddress(token_address), abi=abi)
    try:
        return contract.functions.symbol().call()
    except Exception as e:
        logger.error(f"Error fetching symbol for {token_address}: {e}")
        return "N/A"


# Function to fetch GeckoTerminal data
def get_gecko_data(pair_address):
    try:
        url = f"https://api.geckoterminal.com/api/v2/networks/bitrock/pools/{pair_address}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json().get("data", {}).get("attributes", {})
        return {
            "base_token_price_usd": data.get("base_token_price_usd"),
            "base_token_price_native": data.get("base_token_price_native_currency"),
            "fdv_usd": data.get("fdv_usd"),
        }
    except Exception as e:
        logger.error(f"Error fetching GeckoTerminal data: {e}")
        return {}


# Function to handle new pairs
def handle_new_pair(event, dex_name, chat_id):
    token0 = event["args"]["token0"]
    token1 = event["args"]["token1"]
    pair_address = event["args"]["pair"]

    if pair_address in known_pairs:
        return
    known_pairs.add(pair_address)

    symbol0 = get_token_symbol(token0)
    symbol1 = get_token_symbol(token1)

    gecko_data = get_gecko_data(pair_address)
    message = f"""
✨ New Pair Detected on {dex_name}
Token 1: {symbol0} ({token0})
Token 2: {symbol1} ({token1})
Pair Address: {pair_address}

💵 Price (USD): {gecko_data.get('base_token_price_usd', 'N/A')}
📈 Price in BROCK: {gecko_data.get('base_token_price_native', 'N/A')}
🛍️ FDV (USD): {gecko_data.get('fdv_usd', 'N/A')}
"""
    bot.send_message(chat_id=chat_id, text=message)


# Polling for events on the factories
def monitor_factories(chat_id):
    for dex_name, factory_address in FACTORY_ADDRESSES.items():
        contract = web3.eth.contract(
            address=Web3.toChecksumAddress(factory_address), abi=FACTORY_ABI
        )
        event_filter = contract.events.PairCreated.createFilter(fromBlock="latest")

        while True:
            for event in event_filter.get_new_entries():
                handle_new_pair(event, dex_name, chat_id)
            time.sleep(10)


# Webhook Handler
@api.route("/", methods=["POST"])
def webhook():
    update_json = request.get_json()
    logger.info(f"Received update: {update_json}")
    update = Update.de_json(update_json, app.config["tg_bot"])
    dispatcher.process_update(update)
    return jsonify({"status": "ok"})


@api.route("/")
def home():
    return "Bot is running!"


# Flask setup
app.register_blueprint(api, url_prefix="/api/webhook")

# Start monitoring in a background thread
import threading

def start_monitoring():
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    monitor_thread = threading.Thread(target=monitor_factories, args=(chat_id,))
    monitor_thread.start()


if __name__ == "__main__":
    start_monitoring()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
