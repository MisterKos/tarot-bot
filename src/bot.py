import json
import logging
import random
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web

API_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", 8080))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tarot-bot")

# --- Бот и диспетчер ---
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- Загружаем колоду ---
with open("data/deck.json", "r", encoding="utf-8") as f:
    DECK = json.load(f)

CARDS = DECK["cards"]
IMAGE_BASE = DECK["image_base_url"]

# --- Память для раскладов ---
USER_STATE = {}
HISTORY_FILE = "data/history.json"

if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        HISTORY = json.load(f)
else:
    HISTORY = {}

def save_history():
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(HISTORY, f, ensure_ascii=False, indent=2)

# --- Клавиатуры ---
def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔮 Отношения", "💼 Работа")
    kb.add("💰 Финансы", "🌌 Общий расклад")
    return kb

def spread_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("1 карта", "3 карты")
    kb.add("Кельтский крест")
    return kb

# --- Выбор случайных карт ---
def draw_cards(n=1):
    cards = random.sample(CARDS, n)
    result = []
    for card in cards:
        is_reversed = random.randint(1, 100) <= DECK["reversals_percent"]
        result.append({
            "title": card["title_ru"],
            "image": IMAGE_BASE + card["image"],
            "orientation": "Перевернутая" if is_reversed else "Прямая",
            "meaning": card["reversed"] if is_reversed else card["upright"]
        })
    return result

# --- Формирование красивого текста ---
def format_interpretation(theme, situation, spread_type, cards):
    text = f"✨ *Расклад по теме:* {theme}\n"
    text += f"📝 *Вопрос:* {situation}\n"
    text += f"🔮 *Тип расклада:* {spread_type}\n\n"
    for i, card in enumerate(cards, 1):
        text += f"**Карта {i}: {card['title']} ({card['orientation']})**\n"
        text += f"Толкование: {card['meaning']}\n\n"
    text += "🌟 *Итоговое толкование:* 🌟\n"
    text += (
        "Карты показали глубокую картину ситуации. "
        "Внимательно отнеситесь к их подсказкам: они открывают "
        "возможности для роста, перемен и осознания. "
        "Доверяйте своей интуиции и помните — выбор всегда за вами."
    )
    return text

# --- Обработчики ---
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я виртуальный таролог 🧙‍♂️\n"
        "Выбери тему расклада:", reply_markup=main_menu()
    )

@dp.message_handler(lambda m: m.text in ["🔮 Отношения", "💼 Работа", "💰 Финансы", "🌌 Общий расклад"])
async def choose_theme(message: types.Message):
    theme = message.text
    USER_STATE[message.from_user.id] = {"theme": theme}
    await message.answer(
        f"✏️ Опиши, пожалуйста, свою ситуацию подробнее.", reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message_handler(lambda m: m.from_user.id in USER_STATE and "theme" in USER_STATE[m.from_user.id] and "situation" not in USER_STATE[m.from_user.id])
async def choose_situation(message: types.Message):
    USER_STATE[message.from_user.id]["situation"] = message.text
    await message.answer("Выбери тип расклада:", reply_markup=spread_menu())

@dp.message_handler(lambda m: m.text in ["1 карта", "3 карты", "Кельтский крест"])
async def make_spread(message: types.Message):
    uid = str(message.from_user.id)
    theme = USER_STATE[message.from_user.id]["theme"]
    situation = USER_STATE[message.from_user.id]["situation"]
    spread_type = message.text

    n = 1 if spread_type == "1 карта" else 3 if spread_type == "3 карты" else 10
    cards = draw_cards(n)

    # Сохраняем историю
    entry = {"theme": theme, "situation": situation, "spread": spread_type, "cards": cards}
    HISTORY.setdefault(uid, []).append(entry)
    HISTORY[uid] = HISTORY[uid][-5:]
    save_history()

    # Отправляем карты
    for i, card in enumerate(cards, 1):
        caption = f"Карта {i}: {card['title']} ({card['orientation']})"
        await message.answer_photo(card["image"], caption=caption)

    # Отправляем интерпретацию
    interpretation = format_interpretation(theme, situation, spread_type, cards)
    await message.answer(interpretation, parse_mode="Markdown")

# --- Webhook ---
async def webhook_handler(request):
    data = await request.json()
    update = types.Update.to_object(data)
    await dp.process_update(update)
    return web.Response()

def main():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, webhook_handler)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)

if __name__ == "__main__":
    main()
