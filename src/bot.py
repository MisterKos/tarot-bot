import os
import json
import logging
import random
from typing import List

from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.markdown import hbold

# ---------------------- Логирование ----------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tarot-bot")

# ---------------------- Настройки ----------------------
TOKEN = os.getenv("BOT_TOKEN") or "YOUR_TOKEN_HERE"
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")  # например: tarot-bot-12u6.onrender.com

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# ---------------------- Карты ----------------------
def load_deck() -> List[dict]:
    try:
        with open("data/deck.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error(f"Не удалось загрузить колоду: {e}")
        return []

deck = load_deck()
log.info("Колода загружена локально из data/deck.json")

def draw_cards(n=3) -> List[dict]:
    return random.sample(deck, n)

def summarize_spread(cards: List[dict]) -> str:
    # Итог расклада: живая интерпретация
    keywords = [c.get("meaning", "") for c in cards if c.get("meaning")]
    summary = " ".join(keywords[:5])  # упрощённый вариант
    return f"✨ Итог расклада: {summary if summary else 'ситуация требует осознанного выбора.'}"

# ---------------------- Клавиатуры ----------------------
def menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("🔮 Отношения"),
           KeyboardButton("💼 Работа"),
           KeyboardButton("💰 Деньги"))
    return kb

# ---------------------- Хендлеры ----------------------
@dp.message_handler(commands=["start"])
async def cmd_start(m: types.Message):
    await m.answer("Привет! Это бот раскладов на Таро 🎴", reply_markup=menu_kb())

@dp.message_handler(commands=["menu"])
async def cmd_menu(m: types.Message):
    await m.answer("Выберите расклад:", reply_markup=menu_kb())

@dp.message_handler(lambda m: m.text in ["🔮 Отношения", "💼 Работа", "💰 Деньги"])
async def handle_spread(m: types.Message):
    cards = draw_cards(3)
    text = f"Ваш расклад ({m.text}):\n\n"
    for c in cards:
        text += f"{hbold(c['name'])}: {c['meaning']}\n"
    text += "\n" + summarize_spread(cards)
    await m.answer(text)

@dp.message_handler()
async def on_free_text(m: types.Message):
    await m.answer("Выберите расклад через /menu.", reply_markup=menu_kb())

# ---------------------- Webhook ----------------------
async def webhook_handler(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400)
    update = types.Update.to_object(data)
    await dp.process_update(update)
    return web.Response(status=200, text="ok")

async def on_startup(app_: web.Application):
    if RENDER_EXTERNAL_URL:
        url = f"https://{RENDER_EXTERNAL_URL}/webhook"
        log.info("Webhook URL (нужно установить вручную через setWebhook): %s", url)
    else:
        log.warning("RENDER_EXTERNAL_URL не задан.")

def main():
    app = web.Application()
    app.router.add_post("/webhook", webhook_handler)
    app.on_startup.append(on_startup)
    port = int(os.getenv("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=port, print=None)

if __name__ == "__main__":
    main()
