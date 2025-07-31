# handlers/categories.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from db import SessionLocal
from models import Category, Post
from handlers.utils import subscription_required
import re

# Состояние не используется, но нужно для унификации возвращаемых ConversationHandler.END
CATEGORY_END = ConversationHandler.END

# Шаблон для извлечения chat и message_id из ссылки вида "https://t.me/channel_name/123"
_CHAT_MSG_RE = re.compile(r"https?://t\.me/(?P<chat>[^/]+)/(?P<msg_id>\d+)")

def build_categories_menu(parent_id=None, offset=0, limit=5):
    """
    Строит InlineKeyboardMarkup:
    - Если у категории (parent_id) есть подкатегории, показывает кнопки подкатегорий.
    - Иначе показывает список постов (title→link) с пагинацией.
    """
    db = SessionLocal()

    # 1) Попробуем найти подкатегории текущей parent_id
    subs = (
        db.query(Category)
          .filter(Category.parent_id == parent_id)
          .order_by(Category.name)
          .all()
    )
    if subs:
        buttons = [
            [InlineKeyboardButton(f"📂 {c.name}", callback_data=f"cat:{c.id}:0")]
            for c in subs
        ]
        db.close()
        return InlineKeyboardMarkup(buttons)

    # 2) Если подкатегорий нет, показываем список постов в этой категории
    q = db.query(Post).filter(Post.category_id == parent_id, Post.archived == False).order_by(Post.id)
    total = q.count()
    posts = q.offset(offset).limit(limit).all()
    db.close()

    rows = []
    for p in posts:
        rows.append([InlineKeyboardButton(f"🔗 {p.title}", callback_data=f"view_post:{p.id}")])

    # 3) Навигация «‹ Назад / Далее ›» при большом количестве постов
    nav = []
    if offset > 0:
        nav.append(
            InlineKeyboardButton(
                "‹ Назад",
                callback_data=f"cat:{parent_id}:{max(offset - limit, 0)}"
            )
        )
    if offset + limit < total:
        nav.append(
            InlineKeyboardButton(
                "Далее ›",
                callback_data=f"cat:{parent_id}:{offset + limit}"
            )
        )
    if nav:
        rows.append(nav)

    # 4) Если нет ни постов, ни подкатегорий — показываем единственную кнопку «Нет записей»
    if not rows:
        rows = [[InlineKeyboardButton("🚫 Нет записей", callback_data="nopost:0")]]

    return InlineKeyboardMarkup(rows)


async def _forward_post(update: Update, context: ContextTypes.DEFAULT_TYPE, post: Post):
    """
    Пересылает оригинальное сообщение из канала пользователю.
    Если ссылка post.link соответствует формату t.me/channel_name/msg_id, делает forward_message.
    В противном случае — редактирует сообщение с fallback-текстом.
    """
    qr = update.callback_query
    await qr.answer()

    user_chat_id = qr.message.chat.id

    # Если у модели Post есть поля channel_username и message_id, можно использовать их напрямую.
    if hasattr(post, "channel_username") and hasattr(post, "message_id"):
        try:
            await context.bot.forward_message(
                chat_id=user_chat_id,
                from_chat_id=f"@{post.channel_username}",
                message_id=post.message_id
            )
            return
        except Exception:
            # если forward не прошёл — отправляем ссылку как fallback
            await qr.message.reply_text(f"Не удалось переслать сообщение. Вот ссылка: {post.link}")
            return

    # Пытаемся распарсить ссылку post.link вида "https://t.me/channel_name/123"
    m = _CHAT_MSG_RE.match(post.link)
    if m:
        channel = m.group("chat")
        msg_id = int(m.group("msg_id"))
        try:
            await context.bot.forward_message(
                chat_id=user_chat_id,
                from_chat_id=f"@{channel}",
                message_id=msg_id
            )
            return
        except Exception:
            await qr.message.reply_text(f"Не удалось переслать сообщение. Вот ссылка: {post.link}")
            return

    # Если не получилось распарсить — показываем fallback
    await qr.message.reply_text(f"🔗 <b>{post.title}</b>\n{post.link}", parse_mode="HTML")


@subscription_required
async def categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /categories.
    Выводит пользователю «верхние» категории (parent_id=None) в виде инлайн-клавиатуры.
    """
    await update.message.reply_text(
        "📂 Выберите категорию:",
        reply_markup=build_categories_menu(None)
    )


@subscription_required
async def add_category_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Шаг 1/1: Администраторы вводят название новой категории.
    """
    await update.message.reply_text(
        "📝 Введите название новой категории:",
        reply_markup=ReplyKeyboardRemove()
    )
    return CATEGORY_END  # Используем CATEGORY_END, но фактически Conversation сразу завершится.


async def add_category_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Принимает текст от администратора и создаёт новую запись Category.
    """
    name = update.message.text.strip()
    if not name:
        return await update.message.reply_text("❗️ Название не может быть пустым. Повторите:")

    db = SessionLocal()
    db.add(Category(name=name))
    db.commit()
    db.close()

    await update.message.reply_text(f"✅ Категория «{name}» добавлена.")
    return CATEGORY_END


async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает нажатия инлайн-кнопок из build_categories_menu:
    - callback_data="cat:{category_id}:{offset}"
    - callback_data="view_post:{post_id}"
    - callback_data="nopost:0"
    """
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    parts = data.split(":")

    # 1) Нажали на кнопку «Перейти в подкатегорию» или «Навигация постами»
    if parts[0] == "cat" and len(parts) == 3:
        cat_id = int(parts[1])
        offset = int(parts[2])
        kb = build_categories_menu(parent_id=cat_id, offset=offset)
        await q.edit_message_text(
            f"📂 Содержимое категории (ID {cat_id}):",
            reply_markup=kb
        )
        return

    # 2) Нажали на кнопку «Просмотреть пост» — теперь пересылаем оригинал
    if parts[0] == "view_post" and len(parts) == 2:
        post_id = int(parts[1])
        db = SessionLocal()
        post = db.query(Post).filter(Post.id == post_id).first()
        db.close()
        if post:
            await _forward_post(update, context, post)
        else:
            await q.edit_message_text("❌ Пост не найден.")
        return

    # 3) Нажали «Нет записей» или что-то неизвестное
    if parts[0] == "nopost":
        await q.edit_message_text("🚫 Здесь нет записей.")
        return

    # Если data не подошло ни под одно условие, не делаем ничего.


async def discord_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Универсальный «отменить» для ConversationHandler (если понадобится).
    """
    # Можно просто сообщить об отмене
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.message.reply_text("❌ Операция отменена.")
    else:
        await update.message.reply_text("❌ Операция отменена.")
    context.user_data.clear()
    return CATEGORY_END


def get_handlers():
    """
    Экспорт списка handler’ов для bot.py:
    1) CommandHandler("/categories", categories_command)
    2) ConversationHandler для добавления категории
    3) CallbackQueryHandler для обработки нажатий в меню
    """
    return [
        # 1) Показ списка категорий
        CommandHandler("categories", categories_command),

        # 2) Добавление категории через ConversationHandler
        ConversationHandler(
            entry_points=[CommandHandler("add_category", add_category_start)],
            states={
                CATEGORY_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_category_process)],
            },
            fallbacks=[CommandHandler("cancel", discord_cancel)],
            per_user=True,
            allow_reentry=True,
        ),

        # 3) Обработка кликов в инлайн-меню категорий/постов
        CallbackQueryHandler(category_callback, pattern=r"^(cat|view_post|nopost):"),
    ]
