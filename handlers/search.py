# handlers/search.py

import difflib
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from db import SessionLocal
from models import Post

from handlers.utils import subscription_required

# Состояния для ConversationHandler
SEARCH_QUERY = 0

# Регулярка, чтобы из ссылки типа https://t.me/channel_username/123 выцепить канал и ID сообщения
_CHAT_MSG_RE = re.compile(r"https?://t\.me/(?P<chat>[^/]+)/(?P<msg_id>\d+)")

@subscription_required
async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Точка входа на /search или кнопку «🔍 Поиск».
    Спрашиваем у пользователя текст запроса и убираем ReplyKeyboard.
    """
    # Если вызвано через callback_query (нажатие «menu_search»)
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        target = q.message
    else:
        target = update.message

    await target.reply_text(
        "Введите запрос для поиска:",
        reply_markup=ReplyKeyboardRemove()
    )
    return SEARCH_QUERY


async def _forward_post_to_user(user_chat_id: int, post: Post, context: ContextTypes.DEFAULT_TYPE):
    """
    Вспомогательная функция: из поля post.link (или полей post.channel_username и post.message_id)
    выцепляем, откуда нужно переслать, и делаем forward_message.
    """
    # Если в модели хранится post.channel_username и post.message_id:
    if hasattr(post, "channel_username") and hasattr(post, "message_id"):
        try:
            await context.bot.forward_message(
                chat_id=user_chat_id,
                from_chat_id=f"@{post.channel_username}",
                message_id=post.message_id
            )
        except Exception:
            # Если чего-то вдруг нет доступа или не получилось, отправляем ссылку как fallback
            await context.bot.send_message(
                chat_id=user_chat_id,
                text=f"Не удалось переслать сообщение. Вот ссылка: {post.link}"
            )
        return

    # Иначе, если есть только post.link вида "https://t.me/channel_username/msg_id"
    m = _CHAT_MSG_RE.match(post.link)
    if m:
        chat = m.group("chat")
        msg_id = int(m.group("msg_id"))
        try:
            await context.bot.forward_message(
                chat_id=user_chat_id,
                from_chat_id=f"@{chat}",
                message_id=msg_id
            )
        except Exception:
            # fallback: отправим просто ссылку
            await context.bot.send_message(
                chat_id=user_chat_id,
                text=f"Не удалось переслать сообщение. Вот ссылка: {post.link}"
            )
        return

    # Если не удалось распарсить -- просто отправляем текст с ссылкой
    await context.bot.send_message(
        chat_id=user_chat_id,
        text=f"🔸 {post.title}\n{post.link}"
    )


async def search_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Получили от пользователя текст запроса. Ищем в таблице Post по вхождению в title.
    Если нашлись exact-совпадения – пересылаем оригиналы.
    Иначе – строим список похожих названий и показываем кнопки-подсказки.
    """
    query = update.message.text.strip()
    db = SessionLocal()
    # Ищем точные (substring) совпадения в title, неархивированные
    exact_posts = (
        db.query(Post)
          .filter(Post.title.ilike(f"%{query}%"), Post.archived == False)
          .limit(5)
          .all()
    )

    user_chat_id = update.effective_chat.id

    if exact_posts:
        # Если хоть что-то нашлось – пересылаем оригиналы
        for post in exact_posts:
            await _forward_post_to_user(user_chat_id, post, context)
        db.close()
        return ConversationHandler.END

    # Если exact не нашлось – собираем все названия (unarchived) и через difflib ищем похожие
    all_titles = [p.title for p in db.query(Post).filter_by(archived=False).all()]
    db.close()

    close_matches = difflib.get_close_matches(query, all_titles, n=5, cutoff=0.5)
    if not close_matches:
        await update.message.reply_text("Ничего не найдено и похожих вариантов нет.")
        return ConversationHandler.END

    # Если похожие нашлись – показываем их в виде Inline-кнопок
    buttons = [
        [InlineKeyboardButton(text=title, callback_data=f"search_suggest:{title}")]
        for title in close_matches
    ]
    kb = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(
        "Ничего не нашлось, может, вы имели в виду:",
        reply_markup=kb
    )
    return ConversationHandler.END


async def search_suggest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик нажатия на кнопку-подсказку «search_suggest:НазваниеПоста».
    Берёт из БД пост по title и пересылает оригинальное сообщение.
    """
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if not data.startswith("search_suggest:"):
        return ConversationHandler.END

    title = data.split(":", 1)[1]
    db = SessionLocal()
    post = db.query(Post).filter_by(title=title).first()
    db.close()

    user_chat_id = q.message.chat.id
    if post:
        await _forward_post_to_user(user_chat_id, post, context)
    else:
        await q.edit_message_text("Увы, этот пост недоступен.")
    return ConversationHandler.END


async def search_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик на случай, если пользователь введёт /cancel во время поиска.
    """
    # Если вызван через callback_query (редко), отвечаем и отправляем сообщение
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        target = q.message
    else:
        target = update.message

    await target.reply_text("Поиск отменён.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def get_handlers():
    """
    Возвращает список хендлеров, чтобы bot.py мог просто делать:
        for h in get_search_handlers(): 
            app.add_handler(h)
    """

    # Conversation для команд /search и текстового варианта «🔍 Поиск»
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("search", search_start),
            MessageHandler(filters.Regex(r"^🔍 Поиск$"), search_start),
            CallbackQueryHandler(search_start, pattern=r"^menu_search$")
        ],
        states={
            SEARCH_QUERY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_process)
            ]
        },
        fallbacks=[CommandHandler("cancel", search_cancel)],
        allow_reentry=True,
        per_user=True,
    )

    # CallbackQueryHandler для тех подсказок, что в кнопках search_suggest:<title>
    suggest_cb = CallbackQueryHandler(search_suggest_callback, pattern=r"^search_suggest:")

    return [conv, suggest_cb]
