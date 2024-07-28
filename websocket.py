from flask import Flask, jsonify
import ccxt
import asyncio
import pandas as pd
import json
import os
import numpy as np
import websockets
from telegram import Bot
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram bot token and chat ID
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TP_PERCENT = 0.005
SL_PERCENT = 0.001

app = Flask(__name__)

# Function to fetch the current market price of a symbol
def fetch_market_price(symbol):
    try:
        exchange = ccxt.binance()
        ticker = exchange.fetch_ticker(symbol)
        return ticker['last']
    except ccxt.BaseError as e:
        print('Error fetching market price:', str(e))
        return None

# Function to fetch OHLCV data
def fetch_ohlcv(symbol, timeframe, limit):
    exchange = ccxt.binance()
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

# Function to calculate MACD
def calculate_macd(df, fast_period=12, slow_period=26, signal_period=9):
    df['ema_fast'] = df['close'].ewm(span=fast_period, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow_period, adjust=False).mean()
    df['macd'] = df['ema_fast'] - df['ema_slow']
    df['signal'] = df['macd'].ewm(span=signal_period, adjust=False).mean()
    df['histogram'] = df['macd'] - df['signal']
    return df

# Function to implement trading strategy
def apply_macd_strategy(df):
    df['position'] = np.where(df['macd'] > df['signal'], 1, 0)
    df['position'] = np.where(df['macd'] < df['signal'], -1, df['position'])
    df['signal'] = df['position'].diff()
    return df

# Function to send a message via Telegram
async def send_telegram_message(bot_token, chat_id, message):
    bot = Bot(token=bot_token)
    try:
        await bot.send_message(chat_id=chat_id, text=message)
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

# Function to handle WebSocket messages
async def handle_socket_message(message, symbol,timeframe):
    data = json.loads(message)
    kline = data['k']
    timestamp = pd.to_datetime(kline['t'], unit='ms')
    close = float(kline['c'])
    high = float(kline['h'])
    low = float(kline['l'])
    if kline['x']:
        df = fetch_ohlcv(f'{symbol.upper()}', timeframe, 100)
        df = calculate_macd(df)
        df = apply_macd_strategy(df)
        last_row = df.tail(2)
        print("On running...")
        entry_price = fetch_market_price(symbol.upper())
        tp = entry_price * (1 + TP_PERCENT)
        sl = entry_price * (1 - SL_PERCENT)
        mess = f"🔴SELL WITH PRICE {entry_price}\nTP: {tp}\nSL: {sl}"
        await send_telegram_message(BOT_TOKEN, CHAT_ID, mess)
        if last_row.iloc[0]['signal'] == -2:
            entry_price = fetch_market_price(symbol.upper())
            tp = entry_price * (1 + TP_PERCENT)
            sl = entry_price * (1 - SL_PERCENT)
            mess = f"🔴SELL WITH PRICE {entry_price}\nTP: {tp}\nSL: {sl}"
            await send_telegram_message(BOT_TOKEN, CHAT_ID, mess)
        if last_row.iloc[0]['signal'] == 2:
            entry_price = fetch_market_price(symbol.upper())
            tp = entry_price * (1 - TP_PERCENT)
            sl = entry_price * (1 + SL_PERCENT)
            mess = f"🟢 BUY WITH PRICE {entry_price}\nTP: {tp}\nSL: {sl}"
            await send_telegram_message(BOT_TOKEN, CHAT_ID, mess)

# Main function to run the WebSocket client
async def run_websocket(symbol, timeframe):
    async with websockets.connect(f'wss://stream.binance.com:9443/ws/{symbol.replace("/","")}@kline_{timeframe}') as websocket:
        while True:
            try:
                message = await websocket.recv()
                await handle_socket_message(message, symbol,timeframe)
            except websockets.ConnectionClosed:
                print("WebSocket connection closed. Reconnecting...")
                break

# Flask route to start the WebSocket client
@app.route('/')
def start_websocket():
    symbol = 'icp/usdt'
    timeframe = '1m'
    asyncio.run(run_websocket(symbol, timeframe))
    return jsonify({"status": "WebSocket client started"})

if __name__ == "__main__":
    app.run(debug=True)
