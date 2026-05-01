import os
import sqlite3
import datetime
import threading
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
                  referrer_id INTEGER,
                  language TEXT DEFAULT 'ru',
                  notifications BOOLEAN DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS feedback
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  message TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()
    print("✅ База данных готова")

def get_user(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id, sub_end, trial_used, referrer_id, language, notifications FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "sub_end": row[1], "trial_used": bool(row[2]), "referrer_id": row[3], "language": row[4] or 'ru', "notifications": bool(row[5])}
    return None

def create_user(user_id, referrer_id=None):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, referrer_id, language, notifications) VALUES (?, ?, 'ru', 1)", (user_id, referrer_id))
    conn.commit()
    conn.close()

def save_feedback(user_id, message):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT INTO feedback (user_id, message) VALUES (?, ?)", (user_id, message))
    conn.commit()
    conn.close()

def update_language(user_id, lang):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
    conn.commit()
    conn.close()

def update_notifications(user_id, enabled):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE users SET notifications = ? WHERE user_id = ?", (enabled, user_id))
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

def get_referral_stats(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM referral_bonuses WHERE referrer_id = ?", (user_id,))
    conn.close()
    return total, 0

def main_keyboard():
    kb = [
        [InlineKeyboardButton("🤖 Задать вопрос", callback_data="ask")],
        [InlineKeyboardButton("⭐ Подписка", callback_data="sub")],
        [InlineKeyboardButton("👥 Рефералы", callback_data="ref")],
        [InlineKeyboardButton("📊 Профиль", callback_data="profile")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton("📞 Поддержка", callback_data="support")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(kb)

def settings_keyboard():
    kb = [
        [InlineKeyboardButton("🌐 Язык", callback_data="lang_menu")],
        [InlineKeyboardButton("🔔 Уведомления", callback_data="notif_menu")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back")]
    ]
    return InlineKeyboardMarkup(kb)

def lang_keyboard():
    kb = [
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton("🔙 Назад", callback_data="settings")]
    ]
    return InlineKeyboardMarkup(kb)

def notif_keyboard(notif_enabled):
    status = "✅ Вкл" if notif_enabled else "❌ Выкл"
    kb = [
        [InlineKeyboardButton(f"Уведомления: {status}", callback_data="toggle_notif")],
        [InlineKeyboardButton("🔙 Назад", callback_data="settings")]
    ]
    return InlineKeyboardMarkup(kb)

def back_keyboard():
    kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back")]]
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
        await update.message.reply_text(f"🌟 Привет, {user.first_name}!\n✅ Подписка активна!", reply_markup=main_keyboard())
    else:
        await update.message.reply_text(f"🌟 Привет, {user.first_name}!\n❌ Нет подписки. /subscribe", reply_markup=main_keyboard())

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
        await update.message.reply_text("✅ Подписка активна!")
    else:
        await update.message.reply_text("❌ Нет подписки. /subscribe")

async def trial(update, context):
    uid = update.effective_user.id
    user = get_user(uid)
    if user and user["trial_used"]:
        await update.message.reply_text("❌ Пробный период уже использован!")
    else:
        add_trial(uid)
        await update.message.reply_text(f"🎉 Пробный период активирован! {TRIAL_DAYS} дня")

async def referral(update, context):
    uid = update.effective_user.id
    bot_name = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_name}?start={uid}"
    total, _ = get_referral_stats(uid)
    await update.message.reply_text(f"👥 *Реферальная система*\n\n🔗 Ваша ссылка:\n`{link}`\n\n📊 Приглашено: {total}\n🎁 За друга +{REFERRAL_BONUS} дней", parse_mode="Markdown")

async def profile(update, context):
    uid = update.effective_user.id
    user = get_user(uid)
    st = "✅ Активна" if has_sub(uid) else "❌ Не активна"
    total, _ = get_referral_stats(uid)
    await update.message.reply_text(f"📊 *Профиль*\n\n🆔 ID: `{uid}`\n⭐ Статус: {st}\n👥 Приглашено: {total}\n🌐 Язык: {user['language'] if user else 'ru'}\n🔔 Уведомления: {'Вкл' if (user['notifications'] if user else True) else 'Выкл'}", parse_mode="Markdown")

async def ask(update, context):
    if not has_sub(update.effective_user.id):
        await update.message.reply_text("❌ Нет подписки. /subscribe")
        return
    if not context.args:
        await update.message.reply_text("🤖 Использование: /ask ваш вопрос")
        return
    q = ' '.join(context.args)
    await update.message.reply_text(f"🤖 Ваш вопрос: {q}\n(ИИ будет добавлен позже)")

async def help_cmd(update, context):
    await update.message.reply_text(
        "📖 *Справка*\n\n"
        "/start - Главное меню\n"
        "/subscribe - Купить подписку\n"
        "/status - Статус подписки\n"
        "/trial - Пробный период\n"
        "/referral - Реферальная ссылка\n"
        "/profile - Мой профиль\n"
        "/ask - Задать вопрос ИИ\n"
        "/settings - Настройки\n"
        "/language - Сменить язык\n"
        "/notify - Уведомления\n"
        "/support - Поддержка\n"
        "/feedback - Отзыв\n"
        "/faq - Частые вопросы\n"
        "/terms - Условия",
        parse_mode="Markdown"
    )

async def settings(update, context):
    await update.message.reply_text("⚙️ *Настройки*", reply_markup=settings_keyboard(), parse_mode="Markdown")

async def language(update, context):
    await update.message.reply_text("🌐 *Выберите язык*", reply_markup=lang_keyboard(), parse_mode="Markdown")

async def notifications(update, context):
    uid = update.effective_user.id
    user = get_user(uid)
    enabled = user["notifications"] if user else True
    await update.message.reply_text("🔔 *Уведомления*", reply_markup=notif_keyboard(enabled), parse_mode="Markdown")

async def support(update, context):
    await update.message.reply_text(
        "📞 *Поддержка*\n\n"
        "• По вопросам: @Kirill757team_admin\n"
        "• Или через /feedback",
        parse_mode="Markdown"
    )

async def feedback(update, context):
    if not context.args:
        await update.message.reply_text("📝 Использование: /feedback ваш отзыв")
        return
    msg = ' '.join(context.args)
    save_feedback(update.effective_user.id, msg)
    await update.message.reply_text("✅ Спасибо за отзыв!")

async def faq(update, context):
    await update.message.reply_text(
        "❓ *Частые вопросы*\n\n"
        f"**1. Сколько стоит подписка?**\n{PRICE_STARS} Stars на {DAYS} дней\n\n"
        "**2. Как купить Stars?**\nЧерез App Store или Google Play\n\n"
        "**3. Бот не отвечает?**\nПроверьте статус: /status",
        parse_mode="Markdown"
    )

async def terms(update, context):
    await update.message.reply_text(
        "📜 *Условия использования*\n\n"
        "1. Подписка не возвращается\n"
        "2. Бот предоставляется 'как есть'\n"
        "3. Мы не храним личные данные",
        parse_mode="Markdown"
    )

async def callback(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = q.from_user.id
    
    if data == "ask":
        await q.edit_message_text("🤖 Используйте /ask ваш вопрос", reply_markup=back_keyboard())
    elif data == "sub":
        await subscribe(update, context)
    elif data == "ref":
        await referral(update, context)
    elif data == "profile":
        await profile(update, context)
    elif data == "settings":
        await q.edit_message_text("⚙️ *Настройки*", reply_markup=settings_keyboard(), parse_mode="Markdown")
    elif data == "support":
        await q.edit_message_text("📞 *Поддержка*\n\nПо вопросам: @Kirill757team_admin", reply_markup=back_keyboard(), parse_mode="Markdown")
    elif data == "help":
        await help_cmd(update, context)
    elif data == "back":
        await q.edit_message_text("🌟 *Главное меню*", reply_markup=main_keyboard(), parse_mode="Markdown")
    elif data == "lang_menu":
        await q.edit_message_text("🌐 *Выберите язык*", reply_markup=lang_keyboard(), parse_mode="Markdown")
    elif data == "lang_ru":
        update_language(uid, "ru")
        await q.edit_message_text("🇷🇺 Язык изменён на русский!", reply_markup=back_keyboard())
    elif data == "lang_en":
        update_language(uid, "en")
        await q.edit_message_text("🇬🇧 Language changed to English!", reply_markup=back_keyboard())
    elif data == "notif_menu":
        user = get_user(uid)
        enabled = user["notifications"] if user else True
        await q.edit_message_text("🔔 *Уведомления*", reply_markup=notif_keyboard(enabled), parse_mode="Markdown")
    elif data == "toggle_notif":
        user = get_user(uid)
        current = user["notifications"] if user else True
        update_notifications(uid, not current)
        await q.edit_message_text("🔔 *Уведомления*", reply_markup=notif_keyboard(not current), parse_mode="Markdown")

async def pre_checkout(update, context):
    await update.pre_checkout_query.answer(ok=True)

async def pay_success(update, context):
    add_sub(update.effective_user.id, DAYS)
    await update.message.reply_text("🎉 Оплата прошла! Подписка активирована.", reply_markup=main_keyboard())

async def text_msg(update, context):
    if has_sub(update.effective_user.id):
        await update.message.reply_text("Используйте /ask для вопроса", reply_markup=main_keyboard())
    else:
        await update.message.reply_text("❌ Нет подписки. /subscribe", reply_markup=main_keyboard())

def run_bot():
    print("🚀 Запуск бота...")
    init_db()
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    commands = [
        ("start", "Главное меню"),
        ("help", "Справка"),
        ("subscribe", "Купить подписку"),
        ("status", "Статус подписки"),
        ("trial", "Пробный период"),
        ("referral", "Реферальная ссылка"),
        ("profile", "Мой профиль"),
        ("ask", "Задать вопрос"),
        ("settings", "Настройки"),
        ("language", "Сменить язык"),
        ("notify", "Уведомления"),
        ("support", "Поддержка"),
        ("feedback", "Отзыв"),
        ("faq", "Частые вопросы"),
        ("terms", "Условия"),
    ]
    
    for cmd, desc in commands:
        app.add_handler(CommandHandler(cmd, globals()[cmd if cmd != "notify" else "notifications"]))
    
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, pay_success))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))
    
    print("✅ Бот запущен со всеми функциями!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    def run_flask():
        port = int(os.environ.get("PORT", 8080))
        flask_app.run(host="0.0.0.0", port=port, use_reloader=False, threaded=True)
    
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    run_bot()
