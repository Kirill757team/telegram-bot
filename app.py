import os
import threading
import logging
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Настройка логов
logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    print("Ошибка: TELEGRAM_TOKEN не найден")
    exit(1)

flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return "OK", 200

# ==================== КЛАВИАТУРЫ ====================
def main_keyboard():
    kb = [
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
    await update.message.reply_text(
        "🌟 *Привет!*\n\nВыберите действие:",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )
    return

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_name = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_name}?start={user_id}"
    text = f"👥 *Реферальная ссылка*\n\n`{link}`"
    
    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
        await update.callback_query.answer()
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    return

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = f"📊 *Профиль*\n\n🆔 ID: `{user_id}`\n⭐ Подписка: активна"
    
    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
        await update.callback_query.answer()
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    return

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📞 *Поддержка*\n\nПо всем вопросам: @Kirill757team_admin"
    
    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
        await update.callback_query.answer()
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    return

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "❓ *Помощь*\n\n/start - Главное меню\n/referral - Реферальная ссылка\n/profile - Профиль\n/support - Поддержка"
    
    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
        await update.callback_query.answer()
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    return

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass

# ==================== ОБРАБОТЧИК КНОПОК ====================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    print(f"Нажата кнопка: {data}")
    
    if data == "referral":
        await referral(update, context)
    elif data == "profile":
        await profile(update, context)
    elif data == "support":
        await support(update, context)
    elif data == "help":
        await help_cmd(update, context)
    elif data == "back":
        await query.message.reply_text(
            "🌟 *Главное меню*\n\nВыберите действие:",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )
        await query.answer()
    
    await query.answer()
    return

# ==================== ТЕКСТ ====================
async def text_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Используйте кнопки или команды:\n"
        "/start - Главное меню\n"
        "/referral - Реферальная ссылка\n"
        "/profile - Профиль\n"
        "/support - Поддержка\n"
        "/help - Помощь"
    )

# ==================== ЗАПУСК ====================
def run_bot():
    print("🚀 Запуск бота...")
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("support", support))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # Кнопки (callback)
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    # Текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))
    
    print("✅ Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    def run_flask():
        port = int(os.environ.get("PORT", 8080))
        flask_app.run(host="0.0.0.0", port=port, use_reloader=False, threaded=True)
    
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    run_bot()
