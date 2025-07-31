# bot.py

import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from config import TELEGRAM_TOKEN
from db import init_db

# ───────────── ИНИЦИАЛИЗАЦИЯ ─────────────

# Инициализируем базу и логирование
init_db()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ───────────── ГЛАВНОЕ МЕНЮ ─────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик /start: рисует единственное сообщение с Inline-кнопками.
    """
    keyboard = [
        [
            InlineKeyboardButton("🔍 Поиск", callback_data="menu_search"),
            InlineKeyboardButton("📂 Категории", callback_data="menu_categories"),
        ],
        [
            InlineKeyboardButton("✉️ Обратная связь", callback_data="menu_feedback"),
            InlineKeyboardButton("💬 Discord-анонсы", callback_data="menu_discord"),
        ],
        [
            InlineKeyboardButton("ℹ️ Помощь", callback_data="menu_help"),
        ]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    # Если пользователь зашёл /start — присылаем сообщение с Inline-кнопками:
    await update.message.reply_text(
        "👋 Добро пожаловать! Выберите действие:",
        reply_markup=markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик /help: отправляет краткую справку по всем командам.
    """
    text = (
        "/start — Главное меню\n"
        "/help — Справка по командам\n"
        "/search — Поиск по постам\n"
        "/categories — Просмотр категорий\n"
        "/feedback — Обратная связь\n"
        "/add_category — Добавить категорию (админ)\n"
        "/discord — Меню Discord-анонсов\n"
        "/cancel — Отмена текущей операции\n"
    )
    # /help мог быть вызван и как команда, и как callback_query
    if update.message:
        await update.message.reply_text(text)
    elif update.callback_query:
        await update.callback_query.message.reply_text(text)


# ───────────── РОУТЕР INLINE-КНОПОК ─────────────

async def main_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Когда пользователь нажимает любую кнопку главного меню (callback_data="menu_*"),
    Telegram шлёт CallbackQuery. Здесь мы «ловим» menu_* и вызываем нужный модуль
    из папки handlers/ без отправки буквального "/search" или "/categories" в чат.
    """
    q = update.callback_query
    await q.answer()  # убираем часики-“завантаження”

    data = q.data or ""
    # Получаем “головное” сообщение, в котором лежала клавиатура
    chat_message = q.message

    # 1) Если нажали “🔍 Поиск” → вызывать search_start из handlers/search.py
    if data == "menu_search":
        from handlers.search import search_start

        raw = {
            "update_id": update.update_id,
            "message": chat_message.to_dict()
        }
        fake_update = Update.de_json(raw, context.bot)
        return await search_start(fake_update, context)

    # 2) Если нажали “📂 Категории” → вызывать categories_command из handlers/categories.py
    if data == "menu_categories":
        from handlers.categories import categories_command

        raw = {
            "update_id": update.update_id,
            "message": chat_message.to_dict()
        }
        fake_update = Update.de_json(raw, context.bot)
        return await categories_command(fake_update, context)

    # 3) Если нажали “✉️ Обратная связь” → вызывать feedback_start из handlers/feedback.py
    if data == "menu_feedback":
        from handlers.feedback import feedback_start

        raw = {
            "update_id": update.update_id,
            "message": chat_message.to_dict()
        }
        fake_update = Update.de_json(raw, context.bot)
        return await feedback_start(fake_update, context)

    # 4) Если нажали “💬 Discord-анонсы” → вызывать discord_menu из handlers/discord.py
    if data == "menu_discord":
        from handlers.discord import discord_menu

        raw = {
            "update_id": update.update_id,
            "message": chat_message.to_dict()
        }
        fake_update = Update.de_json(raw, context.bot)
        return await discord_menu(fake_update, context)

    # 5) Если нажали “ℹ️ Помощь” (callback_data="menu_help") — показать встроенную справку
    if data == "menu_help":
        return await help_command(update, context)

    # На всякий случай: если data не подходит — возвращаемся к /start
    return await start_command(update, context)


# ───────────── РЕГИСТРАЦИЯ ВСЕХ ХЕНДЛЕРОВ ─────────────

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # 1) /start и /help
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))


    # 3) Подключаем все остальные группы хендлеров из папки handlers/
    from handlers.admin       import get_handlers as get_admin_handlers
    from handlers.categories  import get_handlers as get_categories_handlers
    from handlers.feedback    import get_handlers as get_feedback_handlers
    from handlers.search      import get_handlers as get_search_handlers
    from handlers.discord     import get_handlers as get_discord_handlers
    from handlers.utils       import get_handlers as get_utils_handlers

    # 3.1) Админские хендлеры
    for h in get_admin_handlers():
        app.add_handler(h)

    # 3.2) Хендлеры “Категории” (handlers/categories.py)
    for h in get_categories_handlers():
        app.add_handler(h)

    # 3.3) Хендлеры “Обратная связь” (handlers/feedback.py)
    for h in get_feedback_handlers():
        app.add_handler(h)

    # 3.4) Хендлеры “Поиск” (handlers/search.py)
    for h in get_search_handlers():
        app.add_handler(h)

    # 3.5) Хендлеры “Discord-анонсы” (handlers/discord.py)
    for h in get_discord_handlers():
        app.add_handler(h)

    # 2) CallbackQueryHandler для любого callback_data, которое начинается с “menu_”
    app.add_handler(CallbackQueryHandler(main_menu_router, pattern=r"^menu_"))

    # 3.6) Утилиты (handlers/utils.py), например /cancel
    for h in get_utils_handlers():
        app.add_handler(h)

    # 4) Запускаем polling
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
