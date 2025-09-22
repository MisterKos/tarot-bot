import logging
import os
import json
import random
from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_webhook
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

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

# --- FSM для ожидания ситуации ---
class Form(StatesGroup):
    waiting_for_situation = State()

# --- Инициализация ---
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# фиксируем контекст
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
async def choose_theme(message: types.Message, state: FSMContext):
    theme = message.text.replace("🔮 ", "").replace("💼 ", "").replace("💰 ", "").replace("🌌 ", "")
    await state.update_data(theme=theme)
    await Form.waiting_for_situation.set()
    await message.answer(f"Опишите, пожалуйста, вашу ситуацию по теме *{theme}*. "
                         "Это поможет сделать расклад более точным.")

@dp.message_handler(state=Form.waiting_for_situation)
async def handle_situation(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    theme = user_data.get("theme", "Общий расклад")
    situation = message.text
    cards = draw_cards(3)
    text = interpret_cards(cards, theme, situation)
    await message.answer(text, parse_mode="Markdown", reply_markup=menu_kb())
    await state.finish()

# --- Webhook ---
async def on_startup(dp):
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook установлен: {WEBHOOK_URL}")
    else:
        logger.warning("WEBHOOK_URL не задан!")

async def on_shutdown(dp):
    logger.info("Отключение...")
    await bot.delete_webhook()

def main():
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
    )

if __name__ == "__main__":
    main()
