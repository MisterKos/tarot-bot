import logging
import os
import json
import random
from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_webhook
from aiohttp import web

# --- Логирование ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tarot-bot")

# --- Настройки ---
API_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = "/webhook"
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", 5000))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
WEBHOOK_URL = f"{RENDER_URL}{WEBHOOK_PATH}"

# --- Инициализация ---
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# фиксируем контекст для webhook-режима
Bot.set_current(bot)
Dispatcher.set_current(dp)

# --- Загрузка колоды ---
with open("data/deck.json", "r", encoding="utf-8") as f:
    TAROT_DECK = json.load(f)
logger.info("Колода загружена локально из data/deck.json")

# --- Клавиатура ---
def menu_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔮 Отношения", "💼 Работа", "💰 Финансы", "🌌 Общий расклад")
    return kb

# --- Генерация карт ---
def draw_cards(n=3):
    return random.sample(TAROT_DECK, n)

# --- Интерпретация ---
def interpret_cards(cards, theme, situation):
    text = f"✨ Тема: *{theme}*\n📝 Ситуация: _{situation}_\n\n"
    for i, card in enumerate(cards, 1):
        text += f"**{i}. {card['name']}** — {card['meaning']}\n\n"

    # Итоговое толкование
    text += "🔮 *Итог расклада*\n"
    if theme == "Отношения":
        text += ("Карты показывают динамику ваших личных связей. "
                 "Есть подсказки, где нужно проявить терпение и мягкость, "
                 "а где важно поставить границы. Следуя этим урокам, "
                 "вы укрепите связь и избежите ненужных конфликтов.")
    elif theme == "Работа":
        text += ("В профессиональной сфере расклад намекает на важные перемены. "
                 "Сейчас важно сохранять инициативу, но не спешить с решениями. "
                 "Доверяйте опыту и ищите новые пути для роста — они уже рядом.")
    elif theme == "Финансы":
        text += ("Финансовая энергия требует аккуратности. "
                 "Карты подсказывают избегать резких трат и держать баланс. "
                 "Есть перспективы улучшения ситуации, если вложить усилия в планирование.")
    else:
        text += ("Ваш путь сейчас связан с внутренними уроками. "
                 "Карты показывают важность доверия к себе и своим решениям. "
                 "Будьте внимательны к знакам, и они укажут верное направление.")

    return text

# --- Хэндлеры ---
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я виртуальный таролог. ✨\n"
        "Выберите тему расклада в меню:",
        reply_markup=menu_kb()
    )

@dp.message_handler(lambda m: m.text in ["🔮 Отношения", "💼 Работа", "💰 Финансы", "🌌 Общий расклад"])
async def choose_theme(message: types.Message):
    theme = message.text.replace("🔮 ", "").replace("💼 ", "").replace("💰 ", "").replace("🌌 ", "")
    dp.current_state(user=message.from_user.id).set_state("await_situation")
    await dp.current_state(user=message.from_user.id).update_data(theme=theme)
    await message.answer(f"Опишите, пожалуйста, вашу ситуацию по теме *{theme}*. "
                         "Это поможет сделать расклад более точным.")

@dp.message_handler(state="await_situation")
async def handle_situation(message: types.Message):
    user_data = await dp.current_state(user=message.from_user.id).get_data()
    theme = user_data.get("theme", "Общий расклад")
    situation = message.text
    cards = draw_cards(3)
    text = interpret_cards(cards, theme, situation)
    await message.answer(text, parse_mode="Markdown", reply_markup=menu_kb())
    await dp.current_state(user=message.from_user.id).reset_state()

# --- Webhook ---
async def on_startup(app):
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook установлен: {WEBHOOK_URL}")
    else:
        logger.warning("WEBHOOK_URL не задан!")

async def on_shutdown(app):
    logger.info("Отключение...")
    await bot.delete_webhook()

def main():
    app = web.Application()
    dp.register_app(app, path=WEBHOOK_PATH)
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)

if __name__ == "__main__":
    main()
