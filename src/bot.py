# -*- coding: utf-8 -*-
"""
Telegram бот: Таро Онлайн (Райдер–Уэйт)
aiogram 2.25.1, long-polling (Render free plan совместим)

Переменные окружения:
- BOT_TOKEN  — токен бота от BotFather
- DECK_URL   — (необязательно) URL до deck.json; используется как фолбэк
Локальный JSON берётся из data/deck.json (если присутствует в репозитории).
"""

import os
import json
import random
import logging
import requests
from aiogram import Bot, Dispatcher, executor, types

# -----------------------
# Настройки/инициализация
# -----------------------
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DECK_URL = os.getenv("DECK_URL", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN в переменных окружения.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# -----------------------
# Загрузка колоды (JSON)
# -----------------------
deck = {"code": "rw", "name_ru": "Райдер–Уэйт (классика)", "reversals_percent": 30, "cards": []}
cards = []

try:
    # 1) Пытаемся прочитать локальный файл
    with open("data/deck.json", "r", encoding="utf-8") as f:
        deck = json.load(f)
        cards = deck.get("cards", [])
        print(f"Колода успешно загружена локально: {len(cards)} карт.")
except Exception as e:
    logging.error(f"Не удалось прочитать локальную колоду: {e}")
    # 2) Фолбэк: пробуем URL, если задан
    try:
        if DECK_URL:
            r = requests.get(DECK_URL, timeout=10)
            r.raise_for_status()
            deck = r.json()
            cards = deck.get("cards", [])
            print(f"Колода загружена по URL: {len(cards)} карт.")
        else:
            print("DECK_URL не задан и локальная колода недоступна.")
    except Exception as e2:
        logging.error(f"Фатально: не удалось загрузить колоду ни локально, ни по URL: {e2}")
        deck = {"cards": []}
        cards = []

IMAGE_BASE = (deck.get("image_base_url") or "").strip()

# -----------------------
# Вспомогательные функции
# -----------------------
def roll_orientation() -> bool:
    """True -> перевёрнутая, False -> прямая."""
    rev_pct = int(deck.get("reversals_percent", 30) or 0)
    return random.randint(1, 100) <= rev_pct

def card_title(card: dict, reversed_: bool) -> str:
    name = card.get("title_ru") or card.get("title_en") or card.get("code", "карта")
    return f"{name} {'(перевёрнутая)' if reversed_ else ''}"

def card_meaning(card: dict, reversed_: bool) -> str:
    key = "reversed" if reversed_ else "upright"
    text = (card.get(key) or "").strip()
    return text

def card_image_url(card: dict) -> str:
    """Вернёт абсолютный URL изображения, если возможно (иначе пустую строку).
    Важно: Telegram предпочитает HTTPS для фото. Если у вас только HTTP,
    лучше отправлять текст + ссылку, а не photo.
    """
    img_name = (card.get("image") or "").strip()
    if not IMAGE_BASE or not img_name:
        return ""
    # гарантируем одиночный слэш
    base = IMAGE_BASE
    if not base.endswith("/"):
        base += "/"
    return base + img_name

async def send_card(message: types.Message, card: dict, reversed_: bool, position_hint: str = ""):
    """Отправляет карту. Если HTTPS-картинки нет — шлём текст с ссылкой."""
    title = card_title(card, reversed_)
    meaning = card_meaning(card, reversed_)
    url = card_image_url(card)

    header = f"**{position_hint + ': ' if position_hint else ''}{title}**"
    body = f"\n{meaning}" if meaning else ""
    caption_md = (header + body).strip()

    # Если url начинается на https — пробуем прислать фото; иначе только текст + ссылка
    if url.startswith("https://"):
        try:
            await message.answer_photo(
                url,
                caption=caption_md,
                parse_mode="Markdown"
            )
            return
        except Exception as e:
            logging.warning(f"Не удалось отправить фото по {url}: {e}")

    # текстовый вариант (для http-ссылок и любых ошибок)
    if url:
        caption_md += f"\n\n[Изображение карты]({url})"
    await message.answer(caption_md, parse_mode="Markdown", disable_web_page_preview=False)

# -----------------------
# Команды
# -----------------------
START_TEXT = (
    "Привет! Я бот для онлайн-раскладов на Таро Райдер–Уэйт.\n\n"
    "Доступные команды:\n"
    "/one — 1 карта (совет/подсказка)\n"
    "/three — 3 карты (прошлое/настоящее/будущее)\n"
    "/help — как пользоваться ботом\n"
)

HELP_TEXT = (
    "Этот бот делает онлайн-расклады на Таро Райдер–Уэйт.\n\n"
    "Доступные быстрые расклады:\n"
    "• /one — одна карта (совет / подсказка)\n"
    "• /three — три карты (прошлое / настоящее / будущее)\n\n"
    "_Помните: карты — это инструмент для размышлений, а не приговор._\n"
    "Все решения в жизни вы принимаете самостоятельно. Всегда есть выбор — "
    "и есть последствия этого выбора."
)

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await message.answer(START_TEXT)

@dp.message_handler(commands=["help"])
async def cmd_help(message: types.Message):
    await message.answer(HELP_TEXT, parse_mode="Markdown")

@dp.message_handler(commands=["deck"])
async def cmd_deck(message: types.Message):
    name = deck.get("name_ru") or deck.get("name_en") or deck.get("code", "колода")
    await message.answer(f"Активная колода: *{name}*. Карт: {len(cards)}.", parse_mode="Markdown")

@dp.message_handler(commands=["one"])
async def cmd_one(message: types.Message):
    if not cards:
        await message.answer("Колода не загружена. Попробуйте позже.")
        return
    card = random.choice(cards)
    reversed_ = roll_orientation()
    await send_card(message, card, reversed_)

@dp.message_handler(commands=["three"])
async def cmd_three(message: types.Message):
    if len(cards) < 3:
        await message.answer("Недостаточно карт в колоде. Попробуйте позже.")
        return
    picks = random.sample(cards, 3)
    labels = ["Прошлое", "Настоящее", "Будущее"]
    for i, card in enumerate(picks):
        await send_card(message, card, roll_orientation(), position_hint=labels[i])

# -----------------------
# Запуск поллинга
# -----------------------
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
