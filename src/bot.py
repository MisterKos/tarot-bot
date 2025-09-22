import logging
import json
import random
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import set_webhook

API_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = "/webhook"
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", 8080))

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("tarot-bot")

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# === Загружаем колоду ===
with open("data/deck.json", "r", encoding="utf-8") as f:
    TAROT_DECK = json.load(f)
logger.info("Колода загружена локально из data/deck.json")

# === Клавиатуры ===
def menu_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❤️ Отношения"),
           types.KeyboardButton("💼 Работа"),
           types.KeyboardButton("💰 Финансы"))
    return kb

def spreads_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("🔮 3 карты"),
           types.KeyboardButton("🌟 5 карт"),
           types.KeyboardButton("✨ Кельтский крест"))
    return kb

# === Хранилище состояния пользователей ===
user_state = {}

# === Итоговые шаблоны ===
SUMMARY_TEMPLATES = [
    "✨ Итог расклада:\nТема: *{theme}*\nЗапрос: _{situation}_\n\n"
    "Карты указывают, что судьба открывает перед вами новые возможности. Главное — слушать свою интуицию и не спешить с решениями.",

    "🌟 Заключение:\nВы выбрали тему *{theme}*, описали её так: _{situation}_.\n\n"
    "Расклад советует обратить внимание на внутреннюю гармонию. В ближайшее время обстоятельства будут складываться в вашу пользу, если действовать осознанно.",

    "🔮 Совет карт:\nВаш запрос: _{situation}_ (сфера: *{theme}*).\n\n"
    "Карты говорят о переменах и возможностях для роста. Итог — держите сердце и разум открытыми, тогда вы получите больше, чем ожидаете.",

    "🌌 Послание расклада:\nТема *{theme}* связана с вашим вопросом: _{situation}_.\n\n"
    "Карты показывают, что сейчас важно сделать паузу, переосмыслить происходящее и довериться процессу. Время работает на вас."
]

# === Обработчики ===
@dp.message_handler(commands=["start"])
async def cmd_start(m: types.Message):
    user_state[m.from_user.id] = {}
    await m.answer("Привет! Я Таро-бот 🎴\nВыберите сферу для расклада:", reply_markup=menu_kb())

@dp.message_handler(commands=["menu"])
async def cmd_menu(m: types.Message):
    user_state[m.from_user.id] = {}
    await m.answer("Выберите сферу для расклада:", reply_markup=menu_kb())

@dp.message_handler(lambda m: m.text in ["❤️ Отношения", "💼 Работа", "💰 Финансы"])
async def choose_theme(m: types.Message):
    user_state[m.from_user.id] = {"theme": m.text}
    await m.answer(
        "✍️ Опишите, пожалуйста, вашу ситуацию своими словами.\n"
        "Например: 'Мы с Сергеем поссорились и я хочу понять, есть ли будущее' или 'Стоит ли менять работу'."
    )

@dp.message_handler(lambda m: m.from_user.id in user_state and "theme" in user_state[m.from_user.id] and "situation" not in user_state[m.from_user.id])
async def save_situation(m: types.Message):
    user_state[m.from_user.id]["situation"] = m.text
    await m.answer("Спасибо 🙏 Теперь выберите расклад:", reply_markup=spreads_kb())

@dp.message_handler(lambda m: m.text in ["🔮 3 карты", "🌟 5 карт", "✨ Кельтский крест"])
async def do_spread(m: types.Message):
    user = user_state.get(m.from_user.id, {})
    theme = user.get("theme", "Общее")
    situation = user.get("situation", "Без описания")

    num_cards = 3 if "3" in m.text else (5 if "5" in m.text else 10)
    drawn_cards = random.sample(TAROT_DECK, num_cards)

    interpretation = []
    for card in drawn_cards:
        if isinstance(card.get("meanings"), list):
            meaning = random.choice(card["meanings"])
        else:
            meaning = card.get("meaning", "Смысл не найден")
        interpretation.append(f"🃏 {card['name']} — {meaning}")

    summary_template = random.choice(SUMMARY_TEMPLATES)
    summary = summary_template.format(theme=theme, situation=situation)

    await m.answer(
        f"Ваш расклад ({m.text}):\n\n" + "\n\n".join(interpretation) + "\n\n" + summary,
        parse_mode="Markdown",
        reply_markup=menu_kb()
    )

@dp.message_handler()
async def fallback(m: types.Message):
    await m.answer("Пожалуйста, выберите тему через /menu или кнопки ниже.", reply_markup=menu_kb())

# === Aiohttp сервер для вебхука ===
async def webhook_handler(request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400)
    update = types.Update.to_object(data)
    await dp.process_update(update)
    return web.Response(text="ok")

async def on_startup(app):
    webhook_url = os.getenv("RENDER_EXTERNAL_URL") + WEBHOOK_PATH
    try:
        await bot.set_webhook(webhook_url)
        logger.info(f"Webhook успешно установлен: {webhook_url}")
    except Exception as e:
        logger.error(f"Ошибка при установке webhook: {e}")

async def on_shutdown(app):
    logger.info("Удаляем webhook...")
    await bot.delete_webhook()

def main():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, webhook_handler)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)

if __name__ == "__main__":
    main()
