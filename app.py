import os
import sqlite3
import datetime
import asyncio
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, PreCheckoutQueryHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    print("Ошибка: TELEGRAM_TOKEN не найден")
    exit(1)

PRICE_STARS = 50
DAYS = 30
TRIAL_DAYS = 3
REFERRAL_BONUS = 7

flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return "OK", 200

def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  sub_end DATE,
                  trial_used BOOLEAN DEFAULT 0,
                  referrer_id INTEGER)''')
    conn.commit()
    conn.close()
    print("✅ База данных готова")

def get_user(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id, sub_end, trial_used, referrer_id FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "sub_end": row[1], "trial_used": bool(row[2]), "referrer_id": row[3]}
    return None

def create_user(user_id, referrer_id=None):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, referrer_id) VALUES (?, ?)", (user_id, referrer_id))
    conn.commit()
    conn.close()

def has_sub(user_id):
    user = get_user(user_id)
    if not user:
        return False
    if user["sub_end"]:
        try:
            end = datetime.datetime.strptime(user["sub_end"], "%Y-%m-%d").date()
            if end >= datetime.date.today():
                return True
        except:
            pass
    if not user["trial_used"]:
        return True
    return False

def add_sub(user_id, days):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    user = get_user(user_id)
    if user and user["sub_end"]:
        try:
            end = datetime.datetime.strptime(user["sub_end"], "%Y-%m-%d").date()
            new_end = end + datetime.timedelta(days=days)
        except:
            new_end = datetime.date.today() + datetime.timedelta(days=days)
    else:
        new_end = datetime.date.today() + datetime.timedelta(days=days)
    c.execute("UPDATE users SET sub_end = ? WHERE user_id = ?", (new_end.strftime("%Y-%m-%d"), user_id))
    conn.commit()
    conn.close()

def add_trial(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    new_end = datetime.date.today() + datetime.timedelta(days=TRIAL_DAYS)
    c.execute("UPDATE users SET sub_end = ?, trial_used = 1 WHERE user_id = ?", (new_end.strftime("%Y-%m-%d"), user_id))
    conn.commit()
    conn.close()

def main_keyboard():
    kb = [
        [InlineKeyboardButton("🤖 Задать вопрос", callback_data="ask")],
        [InlineKeyboardButton("⭐ Подписка", callback_data="sub")],
        [InlineKeyboardButton("👥 Рефералы", callback_data="ref")],
        [InlineKeyboardButton("📊 Профиль", callback_data="profile")]
    ]
    return InlineKeyboardMarkup(kb)

async def start(update, context):
    user = update.effective_user
    uid = user.id
    ref = None
    if context.args:
        try:
            ref = int(context.args[0])
            if ref == uid:
                ref = None
        except:
            pass
    if not get_user(uid):
        create_user(uid, ref)
        if ref:
            add_sub(ref, REFERRAL_BONUS)
        add_trial(uid)
    if has_sub(uid):
        await update.message.reply_text(f"Привет, {user.first_name}! Подписка активна!", reply_markup=main_keyboard())
    else:
        await update.message.reply_text(f"Привет, {user.first_name}! Нет подписки. /subscribe", reply_markup=main_keyboard())

async def subscribe(update, context):
    try:
        await context.bot.send_invoice(
            chat_id=update.effective_user.id,
            title=f"Подписка на {DAYS} дней",
            description=f"Доступ к боту на {DAYS} дней",
            payload=f"sub_{update.effective_user.id}",
            provider_token="",
            currency="XTR",
            prices=[{"label": "Подписка", "amount": PRICE_STARS}],
        )
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def status(update, context):
    if has_sub(update.effective_user.id):
        await update.message.reply_text("Подписка активна!")
    else:
        await update.message.reply_text("Нет подписки. /subscribe")

async def trial(update, context):
    uid = update.effective_user.id
    user = get_user(uid)
    if user and user["trial_used"]:
        await update.message.reply_text("Пробный период уже использован!")
    else:
        add_trial(uid)
        await update.message.reply_text(f"Пробный период активирован! {TRIAL_DAYS} дня")

async def referral(update, context):
    uid = update.effective_user.id
    bot_name = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_name}?start={uid}"
    await update.message.reply_text(f"Ваша ссылка: {link}\n\nЗа друга +{REFERRAL_BONUS} дней")

async def profile(update, context):
    uid = update.effective_user.id
    st = "Активна" if has_sub(uid) else "Не активна"
    await update.message.reply_text(f"Профиль\nID: {uid}\nСтатус: {st}")

async def ask(update, context):
    if not has_sub(update.effective_user.id):
        await update.message.reply_text("Нет подписки. /subscribe")
        return
    if not context.args:
        await update.message.reply_text("Использование: /ask ваш вопрос")
        return
    q = ' '.join(context.args)
    await update.message.reply_text(f"Ваш вопрос: {q}")

async def help_cmd(update, context):
    await update.message.reply_text("/start - Главное меню\n/subscribe - Купить подписку\n/status - Статус\n/trial - Пробный период\n/referral - Реферальная ссылка\n/profile - Профиль\n/ask - Задать вопрос")

async def callback(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "ask":
        await q.edit_message_text("Используйте /ask ваш вопрос")
    elif data == "sub":
        await subscribe(update, context)
    elif data == "ref":
        await referral(update, context)
    elif data == "profile":
        await profile(update, context)

async def pre_checkout(update, context):
    await update.pre_checkout_query.answer(ok=True)

async def pay_success(update, context):
    add_sub(update.effective_user.id, DAYS)
    await update.message.reply_text("Оплата прошла! Подписка активирована.")

async def text_msg(update, context):
    if has_sub(update.effective_user.id):
        await update.message.reply_text("Используйте /ask для вопроса")
    else:
        await update.message.reply_text("Нет подписки. /subscribe")

def run_bot():
    print("🚀 Запуск бота...")
    init_db()
    
    # Создаём новый event loop для потока
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("trial", trial))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, pay_success))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))
    
    print("✅ Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    import threading
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)
