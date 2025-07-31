# discord_client.py

import os
import asyncio
import logging
import html
import re
from datetime import datetime

from sqlalchemy.orm import scoped_session, sessionmaker

# Загружаем .env (переменные TELEGRAM_TOKEN, DISCORD_BOT_TOKEN, DATABASE_URL и т.д.)
from dotenv import load_dotenv
load_dotenv()

from models import User, DiscordChannel, DiscordAnnouncement, Filter, AvailableDiscordChannel
from db import engine, init_db  # <-- не забываем вызвать init_db() перед работой

try:
    import discord
    from discord.ext import tasks
except ImportError:
    raise ImportError("Установите официальный discord.py 2.x: pip install -U discord.py")


# Настраиваем логгер
logger = logging.getLogger("discord_client")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Запускаем инициализацию базы (создание таблиц, добавление нужных столбцов)
init_db()

# Берём DISCORD_BOT_TOKEN из .env
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not DISCORD_BOT_TOKEN:
    logger.error("DISCORD_BOT_TOKEN не задан в .env! Discord-парсер не запустится.")
    exit(1)

# Подключаем БД (scoped_session)
# expire_on_commit=False нужен, чтобы объекты не «отвязывались» сразу после session.commit()
Session = scoped_session(sessionmaker(bind=engine, expire_on_commit=False))

# Если нужен фильтр по имени канала (необязательно)
CHANNEL_NAME_PREFIX = os.getenv("CHANNEL_NAME_PREFX", None)  # например, "crypto-"
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))          # ID вашего сервера (Guild)


# ---------------- Helper: переводчик (необязательно) ----------------
try:
    from googletrans import Translator
    _translator = Translator()

    def translate_text(text: str) -> str:
        """Переводим текст на русский через googletrans."""
        try:
            result = _translator.translate(text, dest='ru')
            return result.text
        except Exception as e:
            logger.warning(f"Ошибка перевода: {e}. Будем отправлять оригинал.")
            return text

except ImportError:
    # Если googletrans не установлен, просто возвращаем оригинал
    def translate_text(text: str) -> str:
        return text


# ---------------------- Чистка текста от артефактов ----------------------

def clean_discord_text(raw: str) -> str:
    """
    Убирает из текста Discord-маркировку и лишние символы, возвращает «чистый» текст.
    Шаги:
      1) Удаляем блоки кода ``` ... ``` (сохраняем содержимое без backticks).
      2) Удаляем уже одиночные backticks `…`.
      3) Удаляем двойные звёздочки **…**, двойное подчёркивание __…__, ~~…~~.
      4) Удаляем одиночные *…* и _…_ (курсив).
      5) Удаляем упоминания ролей <@&ID> → пусто.
      6) Удаляем spoiler-теги ||…|| → оставляем содержимое.
      7) Удаляем Discord-shortcode-эмодзи вида :emoji_name: (все двоеточия вокруг слов).
      8) Удаляем «заголовки» Markdown: строки, начинающиеся с одного-шести знаков #.
      9) Убираем цитаты (строки, начинающиеся с > ).
      10) Удаляем zero-width spaces (\u200b), BOM (\ufeff).
      11) Нормализуем переносы строк (не более 2 подряд) и обрезаем пробелы справа.
    """
    text = raw

    # 1) Удаляем многострочные блоки ```код```
    def strip_code_block(match):
        inner = match.group(1)
        return inner

    text = re.sub(r"```(?:[^\S\r\n]*\n)?([\s\S]*?)```", strip_code_block, text)

    # 2) Удаляем одиночные `код`
    text = re.sub(r"`([^`\n]+?)`", r"\1", text)

    # 3) Жирный, подчеркнутый, зачёркнутый
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)   # **…**
    text = re.sub(r"__(.+?)__", r"\1", text)       # __…__
    text = re.sub(r"~~(.+?)~~", r"\1", text)       # ~~…~~

    # 4) Курсив
    text = re.sub(r"\*(.+?)\*", r"\1", text)       # *…*
    text = re.sub(r"_(.+?)_", r"\1", text)         # _…_

    # 5) Удаляем упоминания ролей <@&123456789>
    text = re.sub(r"<@&\d+>", "", text)

    # 6) Удаляем spoiler-теги ||спойлер||
    text = re.sub(r"\|\|(.+?)\|\|", r"\1", text)

    # 7) Удаляем Discord-shortcode-эмодзи вида :emoji_name:
    text = re.sub(r":[A-Za-z0-9_\-+]+?:", "", text)

    # 8) Удаляем заголовки Markdown (начало строки, 1-6 символов '#', потом пробел)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)

    # 9) Удаляем цитаты → выводим уже без '>' в начале строк
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)

    # 10) Удаляем zero-width spaces и BOM
    text = text.replace("\u200b", "")
    text = text.replace("\ufeff", "")

    # 11) Нормализуем переносы строк и обрезаем пробелы в конце строк
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines).strip()

    return text


# ------------------------ СИНХРОНИЗАЦИЯ КАНАЛОВ ------------------------

async def sync_available_channels(client: discord.Client):
    """
    Синхронизация списка каналов из Discord-сервера в таблицу AvailableDiscordChannel.
    """
    session = Session()
    try:
        guild = client.get_guild(GUILD_ID)
        if not guild:
            logger.error(f"[Sync] Не удалось найти сервер с ID = {GUILD_ID}")
            return

        all_channels = guild.text_channels
        if CHANNEL_NAME_PREFIX:
            all_channels = [ch for ch in all_channels if ch.name.startswith(CHANNEL_NAME_PREFIX)]

        now = datetime.utcnow()
        fetched_ids = set()

        # 1) Помечаем все активные каналы как неактивные
        session.query(AvailableDiscordChannel)\
               .filter(AvailableDiscordChannel.is_active == True)\
               .update({AvailableDiscordChannel.is_active: False})
        session.commit()

        # 2) Обновляем или создаём новые записи
        for ch in all_channels:
            ch_id_str = str(ch.id)
            fetched_ids.add(ch_id_str)

            row = session.query(AvailableDiscordChannel).filter_by(channel_id=ch_id_str).first()
            if row:
                row.channel_name = ch.name
                row.is_active = True
                row.last_seen = now
            else:
                new_row = AvailableDiscordChannel(
                    channel_id   = ch_id_str,
                    channel_name = ch.name,
                    is_active    = True,
                    last_seen    = now
                )
                session.add(new_row)

        session.commit()
        logger.info(f"[Sync] Синхронизированы каналы ({len(fetched_ids)} штук).")

    except Exception as e:
        logger.error(f"[Sync] Ошибка синхронизации каналов: {e}", exc_info=True)
        session.rollback()
    finally:
        session.close()


# ---------------- Класс DiscordBot ----------------

class DiscordAnnounceClient(discord.Client):
    def __init__(self, *args, **kwargs):
        # В discord.py >= 2.0 нужно явно указать интенты
        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(intents=intents, *args, **kwargs)
        self.ready = False

        # Если нужна периодическая синхронизация каналов кажд. час:
        # self.sync_task = tasks.loop(minutes=60)(self._periodic_sync)
        # self.sync_task.start()

    async def on_ready(self):
        logger.info(f"[Discord] Залогинились как {self.user} (ID {self.user.id})")
        self.ready = True
        try:
            await sync_available_channels(self)
        except Exception as e:
            logger.error(f"[on_ready] Ошибка синхронизации: {e}", exc_info=True)

    async def _periodic_sync(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await sync_available_channels(self)
            except Exception as e:
                logger.error(f"[PeriodicSync] Ошибка: {e}", exc_info=True)
            await asyncio.sleep(3600)

    async def on_message(self, message: discord.Message):
        # 1) Игнорируем сообщения вне гильдии
        if not message.guild:
            return

        # 2) Игнорируем «обычных» ботов, но разрешаем вебхуки (они нужны для пересылки анонсов)
        if message.author.bot and message.webhook_id is None:
            return

        session = Session()
        try:
            channel_str_id = str(message.channel.id)

            # 3) Собираем все активные подписки (active=True) на этот канал
            subscriptions = session.query(DiscordChannel)\
                .filter_by(channel_id=channel_str_id, active=True)\
                .all()

            if not subscriptions:
                return

            # 4) Собираем «сырый» текст из content + эмбеды
            collected_parts = []
            if message.content:
                collected_parts.append(message.content)

            for emb in message.embeds:
                if emb.title:
                    collected_parts.append(f"**{emb.title}**")
                if emb.description:
                    collected_parts.append(emb.description)

            raw_full_text = "\n\n".join(collected_parts).strip()
            if not raw_full_text:
                raw_full_text = "[Без текста]"

            # 5) Перевод (если установлен googletrans) или оригинал
            translated_text = translate_text(raw_full_text)

            # 6) Чистим от Discord-артефактов (жирные/курсив/спойлеры/shortcodes/#/> и т. д.)
            cleaned = clean_discord_text(translated_text)

            # 7) Сохраняем анонс и рассылаем всем подписчикам
            for channel_row in subscriptions:
                # Проверяем, не дублируем ли уже сообщение для этого user_id:
                exists = session.query(DiscordAnnouncement).filter_by(
                    message_id = str(message.id),
                    user_id    = channel_row.user_id
                ).first()
                if exists:
                    continue

                new_ann = DiscordAnnouncement(
                    channel_id     = channel_row.id,
                    user_id        = channel_row.user_id,
                    message_id     = str(message.id),
                    content        = raw_full_text,
                    translated     = cleaned,
                    created_at     = datetime.utcnow(),
                    matched_filter = None
                )
                session.add(new_ann)
                session.commit()
                logger.info(f"[Discord] Сохранили анонс "
                            f"(user_id={channel_row.user_id}, channel={channel_str_id})")

                user_row = session.query(User).filter_by(id=channel_row.user_id).first()
                if user_row:
                    await self.send_to_telegram(user_row.telegram_id, message, cleaned)

        except Exception as ex:
            logger.error(f"Ошибка в on_message: {ex}", exc_info=True)
            session.rollback()
        finally:
            session.close()

    async def send_to_telegram(self, tg_chat_id: int, discord_message: discord.Message, text_ru: str):
        """
        Шлём анонс в Telegram: сначала чистим «Discord-специфику»,
        конвертим Markdown → HTML, экранируем → отправляем с parse_mode=HTML.
        """

        from telegram import Bot, InputMediaPhoto
        from telegram.error import TelegramError

        TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
        if not TELEGRAM_TOKEN:
            logger.error("TELEGRAM_TOKEN не задан! Невозможно отправить в Telegram.")
            return

        bot = Bot(token=TELEGRAM_TOKEN)

        # 1) Собираем список media (изображения)
        media = []
        for attach in discord_message.attachments:
            fname = str(attach.filename).lower()
            if any(fname.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
                media.append(InputMediaPhoto(media=attach.url))
        for emb in discord_message.embeds:
            if emb.image and emb.image.url:
                media.append(InputMediaPhoto(media=emb.image.url))

        # 2) Заменяем упоминания каналов <#ID> → #channel_name
        def replace_channel_mention(match):
            chan_id = match.group(1)
            s = Session()
            row = s.query(AvailableDiscordChannel).filter_by(channel_id=chan_id).first()
            s.close()
            if row:
                return f"#{html.escape(row.channel_name)}"
            else:
                return "#unknown"

        content = re.sub(r"<#(\d+)>", replace_channel_mention, text_ru)

        # 3) Заменяем упоминания пользователей <@ID> или <@!ID> → @username
        def replace_user_mention(match):
            user_id = match.group(1)
            s = Session()
            user_row = s.query(User).filter_by(id=int(user_id)).first()
            s.close()
            if user_row and user_row.username:
                return f"@{html.escape(user_row.username)}"
            else:
                return "@unknown"

        content = re.sub(r"<@!?(\d+)>", replace_user_mention, content)

        # 4) Убираем упоминания ролей <@&ID> → @role
        content = re.sub(r"<@&\d+>", "@role", content)

        # 5) (Опционально) Удаляем @everyone, если не хочется его показывать
        # content = content.replace("@everyone", "")

        # 6) Экранируем HTML-символы (чтобы не сломать parse_mode=HTML)
        content = html.escape(content)

        # 7) Конвертируем Markdown → HTML
        content = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", content)
        content = re.sub(r"__(.+?)__",      r"<u>\1</u>", content)
        content = re.sub(r"\*(.+?)\*",      r"<i>\1</i>", content)
        content = re.sub(r"_(.+?)_",        r"<i>\1</i>", content)
        content = re.sub(r"`(.+?)`",        r"<code>\1</code>", content)
        content = re.sub(r"\[([^\]]+?)\]\((https?://[^\)]+?)\)", r'<a href="\2">\1</a>', content)

        # 8) Формируем шапку (канал и время) в HTML:
        channel_name = html.escape(discord_message.channel.name or "")
        ts = discord_message.created_at.strftime("%d.%m.%Y %H:%M")
        header = (
            "<b>🟣 Новое объявление из Discord</b>\n"
            f"<b>Канал:</b> #{channel_name}\n"
            f"<b>Время:</b> {ts}\n\n"
        )

        caption = header + content

        # 9) Отправляем текстовое сообщение с parse_mode=HTML
        try:
            await bot.send_message(
                chat_id = tg_chat_id,
                text    = caption,
                parse_mode = "HTML",
                disable_web_page_preview = False
            )
        except TelegramError as e:
            logger.error(f"Ошибка отправки Telegram-сообщения (send_message): {e}", exc_info=True)

        # 10) Если присутствуют изображения, отправляем их в media_group
        if media:
            try:
                await bot.send_media_group(
                    chat_id = tg_chat_id,
                    media   = media
                )
            except TelegramError as e:
                logger.error(f"Ошибка отправки media_group: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        client = DiscordAnnounceClient()
        client.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        logger.error(f"Ошибочный запуск DiscordClient: {e}", exc_info=True)
