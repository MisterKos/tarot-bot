import os
import json
import logging
import random
import time
from collections import defaultdict, deque
from typing import Dict, Any, List, Optional

from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ParseMode

import requests

# -------------------- базовая конфигурация --------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tarot-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в переменных окружения")

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "300"))

DECK_URL = os.getenv("DECK_URL", "").strip()
DECK: Dict[str, Any] = {}
CARDS: List[Dict[str, Any]] = []
REVERSALS_PCT = 0
IMAGE_BASE_URL: Optional[str] = None

def _load_deck() -> None:
    global DECK, CARDS, REVERSALS_PCT, IMAGE_BASE_URL
    try:
        with open("data/deck.json", "r", encoding="utf-8") as f:
            DECK = json.load(f)
        CARDS = DECK.get("cards", [])
        REVERSALS_PCT = int(DECK.get("reversals_percent", 30))
        IMAGE_BASE_URL = DECK.get("image_base_url")
        log.info("Колода загружена локально из data/deck.json")
        return
    except Exception as e:
        log.warning("Не удалось прочитать локальную колоду: %r", e)

    if DECK_URL:
        try:
            r = requests.get(DECK_URL, timeout=15)
            r.raise_for_status()
            DECK = r.json()
            CARDS = DECK.get("cards", [])
            REVERSALS_PCT = int(DECK.get("reversals_percent", 30))
            IMAGE_BASE_URL = DECK.get("image_base_url")
            log.info("Колода загружена по URL: %s", DECK_URL)
            return
        except Exception as e:
            log.error("Фатально: не удалось загрузить колоду ни локально, ни по URL: %s", e)

    DECK = {}
    CARDS = []
    REVERSALS_PCT = 0
    IMAGE_BASE_URL = None
    log.error("Колода не загружена ни локально, ни по URL — работаю с пустой.")

_load_deck()

# -------------------- инициализация --------------------
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(bot)
app = web.Application()

# -------------------- ручки --------------------
async def handle_root(request):
    return web.Response(status=404, text="Not Found")

async def handle_health(request):
    return web.Response(status=200, text="OK")

async def webhook_handler(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    update = types.Update.to_object(data)
    await dp.process_update(update)
    return web.Response(status=200, text="ok")

app.router.add_get("/", handle_root)
app.router.add_get("/healthz", handle_health)
app.router.add_post("/webhook", webhook_handler)

# -------------------- состояния --------------------
WAIT_TOPIC: Dict[int, Dict[str, Any]] = {}
WAIT_QUESTION: Dict[int, Dict[str, Any]] = {}
HISTORY: Dict[int, deque] = defaultdict(lambda: deque(maxlen=10))
LAST_USED_AT: Dict[int, float] = {}

# -------------------- утилиты --------------------
def pick_cards(n: int) -> List[Dict[str, Any]]:
    if not CARDS or len(CARDS) < n:
        return []
    sample = random.sample(CARDS, n)
    result = []
    for c in sample:
        is_reversed = random.randint(1, 100) <= max(0, min(100, REVERSALS_PCT))
        result.append({
            "code": c.get("code"),
            "title_en": c.get("title_en"),
            "title_ru": c.get("title_ru"),
            "image": c.get("image"),
            "upright": c.get("upright"),
            "reversed": c.get("reversed"),
            "reversed_flag": is_reversed,
        })
    return result

def card_title(c: Dict[str, Any]) -> str:
    t = c.get("title_ru") or c.get("title_en") or c.get("code") or "Карта"
    return f"{t}{' (перевёрнутая)' if c.get('reversed_flag') else ''}"

def card_image_url(c: Dict[str, Any]) -> Optional[str]:
    img = c.get("image")
    if not img:
        return None
    if IMAGE_BASE_URL and IMAGE_BASE_URL.startswith("http"):
        return IMAGE_BASE_URL.rstrip("/") + "/" + img
    return None

def spread_positions(spread: str) -> List[str]:
    return ["Совет"] if spread == "1" else ["Прошлое", "Настоящее", "Будущее"]

def summarize_spread(cards: List[Dict[str, Any]], spread: str, topic: str, question: str) -> str:
    if not cards:
        return "Итог: колода недоступна."

    majors = sum(1 for c in cards if (c.get("code") or "").startswith("major_"))
    reversed_cnt = sum(1 for c in cards if c.get("reversed_flag"))
    suits = {"cups":0, "swords":0, "wands":0, "pentacles":0}
    for c in cards:
        code = (c.get("code") or "")
        for s in suits.keys():
            if s in code:
                suits[s] += 1
                break
    main_suit = max(suits, key=suits.get)
    suit_text_map = {
        "cups": "эмоции, чувства и отношения",
        "swords": "мысли, напряжение и выбор",
        "wands": "энергия, действия и инициатива",
        "pentacles": "материальные вопросы и стабильность",
    }
    suit_text = suit_text_map.get(main_suit, "разные сферы жизни")

    lines = ["✨ Итог расклада:"]
    if majors >= 2:
        lines.append("Ситуация находится под влиянием важных событий — ваши шаги сейчас определяют будущее.")
    elif majors == 1:
        lines.append("Есть один ключевой момент, на который стоит обратить особое внимание.")

    if reversed_cnt >= 2:
        lines.append("Много перевёрнутых карт — это знак внутренних сомнений и блоков. Важно сначала разобраться в себе.")
    else:
        lines.append("Карты в целом указывают на благоприятные обстоятельства вокруг вас.")

    lines.append(f"Основная тема расклада: {suit_text}.")
    if topic.lower() != "общее":
        lines.append(f"Контекст: {topic}.")
    if question:
        lines.append(f"Ваш вопрос: «{question}». Карты подсказывают, что ответ связан с вашей готовностью меняться и действовать.")

    lines.append("Помните: карты показывают тенденции, а окончательный выбор остаётся за вами.")
    return "\n".join(lines)

def format_spread_text(spread: str, cards: List[Dict[str, Any]]) -> str:
    pos = spread_positions(spread)
    chunks = []
    for i, c in enumerate(cards):
        title = card_title(c)
        meaning = (c.get("reversed") if c.get("reversed_flag") else c.get("upright")) or "—"
        chunks.append(f"<b>{pos[i]}:</b> {title}\n<i>{meaning}</i>")
    return "\n\n".join(chunks)

# -------------------- клавиатуры --------------------
def menu_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("🔮 1 карта — совет"), KeyboardButton("🔮 3 карты — П/Н/Б"))
    kb.row(KeyboardButton("🧾 История"), KeyboardButton("❌ Отмена"))
    return kb

def topics_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row(KeyboardButton("Отношения"), KeyboardButton("Работа"))
    kb.row(KeyboardButton("Деньги"), KeyboardButton("Общее"))
    kb.row(KeyboardButton("❌ Отмена"))
    return kb

# -------------------- кулдаун --------------------
def check_cooldown(user_id: int) -> Optional[int]:
    last = LAST_USED_AT.get(user_id)
    if not last:
        return None
    remain = COOLDOWN_SECONDS - int(time.time() - last)
    return remain if remain > 0 else None

def mark_used(user_id: int):
    LAST_USED_AT[user_id] = time.time()

# -------------------- хендлеры --------------------
@dp.message_handler(commands=["start"])
async def cmd_start(m: types.Message):
    await m.answer(
        "Привет! Это бот раскладов на Таро 🎴\n"
        "Выберите расклад через /menu.\n\n"
        "<i>Помните: решения принимаете только вы.</i>",
        reply_markup=menu_kb()
    )

@dp.message_handler(commands=["menu"])
async def cmd_menu(m: types.Message):
    await m.answer("Выберите расклад:", reply_markup=menu_kb())

@dp.message_handler(commands=["history"])
async def cmd_history(m: types.Message):
    items = list(HISTORY[m.from_user.id])
    if not items:
        return await m.answer("История пуста.")
    lines = ["<b>Последние расклады:</b>"]
    for it in reversed(items):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(it["ts"]))
        lines.append(f"• {when} — {('1 карта' if it['spread']=='1' else '3 карты')}: {it['topic']} — «{it['question'] or 'без вопроса'}»")
    await m.answer("\n".join(lines))

@dp.message_handler(lambda m: m.text in {"🔮 1 карта — совет", "🔮 3 карты — П/Н/Б"})
async def on_pick_spread(m: types.Message):
    remain = check_cooldown(m.from_user.id)
    if remain:
        return await m.answer(f"Подождите ещё {remain} сек 🙏")
    spread = "1" if "1 карта" in m.text else "3"
    WAIT_TOPIC[m.from_user.id] = {"spread": spread}
    await m.answer("Выберите тему:", reply_markup=topics_kb())

@dp.message_handler(lambda m: m.text in {"Отношения", "Работа", "Деньги", "Общее"})
async def on_pick_topic(m: types.Message):
    state = WAIT_TOPIC.pop(m.from_user.id, None)
    if not state:
        return await m.answer("Сначала выберите расклад через /menu.")
    WAIT_QUESTION[m.from_user.id] = {"spread": state["spread"], "topic": m.text}
    await m.answer("Сформулируйте вопрос:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("❌ Отмена")))

@dp.message_handler(lambda m: m.text == "❌ Отмена")
async def on_cancel(m: types.Message):
    WAIT_TOPIC.pop(m.from_user.id, None)
    WAIT_QUESTION.pop(m.from_user.id, None)
    await m.answer("Отменено.", reply_markup=menu_kb())

@dp.message_handler()
async def on_free_text(m: types.Message):
    qstate = WAIT_QUESTION.pop(m.from_user.id, None)
    if qstate:
        spread, topic, question = qstate["spread"], qstate["topic"], m.text.strip()
        remain = check_cooldown(m.from_user.id)
        if remain:
            WAIT_QUESTION[m.from_user.id] = qstate
            return await m.answer(f"Подождите ещё {remain} сек 🙏")
        n = 1 if spread == "1" else 3
        cards = pick_cards(n)
        if not cards:
            return await m.answer("Колода недоступна.", reply_markup=menu_kb())
        body = format_spread_text(spread, cards)
        summary = summarize_spread(cards, spread, topic, question)

        media_urls = [card_image_url(c) for c in cards if card_image_url(c)]
        if media_urls:
            media = [types.InputMediaPhoto(media=media_urls[0], caption=f"<b>Ваш расклад</b>\n\n{body}", parse_mode=ParseMode.HTML)]
            for u in media_urls[1:]:
                media.append(types.InputMediaPhoto(media=u))
            try:
                await m.answer_media_group(media)
            except Exception:
                await m.answer(f"<b>Ваш расклад</b>\n\n{body}")
        else:
            await m.answer(f"<b>Ваш расклад</b>\n\n{body}")

        await m.answer(summary, reply_markup=menu_kb())
        HISTORY[m.from_user.id].append({"ts": time.time(), "spread": spread, "topic": topic, "question": question})
        mark_used(m.from_user.id)
        return
    if not m.text.startswith("/"):
        await m.answer("Выберите расклад через /menu.", reply_markup=menu_kb())

# -------------------- запуск --------------------
async def on_startup(app_: web.Application):
    if not RENDER_EXTERNAL_URL:
        log.warning("RENDER_EXTERNAL_URL не задан — webhook не будет установлен.")
        return
    log.info("Webhook URL (нужно установить вручную через setWebhook): %s/webhook", RENDER_EXTERNAL_URL)

def main():
    port = int(os.getenv("PORT", "10000"))
    web.run_app(app, host="0.0.0.0", port=port, print=None)

if __name__ == "__main__":
    app.on_startup.append(on_startup)
    main()
