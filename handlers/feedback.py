# handlers/feedback.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from models import Feedback
from db import SessionLocal

from handlers.utils import subscription_required

# ─── Состояния для ConversationHandler ───
(
    FEEDBACK_MENU,
    FEEDBACK_TITLE,
    FEEDBACK_DESC,
    FEEDBACK_URL,
    FEEDBACK_CLOSE
) = range(5)


def build_feedback_menu():
    """
    Возвращает InlineKeyboardMarkup для меню обратной связи.
    """
    kb = [
        [InlineKeyboardButton("📜 Мои заявки",   callback_data="fb_list")],
        [InlineKeyboardButton("🆕 Новая заявка", callback_data="fb_new")],
        [InlineKeyboardButton("🔒 Закрыть заявку", callback_data="fb_close")],
        [InlineKeyboardButton("◀️ Назад",        callback_data="fb_back_to_main")],
    ]
    return InlineKeyboardMarkup(kb)

@subscription_required
async def feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик /feedback или callback_data="menu_feedback": рисует inline-меню “Обратная связь”.
    """
    markup = build_feedback_menu()
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.message.edit_text(
            "✉️ Обратная связь. Выберите действие:",
            reply_markup=markup
        )
    else:
        await update.message.reply_text(
            "✉️ Обратная связь. Выберите действие:",
            reply_markup=markup
        )
    return FEEDBACK_MENU


async def feedback_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    db = SessionLocal()
    items = db.query(Feedback).filter_by(telegram_id=q.from_user.id).order_by(Feedback.created_at.desc()).all()
    db.close()

    if not items:
        await q.message.edit_text("У вас нет заявок.", reply_markup=build_feedback_menu())
        return FEEDBACK_MENU

    text = "Ваши заявки:\n\n"
    for fb in items:
        text += (
            f"ID {fb.id}: {fb.title}\n"
            f"Статус: {fb.status}\n"
            f"Прогресс: {fb.progress}\n\n"
        )
    await q.message.edit_text(text, reply_markup=build_feedback_menu())
    return FEEDBACK_MENU


async def feedback_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    await q.message.edit_text("Шаг 1/3: Заголовок (1–100 символов):", reply_markup=None)
    return FEEDBACK_TITLE


async def feedback_title_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = update.message.text.strip()
    if not (1 <= len(s) <= 100):
        return await update.message.reply_text("❗️ Заголовок 1–100 символов. Повторите:")

    context.user_data["fb_title"] = s
    await update.message.reply_text("Шаг 2/3: Описание (1–500 символов):")
    return FEEDBACK_DESC


async def feedback_desc_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = update.message.text.strip()
    if not (1 <= len(s) <= 500):
        return await update.message.reply_text("❗️ Описание 1–500 символов. Повторите:")

    context.user_data["fb_desc"] = s
    await update.message.reply_text("Шаг 3/3: HTTPS-ссылка или “нет” для пропуска:")
    return FEEDBACK_URL


async def feedback_url_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    if raw.lower() != "нет":
        if not raw.startswith("https://"):
            return await update.message.reply_text("❗️ Неверная ссылка. Повторите или “нет”:")
        context.user_data["fb_url"] = raw
    else:
        context.user_data["fb_url"] = ""

    db = SessionLocal()
    fb = Feedback(
        telegram_id=update.effective_user.id,
        title=context.user_data["fb_title"],
        description=context.user_data["fb_desc"],
        url=context.user_data["fb_url"],
        status="Новая",
        progress="0%"
    )
    db.add(fb)
    db.commit()
    fb_id = fb.id
    db.close()

    await update.message.reply_text(
        f"✅ Заявка принята! ID: {fb_id}\nСтатус: Новая"
    )
    # Возвращаемся к меню обратной связи
    return await feedback_start(update, context)


async def feedback_close_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    await q.message.edit_text("Введите ID заявки для закрытия:", reply_markup=None)
    return FEEDBACK_CLOSE


async def feedback_close_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if not txt.isdigit():
        return await update.message.reply_text("Введите числовой ID или /cancel:")

    fb_id = int(txt)
    db = SessionLocal()
    fb = db.query(Feedback).filter(Feedback.id == fb_id).first()
    if not fb or fb.telegram_id != update.effective_user.id:
        db.close()
        return await update.message.reply_text("Заявка не найдена или не ваша.")

    fb.status = "Закрыта"
    db.commit()
    db.close()

    await update.message.reply_text(f"✅ Заявка {fb_id} закрыта.")
    return await feedback_start(update, context)


async def feedback_back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # При callback: ответ и переход в меню
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        return await feedback_start(update, context)
    # При текстовом сообщении: просто /cancel
    return await feedback_start(update, context)


# ─── ConversationHandler и CallbackQueryHandler ───
feedback_conv = ConversationHandler(
    entry_points=[
        CommandHandler("feedback", feedback_start),
        CallbackQueryHandler(feedback_start, pattern=r"^menu_feedback$")
    ],
    states={
        FEEDBACK_MENU: [
            CallbackQueryHandler(feedback_list,         pattern=r"^fb_list$"),
            CallbackQueryHandler(feedback_new,          pattern=r"^fb_new$"),
            CallbackQueryHandler(feedback_close_select, pattern=r"^fb_close$"),
            CallbackQueryHandler(feedback_back_to_main, pattern=r"^fb_back_to_main$"),
        ],
        FEEDBACK_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_title_received)],
        FEEDBACK_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_desc_received)],
        FEEDBACK_URL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_url_received)],
        FEEDBACK_CLOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_close_process)],
    },
    fallbacks=[CallbackQueryHandler(feedback_back_to_main, pattern=r"^fb_back_to_main$")],
    per_user=True,
    allow_reentry=True,
)


def get_handlers():
    return [
        feedback_conv,
    ]
