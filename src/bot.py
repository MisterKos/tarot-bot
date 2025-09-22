import os
import json
import random
import logging
import time
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import requests
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.utils.executor import start_webhook

# =========================
# ENV & constants
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DECK_URL = os.getenv("DECK_URL", "").strip()  # CDN deck.json (jsDelivr)
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "360"))  # 6 минут по умолчанию

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в переменных окружения")

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", "10000"))
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}" if RENDER_EXTERNAL_URL else f"http://localhost:{WEBAPP_PORT}{WEBHOOK_PATH}"

# =========================
# Logging
# =========================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tarot-bot")

# =========================
# Bot / Dispatcher (FSM)
# =========================
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# =========================
# Data dirs & DB
# =========================
DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "history.db"

def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          ts INTEGER NOT NULL,
          spread TEXT NOT NULL,
          category TEXT,
          topic TEXT,
          cards_json TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cooldown (
          user_id INTEGER PRIMARY KEY,
          last_ts INTEGER NOT NULL
        )
    """)
    conn.commit()
    return conn

# =========================
# Deck loading
# =========================
deck: Dict[str, Any] = {"cards": []}
cards: List[Dict[str, Any]] = []
image_base_url: str = ""
reversals_percent: int = 30

def load_deck() -> Dict[str, Any]:
    """
    1) Сначала пытаемся прочитать локальный data/deck.json
    2) Если не вышло — тянем по DECK_URL (jsDelivr)
    """
    local_path = DATA_DIR / "deck.json"
    if local_path.exists():
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                d = json.load(f)
                log.info("Колода загружена локально: %s карт", len(d.get("cards", [])))
                return d
        except Exception as e:
            log.warning("Не удалось прочитать локальную колоду: %r", e)

    if DECK_URL:
        try:
            r = requests.get(DECK_URL, timeout=10)
            r.raise_for_status()
            d = r.json()
            log.info("Колода загружена по URL (%s): %s карт", DECK_URL, len(d.get("cards", [])))
            return d
        except Exception as e:
            log.error("Не удалось загрузить колоду по URL (%s): %r", DECK_URL, e)

    log.error("Колода не загружена ни локально, ни по URL — работаю с пустой.")
    return {"cards": []}

def deck_init():
    global deck, cards, image_base_url, reversals_percent
    deck = load_deck()
    cards = deck.get("cards", [])
    image_base_url = (deck.get("image_base_url") or "").rstrip("/")
    reversals_percent = int(deck.get("reversals_percent", 30))

deck_init()

# =========================
# Helpers: cards & text
# =========================
CATEGORIES = [
    ("relationships", "❤️ Отношения"),
    ("work", "💼 Работа"),
    ("money", "💰 Деньги"),
    ("health", "🩺 Здоровье"),
    ("growth", "🌱 Саморазвитие"),
    ("general", "✨ Общее"),
]

def _is_blank(val: Optional[str]) -> bool:
    return not val or val.strip() == "" or val.strip() == "…"

def pick_card() -> Dict[str, Any]:
    c = random.choice(cards).copy()
    c["is_reversed"] = (random.randint(1, 100) <= reversals_percent)
    return c

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
    return img_name

def meaning_text(card: Dict[str, Any]) -> str:
    is_rev = card.get("is_reversed", False)
    raw = (card.get("reversed") if is_rev else card.get("upright")) or ""
    if not _is_blank(raw):
        return raw.strip()
    title = card.get("title_ru") or card.get("title_en") or "Карта"
    if is_rev:
        return f"{title}: перевёрнутая динамика — тема требует аккуратности, переоценки ожиданий и времени."
    else:
        return f"{title}: прямая динамика — энергия благоприятна, действуйте осознанно и последовательно."

def summarize_reading(topic: str, category_code: str, picked: List[Dict[str, Any]]) -> str:
    rev_count = sum(1 for c in picked if c.get("is_reversed"))
    tendency = "скорее благоприятна" if rev_count <= len(picked) // 2 else "требует осторожности"
    human_cat = dict(CATEGORIES).get(category_code, "✨ Общее")
    advice = "Двигайтесь шаг за шагом, отмечая промежуточные результаты." if rev_count else "Хороший момент для инициативы, но не забывайте о последствиях."
    return (
        f"Тема: {human_cat}. Запрос: {topic}\n"
        f"Перевёрнутых карт: {rev_count} из {len(picked)} — тенденция {tendency}.\n"
        f"Итог: {advice}\n\n"
        "Помните: решения принимаете вы. Любой выбор тянет последствия — выбирайте то, что поддерживает вас в долгую."
    )

# =========================
# Helpers: cooldown & history
# =========================
def get_last_ts(user_id: int) -> Optional[int]:
    with _db() as conn:
        cur = conn.execute("SELECT last_ts FROM cooldown WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None

def set_last_ts(user_id: int, ts: int):
    with _db() as conn:
        conn.execute(
            "INSERT INTO cooldown(user_id, last_ts) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET last_ts=excluded.last_ts",
            (user_id, ts),
        )
        conn.commit()

def check_cooldown(user_id: int) -> Tuple[bool, int]:
    """
    return (allowed, seconds_left)
    """
    now = int(time.time())
    last = get_last_ts(user_id)
    if last is None:
        return True, 0
    diff = now - last
    if diff >= COOLDOWN_SECONDS:
        return True, 0
    return False, COOLDOWN_SECONDS - diff

def save_history(user_id: int, spread: str, category: str, topic: str, picked: List[Dict[str, Any]]):
    payload = {
        "cards": [
            {
                "code": c.get("code"),
                "title_ru": c.get("title_ru"),
                "is_reversed": c.get("is_reversed", False),
            } for c in picked
        ]
    }
    with _db() as conn:
        conn.execute(
            "INSERT INTO history(user_id, ts, spread, category, topic, cards_json) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, int(time.time()), spread, category, topic, json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()

def fetch_history(user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    with _db() as conn:
        cur = conn.execute(
            "SELECT ts, spread, category, topic, cards_json FROM history WHERE user_id=? ORDER BY ts DESC LIMIT ?",
            (user_id, limit),
        )
        out = []
        for ts, spread, category, topic, cards_json in cur.fetchall():
            out.append({
                "ts": ts,
                "spread": spread,
                "category": category,
                "topic": topic,
                "cards": json.loads(cards_json).get("cards", []),
            })
        return out

# =========================
# FSM states
# =========================
class Flow(StatesGroup):
    choosing_spread = State()
    choosing_category_for_one = State()
    entering_topic_for_one = State()
    choosing_category_for_three = State()
    entering_topic_for_three = State()

# =========================
# Keyboards
# =========================
def kb_main() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("1 карта", callback_data="spread:one"),
        InlineKeyboardButton("3 карты", callback_data="spread:three"),
    )
    kb.add(InlineKeyboardButton("🗂 История", callback_data="history:open"))
    return kb

def kb_categories(prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    for code, label in CATEGORIES:
        kb.insert(InlineKeyboardButton(label, callback_data=f"{prefix}:{code}"))
    return kb

# =========================
# Handlers: menu & help
# =========================
@dp.message_handler(commands=["start", "help", "menu"])
async def start_menu(m: types.Message, state: FSMContext):
    text = (
        "Привет! Я Таро-бот 🔮\n\n"
        "Выберите расклад или откройте историю.\n"
        "Важно: это развлекательный сервис. Решения — на вашей стороне."
    )
    await m.answer(text, reply_markup=kb_main())
    await Flow.choosing_spread.set()

# =========================
# Handlers: open history
# =========================
@dp.callback_query_handler(lambda c: c.data == "history:open", state="*")
async def open_history(cq: CallbackQuery, state: FSMContext):
    user_id = cq.from_user.id
    rows = fetch_history(user_id, limit=5)
    if not rows:
        await cq.message.answer("История пуста. Сделайте первый расклад!")
    else:
        parts = ["Последние расклады:"]
        for i, h in enumerate(rows, start=1):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(h["ts"]))
            parts.append(f"{i}) {when} • {h['spread']} • {dict(CATEGORIES).get(h['category'], h['category'])}\n— {h['topic']}")
        await cq.message.answer("\n\n".join(parts))
    await cq.answer()

# =========================
# Handlers: choose spread
# =========================
@dp.callback_query_handler(lambda c: c.data.startswith("spread:"), state=Flow.choosing_spread)
async def choose_spread(cq: CallbackQuery, state: FSMContext):
    spread = cq.data.split(":", 1)[1]  # one | three

    # cooldown check
    allowed, left = check_cooldown(cq.from_user.id)
    if not allowed:
        mins = max(1, left // 60)
        await cq.message.answer(f"Подождите ещё {mins} мин. чтобы не перегружать бота 🙏")
        await cq.answer()
        return

    if spread == "one":
        await state.update_data(spread="one")
        await cq.message.answer("Выберите тему:", reply_markup=kb_categories("cat_one"))
        await Flow.choosing_category_for_one.set()
    elif spread == "three":
        if len(cards) < 3:
            await cq.message.answer("Карточек пока мало для 3-картного расклада 😕")
            await cq.answer()
            return
        await state.update_data(spread="three")
        await cq.message.answer("Выберите тему:", reply_markup=kb_categories("cat_three"))
        await Flow.choosing_category_for_three.set()
    await cq.answer()

# =========================
# Handlers: categories → topic input
# =========================
@dp.callback_query_handler(lambda c: c.data.startswith("cat_one:"), state=Flow.choosing_category_for_one)
async def cat_one(cq: CallbackQuery, state: FSMContext):
    category = cq.data.split(":", 1)[1]
    await state.update_data(category=category)
    await cq.message.answer("Коротко опишите запрос одной фразой:")
    await Flow.entering_topic_for_one.set()
    await cq.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("cat_three:"), state=Flow.choosing_category_for_three)
async def cat_three(cq: CallbackQuery, state: FSMContext):
    category = cq.data.split(":", 1)[1]
    await state.update_data(category=category)
    await cq.message.answer("Коротко опишите запрос одной фразой:")
    await Flow.entering_topic_for_three.set()
    await cq.answer()

# =========================
# Handlers: do spreads
# =========================
@dp.message_handler(state=Flow.entering_topic_for_one)
async def do_one(m: types.Message, state: FSMContext):
    if not cards:
        await m.reply("Колода пока недоступна 😕")
        await state.finish()
        return

    data = await state.get_data()
    topic = (m.text or "").strip()
    category = data.get("category", "general")

    # pick
    c = pick_card()
    cap = card_caption(c)
    img = card_image_url(c)
    if img:
        await m.answer_photo(photo=img, caption=cap)
    else:
        await m.reply(cap)

    meaning = meaning_text(c)
    summary = summarize_reading(topic, category, [c])
    await m.answer(f"Интерпретация:\n— {meaning}\n\n{summary}")

    # save & cooldown
    save_history(m.from_user.id, "one", category, topic, [c])
    set_last_ts(m.from_user.id, int(time.time()))

    # back to menu
    await m.answer("Готово. Вернуться в меню:", reply_markup=kb_main())
    await Flow.choosing_spread.set()

@dp.message_handler(state=Flow.entering_topic_for_three)
async def do_three(m: types.Message, state: FSMContext):
    if len(cards) < 3:
        await m.reply("Карточек пока мало для 3-картного расклада 😕")
        await state.finish()
        return

    data = await state.get_data()
    topic = (m.text or "").strip()
    category = data.get("category", "general")

    chosen = random.sample(cards, 3)
    positions = ["Прошлое", "Настоящее", "Будущее"]
    picked = []

    for i, card in enumerate(chosen):
        card = card.copy()
        card["is_reversed"] = (random.randint(1, 100) <= reversals_percent)
        picked.append(card)

        cap = f"{positions[i]} • " + card_caption(card)
        img = card_image_url(card)
        if img:
            await m.answer_photo(photo=img, caption=cap)
        else:
            await m.reply(cap)
        await m.answer(f"Краткая интерпретация ({positions[i]}):\n— {meaning_text(card)}")

    summary = summarize_reading(topic, category, picked)
    await m.answer(summary)

    # save & cooldown
    save_history(m.from_user.id, "three", category, topic, picked)
    set_last_ts(m.from_user.id, int(time.time()))

    await m.answer("Готово. Вернуться в меню:", reply_markup=kb_main())
    await Flow.choosing_spread.set()

# =========================
# Webhook lifecycle
# =========================
async def on_startup(dp_: Dispatcher):
    await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
    log.info("Webhook установлен: %s", WEBHOOK_URL)

async def on_shutdown(dp_: Dispatcher):
    log.info("Удаляю вебхук…")
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
