# handlers/admin.py

from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from config import ADMIN_IDS
from db import SessionLocal
from models import User
import logging
from handlers.utils import subscription_required  # импорт декоратора подписки

logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
BROADCAST_TEXT = 1


def admin_required(func):
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            if update.callback_query:
                q = update.callback_query
                await q.answer()
                await q.message.reply_text("❌ У вас нет прав.")
            else:
                await update.message.reply_text("❌ У вас нет прав.")
            return ConversationHandler.END
        return await func(update, context, *args, **kwargs)
    return wrapped


@subscription_required
@admin_required
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Запрашиваем у администратора текст для рассылки.
    """
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.message.reply_text("📝 Введите текст для рассылки всем пользователям:")
    else:
        await update.message.reply_text("📝 Введите текст для рассылки всем пользователям:")
    return BROADCAST_TEXT


@subscription_required
@admin_required
async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Получили текст от администратора, рассылаем его всем зарегистрированным пользователям.
    """
    text = update.message.text
    db = SessionLocal()
    users = db.query(User).all()
    db.close()
    bot = context.bot
    failed = 0
    for u in users:
        try:
            await bot.send_message(chat_id=u.telegram_id, text=text)
        except Exception as e:
            failed += 1
            logger.warning(f"Не удалось отправить {u.telegram_id}: {e}")
    await update.message.reply_text(f"✅ Рассылка завершена. Не доставлено: {failed}")
    return ConversationHandler.END


def get_handlers():
    """
    Возвращает список handler’ов для регистрации в bot.py.
    """
    return [
        ConversationHandler(
            entry_points=[CommandHandler("broadcast", broadcast_start)],
            states={
                BROADCAST_TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)
                ]
            },
            fallbacks=[],
            per_user=True,
            allow_reentry=True,
        ),
    ]
