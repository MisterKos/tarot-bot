import os
import json
import random
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# 🔹 Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tarot-bot")

# 🔹 Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", 5000))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# 🔹 Загружаем колоду
with open("data/deck.json", "r", encoding="utf-8") as f:
    DECK = json.load(f)

# 🔹 Клавиатура меню
def menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("Отношения 💞"))
    kb.add(KeyboardButton("Работа ⚒️"))
    kb.add(KeyboardButton("Финансы 💰"))
    kb.add(KeyboardButton("Общий расклад 🔮"))
    return kb

# 🔹 Состояния пользователей
user_state = {}

# 📌 Итоговый анализ как у таролога
def generate_summary(theme, situation, cards):
    cards_text = "\n".join([f"— {c['name']}: {c['meaning']}" for c in cards])

    endings = [
        (
            "Этот расклад словно подсвечивает скрытые пружины вашей ситуации. "
            "Карты намекают, что ключ к изменениям лежит внутри вас. "
            "Совет: примите происходящее как этап пути, на котором важно сохранять внутреннее равновесие."
        ),
        (
            "Карты словно подталкивают к переоценке привычного. "
            "Перед вами открываются новые горизонты, но нужно отпустить старые страхи. "
            "Совет: доверяйте процессу и делайте шаги вперёд, даже если дорога ещё неясна."
        ),
        (
            "Выпавшие карты указывают на важный поворот в вашей истории. "
            "Даже трудности здесь выступают как трамплин для роста. "
            "Совет: ищите баланс между разумом и чувствами, и тогда ситуация разрешится наилучшим образом."
        ),
    ]
    final_text = random.choice(endings)

    return (
        f"✨ Тема: {theme}\n"
        f"Ваш запрос: {situation}\n\n"
        f"Карты, которые выпали:\n{cards_text}\n\n"
        f"🔮 Итог расклада:\n{final_text}"
    )

# 🔹 Команда /start
@dp.message_handler(commands=["start"])
async def cmd_start(m: types.Message):
    await m.answer(
        "Привет! Я Таро-бот 🔮\n"
        "Выберите тему для расклада:",
        reply_markup=menu_kb()
    )

# 🔹 Выбор темы
@dp.message_handler(lambda m: m.text in ["Отношения 💞", "Работа ⚒️", "Финансы 💰", "Общий расклад 🔮"])
async def on_theme(m: types.Message):
    user_state[m.from_user.id] = {"theme": m.text, "awaiting_situation": True}
    await m.answer(
        f"Вы выбрали тему: *{m.text}*\n\n"
        "Теперь опишите свою ситуацию подробнее (например: «отношения с Иваном», "
        "«устроился в новую фирму» или «беспокоит стабильность дохода»).",
        parse_mode="Markdown"
    )

# 🔹 Описание ситуации + расклад
@dp.message_handler(lambda m: m.from_user.id in user_state and user_state[m.from_user.id].get("awaiting_situation"))
async def on_situation(m: types.Message):
    state = user_state[m.from_user.id]
    theme = state["theme"]
    situation = m.text

    cards = random.sample(DECK, 3)
    summary = generate_summary(theme, situation, cards)

    await m.answer(summary)
    user_state.pop(m.from_user.id, None)

# 🔹 Любой другой текст
@dp.message_handler()
async def on_free_text(m: types.Message):
    await m.answer("Выберите тему через меню ниже 👇", reply_markup=menu_kb())

# 🔹 Веб-сервер aiohttp
async def on_startup(app):
    await bot.delete_webhook()
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.close()

async def webhook_handler(request):
    try:
        data = await request.json()
        update = types.Update.to_object(data)
        if update:
            await dp.process_update(update)
    except Exception as e:
        logger.error(f"Ошибка при обработке апдейта: {e}")
    return web.Response()

app = web.Application()
app.router.add_post(WEBHOOK_PATH, webhook_handler)
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)
