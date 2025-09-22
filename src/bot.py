import os
import logging
import random
import requests
from aiogram import Bot, Dispatcher, executor, types

BOT_TOKEN = os.getenv("BOT_TOKEN")
DECK_URL = os.getenv("DECK_URL")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# Загружаем JSON колоды при старте
deck = {}
try:
    r = requests.get(DECK_URL)
    r.raise_for_status()
    deck = r.json()
except Exception as e:
    logging.error(f"Не удалось загрузить колоду: {e}")

cards = deck.get("cards", [])
base_url = deck.get("image_base_url", "")

@dp.message_handler(commands=["start", "help"])
async def send_welcome(message: types.Message):
    await message.answer(
        "🔮 Привет! Это Таро-бот.\n"
        "Доступные расклады:\n"
        "/onecard — одна карта (совет)\n"
        "/threecards — три карты (прошлое/настоящее/будущее)\n\n"
        "Помните: все решения вы принимаете сами ✨"
    )

@dp.message_handler(commands=["onecard"])
async def one_card(message: types.Message):
    card = random.choice(cards)
    img = base_url + card["image"]
    await message.answer_photo(img, caption=f"🔮 {card['title_ru']} ({card['title_en']})")

@dp.message_handler(commands=["threecards"])
async def three_cards(message: types.Message):
    sample = random.sample(cards, 3)
    captions = ["Прошлое", "Настоящее", "Будущее"]
    for c, title in zip(sample, captions):
        img = base_url + c["image"]
        await message.answer_photo(img, caption=f"{title}: {c['title_ru']} ({c['title_en']})")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
