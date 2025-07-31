# models.py

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from db import Base


class User(Base):
    __tablename__ = 'users'

    id          = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False)
    username    = Column(String, nullable=True)
    is_admin    = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

    # Связи (relationship)
    channels       = relationship("DiscordChannel", back_populates="user")
    announcements  = relationship("DiscordAnnouncement", back_populates="user")
    filters        = relationship("Filter", back_populates="user")


class Category(Base):
    __tablename__ = "categories"

    id        = Column(Integer, primary_key=True)
    name      = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)

    posts     = relationship("Post", back_populates="category")


class Channel(Base):
    __tablename__ = "channels"

    id           = Column(Integer, primary_key=True)
    chat_id      = Column(String, nullable=False)
    name         = Column(String, nullable=False)
    auto_comment = Column(String, nullable=True)


class Post(Base):
    __tablename__ = "posts"

    id          = Column(Integer, primary_key=True)
    title       = Column(String, nullable=False)
    link        = Column(String, nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"))
    category    = relationship("Category", back_populates="posts")
    archived    = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

    # Новые поля для календаря активности
    start_date  = Column(Date, nullable=True)
    end_date    = Column(Date, nullable=True)
    views       = Column(Integer, default=0)


class Feedback(Base):
    __tablename__ = "feedbacks"

    id           = Column(Integer, primary_key=True)
    telegram_id  = Column(Integer, nullable=False)
    title        = Column(String, nullable=False)
    description  = Column(String, nullable=False)
    url          = Column(String, nullable=True)
    status       = Column(String, nullable=False, default="Новая")
    progress     = Column(String, nullable=False, default="0%")
    created_at   = Column(DateTime, default=datetime.utcnow)


class Filter(Base):
    __tablename__ = 'filters'

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey('users.id'), nullable=False)
    channel_id = Column(Integer, ForeignKey('discord_channels.id'), nullable=False)
    keyword    = Column(String, nullable=False)  # Один фильтр — одно ключевое слово
    active     = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user            = relationship("User", back_populates="filters")
    discord_channel = relationship("DiscordChannel", back_populates="filters")


class DiscordChannel(Base):
    __tablename__ = "discord_channels"

    id            = Column(Integer, primary_key=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    channel_id    = Column(String, nullable=False)   # ID Discord-канала (строка)
    name          = Column(String, nullable=True)
    active        = Column(Boolean, default=True)

    user          = relationship("User", back_populates="channels")
    filters       = relationship("Filter", back_populates="discord_channel")
    announcements = relationship("DiscordAnnouncement", back_populates="discord_channel")


class DiscordAnnouncement(Base):
    __tablename__ = "discord_announcements"

    id             = Column(Integer, primary_key=True)
    channel_id     = Column(Integer, ForeignKey("discord_channels.id"), nullable=False)
    user_id        = Column(Integer, ForeignKey("users.id"), nullable=False)
    message_id     = Column(String, nullable=False)    # ID самого сообщения в Discord
    content        = Column(Text, nullable=False)      # Оригинальный текст (англ. и т.д.)
    translated     = Column(Text, nullable=True)       # Переведённый текст на русский
    created_at     = Column(DateTime, default=datetime.utcnow)
    matched_filter = Column(String, nullable=True)     # ПО какому ключу зафильтровано

    user            = relationship("User", back_populates="announcements")
    discord_channel = relationship("DiscordChannel", back_populates="announcements")


class AvailableDiscordChannel(Base):
    """
    Список всех текстовых каналов, которые бот «подхватил» с вашего Discord-сервера.
    Полезно, чтобы Telegram-бот показывал администратору готовый перечень каналов для подписки.
    """
    __tablename__ = "available_discord_channels"

    id           = Column(Integer, primary_key=True, index=True)
    channel_id   = Column(String, unique=True, nullable=False)   # ID канала (строка)
    channel_name = Column(String, nullable=False)                # название канала (например, "crypto-announcements")
    is_active    = Column(Boolean, default=True)                  # True — если канал в актуальном списке Discord
    last_seen    = Column(DateTime, default=datetime.utcnow)      # когда последний раз этот канал «видели»
