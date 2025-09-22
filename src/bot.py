import os
import json
import random
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_webhook
from aiohttp import web

# ---------------------- ЛОГИ ----------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tarot-bot")

# ---------------------- НАСТРОЙКИ ----------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", 5000))

DECK_PATH = "data/deck.json"
CARDS_PATH = "assets/rw/cards"
HISTORY_PATH = "data/history.json"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# ---------------------- ЗАГРУЗКА КОЛОДЫ ----------------------
with open(DECK_PATH, "r", encoding="utf-8") as f:
    DECK = json.load(f)

def get_card(card_name: str):
    """Возвращает описание карты по имени"""
    for card in DECK:
        if card["name"] == card_name:
            return card
    return None

# ---------------------- СОСТОЯНИЯ ----------------------
user_context = {}  # user_id -> {"topic":..., "situation":...}

# ---------------------- ИСТОРИЯ ----------------------
def save_history(user_id, spread_type, cards, interpretation):
    try:
        if os.path.exists(HISTORY_PATH):
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                history = json.load(f)
        else:
            history = {}

        user_id = str(user_id)
        if user_id not in history:
            history[user_id] = []

        history[user_id].insert(0, {
            "spread": spread_type,
            "cards": cards,
            "interpretation": interpretation
        })

        history[user_id] = history[user_id][:5]  # только 5 последних
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(f"Ошибка сохранения истории: {e}")

# ---------------------- ГЕНЕРАЦИЯ РАСКЛАДА ----------------------
def generate_interpretation(spread_type, cards, situation, topic):
    text = f"✨ *Расклад: {spread_type}*\n"
    text += f"🔮 Тема: *{topic}*\n"
    if situation:
        text += f"📝 Вопрос: _{situation}_\n\n"

    # Описание каждой карты
    for i, card_name in enumerate(cards, 1):
        card = get_card(card_name)
        if card:
            text += f"**Карта {i}: {card['name']}**\n"
            text += f"_{card['meaning']}_\n\n"

    # Итоговое толкование
    text += "🌟 *Итоговое толкование:*\n"
    text += (
        "Карты показывают важные аспекты вашей ситуации. "
        "В них отражаются как скрытые возможности, так и предостережения. "
        "Главный совет — сохранять осознанность, доверять своей интуиции и идти шаг за шагом. "
        "Ваш путь открыт, и выбор за вами. ✨"
    )

    return text

# ---------------------- КНОПКИ ----------------------
def topic_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔮 Отношения", "💼 Работа")
    kb.add("💰 Финансы", "🌟 Общий")
    return kb

def spread_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("1 карта", "3 карты")
    kb.add("Кельтский крест")
    return kb

# ---------------------- ХЕНДЛЕРЫ ----------------------
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await message.answer("Привет! Я виртуальный таролог. ✨\nВыбери тему расклада:", reply_markup=topic_kb())

@dp.message_handler(lambda m: m.text in ["🔮 Отношения", "💼 Работа", "💰 Финансы", "🌟 Общий"])
async def choose_topic(message: types.Message):
    user_context[message.from_user.id] = {"topic": message.text, "situation": None}
    await message.answer("Опиши, пожалуйста, свою ситуацию подробнее:")

@dp.message_handler(lambda m: m.from_user.id in user_context and user_context[m.from_user.id].get("situation") is None)
async def save_situation(message: types.Message):
    user_context[message.from_user.id]["situation"] = message.text
    await message.answer("Какой расклад сделать?", reply_markup=spread_kb())

@dp.message_handler(lambda m: m.text in ["1 карта", "3 карты", "Кельтский крест"])
async def do_spread(message: types.Message):
    ctx = user_context.get(message.from_user.id)
    if not ctx:
        await message.answer("Сначала выбери тему через /start")
        return

    spread_type = message.text
    situation = ctx["situation"]
    topic = ctx["topic"]

    if spread_type == "1 карта":
        cards = random.sample([c["name"] for c in DECK], 1)
    elif spread_type == "3 карты":
        cards = random.sample([c["name"] for c in DECK], 3)
    else:  # Кельтский крест
        cards = random.sample([c["name"] for c in DECK], 10)

    # Отправляем карты
    for card_name in cards:
        path = os.path.join(CARDS_PATH, f"{card_name}.jpg")
        if os.path.exists(path):
            with open(path, "rb") as photo:
                await message.answer_photo(photo, caption=card_name)
        else:
            await message.answer(card_name)

    # Интерпретация
    interpretation = generate_interpretation(spread_type, cards, situation, topic)
    await message.answer(interpretation, parse_mode="Markdown")

    save_history(message.from_user.id, spread_type, cards, interpretation)

    user_context.pop(message.from_user.id, None)

# ---------------------- ВЕБХУК ----------------------
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app):
    await bot.delete_webhook()
    logger.info("Webhook удалён")

async def webhook_handler(request):
    data = await request.json()
    update = types.Update.to_object(data)
    await dp.process_update(update)
    return web.Response()

def main():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, webhook_handler)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)

if __name__ == "__main__":
    main()
