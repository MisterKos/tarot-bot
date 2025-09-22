import json
import logging
import os
import random
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils.executor import start_webhook

# ================== НАСТРОЙКИ ==================
API_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL")  # например https://tarot-bot-12u6.onrender.com
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", 5000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tarot-bot")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ================== СОСТОЯНИЯ ==================
class TarotStates(StatesGroup):
    waiting_for_topic = State()
    waiting_for_situation = State()
    waiting_for_spread = State()

# ================== ЗАГРУЗКА КОЛОДЫ ==================
with open("data/deck.json", "r", encoding="utf-8") as f:
    deck = json.load(f)
cards = deck["cards"]
IMAGE_BASE = deck["image_base_url"]

# ================== ИСТОРИЯ ==================
user_history = {}

def save_history(user_id, spread):
    if user_id not in user_history:
        user_history[user_id] = []
    user_history[user_id].insert(0, spread)
    user_history[user_id] = user_history[user_id][:5]

# ================== КНОПКИ ==================
def topic_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("🔮 Отношения"), KeyboardButton("💼 Работа"))
    kb.add(KeyboardButton("💰 Финансы"), KeyboardButton("🌟 Общий расклад"))
    return kb

def spread_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("1 карта"), KeyboardButton("3 карты"))
    kb.add(KeyboardButton("Кельтский крест"))
    return kb

# ================== ГЕНЕРАЦИЯ КАРТ ==================
def draw_cards(n):
    result = []
    for _ in range(n):
        card = random.choice(cards)
        is_reversed = random.randint(1, 100) <= deck["reversals_percent"]
        result.append({
            "title": card["title_ru"],
            "upright": card["upright"],
            "reversed": card["reversed"],
            "image": IMAGE_BASE + card["image"],
            "is_reversed": is_reversed
        })
    return result

def interpret_cards(cards_drawn, situation, topic, spread_type):
    text = f"✨ Расклад по теме *{topic}* ({spread_type}) ✨\n\n"
    positions = ["Прошлое", "Настоящее", "Будущее"]

    for i, card in enumerate(cards_drawn):
        pos = positions[i] if spread_type == "3 карты" else f"Карта {i+1}"
        orientation = "Перевёрнутая" if card["is_reversed"] else "Прямая"
        meaning = card["reversed"] if card["is_reversed"] else card["upright"]

        text += f"🔹 *{pos}:* {card['title']} ({orientation})\n{meaning}\n\n"

    text += f"🌙 *Итог:* В контексте вашей ситуации ({situation}), карты показывают общий совет: доверяйте процессу, ищите баланс и будьте открыты к переменам."
    return text

# ================== ХЕНДЛЕРЫ ==================
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Привет! Я виртуальный таролог. ✨\nВыберите тему расклада:", reply_markup=topic_kb())
    await TarotStates.waiting_for_topic.set()

@dp.message_handler(lambda m: m.text in ["🔮 Отношения", "💼 Работа", "💰 Финансы", "🌟 Общий расклад"], state=TarotStates.waiting_for_topic)
async def choose_topic(message: types.Message, state: FSMContext):
    topic = message.text.replace("🔮 ", "").replace("💼 ", "").replace("💰 ", "").replace("🌟 ", "")
    await state.update_data(topic=topic)
    await message.answer(f"📝 Опишите, пожалуйста, вашу ситуацию по теме *{topic}*.", reply_markup=types.ReplyKeyboardRemove())
    await TarotStates.waiting_for_situation.set()

@dp.message_handler(state=TarotStates.waiting_for_situation)
async def describe_situation(message: types.Message, state: FSMContext):
    await state.update_data(situation=message.text)
    await message.answer("Выберите тип расклада:", reply_markup=spread_kb())
    await TarotStates.waiting_for_spread.set()

@dp.message_handler(lambda m: m.text in ["1 карта", "3 карты", "Кельтский крест"], state=TarotStates.waiting_for_spread)
async def make_spread(message: types.Message, state: FSMContext):
    data = await state.get_data()
    topic, situation = data["topic"], data["situation"]
    spread_type = message.text

    if spread_type == "1 карта":
        n = 1
    elif spread_type == "3 карты":
        n = 3
    else:
        n = 10

    drawn = draw_cards(n)
    interpretation = interpret_cards(drawn, situation, topic, spread_type)

    # Отправляем карты
    media = [types.InputMediaPhoto(card["image"], caption=f"{card['title']} ({'перевёрнутая' if card['is_reversed'] else 'прямая'})") if i == 0 else types.InputMediaPhoto(card["image"]) for i, card in enumerate(drawn)]
    await message.answer_media_group(media)

    # Отправляем текст
    await message.answer(interpretation, parse_mode="Markdown")

    save_history(message.from_user.id, {"topic": topic, "situation": situation, "spread": spread_type, "cards": drawn})

    await state.finish()

# ================== ВЕБХУК ==================
async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(dp):
    await bot.delete_webhook()

if __name__ == "__main__":
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
    )
