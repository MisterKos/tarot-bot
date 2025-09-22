import os
import json
import random
import logging
from typing import List, Dict, Any

import requests
from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_webhook

# ----------------------------
# ENV
# ----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DECK_URL = os.getenv("DECK_URL", "").strip()  # jsDelivr URL к deck.json

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в переменных окружения")

# Render отдаёт внешний адрес сервиса в переменной RENDER_EXTERNAL_URL
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
# Под какой порт слушаем (Render задаёт PORT)
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", "10000"))

# Путь вебхука (делаем “секретным” — включаем токен)
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
# Полный URL вебхука. Если Render дал внешний URL — используем его.
if RENDER_EXTERNAL_URL:
    WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"
else:
    # запасной вариант: если переменной нет (локальный запуск)
    WEBHOOK_URL = f"http://localhost:{WEBAPP_PORT}{WEBHOOK_PATH}"

# ----------------------------
# ЛОГИ
# ----------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tarot-bot")

# ----------------------------
# БОТ/ДИСПЕТЧЕР
# ----------------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# ----------------------------
# ЗАГРУЗКА КОЛОДЫ
# ----------------------------
deck: Dict[str, Any] = {"cards": []}

def load_deck() -> Dict[str, Any]:
    """
    Пытаемся прочитать локальный data/deck.json,
    если нет — тянем по DECK_URL (jsDelivr) и кешируем в памяти.
    """
    # 1) локальный файл (на всякий случай)
    local_path = "data/deck.json"
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                d = json.load(f)
                log.info("Колода загружена локально: %s карт", len(d.get("cards", [])))
                return d
        except Exception as e:
            log.warning("Не удалось прочитать локальную колоду: %r", e)

    # 2) CDN
    if DECK_URL:
        try:
            r = requests.get(DECK_URL, timeout=10)
            r.raise_for_status()
            d = r.json()
            log.info("Колода загружена с %s: %s карт", DECK_URL, len(d.get("cards", [])))
            return d
        except Exception as e:
            log.error("Не удалось загрузить колоду по URL (%s): %r", DECK_URL, e)

    log.error("Колода не загружена ни локально, ни по URL — работаю с пустой.")
    return {"cards": []}

deck = load_deck()
cards: List[Dict[str, Any]] = deck.get("cards", [])
image_base_url = deck.get("image_base_url", "").rstrip("/")

# ----------------------------
# ХЕЛПЕРЫ
# ----------------------------
def pick_random_card() -> Dict[str, Any]:
    if not cards:
        return {}
    card = random.choice(cards).copy()
    # решаем ориентацию
    reversed_percent = deck.get("reversals_percent", 30)
    is_reversed = random.randint(1, 100) <= reversed_percent
    card["is_reversed"] = is_reversed
    return card

def card_caption(card: Dict[str, Any]) -> str:
    title_ru = card.get("title_ru") or card.get("title_en") or "Карта"
    orientation = "Перевёрнутая" if card.get("is_reversed") else "Прямая"
    return f"{title_ru}\n{orientation}"

def card_image_url(card: Dict[str, Any]) -> str:
    img_name = card.get("image", "")
    if not img_name:
        return ""
    if image_base_url:
        return f"{image_base_url}/{img_name}"
    return img_name  # на случай, если уже полный URL

# ----------------------------
# ХЕНДЛЕРЫ
# ----------------------------
@dp.message_handler(commands=["start", "help"])
async def start_help(m: types.Message):
    text = (
        "Привет! Я Таро-бот 🔮\n\n"
        "Команды:\n"
        "/card — вытянуть случайную карту\n"
        "/three — три карты (прошлое/настоящее/будущее)\n"
    )
    await m.reply(text)

@dp.message_handler(commands=["card"])
async def one_card(m: types.Message):
    card = pick_random_card()
    if not card:
        await m.reply("Колода пока недоступна 😕")
        return
    caption = card_caption(card)
    img_url = card_image_url(card)
    if img_url:
        await m.answer_photo(photo=img_url, caption=caption)
    else:
        await m.reply(caption)

@dp.message_handler(commands=["three"])
async def three_cards(m: types.Message):
    if len(cards) < 3:
        await m.reply("Карточек пока мало для трёхкартного расклада 😕")
        return
    chosen = random.sample(cards, 3)
    for i, card in enumerate(chosen, start=1):
        card = card.copy()
        reversed_percent = deck.get("reversals_percent", 30)
        card["is_reversed"] = random.randint(1, 100) <= reversed_percent
        caption = f"{i}/3 • " + card_caption(card)
        img_url = card_image_url(card)
        if img_url:
            await m.answer_photo(photo=img_url, caption=caption)
        else:
            await m.reply(caption)

# ----------------------------
# ВЕБХУКИ (aiogram v2)
# ----------------------------
async def on_startup(dp: Dispatcher):
    # ставим вебхук
    await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
    log.info("Webhook установлен: %s", WEBHOOK_URL)

async def on_shutdown(dp: Dispatcher):
    log.info("Удаляю вебхук…")
    await bot.delete_webhook()

def main():
    # запуск веб-сервера aiohttp, который слушает PORT и принимает вебхуки
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
