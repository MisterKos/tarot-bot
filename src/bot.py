import os
import json
import random
import logging
from pathlib import Path
from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_webhook
from aiohttp import web

# ----------------- НАСТРОЙКИ -----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", "https://tarot-bot-12u6.onrender.com")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", 8080))

DATA_PATH = Path("data")
DECK_FILE = DATA_PATH / "deck.json"
HISTORY_FILE = DATA_PATH / "history.json"
CARDS_PATH = Path("assets/rw/cards")

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("tarot-bot")

# ----------------- ИНИЦИАЛИЗАЦИЯ -----------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

Bot.set_current(bot)
Dispatcher.set_current(dp)

# Загружаем колоду
if DECK_FILE.exists():
    with open(DECK_FILE, "r", encoding="utf-8") as f:
        deck = json.load(f)
    logger.info("Колода загружена из data/deck.json")
else:
    deck = {}
    logger.error("deck.json не найден!")

# История раскладов
if HISTORY_FILE.exists():
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)
else:
    history = {}

# ----------------- УТИЛИТЫ -----------------
def save_history():
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def draw_cards(n=1):
    return random.sample(list(deck.keys()), n)

def generate_interpretation(cards, situation, spread_type, theme):
    """Создание красивого толкования расклада"""
    text = f"✨ Тема: *{theme}*\n📖 Ситуация: _{situation}_\n\n"
    if spread_type == "1 карта":
        card = cards[0]
        meaning = deck[card]["meaning"]
        text += f"🔮 Ваша карта: *{card}*\n\n{meaning}\n\n"
        text += f"💡 Совет: доверьтесь своим чувствам — карта показывает ключ к вашей ситуации."
    elif spread_type == "3 карты":
        parts = ["Прошлое", "Настоящее", "Будущее"]
        for i, card in enumerate(cards):
            text += f"🃏 {parts[i]} — *{card}*\n{deck[card]['meaning']}\n\n"
        text += "✨ Итог: картина прошлого, настоящего и будущего складывается в единый поток. Сделайте выводы и примите мудрое решение."
    else:  # Кельтский крест
        positions = [
            "Суть ситуации", "Препятствия", "Прошлое", "Будущее",
            "Осознанное", "Бессознательное", "Вы", "Окружение",
            "Надежды и страхи", "Итог"
        ]
        for i, card in enumerate(cards):
            text += f"🔹 {positions[i]} — *{card}*\n{deck[card]['meaning']}\n\n"
        text += "🌟 Итог расклада: глубокий анализ показывает скрытые влияния и пути развития. Обратите внимание на советы карт."
    return text

async def send_cards(message, cards):
    for card in cards:
        img_path = CARDS_PATH / f"{card}.jpg"
        caption = f"🃏 {card}"
        if img_path.exists():
            with open(img_path, "rb") as photo:
                await message.answer_photo(photo, caption=caption)
        else:
            await message.answer(caption)

# ----------------- СОСТОЯНИЕ -----------------
user_context = {}  # user_id -> {"theme": str, "situation": str, "spread": str}

# ----------------- КНОПКИ -----------------
def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔮 Отношения", "💼 Работа")
    kb.add("💰 Финансы", "🌟 Общий расклад")
    return kb

def spread_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("1 карта", "3 карты", "Кельтский крест")
    return kb

# ----------------- ОБРАБОТЧИКИ -----------------
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await message.answer(
        "Добро пожаловать в Таро-бота 🔮\n\nВыберите тему расклада:",
        reply_markup=main_menu()
    )

@dp.message_handler(lambda m: m.text in ["🔮 Отношения", "💼 Работа", "💰 Финансы", "🌟 Общий расклад"])
async def choose_theme(message: types.Message):
    theme = message.text
    user_context[message.from_user.id] = {"theme": theme}
    await message.answer("📝 Опишите, пожалуйста, вашу ситуацию подробнее.", reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(lambda m: m.from_user.id in user_context and "situation" not in user_context[m.from_user.id])
async def get_situation(message: types.Message):
    user_context[message.from_user.id]["situation"] = message.text
    await message.answer("Выберите тип расклада:", reply_markup=spread_menu())

@dp.message_handler(lambda m: m.text in ["1 карта", "3 карты", "Кельтский крест"])
async def make_spread(message: types.Message):
    user_id = message.from_user.id
    ctx = user_context.get(user_id, {})
    if not ctx or "situation" not in ctx:
        await message.answer("Сначала выберите тему и опишите ситуацию через /start.")
        return

    spread_type = message.text
    ctx["spread"] = spread_type

    n = 1 if spread_type == "1 карта" else 3 if spread_type == "3 карты" else 10
    cards = draw_cards(n)

    # Сохраняем в историю
    rec = {"theme": ctx["theme"], "situation": ctx["situation"], "spread": spread_type, "cards": cards}
    history.setdefault(str(user_id), []).append(rec)
    history[str(user_id)] = history[str(user_id)][-5:]  # только 5 последних
    save_history()

    # Отправляем карты
    await send_cards(message, cards)

    # Итоговое толкование
    interpretation = generate_interpretation(cards, ctx["situation"], spread_type, ctx["theme"])
    await message.answer(interpretation, parse_mode="Markdown", reply_markup=main_menu())

    # Сброс контекста
    user_context.pop(user_id, None)

# ----------------- ВЕБ-СЕРВЕР -----------------
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.close()

async def handle_get(request):
    return web.Response(text="OK")

async def handle_post(request):
    try:
        data = await request.json()
        update = types.Update(**data)
        Bot.set_current(bot)
        Dispatcher.set_current(dp)
        await dp.process_update(update)
    except Exception as e:
        logger.error(f"Ошибка при обработке апдейта: {e}")
    return web.Response(text="OK")

def main():
    app = web.Application()
    app.router.add_get("/", handle_get)
    app.router.add_post(WEBHOOK_PATH, handle_post)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)

if __name__ == "__main__":
    main()
