# handlers/discord.py
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from db import SessionLocal
from models import (
    User,
    DiscordChannel,
    Filter,
    DiscordAnnouncement,
    AvailableDiscordChannel,
)
from config import ADMIN_IDS
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

from handlers.utils import subscription_required

# Мануальный словарь русских названий месяцев
RU_MONTHS = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}

# ─── Состояния ConversationHandler ───────────────────────────────────────────
(
    VIEW_LAST_ANNOUNCEMENTS,   # 105 – главное меню “Discord-анонсы”
    ADD_CHANNEL_NAME,          # 100 – ждём ID/ссылку от пользователя
    SELECT_CHANNEL_FOR_UNSUB,  # 101 – пользователь нажал "Отписаться от оповещений"
    SELECT_CHANNEL_FOR_FILTER, # 102 – пользователь нажал "Добавить фильтр"
    ADD_FILTER_KEYWORD,        # 103 – ждём от пользователя текст (ключевое слово)
    SELECT_FILTER_FOR_DELETE   # 104 – пользователь нажал "Удалить фильтр"
) = range(100, 106)

# ─── Callback_data префиксы и константы ──────────────────────────────────────
CB_ADD_CHANNEL           = "add_discord_channel"
CB_UNSUBSCRIBE_CHANNEL   = "unsubscribe_discord_channel"
CB_VIEW_MY_CHANNELS      = "view_my_channels"
CB_ADD_FILTER            = "add_discord_filter"
CB_DELETE_FILTER         = "delete_discord_filter"
CB_LATEST_ANNOUNCEMENTS  = "latest_discord_announcements"
CB_BACK_TO_START         = "back_to_start"
CB_LIST_AVAILABLE        = "list_available_discord_channels"
CB_ADD_FROM_LIST_PREFIX  = "add_from_list:"
CB_ANN_PAGE_PREFIX       = "anns_page:"  # используется для пагинации


def escape_md_v2(text: str) -> str:
    """
    Экранирует все символы, зарезервированные в MarkdownV2, кроме самого символа '>' в начале строки.
    Библиотечный список символов, которые нужно экранировать: _ * [ ] ( ) ~ ` > # + - = | { } . !
    Однако мы НЕ экранируем полный маркер цитаты '>' (он должен остаться чистым).
    Поэтому внутри каждой строки мы экранируем ВСЁ, а префикс '> ' добавляем отдельно.
    """
    # Список символов MarkdownV2, подлежащих экранированию
    specials = r"\_*\[\]()~`>#+\-=|{}\.!"
    # Функция replaces each special char with a backslash + char
    return re.sub(rf"([{specials}])", r"\\\1", text)


@subscription_required
async def discord_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Точка входа: /discord или callback_data="menu_discord" —
    рисует меню с Inline-кнопками и переводит Conversation в состояние VIEW_LAST_ANNOUNCEMENTS.
    """
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        send_target = q.message
    else:
        send_target = update.message

    user_id = update.effective_user.id

    keyboard = [
        [InlineKeyboardButton("➕ Добавить канал", callback_data=CB_ADD_CHANNEL)],
        [InlineKeyboardButton("➖ Отписаться от оповещений", callback_data=CB_UNSUBSCRIBE_CHANNEL)],
        [InlineKeyboardButton("📜 Мои каналы",             callback_data=CB_VIEW_MY_CHANNELS)],
        [InlineKeyboardButton("📜 Список каналов",         callback_data=CB_LIST_AVAILABLE)],
        [InlineKeyboardButton("➕ Добавить фильтр",        callback_data=CB_ADD_FILTER)],
        [InlineKeyboardButton("➖ Удалить фильтр",         callback_data=CB_DELETE_FILTER)],
        [InlineKeyboardButton("📰 Последние анонсы",       callback_data=CB_LATEST_ANNOUNCEMENTS)],
        [InlineKeyboardButton("◀️ Назад",                  callback_data=CB_BACK_TO_START)],
    ]

    # Упрощённое меню для не-админов:
    if user_id not in ADMIN_IDS:
        keyboard = [
            [InlineKeyboardButton("➖ Отписаться от оповещений", callback_data=CB_UNSUBSCRIBE_CHANNEL)],
            [InlineKeyboardButton("📜 Список каналов",            callback_data=CB_LIST_AVAILABLE)],
            [InlineKeyboardButton("📜 Мои каналы",                callback_data=CB_VIEW_MY_CHANNELS)],
            [InlineKeyboardButton("📰 Последние анонсы",          callback_data=CB_LATEST_ANNOUNCEMENTS)],
            [InlineKeyboardButton("◀️ Назад",                     callback_data=CB_BACK_TO_START)],
        ]

    markup = InlineKeyboardMarkup(keyboard)
    await send_target.reply_text("Меню Discord-анонсов:", reply_markup=markup)
    return VIEW_LAST_ANNOUNCEMENTS


async def show_announcements(update: Update, context: ContextTypes.DEFAULT_TYPE, page_index: int = 0):
    """
    Показывает лог из последних 5 анонсов, разбитых на страницы.
    Каждый анонс выводится в MarkdownV2-цитате ("> "), чтобы Telegram отрисовал
    его с левым бортиком и серым фоном.
    """
    q = update.callback_query
    if not q:
        return

    telegram_id = q.from_user.id
    db = SessionLocal()

    user_row = db.query(User).filter_by(telegram_id=telegram_id).first()
    if not user_row:
        db.close()
        return

    # Берём последние 5 анонсов (по дате DESC)
    last_five = (
        db.query(DiscordAnnouncement)
          .filter_by(user_id=user_row.id)
          .order_by(DiscordAnnouncement.created_at.desc())
          .limit(5)
          .all()
    )
    db.close()

    if not last_five:
        # Если нет ни одного анонса
        await q.edit_message_text("❗ Пока нет анонсов для вас.")
        return

    # Собираем анонсы в список словарей
    announcements = []
    for a in last_five:
        content = a.translated if a.translated else a.content
        announcements.append({
            "created_at": a.created_at,
            "content": content,
            "matched_filter": a.matched_filter
        })

    # Формируем страницы: если длина > 300 → отдельная страница,
    # иначе пробуем объединить два подряд коротких (≤ 300) на одной странице
    pages = []
    i = 0
    while i < len(announcements):
        a = announcements[i]
        if len(a["content"]) > 300:
            pages.append([a])
            i += 1
        else:
            if (i + 1 < len(announcements)) and (len(announcements[i + 1]["content"]) <= 300):
                pages.append([a, announcements[i + 1]])
                i += 2
            else:
                pages.append([a])
                i += 1

    # Корректируем индекс страницы
    if page_index < 0:
        page_index = 0
    if page_index >= len(pages):
        page_index = len(pages) - 1

    current_page = pages[page_index]

    # Группируем объявления текущей страницы по дате (день месяц год)
    grouped = {}
    for ann in current_page:
        dt = ann["created_at"]
        day = dt.day
        month_ru = RU_MONTHS.get(dt.month, str(dt.month))
        year = dt.year
        date_key = f"{day} {month_ru} {year}"
        grouped.setdefault(date_key, []).append(ann)

    # Формируем текст с цитированием (MarkdownV2)
    text_lines = []
    for date_str, anns_list in grouped.items():
        # Добавляем жирный заголовок даты (MarkdownV2: *дата*)
        date_escaped = escape_md_v2(date_str)
        text_lines.append(f"*{date_escaped}*")

        for a in anns_list:
            time_part = a["created_at"].strftime("%H:%M")
            content_raw = a["content"]
            # Разбиваем содержимое по строкам, чтобы каждую строку цитировать
            content_lines = content_raw.splitlines() or [content_raw]

            # Первая строка: добавляем время и начало контента, экранируем
            first_line = content_lines[0]
            first_escaped = escape_md_v2(first_line)
            time_escaped = escape_md_v2(time_part)
            text_lines.append(f"> `{time_escaped}` · {first_escaped}")

            # Остальные строки: экранируем и цитируем
            for extra_line in content_lines[1:]:
                extra_escaped = escape_md_v2(extra_line)
                text_lines.append(f"> {extra_escaped}")

        text_lines.append("")  # пустая строка после группы по дате

    # Убираем лишний пустой "\n" в конце
    text = "\n".join(text_lines).rstrip()

    # Собираем кнопки навигации (постранично)
    keyboard = []
    nav_buttons = []
    if page_index > 0:
        prev_idx = page_index - 1
        nav_buttons.append(
            InlineKeyboardButton("◀️ Назад", callback_data=f"{CB_ANN_PAGE_PREFIX}{prev_idx}")
        )
    if page_index + 1 < len(pages):
        next_idx = page_index + 1
        nav_buttons.append(
            InlineKeyboardButton("👉 Далее", callback_data=f"{CB_ANN_PAGE_PREFIX}{next_idx}")
        )
    if nav_buttons:
        keyboard.append(nav_buttons)

    # Кнопка возврата в меню Discord
    keyboard.append([InlineKeyboardButton("◀️ Назад в меню Discord", callback_data=CB_BACK_TO_START)])
    markup = InlineKeyboardMarkup(keyboard)

    # Отправляем через MarkdownV2 — Telegram теперь отдаёт блок-цитату за ">"
    await q.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=markup
    )


async def discord_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка нажатий inline-кнопок из состояния VIEW_LAST_ANNOUNCEMENTS.
    """
    q = update.callback_query
    await q.answer()
    data = q.data
    chat_id = q.message.chat.id

    # Если нажали «◀️ Назад в меню Discord» — возвращаем главное меню
    if data == CB_BACK_TO_START:
        user_id = q.from_user.id

        keyboard = [
            [InlineKeyboardButton("➕ Добавить канал", callback_data=CB_ADD_CHANNEL)],
            [InlineKeyboardButton("➖ Отписаться от оповещений", callback_data=CB_UNSUBSCRIBE_CHANNEL)],
            [InlineKeyboardButton("📜 Мои каналы",             callback_data=CB_VIEW_MY_CHANNELS)],
            [InlineKeyboardButton("📜 Список каналов",         callback_data=CB_LIST_AVAILABLE)],
            [InlineKeyboardButton("➕ Добавить фильтр",        callback_data=CB_ADD_FILTER)],
            [InlineKeyboardButton("➖ Удалить фильтр",         callback_data=CB_DELETE_FILTER)],
            [InlineKeyboardButton("📰 Последние анонсы",       callback_data=CB_LATEST_ANNOUNCEMENTS)],
            [InlineKeyboardButton("◀️ Назад",                  callback_data=CB_BACK_TO_START)],
        ]
        if user_id not in ADMIN_IDS:
            keyboard = [
                [InlineKeyboardButton("➖ Отписаться от оповещений", callback_data=CB_UNSUBSCRIBE_CHANNEL)],
                [InlineKeyboardButton("📜 Список каналов",            callback_data=CB_LIST_AVAILABLE)],
                [InlineKeyboardButton("📜 Мои каналы",                callback_data=CB_VIEW_MY_CHANNELS)],
                [InlineKeyboardButton("📰 Последние анонсы",          callback_data=CB_LATEST_ANNOUNCEMENTS)],
                [InlineKeyboardButton("◀️ Назад",                     callback_data=CB_BACK_TO_START)],
            ]

        markup = InlineKeyboardMarkup(keyboard)
        try:
            await q.edit_message_text("Меню Discord-анонсов:", reply_markup=markup)
        except Exception as e:
            # Если Telegram бросил «Message is not modified», значит контент/разметка не изменились
            if "Message is not modified" not in str(e):
                raise
        return VIEW_LAST_ANNOUNCEMENTS

    # Получаем (или создаём) пользователя в БД
    db = SessionLocal()
    telegram_id = q.from_user.id
    user_row = db.query(User).filter_by(telegram_id=telegram_id).first()
    if not user_row:
        user_row = User(telegram_id=telegram_id, username=q.from_user.username)
        db.add(user_row)
        db.commit()
        db.refresh(user_row)

    # ───── 1) «➕ Добавить канал»
    if data == CB_ADD_CHANNEL:
        if telegram_id not in ADMIN_IDS:
            await q.edit_message_text("❌ У вас нет прав на ручное добавление канала.")
            db.close()
            return VIEW_LAST_ANNOUNCEMENTS

        await q.edit_message_text(
            "Шаг 1: Пришлите ID Discord-канала (число) или ссылку вида:\n"
            "https://discord.com/channels/ID_сервера/ID_канала"
        )
        db.close()
        return ADD_CHANNEL_NAME

    # ───── 2) «➖ Отписаться от оповещений»
    if data == CB_UNSUBSCRIBE_CHANNEL:
        channels = (
            db.query(DiscordChannel)
              .filter_by(user_id=user_row.id, active=True)
              .order_by(DiscordChannel.id)
              .all()
        )
        if not channels:
            db.close()
            await q.edit_message_text("❗ У вас нет активных подписок на Discord-каналы.")
            return VIEW_LAST_ANNOUNCEMENTS

        buttons = []
        for ch in channels:
            db2 = SessionLocal()
            adc = db2.query(AvailableDiscordChannel).filter_by(channel_id=ch.channel_id).first()
            db2.close()

            label = adc.channel_name if adc else ch.channel_id
            buttons.append([InlineKeyboardButton(label, callback_data=f"unsub_chan_{ch.id}")])

        kb_unsub = InlineKeyboardMarkup(buttons)
        await q.edit_message_text(
            "Выберите канал, от которого хотите отписаться:",
            reply_markup=kb_unsub
        )
        db.close()
        return SELECT_CHANNEL_FOR_UNSUB

    # ───── 2a) «📜 Список каналов»
    if data == CB_LIST_AVAILABLE:
        db2 = SessionLocal()
        available = (
            db2.query(AvailableDiscordChannel)
               .filter_by(is_active=True)
               .order_by(AvailableDiscordChannel.channel_name)
               .all()
        )
        db2.close()

        if not available:
            await q.edit_message_text("❗ Пока нет доступных каналов.")
            db.close()
            return VIEW_LAST_ANNOUNCEMENTS

        buttons = [
            [InlineKeyboardButton(row.channel_name, callback_data=f"{CB_ADD_FROM_LIST_PREFIX}{row.channel_id}")]
            for row in available
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        await q.edit_message_text("Выберите канал для подписки:", reply_markup=keyboard)
        db.close()
        return VIEW_LAST_ANNOUNCEMENTS

    # ───── 3) «add_from_list:<channel_id>»
    if data.startswith(CB_ADD_FROM_LIST_PREFIX):
        channel_id = data.split(":", 1)[1]
        db_ch = SessionLocal()
        existing = db_ch.query(DiscordChannel).filter_by(
            channel_id=channel_id, active=True, user_id=user_row.id
        ).first()
        if existing:
            db_ch.close()
            await q.edit_message_text("Этот канал уже добавлен.")
            return VIEW_LAST_ANNOUNCEMENTS

        new_ch = DiscordChannel(
            user_id=user_row.id,
            channel_id=channel_id,
            name=f"Discord_{channel_id}",
            active=True
        )
        db_ch.add(new_ch)
        db_ch.commit()
        db_ch.close()

        await q.edit_message_text(f"✅ Вы успешно подписались на канал {channel_id}.")
        db.close()
        return VIEW_LAST_ANNOUNCEMENTS

    # ───── 4) «📜 Мои каналы»
    if data == CB_VIEW_MY_CHANNELS:
        channels = (
            db.query(DiscordChannel)
              .filter_by(user_id=user_row.id, active=True)
              .order_by(DiscordChannel.id)
              .all()
        )
        db.close()
        if not channels:
            await q.edit_message_text("❗ У вас нет активных подписок на Discord-каналы.")
            return VIEW_LAST_ANNOUNCEMENTS

        text = "Ваши активные подписки Discord:\n"
        for ch in channels:
            db2 = SessionLocal()
            adc = db2.query(AvailableDiscordChannel).filter_by(channel_id=ch.channel_id).first()
            db2.close()

            disp = f"• {adc.channel_name}" if adc else f"• {ch.channel_id}"
            text += disp + "\n"

        await q.edit_message_text(text)
        return VIEW_LAST_ANNOUNCEMENTS

    # ───── 5) «➕ Добавить фильтр»
    if data == CB_ADD_FILTER:
        channels = (
            db.query(DiscordChannel)
              .filter_by(user_id=user_row.id, active=True)
              .order_by(DiscordChannel.id)
              .all()
        )
        if not channels:
            db.close()
            await q.edit_message_text("❗ Сначала добавьте канал.")
            return VIEW_LAST_ANNOUNCEMENTS

        buttons = [
            [InlineKeyboardButton(ch.name or ch.channel_id, callback_data=f"addf_{ch.id}")]
            for ch in channels
        ]
        kb_filter = InlineKeyboardMarkup(buttons)
        await q.edit_message_text("К какому каналу добавить фильтр?", reply_markup=kb_filter)
        db.close()
        return SELECT_CHANNEL_FOR_FILTER

    # ───── 6) «➖ Удалить фильтр»
    if data == CB_DELETE_FILTER:
        filters_ = (
            db.query(Filter)
              .filter_by(user_id=user_row.id, active=True)
              .order_by(Filter.id)
              .all()
        )
        if not filters_:
            db.close()
            await q.edit_message_text("❗ У вас нет активных фильтров.")
            return VIEW_LAST_ANNOUNCEMENTS

        buttons = [
            [InlineKeyboardButton(
                f"#{f.keyword} (канал {f.discord_channel.channel_id})",
                callback_data=f"delf_{f.id}"
            )]
            for f in filters_
        ]
        kb_delf = InlineKeyboardMarkup(buttons)
        await q.edit_message_text("Выберите фильтр для удаления:", reply_markup=kb_delf)
        db.close()
        return SELECT_FILTER_FOR_DELETE

    # ───── 7) «📰 Последние анонсы»
    if data == CB_LATEST_ANNOUNCEMENTS:
        await show_announcements(update, context, page_index=0)
        db.close()
        return VIEW_LAST_ANNOUNCEMENTS

    # ───── 8) «anns_page:<page_index>» — перелистывание страниц
    if data.startswith(CB_ANN_PAGE_PREFIX):
        try:
            page_index = int(data.split(":", 1)[1])
        except ValueError:
            page_index = 0
        await show_announcements(update, context, page_index)
        return VIEW_LAST_ANNOUNCEMENTS

    # ───── Незнакомый callback_data — остаёмся в этом меню
    db.close()
    return VIEW_LAST_ANNOUNCEMENTS


async def add_channel_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка текста после “➕ Добавить канал”.
    """
    raw = update.message.text.strip()
    if "/" in raw:
        channel_id = raw.rstrip("/").rsplit("/", 1)[-1]
    else:
        channel_id = raw

    db = SessionLocal()
    telegram_id = update.effective_user.id
    user_row = db.query(User).filter_by(telegram_id=telegram_id).first()
    if not user_row:
        user_row = User(telegram_id=telegram_id, username=update.effective_user.username)
        db.add(user_row)
        db.commit()
        db.refresh(user_row)

    new_ch = DiscordChannel(
        user_id=user_row.id,
        channel_id=channel_id,
        name=f"Discord_{channel_id}",
        active=True
    )
    db.add(new_ch)
    db.commit()
    db.close()

    await update.message.reply_text(
        f"✅ Вы подписались на Discord-канал {channel_id}.\n"
        "Теперь можно добавить фильтр или получать анонсы."
    )
    return ConversationHandler.END


async def select_channel_for_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка 'unsub_chan_{id}': помечаем DiscordChannel.active=False.
    """
    q = update.callback_query
    await q.answer()

    ch_id = int(q.data.replace("unsub_chan_", ""))
    db = SessionLocal()
    ch = db.query(DiscordChannel).filter(DiscordChannel.id == ch_id).first()
    if ch:
        ch.active = False
        db.commit()
    db.close()

    await q.edit_message_text("✅ Вы отписались от оповещений этого Discord-канала.")
    return VIEW_LAST_ANNOUNCEMENTS


async def select_channel_for_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка 'addf_{id}': запоминаем id канала в user_data.
    """
    q = update.callback_query
    await q.answer()

    ch_id = int(q.data.replace("addf_", ""))
    context.user_data["discord_channel_id"] = ch_id

    await q.edit_message_text("Шаг 2: Пришлите текст (ключевое слово) для фильтра:")
    return ADD_FILTER_KEYWORD


async def add_filter_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Сохраняем новый фильтр.
    """
    keyword = update.message.text.strip()
    ch_id = context.user_data.get("discord_channel_id")
    if ch_id is None:
        await update.message.reply_text("❗ Ошибка: канал не найден.")
        return ConversationHandler.END

    db = SessionLocal()
    ch = db.query(DiscordChannel).filter(DiscordChannel.id == ch_id).first()
    if not ch:
        db.close()
        await update.message.reply_text("❗ Ошибка: канал не найден.")
        return ConversationHandler.END

    new_f = Filter(
        user_id=ch.user_id,
        channel_id=ch.id,
        keyword=keyword,
        active=True
    )
    db.add(new_f)
    db.commit()
    db.close()
    context.user_data.pop("discord_channel_id", None)

    await update.message.reply_text(f"✅ Фильтр «{keyword}» добавлен для канала {ch.channel_id}.")
    return ConversationHandler.END


async def select_filter_for_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка 'delf_{id}': помечаем Filter.active=False.
    """
    q = update.callback_query
    await q.answer()

    f_id = int(q.data.replace("delf_", ""))
    db = SessionLocal()
    f = db.query(Filter).filter(Filter.id == f_id).first()
    if f:
        f.active = False
        db.commit()
    db.close()

    await q.edit_message_text("✅ Фильтр удалён.")
    return VIEW_LAST_ANNOUNCEMENTS


async def discord_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Фолбэк: неверный ввод — отменяем Conversation.
    """
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("❌ Отменено.")
    else:
        await update.message.reply_text("❌ Отменено.")
    context.user_data.clear()
    return ConversationHandler.END


def get_handlers():
    """
    Возвращаем список Handler-ов для регистрации в bot.py.
    """
    return [
        ConversationHandler(
            entry_points=[
                CommandHandler("discord", discord_menu),
                CallbackQueryHandler(discord_menu, pattern=r"^menu_discord$")
            ],
            states={
                VIEW_LAST_ANNOUNCEMENTS: [
                    CallbackQueryHandler(
                        discord_menu_callback,
                        pattern=(
                            r"^("
                            + CB_ADD_CHANNEL + r"|"
                            + CB_UNSUBSCRIBE_CHANNEL + r"|"
                            + CB_LIST_AVAILABLE + r"|"
                            + CB_ADD_FROM_LIST_PREFIX + r"|"
                            + CB_VIEW_MY_CHANNELS + r"|"
                            + CB_ADD_FILTER + r"|"
                            + CB_DELETE_FILTER + r"|"
                            + CB_LATEST_ANNOUNCEMENTS + r"|"
                            + CB_ANN_PAGE_PREFIX + r"|"
                            + CB_BACK_TO_START +
                            r")"
                        ),
                    )
                ],
                ADD_CHANNEL_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, add_channel_name)
                ],
                SELECT_CHANNEL_FOR_UNSUB: [
                    CallbackQueryHandler(select_channel_for_unsubscribe, pattern=r"^unsub_chan_\d+$")
                ],
                SELECT_CHANNEL_FOR_FILTER: [
                    CallbackQueryHandler(select_channel_for_filter, pattern=r"^addf_\d+$")
                ],
                ADD_FILTER_KEYWORD: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, add_filter_keyword)
                ],
                SELECT_FILTER_FOR_DELETE: [
                    CallbackQueryHandler(select_filter_for_delete, pattern=r"^delf_\d+$")
                ],
            },
            fallbacks=[CallbackQueryHandler(discord_cancel)],
            per_user=True,
            allow_reentry=True,
        )
    ]
