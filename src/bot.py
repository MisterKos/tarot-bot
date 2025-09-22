# src/bot.py
# -*- coding: utf-8 -*-
import os
import json
import time
import logging
import random
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests

from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_webhook
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

###############################################################################
# Конфигурация
###############################################################################
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tarot-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в переменных окружения")

# Render даёт внешний адрес — используем его для вебхука
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", "5000"))

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}" if RENDER_EXTERNAL_URL else ""

# Пути/источники колоды
LOCAL_DECK_PATH = Path("data/deck.json")
DECK_URL = os.getenv("DECK_URL", "").strip()

# Лимит на частоту раскладов (сек)
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "360"))

# Админы (могут игнорировать кулдаун)
ADMIN_IDS: set = set()
_admin_raw = os.getenv("ADMIN_IDS", "").strip()
if _admin_raw:
    for p in _admin_raw.split(","):
        p = p.strip()
        if p.isdigit():
            ADMIN_IDS.add(int(p))

###############################################################################
# Инициализация бота/Диспетчера/Памяти
###############################################################################
bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot, storage=MemoryStorage())

###############################################################################
# Состояния
###############################################################################
class SpreadStates(StatesGroup):
    kind = State()      # "one" | "three"
    topic = State()     # "relations" | "work" | "money" | "general"
    question = State()  # текст вопроса

###############################################################################
# Данные колоды + служебные структуры
###############################################################################
DECK: Dict[str, Any] = {}
CARDS: List[Dict[str, Any]] = []   # список карточек
IMAGE_BASE: str = ""               # base URL/путь для картинок
LAST_USED_AT: Dict[int, float] = {}  # user_id -> ts последнего расклада

def _load_deck_local() -> Dict[str, Any]:
    if not LOCAL_DECK_PATH.exists():
        raise FileNotFoundError(str(LOCAL_DECK_PATH))
    with LOCAL_DECK_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

def _load_deck_remote(url: str) -> Dict[str, Any]:
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def _normalize_base_url(s: str) -> str:
    # Убираем завершающий / если есть
    return s[:-1] if s.endswith("/") else s

def _pick_cards(n: int, allow_reversed: bool = True, reversals_percent: int = 30) -> List[Dict[str, Any]]:
    if not CARDS:
        return []
    chosen = random.sample(CARDS, k=min(n, len(CARDS)))
    out = []
    for c in chosen:
        is_reversed = allow_reversed and (random.randint(1, 100) <= reversals_percent)
        out.append({
            "code": c.get("code"),
            "title_en": c.get("title_en"),
            "title_ru": c.get("title_ru"),
            "image": c.get("image"),
            "upright": c.get("upright") or "",
            "reversed": c.get("reversed") or "",
            "reversed_flag": is_reversed,
        })
    return out

def _cooldown_left(user_id: int) -> int:
    if user_id in ADMIN_IDS:
        return 0
    last = LAST_USED_AT.get(user_id, 0.0)
    delta = time.time() - last
    left = COOLDOWN_SECONDS - int(delta)
    return max(0, left)

def _set_used_now(user_id: int) -> None:
    LAST_USED_AT[user_id] = time.time()

def _cards_text_block(spread_kind: str, cards: List[Dict[str, Any]]) -> str:
    # Текстовая сводка расклада с краткими подписями
    if spread_kind == "one":
        c = cards[0]
        dir_text = "перевёрнута" if c["reversed_flag"] else "прямая"
        title = c.get("title_ru") or c.get("title_en") or c.get("code", "карта")
        meaning = (c["reversed"] if c["reversed_flag"] else c["upright"]) or "Описание скоро добавим."
        return f"🃏 <b>1 карта</b>\n<b>{title}</b> ({dir_text})\n\n{meaning}"
    else:
        labels = ["Прошлое", "Настоящее", "Будущее"]
        lines = [f"🔮 <b>3 карты</b>"]
        for label, c in zip(labels, cards):
            dir_text = "перевёрнута" if c["reversed_flag"] else "прямая"
            title = c.get("title_ru") or c.get("title_en") or c.get("code", "карта")
            meaning = (c["reversed"] if c["reversed_flag"] else c["upright"]) or "Описание скоро добавим."
            lines.append(f"\n<b>{label}:</b> {title} ({dir_text})\n{meaning}")
        return "\n".join(lines)

def _card_image_url(card: Dict[str, Any]) -> Optional[str]:
    img = card.get("image")
    if not img or not IMAGE_BASE:
        return None
    return f"{IMAGE_BASE}/{img}"

###############################################################################
# UI клавиатуры
###############################################################################
def main_menu_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("🃏 1 карта — совет"))
    kb.add(KeyboardButton("🔮 3 карты — п/н/б"))
    return kb

TOPIC_INLINE_KB = InlineKeyboardMarkup(row_width=2)
TOPIC_INLINE_KB.add(
    InlineKeyboardButton("❤️ Отношения", callback_data="topic:relations"),
    InlineKeyboardButton("💼 Работа", callback_data="topic:work"),
    InlineKeyboardButton("💰 Деньги", callback_data="topic:money"),
    InlineKeyboardButton("✨ Общее", callback_data="topic:general"),
)

###############################################################################
# Хэндлеры
###############################################################################
@dp.message_handler(commands=["start"])
async def cmd_start(m: types.Message, state: FSMContext):
    await state.finish()
    await m.answer(
        "Привет! Я делаю онлайн-расклады на Таро Райдер–Уэйт.\n"
        "Выбери тип расклада в меню ниже 👇\n\n"
        "Помни: решения принимаешь ты сам(а). Карты — это подсказки, а не приговор.",
        reply_markup=main_menu_kb(),
    )

@dp.message_handler(commands=["menu"])
async def cmd_menu(m: types.Message, state: FSMContext):
    await state.finish()
    await m.answer("Выбери тип расклада:", reply_markup=main_menu_kb())

@dp.message_handler(commands=["ping"])
async def cmd_ping(m: types.Message):
    await m.answer("pong")

@dp.message_handler(commands=["status"])
async def cmd_status(m: types.Message):
    await m.answer(
        "Статус:\n"
        f"- Колода: {DECK.get('name_ru') or DECK.get('name_en') or 'не загружена'}\n"
        f"- Карт: {len(CARDS)}\n"
        f"- База изображений: {IMAGE_BASE or '—'}\n"
        f"- Кулдаун: {COOLDOWN_SECONDS} сек\n"
        f"- Вебхук: {'OK' if WEBHOOK_URL else 'не сконфигурирован'}",
    )

@dp.message_handler(commands=["resetwebhook"])
async def cmd_resetwebhook(m: types.Message):
    if not WEBHOOK_URL:
        return await m.answer("RENDER_EXTERNAL_URL не задан. Вебхук нельзя выставить автоматически.")
    await bot.set_webhook(WEBHOOK_URL)
    await m.answer(f"Вебхук переустановлен:\n{WEBHOOK_URL}")

# Кнопки меню (тексты)
@dp.message_handler(lambda msg: msg.text and msg.text.startswith("🃏"))
async def choose_onecard(m: types.Message, state: FSMContext):
    left = _cooldown_left(m.from_user.id)
    if left > 0:
        return await m.answer(f"Подожди ещё {left} сек перед новым раскладом 🙏")

    await state.update_data(kind="one")
    await SpreadStates.topic.set()
    await m.answer("На какую тему делаем расклад?", reply_markup=types.ReplyKeyboardRemove())
    await m.answer("Выбери тему:", reply_markup=TOPIC_INLINE_KB)

@dp.message_handler(lambda msg: msg.text and msg.text.startswith("🔮"))
async def choose_threecards(m: types.Message, state: FSMContext):
    left = _cooldown_left(m.from_user.id)
    if left > 0:
        return await m.answer(f"Подожди ещё {left} сек перед новым раскладом 🙏")

    await state.update_data(kind="three")
    await SpreadStates.topic.set()
    await m.answer("На какую тему делаем расклад?", reply_markup=types.ReplyKeyboardRemove())
    await m.answer("Выбери тему:", reply_markup=TOPIC_INLINE_KB)

# Выбор темы (inline)
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("topic:"), state=SpreadStates.topic)
async def topic_selected(cq: types.CallbackQuery, state: FSMContext):
    topic = cq.data.split(":", 1)[1]
    await state.update_data(topic=topic)
    await SpreadStates.question.set()
    await cq.message.edit_reply_markup()  # убрать кнопки
    await cq.message.answer("Сформулируй свой вопрос в одном-двух предложениях.")
    await cq.answer()

# Получение вопроса и выполнение расклада
@dp.message_handler(state=SpreadStates.question, content_types=types.ContentTypes.TEXT)
async def receive_question_and_spread(m: types.Message, state: FSMContext):
    data = await state.get_data()
    kind = data.get("kind", "one")
    topic = data.get("topic", "general")
    question = m.text.strip()

    # Кулдаун (повторная проверка, если пользователь затянул)
    left = _cooldown_left(m.from_user.id)
    if left > 0:
        await state.finish()
        return await m.answer(f"Подожди ещё {left} сек перед новым раскладом 🙏", reply_markup=main_menu_kb())

    # Выбор карт
    reversals_percent = int(DECK.get("reversals_percent", 30))
    if kind == "one":
        cards = _pick_cards(1, allow_reversed=True, reversals_percent=reversals_percent)
    else:
        cards = _pick_cards(3, allow_reversed=True, reversals_percent=reversals_percent)

    if not cards:
        await state.finish()
        return await m.answer("Колода недоступна. Попробуй позже.", reply_markup=main_menu_kb())

    # Текстовая сводка
    summary = _cards_text_block(kind, cards)
    intro = (
        f"Тема: <b>{topic}</b>\n"
        f"Вопрос: <i>{question}</i>\n\n"
    )
    await m.answer(intro + summary)

    # Картинки карт (если доступны URL)
    for c in cards:
        url = _card_image_url(c)
        if url:
            caption = (c.get("title_ru") or c.get("title_en") or c.get("code", "Карта"))
            if c["reversed_flag"]:
                caption += " (перевёрнута)"
            try:
                await m.answer_photo(url, caption=caption)
            except Exception as e:
                log.warning(f"Не удалось отправить изображение {url}: {e}")

    _set_used_now(m.from_user.id)
    await state.finish()
    await m.answer("Готово. Чтобы сделать новый расклад — нажми /menu", reply_markup=main_menu_kb())

###############################################################################
# Вебхук-роут и стартап/шутдаун
###############################################################################
async def on_startup(dp: Dispatcher):
    # 1) Загрузка колоды
    global DECK, CARDS, IMAGE_BASE
    try:
        if LOCAL_DECK_PATH.exists():
            DECK = _load_deck_local()
            log.info("Колода загружена локально из data/deck.json")
        elif DECK_URL:
            DECK = _load_deck_remote(DECK_URL)
            log.info(f"Колода загружена по URL: {DECK_URL}")
        else:
            DECK = {}
            log.error("Колода не загружена: нет data/deck.json и DECK_URL")
    except Exception as e:
        DECK = {}
        log.error(f"Не удалось загрузить колоду: {e}")

    CARDS = DECK.get("cards", []) if isinstance(DECK, dict) else []
    IMAGE_BASE = _normalize_base_url(DECK.get("image_base_url", "")) if isinstance(DECK, dict) else ""

    # 2) Вебхук
    if not WEBHOOK_URL:
        log.warning("RENDER_EXTERNAL_URL не задан — вебхук автоматически не выставлен.")
    else:
        await bot.set_webhook(WEBHOOK_URL)
        log.info(f"Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(dp: Dispatcher):
    try:
        await bot.delete_webhook()
    except Exception:
        pass
    await dp.storage.close()
    await dp.storage.wait_closed()

###############################################################################
# Запуск
###############################################################################
if __name__ == "__main__":
    # Вебхук сервер на Render: должен слушать порт, который Render задаёт в $PORT
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
    )
