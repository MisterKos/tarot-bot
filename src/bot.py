import os
import json
import random
import logging
from typing import List, Dict
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.executor import Executor

# ------------------------------------------------------------
# Логирование
# ------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tarot-bot")

# ------------------------------------------------------------
# Конфиг
# ------------------------------------------------------------
TOKEN = os.getenv("BOT_TOKEN", "").strip()
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip()

if not TOKEN:
    raise RuntimeError("Не указан BOT_TOKEN")

bot = Bot(token=TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot)

# ------------------------------------------------------------
# Загрузка колоды
# ------------------------------------------------------------
DECK_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "deck.json")
with open(DECK_PATH, "r", encoding="utf-8") as f:
    DECK = json.load(f)

log.info("Колода загружена локально из data/deck.json")

# ------------------------------------------------------------
# Утилиты для клавиатуры
# ------------------------------------------------------------
def menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("🔮 Отношения"))
    kb.add(KeyboardButton("💼 Работа"))
    kb.add(KeyboardButton("💰 Деньги"))
    kb.add(KeyboardButton("🌌 Общий расклад"))
    return kb

# ------------------------------------------------------------
# Работа с картами
# ------------------------------------------------------------
def draw_cards(n: int = 3) -> List[Dict]:
    cards = random.sample(DECK, n)
    for c in cards:
        c["reversed"] = random.choice([True, False])
    return cards

def interpret_card(card: Dict) -> str:
    name = card["name"]
    meaning = card["meaning_rev"] if card.get("reversed") else card["meaning_up"]
    orientation = "перевёрнутая" if card.get("reversed") else "прямая"
    return f"<b>{name}</b> ({orientation}): {meaning}"

# ------------------------------------------------------------
# Глубокая интерпретация расклада
# ------------------------------------------------------------
def summarize_spread(cards: List[Dict], theme: str = "Общий") -> str:
    majors = [c for c in cards if c.get("arcana") == "major"]
    reversed_cards = [c for c in cards if c.get("reversed")]
    suits = [c.get("suit") for c in cards if c.get("suit")]

    text_parts = []

    # Вступление
    if len(majors) >= 2:
        text_parts.append(
            "✨ Перед вами период судьбоносных перемен — старшие арканы указывают, "
            "что события будут иметь длительное влияние на вашу жизнь."
        )
    else:
        text_parts.append(
            "Карты отражают текущие процессы и внутренние переживания, "
            "дают подсказки для ближайших шагов."
        )

    # Прямые / перевёрнутые
    if reversed_cards:
        text_parts.append(
            "Перевёрнутые карты показывают наличие сомнений, внутренних блоков "
            "или задержек в развитии ситуации."
        )
    else:
        text_parts.append("Все карты выпали прямыми — это усиливает позитивный характер расклада.")

    # По масти
    if suits:
        dominant = max(set(suits), key=suits.count)
        if dominant == "cups":
            text_parts.append(
                "Доминируют Кубки — это сфера эмоций и отношений. "
                "Главное сейчас — слушать сердце и быть искренним."
            )
        elif dominant == "swords":
            text_parts.append(
                "Много Мечей в раскладе — период интеллектуального напряжения, "
                "анализа и возможных конфликтов."
            )
        elif dominant == "pentacles":
            text_parts.append(
                "Пентакли преобладают — акцент на материальной стороне жизни, "
                "финансах и стабильности."
            )
        elif dominant == "wands":
            text_parts.append(
                "Жезлы ведут расклад — время для действий, смелых решений и инициативы."
            )

    # Тема
    if theme == "Отношения":
        text_parts.append(
            "Тема расклада — отношения. Здесь проявляются вопросы доверия, "
            "чувств и выбора между сердцем и разумом."
        )
    elif theme == "Работа":
        text_parts.append(
            "Тема расклада — работа. Карты указывают на карьерные перемены, "
            "возможности роста и важность проявления инициативы."
        )
    elif theme == "Деньги":
        text_parts.append(
            "Тема расклада — финансы. Важен баланс между расходами и накоплениями, "
            "а также умение вовремя использовать шансы."
        )
    else:
        text_parts.append(
            "Общий расклад показывает ваш личный путь, внутренние уроки "
            "и стремление к гармонии."
        )

    # Заключение
    text_parts.append(
        "Карты дают направление, но выбор всегда остаётся за вами. "
        "Используйте подсказки мудро, чтобы извлечь максимум пользы."
    )

    return "\n\n".join(text_parts)

# ------------------------------------------------------------
# Хэндлеры
# ------------------------------------------------------------
@dp.message_handler(commands=["start"])
async def cmd_start(m: types.Message):
    await m.answer(
        "Привет! Это бот раскладов на Таро 🎴\n\n"
        "Выберите тему для расклада:",
        reply_markup=menu_kb(),
    )

@dp.message_handler(commands=["menu"])
async def cmd_menu(m: types.Message):
    await m.answer("Выберите тему расклада:", reply_markup=menu_kb())

@dp.message_handler(lambda m: m.text in ["🔮 Отношения", "💼 Работа", "💰 Деньги", "🌌 Общий расклад"])
async def cmd_spread(m: types.Message):
    theme_map = {
        "🔮 Отношения": "Отношения",
        "💼 Работа": "Работа",
        "💰 Деньги": "Деньги",
        "🌌 Общий расклад": "Общий",
    }
    theme = theme_map.get(m.text, "Общий")
    cards = draw_cards(3)

    # Карточки
    card_texts = [interpret_card(c) for c in cards]
    spread_text = "\n\n".join(card_texts)

    # Итог
    summary = summarize_spread(cards, theme)

    await m.answer(f"Ваш расклад ({theme}):\n\n{spread_text}\n\n{summary}")

@dp.message_handler()
async def on_free_text(m: types.Message):
    await m.answer("Выберите расклад через /menu.", reply_markup=menu_kb())

# ------------------------------------------------------------
# Webhook handler
# ------------------------------------------------------------
async def webhook_handler(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return web.Response()
    update = types.Update.to_object(data)
    Bot.set_current(bot)
    Dispatcher.set_current(dp)
    await dp.process_update(update)
    return web.Response()

# ------------------------------------------------------------
# Запуск приложения
# ------------------------------------------------------------
def main():
    app = web.Application()
    app.router.add_post("/webhook", webhook_handler)

    async def on_startup(app_):
        if not RENDER_EXTERNAL_URL:
            log.warning("RENDER_EXTERNAL_URL не задан")
            return
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
        try:
            await bot.set_webhook(webhook_url)
            log.info("Webhook установлен: %s", webhook_url)
        except Exception as e:
            log.error("Ошибка при установке webhook: %s", e)

    app.on_startup.append(on_startup)

    port = int(os.getenv("PORT", 5000))
    web.run_app(app, host="0.0.0.0", port=port, print=None)

if __name__ == "__main__":
    main()
