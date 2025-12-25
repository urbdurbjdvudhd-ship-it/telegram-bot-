import time
import telebot
from config import BOT_TOKEN

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "✅ Bot Online!")

while True:
    try:
        print("✅ Bot running...")
        bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
    except Exception as e:
        print("⚠️ Polling error:", e)
        time.sleep(5)
