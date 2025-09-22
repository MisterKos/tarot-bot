import os
import json
import logging
import random
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.executor import start_webhook
from aiohttp import web

# --- Логирование ---
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("tarot-bot")

# --- Переменные окружения ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL")  # https://tarot-bot-xxx.onrender.com
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", 5000))

# --- Инициализация бота ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# --- Пути ---
DATA_PATH = Path("data/deck.json")
HISTORY_PATH = Path("data/history.json")
CARDS_PATH = Path("assets/rw/cards/")

# --- Загрузка колоды ---
if DATA_PATH.exists():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        DECK = json.load(f)
    logger.info("Колода загружена локально из data/deck.json")
else:
    DECK = {}
    logger.error("deck.json не найден!")

# --- Хранилище истории ---
if not HISTORY_PATH.exists():
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump({}, f)


def save_history(user_id: int, spread: dict):
    """Сохраняем расклад в историю (последние 5)."""
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        history = json.load(f)

    user_id = str(user_id)
    if user_id not in history:
        history[user_id] = []
    history[user_id].append(spread)
    history[user_id] = history[user_id][-5:]  # оставляем последние 5

    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# --- Клавиатуры ---
def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("🔮 Отношения"), KeyboardButton("💼 Работа"))
    kb.add(KeyboardButton("💰 Финансы"), KeyboardButton("🌌 Общий расклад"))
    kb.add(KeyboardButton("📜 История раскладов"))
    return kb


def spread_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("1 карта"))
    kb.add(KeyboardButton("3 карты"))
    kb.add(KeyboardButton("Кельтский крест"))
    kb.add(KeyboardButton("⬅️ Назад"))
    return kb


# --- Вспомогательные ---
def draw_cards(n: int):
    return random.sample(DECK, n)


def card_image(card_name: str):
    file_path = CARDS_PATH / f"{card_name}.jpg"
    if file_path.exists():
        return file_path
    return None


def generate_interpretation(cards, situation: str, theme: str):
    """Создаёт красивую интерпретацию в стиле опытного таролога."""
    intro = f"✨ Тема: *{theme}*\n📖 Вопрос: _{situation}_\n"
    body = ""
    for i, card in enumerate(cards, 1):
        body += f"\n**{i}. {card['name']}** — {card['meaning']}\n"

    # «сочный» итог
    summary = (
        "\n🌌 Итог расклада\n"
        "Карты образуют единую историю. Сейчас вы стоите на пороге перемен, "
        "и каждая карта подсвечивает свой аспект. "
        "Судьба словно приглашает вас к честности с собой: "
        "смело принимайте решения, опирайтесь на интуицию, "
        "не забывая об опыте прошлого. Важно видеть не только трудности, "
        "но и возможности, которые открываются.\n\n"
        "Этот расклад словно совет опытного наставника: "
        "будьте внимательны к знакам, не спешите — и дорога выведет туда, где вы найдёте гармонию."
    )

    return intro + body + summary


# --- Хендлеры ---
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я Таро-бот 🃏\n"
        "Выбери тему расклада:", reply_markup=main_menu()
    )


@dp.message_handler(lambda m: m.text in ["🔮 Отношения", "💼 Работа", "💰 Финансы", "🌌 Общий расклад"])
async def ask_situation(message: types.Message):
    dp.current_state(user=message.from_user.id).update_data(theme=message.text)
    await message.answer("Опиши, пожалуйста, свою ситуацию подробнее:", reply_markup=types.ReplyKeyboardRemove())


@dp.message_handler(lambda m: m.text and m.text not in ["⬅️ Назад", "📜 История раскладов"])
async def choose_spread(message: types.Message):
    state = dp.current_state(user=message.from_user.id)
    data = await state.get_data()
    if "theme" in data and "situation" not in data:
        await state.update_data(situation=message.text)
        await message.answer("Выбери расклад:", reply_markup=spread_menu())
    elif "situation" in data:
        await message.answer("Выбери расклад:", reply_markup=spread_menu())


@dp.message_handler(lambda m: m.text in ["1 карта", "3 карты", "Кельтский крест"])
async def do_spread(message: types.Message):
    state = dp.current_state(user=message.from_user.id)
    data = await state.get_data()
    theme = data.get("theme", "Общий расклад")
    situation = data.get("situation", "Без описания")

    if message.text == "1 карта":
        cards = draw_cards(1)
    elif message.text == "3 карты":
        cards = draw_cards(3)
    else:
        cards = draw_cards(10)

    spread = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "theme": theme,
        "situation": situation,
        "cards": [c["name"] for c in cards],
    }
    save_history(message.from_user.id, spread)

    # отправка карт
    for card in cards:
        img = card_image(card["name"])
        if img:
            with open(img, "rb") as f:
                await message.answer_photo(f, caption=f"**{card['name']}**\n{card['meaning']}", parse_mode="Markdown")
        else:
            await message.answer(f"**{card['name']}**\n{card['meaning']}", parse_mode="Markdown")

    # общий итог
    text = generate_interpretation(cards, situation, theme)
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())
    await state.finish()


@dp.message_handler(lambda m: m.text == "📜 История раскладов")
async def show_history(message: types.Message):
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        history = json.load(f)
    user_history = history.get(str(message.from_user.id), [])
    if not user_history:
        await message.answer("История пуста.", reply_markup=main_menu())
        return

    text = "📝 Последние расклады:\n"
    for spread in user_history[-5:]:
        text += f"\n📅 {spread['date']} — {spread['theme']}\nВопрос: {spread['situation']}\nКарты: {', '.join(spread['cards'])}\n"
    await message.answer(text, reply_markup=main_menu())


# --- Webhook ---
async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")


async def on_shutdown(dp):
    await bot.delete_webhook()
    logger.info("Webhook удалён")


def main():
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
    )


if __name__ == "__main__":
    main()
