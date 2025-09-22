import os
import json
import logging
import random
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.executor import set_webhook

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tarot-bot")

TOKEN = os.getenv("BOT_TOKEN")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")  # https://tarot-bot-xxxx.onrender.com
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{RENDER_URL}{WEBHOOK_PATH}"

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# ------------------ Загрузка колоды ------------------
with open("data/deck.json", "r", encoding="utf-8") as f:
    TAROT_DECK = json.load(f)

# ------------------ Клавиатура меню ------------------
def menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("💖 Отношения"), KeyboardButton("💼 Работа"))
    kb.add(KeyboardButton("💰 Финансы"), KeyboardButton("🌌 Общий расклад"))
    return kb

# ------------------ Интерпретация ------------------
def interpret_card(card, position):
    """Длинное красивое толкование каждой карты"""
    base = f"{card['name']}: {card['meaning_up'] if random.choice([True, False]) else card['meaning_rev']}."
    detail = (
        f"\n🌟 В позиции {position} эта карта указывает на глубинные процессы. "
        f"Она словно зеркало отражает вашу ситуацию: {random.choice(['скрытые мотивы', 'подсознательные страхи', 'новые возможности'])}. "
        f"Важно всмотреться внимательнее — здесь заключён урок, который ведёт к росту."
    )
    return base + detail

def summarize_spread(topic, cards):
    """Финальный вывод как у таролога"""
    text = f"🔮 Итог расклада по теме: *{topic}*\n\n"
    insights = []
    for i, card in enumerate(cards, 1):
        insights.append(interpret_card(card, f'позиции {i}'))
    text += "\n\n".join(insights)
    text += (
        "\n\n✨ Общая картина показывает, что перед вами открываются новые пути. "
        "Совет карт — не бояться перемен и внимательнее слушать внутренний голос. "
        "Сейчас время для осознанных шагов и доверия интуиции."
    )
    return text

# ------------------ Хендлеры ------------------
@dp.message_handler(commands=["start"])
async def cmd_start(m: types.Message):
    await m.answer("Привет! Я Таро-бот 🃏\n\nВыбери тему расклада:", reply_markup=menu_kb())

@dp.message_handler(lambda m: m.text in ["💖 Отношения", "💼 Работа", "💰 Финансы", "🌌 Общий расклад"])
async def ask_context(m: types.Message):
    topic = m.text.replace("💖 ", "").replace("💼 ", "").replace("💰 ", "").replace("🌌 ", "")
    await m.answer(f"Вы выбрали тему *{topic}*.\n\nОпишите свою ситуацию подробнее — как у настоящего таролога 🙏")

    # сохраняем тему в data пользователя
    dp.current_state(user=m.from_user.id).update_data(topic=topic)

@dp.message_handler()
async def make_spread(m: types.Message):
    state = dp.current_state(user=m.from_user.id)
    data = await state.get_data()
    topic = data.get("topic")

    if not topic:
        await m.answer("Пожалуйста, выбери тему расклада через меню:", reply_markup=menu_kb())
        return

    # Делаем расклад на 3 карты
    cards = random.sample(TAROT_DECK, 3)
    spread_text = summarize_spread(topic, cards)

    # Отправляем результат
    for card in cards:
        await m.answer_photo(card["img"], caption=card["name"])
    await m.answer(spread_text, parse_mode="Markdown")

    # Сбрасываем тему, чтобы можно было выбрать заново
    await state.reset_data()

# ------------------ Webhook ------------------
async def webhook_handler(request):
    try:
        data = await request.json()
        update = types.Update.to_object(data)
        if update:
            # 🟢 фикс контекста
            Bot.set_current(bot)
            Dispatcher.set_current(dp)
            await dp.process_update(update)
    except Exception as e:
        logger.error(f"Ошибка при обработке апдейта: {e}")
    return web.Response()

async def on_startup(app):
    await bot.delete_webhook()
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")

def main():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, webhook_handler)
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

if __name__ == "__main__":
    main()
