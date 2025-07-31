# handlers/utils.py

from functools import wraps
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ConversationHandler, ContextTypes
from config import SUBSCRIPTION_CHANNEL, ADMIN_IDS

# Декоратор: требует подписку на канал
def subscription_required(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            user_id = update.effective_user.id
            m = await context.bot.get_chat_member(SUBSCRIPTION_CHANNEL, user_id)
            if m.status not in ("creator", "administrator", "member"):
                raise RuntimeError()
            return await func(update, context, *args, **kwargs)
        except Exception:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "Подписаться",
                    url=f"https://t.me/{SUBSCRIPTION_CHANNEL.lstrip('@')}"
                )
            ]])
            msg = "Чтобы пользоваться ботом, подпишитесь на канал:"
            if update.message:
                await update.message.reply_text(msg, reply_markup=kb)
            elif update.callback_query:
                q = update.callback_query
                await q.answer()
                await q.message.reply_text(msg, reply_markup=kb)
            return ConversationHandler.END
    return wrapped

# Декоратор: требует права админа
def admin_required(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            if update.message:
                await update.message.reply_text("❌ У вас нет прав.", reply_markup=None)
            elif update.callback_query:
                q = update.callback_query
                await q.answer()
                await q.message.reply_text("❌ У вас нет прав.", reply_markup=None)
            return ConversationHandler.END
        return await func(update, context, *args, **kwargs)
    return wrapped

# Пустая заглушка для унификации импорта
def get_handlers():
    return []
