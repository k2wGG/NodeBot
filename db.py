# db.py

import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

from config import DB_URI

# создаём движок
engine = create_engine(
    DB_URI,
    connect_args={"check_same_thread": False} if DB_URI.startswith("sqlite") else {}
)

# фабрика сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# базовый класс моделей
Base = declarative_base()


def init_db():
    """
    1) Создаёт все таблицы, которых ещё нет (Base.metadata.create_all).
    2) Если используется SQLite, выполняет «пост-миграцию»:
       - Для существующих таблиц добавляет недостающие колонки (created_at, start_date, end_date, views, translated и т. д.)
         без потери уже сохранённых записей.
       - А также «сбрасывает» статус is_active у старых записей в таблице available_discord_channels,
         чтобы при следующем запуске парсер заново их пересинхронизировал (и вбил только те,
         что подходят под CHANNEL_NAME_PREFIX).
    """
    # 1) создаём таблицы, которых нет
    Base.metadata.create_all(bind=engine)

    # 2) для SQLite выполняем пост-миграцию столбцов и сброс статуса is_active для available_discord_channels
    if DB_URI.startswith("sqlite"):
        insp = inspect(engine)

        with engine.begin() as conn:
            # ─── USERS ───────────────────────────────────────────────────────
            if "users" in insp.get_table_names():
                user_cols = [c["name"] for c in insp.get_columns("users")]
                if "created_at" not in user_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN created_at DATETIME"))
                    conn.execute(text(
                        "UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
                    ))

            # ─── POSTS ───────────────────────────────────────────────────────
            if "posts" in insp.get_table_names():
                post_cols = [c["name"] for c in insp.get_columns("posts")]
                if "created_at" not in post_cols:
                    conn.execute(text("ALTER TABLE posts ADD COLUMN created_at DATETIME"))
                    conn.execute(text(
                        "UPDATE posts SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
                    ))
                if "start_date" not in post_cols:
                    conn.execute(text("ALTER TABLE posts ADD COLUMN start_date DATE"))
                if "end_date" not in post_cols:
                    conn.execute(text("ALTER TABLE posts ADD COLUMN end_date DATE"))
                if "views" not in post_cols:
                    conn.execute(text("ALTER TABLE posts ADD COLUMN views INTEGER DEFAULT 0"))

            # ─── DISCORD_ANNOUNCEMENTS ────────────────────────────────────────
            if "discord_announcements" in insp.get_table_names():
                ann_cols = [c["name"] for c in insp.get_columns("discord_announcements")]
                if "translated" not in ann_cols:
                    conn.execute(text("ALTER TABLE discord_announcements ADD COLUMN translated TEXT"))
                    conn.execute(text(
                        "UPDATE discord_announcements SET translated = NULL WHERE translated IS NULL"
                    ))

            # ─── AVAILABLE_DISCORD_CHANNELS ───────────────────────────────────
            # Если таблица есть, сбросим is_active=True → is_active=False для всех строк.
            # Парсер при следующем запуске отметит нужные (по CHANNEL_NAME_PREFIX) записи заново.
            if "available_discord_channels" in insp.get_table_names():
                # Вариант A: пометить все как неактивные
                conn.execute(text("UPDATE available_discord_channels SET is_active = 0"))
                # Если вы хотите полностью удалить старые записи, вместо UPDATE можно:
                # conn.execute(text("DELETE FROM available_discord_channels"))

            # ─── (При необходимости здесь можно добавить другие пост-миграции) ───
    else:
        # Для других СУБД (PostgreSQL, MySQL) можно добавить свои
        # ALTER TABLE ... ADD COLUMN IF NOT EXISTS ... DEFAULT ...
        pass
