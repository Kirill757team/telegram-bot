import os
import sqlite3
import datetime
import threading
import logging
import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, PreCheckoutQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = "AIzaSyBUZk0bq3bto6Kwz7S2XH2ga8UNH3N_KvA"  # Ваш ключ Gemini

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

# ==================== БАЗА ДАННЫХ ====================
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

def get_referral_count(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

# ==================== GEMINI AI ====================
async def ask_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        result = response.json()
        if response.status_code == 200:
            return result["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return None
    except Exception as e:
        print(f"Gemini ошибка: {e}")
        return None

# ==================== КЛАВИАТУРЫ ====================
def main_keyboard():
    kb = [
        [InlineKeyboardButton("🤖 Задать вопрос", callback_data="ask")],
        [InlineKeyboardButton("⭐ Подписка", callback_data="sub")],
        [InlineKeyboardButton("👥 Рефералы", callback_data="referral")],
        [InlineKeyboardButton("📊 Профиль", callback_data="profile")],
        [InlineKeyboardButton("📞 Поддержка", callback_data="support")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(kb)

def back_keyboard():
    kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back")]]
    return InlineKeyboardMarkup(kb)

# ==================== КОМАНДЫ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    status_text = "✅ Подписка активна" if has_sub(uid) else "❌ Нет подписки"
    await update.message.reply_text(
        f"🌟 *Привет, {user.first_name}!*\n\n{status_text}\n\n👇 Выберите действие:",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )

async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not has_sub(uid):
        await update.message.reply_text("❌ *Нет активной подписки*\n\nИспользуйте кнопку '⭐ Подписка'", parse_mode="Markdown")
        return
    
    if not context.args:
        await update.message.reply_text(
            "🤖 *Как задать вопрос:*\n\n`/ask ваш вопрос`\n\nПример: `/ask Что такое Python?`",
            parse_mode="Markdown"
        )
        return
    
    question = ' '.join(context.args)
    
    # Отправляем статус "печатает"
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # Получаем ответ от Gemini
    response = await ask_gemini(question)
    
    if response:
        await update.message.reply_text(response, parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "😔 *Извините, ИИ временно недоступен*\n\nПопробуйте позже или задайте вопрос иначе.",
            parse_mode="Markdown"
        )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_invoice(
            chat_id=update.effective_user.id,
            title=f"Подписка на {DAYS} дней",
            description=f"Доступ к ИИ-боту на {DAYS} дней",
            payload=f"sub_{update.effective_user.id}",
            provider_token="",
            currency="XTR",
            prices=[{"label": "Подписка", "amount": PRICE_STARS}],
        )
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if has_sub(update.effective_user.id):
        await update.message.reply_text("✅ *Подписка активна!*", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ *Нет активной подписки*\n\nИспользуйте кнопку '⭐ Подписка'", parse_mode="Markdown")

async def trial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if user and user["trial_used"]:
        await update.message.reply_text("❌ *Пробный период уже использован!*", parse_mode="Markdown")
    else:
        add_trial(uid)
        await update.message.reply_text(f"🎉 *Пробный период активирован!*\n\n{TRIAL_DAYS} дня бесплатного доступа.", parse_mode="Markdown")

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bot_name = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_name}?start={uid}"
    count = get_referral_count(uid)
    text = f"👥 *Реферальная система*\n\n🔗 `{link}`\n\n📊 Приглашено: {count}\n🎁 Бонус: +{REFERRAL_BONUS} дней подписки"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=back_keyboard())

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    status_text = "✅ Активна" if has_sub(uid) else "❌ Не активна"
    count = get_referral_count(uid)
    text = f"📊 *Ваш профиль*\n\n🆔 ID: `{uid}`\n⭐ Статус: {status_text}\n👥 Приглашено друзей: {count}\n🎁 Бонус за друга: +{REFERRAL_BONUS} дней"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=back_keyboard())

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📞 *Поддержка*\n\nПо всем вопросам: @Kirill757team_admin\n\nМы ответим в ближайшее время!"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=back_keyboard())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "❓ *Помощь*\n\n"
        "📋 *Доступные команды:*\n\n"
        "🤖 `/ask [вопрос]` - Задать вопрос ИИ Gemini\n"
        "⭐ `/subscribe` - Купить подписку\n"
        "📊 `/status` - Проверить статус подписки\n"
        "🎁 `/trial` - Активировать пробный период (3 дня)\n"
        "👥 `/referral` - Получить реферальную ссылку\n"
        "📊 `/profile` - Посмотреть профиль\n"
        "📞 `/support` - Связаться с поддержкой\n"
        "❓ `/help` - Эта справка\n\n"
        "💡 *Совет:* Используйте кнопки в меню для быстрого доступа!"
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=back_keyboard())

# ==================== ОБРАБОТЧИК КНОПОК ====================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id
    
    if data == "ask":
        await query.edit_message_text(
            "🤖 *Задать вопрос ИИ*\n\nИспользуйте: `/ask ваш вопрос`\n\nПример: `/ask Что такое Python?`",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )
    elif data == "sub":
        await subscribe(update, context)
    elif data == "referral":
        await referral(update, context)
    elif data == "profile":
        await profile(update, context)
    elif data == "support":
        await support(update, context)
    elif data == "help":
        await help_cmd(update, context)
    elif data == "back":
        status_text = "✅ Подписка активна" if has_sub(uid) else "❌ Нет подписки"
        await query.edit_message_text(
            f"🌟 *Главное меню*\n\n{status_text}\n\n👇 Выберите действие:",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )

# ==================== ПЛАТЕЖИ ====================
async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def pay_success(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_sub(update.effective_user.id, DAYS)
    await update.message.reply_text(
        f"🎉 *Оплата прошла успешно!*\n\nПодписка активирована на {DAYS} дней.\n\nСпасибо, что выбрали нас! 🚀",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def text_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if has_sub(uid):
        await update.message.reply_text(
            "🤖 *Используйте команду /ask для вопросов ИИ*\n\nНапример: `/ask Как дела?`",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ *Нет активной подписки*\n\nНажмите кнопку '⭐ Подписка' для оформления",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

# ==================== ЗАПУСК ====================
def run_bot():
    print("🚀 Запуск бота...")
    init_db()
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("trial", trial))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("support", support))
    app.add_handler(CommandHandler("help", help_cmd))
    
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, pay_success))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))
    
    print("✅ Бот запущен со всеми функциями и ИИ Gemini!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    def run_flask():
        port = int(os.environ.get("PORT", 8080))
        flask_app.run(host="0.0.0.0", port=port, use_reloader=False, threaded=True)
    
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    run_bot()
    
