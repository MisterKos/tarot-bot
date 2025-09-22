import os
import json
import logging
import random
import time
from collections import defaultdict, deque
from typing import Dict, Any, List, Optional

from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import set_webhook
from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton,
                           ReplyKeyboardMarkup, KeyboardButton, ParseMode)

import requests

# -------------------- базовая конфигурация --------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tarot-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в переменных окружения")

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "300"))

# Загрузка колоды: сначала локально data/deck.json, потом по DECK_URL
DECK_URL = os.getenv("DECK_URL", "").strip()
DECK: Dict[str, Any] = {}
CARDS: List[Dict[str, Any]] = []
REVERSALS_PCT = 0
IMAGE_BASE_URL: Optional[str] = None

def _load_deck() -> None:
    global DECK, CARDS, REVERSALS_PCT, IMAGE_BASE_URL
    # 1) локально
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

    # 2) по URL (если задан)
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

    # Если совсем пусто — работаем без колоды (но сообщим в /status)
    DECK = {}
    CARDS = []
    REVERSALS_PCT = 0
    IMAGE_BASE_URL = None
    log.error("Колода не загружена ни локально, ни по URL — работаю с пустой.")

_load_deck()

# -------------------- инициализация бота и веб-сервера --------------------
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(bot)

app = web.Application()

# Корень и healthz — сознательно 404/200 чтобы не будить бот
async def handle_root(request):
    return web.Response(status=404, text="Not Found")

async def handle_health(request):
    return web.Response(status=200, text="OK")

app.router.add_get("/", handle_root)
app.router.add_get("/healthz", handle_health)
app.router.add_head("/", handle_root)

# Webhook endpoint (POST от Telegram)
async def webhook_handler(request):
    if request.match_info.get("token") != BOT_TOKEN:
        return web.Response(status=403, text="forbidden")
    try:
        data = await request.json()
    except Exception:
        data = {}
    update = types.Update.to_object(data)
    await dp.process_update(update)
    return web.Response(status=200, text="ok")

app.router.add_post(f"/webhook/{{token}}", webhook_handler)

# -------------------- пользовательские состояния --------------------
# Простое FSM на словарях (без aiogram FSM, чтобы держать всё в одном файле)
WAIT_TOPIC: Dict[int, Dict[str, Any]] = {}      # user_id -> {"spread": "1"|"3"}
WAIT_QUESTION: Dict[int, Dict[str, Any]] = {}   # user_id -> {"spread": "...", "topic": "..."}

# История раскладов per-user (в памяти, до 10)
HISTORY: Dict[int, deque] = defaultdict(lambda: deque(maxlen=10))

# Кулдаун
LAST_USED_AT: Dict[int, float] = {}

# -------------------- утилиты раскладов --------------------
def pick_cards(n: int) -> List[Dict[str, Any]]:
    """Случайный выбор карт без повторов + флаг reversed по проценту из deck.json."""
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
    if IMAGE_BASE_URL and isinstance(IMAGE_BASE_URL, str) and IMAGE_BASE_URL.startswith("http"):
        return IMAGE_BASE_URL.rstrip("/") + "/" + img
    # если image_base_url относительный или отсутствует — картинку не прикладываем
    return None

def spread_positions(spread: str) -> List[str]:
    if spread == "1":
        return ["Совет"]
    return ["Прошлое", "Настоящее", "Будущее"]

def summarize_spread(cards: List[Dict[str, Any]], spread: str, topic: str, question: str) -> str:
    """Шаблонный «итог расклада»: без LLM, на основе структуры и признаков."""
    if not cards:
        return "Итог: колода недоступна, расклад не выполнен."

    majors = sum(1 for c in cards if (c.get("code") or "").startswith("major_"))
    reversed_cnt = sum(1 for c in cards if c.get("reversed_flag"))
    # грубая масть по коду: cups / swords / wands / pentacles
    suits = {"cups":0, "swords":0, "wands":0, "pentacles":0, "other":0}
    for c in cards:
        code = (c.get("code") or "")
        found = False
        for s in ["cups", "swords", "wands", "pentacles"]:
            if s in code:
                suits[s] += 1
                found = True
                break
        if not found and not code.startswith("major_"):
            suits["other"] += 1

    suit_hint = max(suits, key=suits.get) if cards else "other"
    suit_text_map = {
        "cups": "эмоции и отношения",
        "swords": "мысли, выбор и напряжение",
        "wands": "действия, энергия и инициативы",
        "pentacles": "материальные вопросы и стабильность",
        "other": "разнородные влияния",
    }
    suit_text = suit_text_map.get(suit_hint, "разнородные влияния")

    lines = []
    if spread == "1":
        lines.append("Итог: карта-совет акцентирует ключевой фокус: прислушайтесь к своему ощущению «да/нет», но решение — за вами.")
    else:
        lines.append("Итог расклада:")
        if majors >= 2:
            lines.append("• Много старших арканов — период важных поворотных моментов, решения повлияют надолго.")
        elif majors == 1:
            lines.append("• Один старший аркан — есть центральная тема, на которой стоит сфокусироваться.")
        if reversed_cnt >= 2:
            lines.append("• Много перевёрнутых карт — внутренние блоки/сомнения сильнее внешних факторов; начните с коррекции привычных реакций.")
        lines.append(f"• Преобладающая тема: {suit_text}.")
        if topic.lower() != "общее":
            lines.append(f"• Контекст: {topic}.")
        if question:
            lines.append(f"• Вопрос: {question}")

        lines.append("Помните: карты показывают тенденции, а решения принимаете вы. Любой выбор несёт последствия и открывает новые возможности.")

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

# -------------------- хендлеры команд --------------------
@dp.message_handler(commands=["start"])
async def cmd_start(m: types.Message):
    await m.answer(
        "Привет! Это бот онлайн-раскладов на Таро Райдер–Уэйт.\n"
        "Выберите расклад через /menu.\n\n"
        "<i>Дисклеймер: решения в жизни принимаете только вы. Карты помогают осознать тенденции.</i>",
        reply_markup=menu_kb()
    )

@dp.message_handler(commands=["help"])
async def cmd_help(m: types.Message):
    await m.answer(
        "Доступные команды:\n"
        "• /menu — кнопки раскладов\n"
        "• /history — последние расклады\n"
        "• /status — состояние бота\n"
        "• /ping — проверка связи\n\n"
        "Расклады:\n"
        "• 1 карта — совет\n"
        "• 3 карты — прошлое/настоящее/будущее\n\n"
        "<i>Помните: выбор и ответственность — на вашей стороне.</i>",
        reply_markup=menu_kb()
    )

@dp.message_handler(commands=["menu"])
async def cmd_menu(m: types.Message):
    await m.answer("Выберите расклад:", reply_markup=menu_kb())

@dp.message_handler(commands=["ping"])
async def cmd_ping(m: types.Message):
    await m.answer("pong")

@dp.message_handler(commands=["status"])
async def cmd_status(m: types.Message):
    info = [
        f"Колода: {'загружена' if CARDS else 'нет'}",
        f"Карт: {len(CARDS)}",
        f"Перевёрнутые: {REVERSALS_PCT}%",
        f"Cooldown: {COOLDOWN_SECONDS}s",
        f"Webhook: {RENDER_EXTERNAL_URL + '/webhook/…' if RENDER_EXTERNAL_URL else 'локально/не задан'}",
    ]
    await m.answer("\n".join(info))

@dp.message_handler(commands=["history"])
async def cmd_history(m: types.Message):
    items = list(HISTORY[m.from_user.id])
    if not items:
        return await m.answer("История пуста. Сделайте первый расклад через /menu.")
    lines = ["<b>Последние расклады:</b>"]
    for it in reversed(items):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(it["ts"]))
        lines.append(f"• {when} — {('1 карта' if it['spread']=='1' else '3 карты')}: {it['topic']} — «{it['question'] or 'без вопроса'}»")
    await m.answer("\n".join(lines))

# -------------------- кнопки меню (текстовые) --------------------
@dp.message_handler(lambda m: m.text in {"🔮 1 карта — совет", "🔮 3 карты — П/Н/Б"})
async def on_pick_spread(m: types.Message):
    if not CARDS:
        return await m.answer("Колода недоступна. Сообщите администратору.")

    remain = check_cooldown(m.from_user.id)
    if remain:
        return await m.answer(f"Подождите ещё {remain} сек перед новым раскладом 🙏")

    spread = "1" if "1 карта" in m.text else "3"
    WAIT_TOPIC[m.from_user.id] = {"spread": spread}
    await m.answer("Выберите контекст расклада:", reply_markup=topics_kb())

@dp.message_handler(lambda m: m.text in {"Отношения", "Работа", "Деньги", "Общее"})
async def on_pick_topic(m: types.Message):
    state = WAIT_TOPIC.pop(m.from_user.id, None)
    if not state:
        return await m.answer("Сначала выберите расклад через /menu.")
    WAIT_QUESTION[m.from_user.id] = {"spread": state["spread"], "topic": m.text}
    await m.answer("Сформулируйте ваш вопрос (одним сообщением).", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("❌ Отмена")))

@dp.message_handler(lambda m: m.text == "❌ Отмена")
async def on_cancel(m: types.Message):
    WAIT_TOPIC.pop(m.from_user.id, None)
    WAIT_QUESTION.pop(m.from_user.id, None)
    await m.answer("Отменено.", reply_markup=menu_kb())

# -------------------- принятие вопроса и выполнение расклада --------------------
@dp.message_handler()
async def on_free_text(m: types.Message):
    # если ждём вопрос
    qstate = WAIT_QUESTION.pop(m.from_user.id, None)
    if qstate:
        spread = qstate["spread"]
        topic = qstate["topic"]
        question = m.text.strip()

        # проверка кулдауна
        remain = check_cooldown(m.from_user.id)
        if remain:
            WAIT_QUESTION[m.from_user.id] = qstate  # вернуть ожидание, чтобы не потерять
            return await m.answer(f"Подождите ещё {remain} сек перед новым раскладом 🙏")

        # сделать расклад
        n = 1 if spread == "1" else 3
        cards = pick_cards(n)
        if not cards:
            return await m.answer("Колода недоступна. Сообщите администратору.", reply_markup=menu_kb())

        # текстовая часть
        body = format_spread_text(spread, cards)
        summary = summarize_spread(cards, spread, topic, question)

        # отправка: если есть http-картинки — приложим медиа-группой
        media_urls = [card_image_url(c) for c in cards]
        media_urls = [u for u in media_urls if u]

        if media_urls:
            media = [types.InputMediaPhoto(media=media_urls[0], caption=f"<b>Ваш расклад</b>\n\n{body}", parse_mode=ParseMode.HTML)]
            for u in media_urls[1:]:
                media.append(types.InputMediaPhoto(media=u))
            try:
                await m.answer_media_group(media)
            except Exception as e:
                log.warning("Не удалось отправить media group: %r — отправлю текстом", e)
                await m.answer(f"<b>Ваш расклад</b>\n\n{body}")
        else:
            await m.answer(f"<b>Ваш расклад</b>\n\n{body}")

        await m.answer(summary, reply_markup=menu_kb())

        # сохранить историю
        HISTORY[m.from_user.id].append({
            "ts": time.time(),
            "spread": spread,
            "topic": topic,
            "question": question,
            "cards": [{"code": c["code"], "reversed": bool(c["reversed_flag"])} for c in cards],
        })
        # отметить кулдаун
        mark_used(m.from_user.id)
        return

    # если не ждём вопрос и это не команда — покажем меню
    if m.text.startswith("/"):
        return  # команды обработают хендлеры выше
    await m.answer("Выберите расклад через /menu.", reply_markup=menu_kb())

# -------------------- запуск webhook-сервера --------------------
async def on_startup(app_: web.Application):
    if not RENDER_EXTERNAL_URL:
        log.warning("RENDER_EXTERNAL_URL не задан — webhook не будет установлен.")
        return
    url = f"{RENDER_EXTERNAL_URL}/webhook/{BOT_TOKEN}"
    ok = await set_webhook(bot, url)
    if ok:
        log.info("Webhook установлен: %s", url)
    else:
        log.error("Не удалось установить webhook: %s", url)

def main():
    # Render автоматически пробрасывает порт, по умолчанию 10000
    port = int(os.getenv("PORT", "10000"))
    web.run_app(app, host="0.0.0.0", port=port, print=None)

if __name__ == "__main__":
    # Привязываем хуки старта
    app.on_startup.append(on_startup)
    main()
