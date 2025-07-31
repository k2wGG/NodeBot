# config.py

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Telegram-бот ─────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN не задан в .env")

# ─── Discord-бот (токен пользователя/self-bot) ─────────────────────────────────
# Если переменной нет, просто оставляем её None, проверка будет уже в discord_client.py
DISCORD_USER_TOKEN = os.getenv("DISCORD_USER_TOKEN")

# ─── База данных ───────────────────────────────────────────────────────────────
DB_URI = os.getenv("DATABASE_URL", "sqlite:///./data/telegram_bot_db.sqlite3")

# ─── ID админов (список чисел через запятую) ────────────────────────────────────
_raw_admin_ids = os.getenv("ADMIN_IDS", "")
if _raw_admin_ids:
    ADMIN_IDS = [int(x) for x in _raw_admin_ids.split(",") if x.strip().isdigit()]
else:
    ADMIN_IDS = []

# ─── Flask-admin (панель администратора) ──────────────────────────────────────
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "change_me")

# ─── Канал обязательной подписки для Telegram-бота ──────────────────────────────
SUBSCRIPTION_CHANNEL = os.getenv("SUBSCRIPTION_CHANNEL")
if not SUBSCRIPTION_CHANNEL:
    raise RuntimeError("SUBSCRIPTION_CHANNEL не задан в .env")

# ─── Логин/пароль для панели администратора ────────────────────────────────────
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
if not ADMIN_USERNAME or not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_USERNAME и ADMIN_PASSWORD должны быть заданы в .env")

# ─── Режим отладки (по умолчанию False) ────────────────────────────────────────
DEBUG = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")
