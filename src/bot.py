import os
import json
import random
import logging
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor

# ---------------- CONFIG ----------------
API_TOKEN = os.getenv("TELEGRAM_TOKEN") or "8162496264:AAEomZ-eUtqf_jESd6VZSpdHBYJsjPgds7o"

DATA_PATH = "data/deck.json"
HISTORY_PATH = "data/history.json"

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tarot-bot")

# ---------------- BOT INIT ----------------
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ---------------- LOAD DECK ----------------
with open(DATA_PATH, "r", encoding="utf-8") as f:
    DECK = json.load(f)["cards"]

IMAGE_BASE_URL = "https://cdn.jsdelivr.net/gh/MisterKos/tarot-bot@main/assets/rw/cards/"

# ---------------- HISTORY ----------------
if os.path.exists(HISTORY_PATH):
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        HISTORY = json.load(f)
else:
    HISTORY = defaultdict(list)

def save_history():
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(HISTORY, f, ensure_ascii=False, indent=2)

# ---------------- KEYBOARDS ----------------
menu_kb = ReplyKeyboardMarkup(resize_keyboard=True)
menu_kb.add("🔮 Отношения", "💼 Работа")
menu_kb.add("💰 Финансы", "🌌 Общий расклад")

def spreads_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("1 карта", "3 карты", "Кельтский крест")
    return kb

# ---------------- HELPERS ----------------
def draw_cards(n=1):
    return random.sample(DECK, n)

def format_interpretation(card, position=None):
    direction = random.choice(["upright", "reversed"])
    title = f"{card['title_ru']} ({'Прямое' if direction == 'upright' else 'Перевёрнутое'})"
    text = card[direction] if card[direction] != "…" else "Здесь идёт детальное толкование карты."
    pos = f"Позиция: {position}\n" if position else ""
    return f"✨ {title}\n{pos}{text}"

def final_summary(topic, situation, cards):
    summary = f"🔔 Итог по теме «{topic}»:\n\n"
    summary += f"Ситуация: {situation}\n\n"
    summary += "Карты раскрывают многослойную картину происходящего. "
    summary += "Опытный таролог сказал бы, что эти образы указывают на скрытые причины, возможные исходы и внутренние ресурсы. "
    summary += "Важно обратить внимание на то, что совпадения не случайны, а сами карты словно ведут вас к переосмыслению.\n\n"
    summary += "🌟 Совет: примите этот расклад как зеркало, позволяющее заглянуть вглубь себя. "
    summary += "Используйте полученные инсайты для мудрых решений."
    return summary

# ---------------- FSM ----------------
user_state = {}
user_topic = {}
user_situation = {}

# ---------------- HANDLERS ----------------
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)
    await message.answer(
        "Привет! 🙌 Я Таро-бот.\nВыберите тему для расклада:",
        reply_markup=menu_kb
    )
    user_state[user_id] = "choose_topic"

@dp.message_handler(lambda m: m.text in ["🔮 Отношения", "💼 Работа", "💰 Финансы", "🌌 Общий расклад"])
async def choose_topic(message: types.Message):
    user_id = str(message.from_user.id)
    topic = message.text
    user_topic[user_id] = topic
    user_state[user_id] = "describe_situation"
    await message.answer("Опиши, пожалуйста, свою ситуацию подробнее…")

@dp.message_handler(lambda m: user_state.get(str(m.from_user.id)) == "describe_situation")
async def describe_situation(message: types.Message):
    user_id = str(message.from_user.id)
    user_situation[user_id] = message.text
    user_state[user_id] = "choose_spread"
    await message.answer("Какой расклад сделаем?", reply_markup=spreads_kb())

@dp.message_handler(lambda m: m.text in ["1 карта", "3 карты", "Кельтский крест"])
async def choose_spread(message: types.Message):
    user_id = str(message.from_user.id)
    topic = user_topic.get(user_id, "Общий")
    situation = user_situation.get(user_id, "—")

    if message.text == "1 карта":
        cards = draw_cards(1)
    elif message.text == "3 карты":
        cards = draw_cards(3)
    else:
        cards = draw_cards(10)

    result = []
    for idx, card in enumerate(cards, start=1):
        interpretation = format_interpretation(card, position=idx)
        photo_url = IMAGE_BASE_URL + card["image"]
        await message.answer_photo(photo=photo_url, caption=interpretation)
        result.append(interpretation)

    summary = final_summary(topic, situation, cards)
    await message.answer(summary, reply_markup=menu_kb)

    # Сохраняем историю
    HISTORY.setdefault(user_id, deque(maxlen=5))
    HISTORY[user_id].appendleft({
        "topic": topic,
        "situation": situation,
        "cards": [c["title_ru"] for c in cards],
        "summary": summary
    })
    save_history()

    user_state[user_id] = "choose_topic"

# ---------------- RUN ----------------
if __name__ == "__main__":
    logger.info("Бот запущен")
    executor.start_polling(dp, skip_updates=True)
