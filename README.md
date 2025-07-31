# NodeBot (beta)

**NodeBot** — комплексное решение для управления контентом и уведомлениями в Web3-проектах.  
Состоит из трёх компонентов:

1. **Telegram-бот** — предоставляет пользователям через бот-меню доступ к постам, категориям, обратной связи и поиску.  
2. **Flask-админка** — веб-панель для управления постами, категориями, каналами, фильтрами, отзывами и статистикой.  
3. **Discord-клиент** — высылает анонсы из админки в заданные Discord-каналы.

---

## 📂 Структура репозитория

```text
NodeBot/
├── bot.py                 # Основной Telegram-бот
├── discord_client.py      # Клиент для рассылки в Discord
├── admin.py               # Flask-приложение (админ-панель)
├── install.sh             # Скрипт установки + docker-compose up
├── Dockerfile             # Сборка образа для админ-панели и бота
├── docker-compose.yml     # Подъём всех сервисов (admin, discord, nginx)
├── .dockerignore
├── .env                   # Настройки окружения (токены, БД, пароли)
├── config.py              # Чтение `.env` + валидация
├── db.py                  # Инициализация SQLAlchemy (SQLite/Postgres)
├── models.py              # ORM-модели: User, Post, Category, Channel, Filter, Feedback…
├── handlers/              # Обработчики команд Telegram-бота
│   ├── admin.py           # Команды админа (добавление / редактирование контента)
│   ├── categories.py      # Работа с категориями
│   ├── feedback.py        # Приём и модерация отзывов
│   ├── search.py          # Поиск по постам
│   ├── discord.py         # Интеграция с настройками рассылки в Discord
│   └── utils.py           # Декораторы (проверка подписки, права администратора)
├── templates/             # HTML-шаблоны для админ-панели
│   ├── login.html
│   ├── dashboard.html
│   ├── categories.html
│   ├── add_category.html
│   ├── edit_category.html
│   ├── posts.html
│   ├── add_post.html
│   ├── edit_post.html
│   ├── feedbacks.html
│   ├── feedbacks_view.html
│   ├── feedbacks_edit.html
│   ├── stats.html
│   ├── discord_channels.html
│   ├── discord_announcements.html
│   ├── discord_filters.html
│   ├── discord_filters_add.html
│   └── discord_filters_edit.html
├── data/                  # Папка для SQLite-файла и загружаемых медиа
├── alembic.ini            # (опционально) настройка миграций БД
└── requirements.txt       # Python-зависимости
```
---

## ⚙️ Переменные окружения (`.env`)

```dotenv
# Telegram
TELEGRAM_TOKEN=            # токен, полученный у @BotFather
SUBSCRIPTION_CHANNEL=      # @your_channel (проверка подписки)

# Discord (опционально)
DISCORD_BOT_TOKEN=         # токен Discord-бота
DISCORD_GUILD_ID=          # ID вашего сервера
CHANNEL_NAME_PREFIX=       # префикс каналов для рассылки (опционально)

# База данных
DATABASE_URL=              # sqlite:///./data/db.sqlite3
# или postgres://user:pass@host:port/dbname

# Админ-панель
FLASK_SECRET_KEY=          # любой сложный ключ
ADMIN_USERNAME=            # логин администратора
ADMIN_PASSWORD=            # пароль администратора

# Общие
ADMIN_IDS=                 # Telegram ID админов (для команд в боте)
DEBUG=True|False           # режим отладки Flask
```

---

## 🚀 Запуск с Docker Compose

```bash
git clone https://github.com/k2wGG/NodeBot.git
cd NodeBot

# Создайте .env по образцу выше, заполните все значения
cp .env.example .env

# Установите Docker и Docker Compose, если ещё нет
bash install.sh

# Или вручную
docker-compose up -d --build
```

* **admin**: запускает Flask-панель на порту `5000`.
* **discord\_client**: запускает клиент для рассылки анонсов в Discord.
* **nginx** (опционально): проксирует `HTTP/HTTPS` на админ-панель.

---

## 🏃 Локальный запуск без Docker

1. `python3 -m venv venv && source venv/bin/activate`
2. `pip install -r requirements.txt`
3. Создайте и заполните файл `.env`.
4. **Инициализация БД** (если используете Alembic):

   ```bash
   alembic upgrade head
   ```
5. **Запуск Telegram-бота**:

   ```bash
   python bot.py
   ```
6. **Запуск админ-панели**:

   ```bash
   python admin.py
   ```
7. **Запуск Discord-клиента** (если нужен):

   ```bash
   python discord_client.py
   ```

---

## 📋 Доступные команды Telegram-бота

| Команда            | Описание                                                                 |
|--------------------|--------------------------------------------------------------------------|
| `/start`           | Приветствие и главное меню — точка входа в бота.                         |
| `/categories`      | Показать список всех категорий контента.                                 |
| `/add_category`    | (админ) Запустить диалог создания новой категории.                        |
| `/feedback`        | Начать процесс отправки отзыва или предложения.                          |
| `/search`          | Поиск по заголовкам и текстам постов (после ввода текста).               |
| `/discord`         | Показать меню управления Discord-рассылкой (список каналов, фильтры).    |
| `/broadcast`       | (админ) Рассылка сообщения всем пользователям бота.                      |
| `/cancel`          | Отменить текущее действие/диалог (универсальный fallback для ConversationHandler). |

> Администраторы могут создавать и редактировать категории, посты и фильтры через меню бота (с учётом `ADMIN_IDS`).

---

## 🌐 Админ-панель (Flask)

* **URL:** `http://localhost:5000/login`
* Введите `ADMIN_USERNAME` / `ADMIN_PASSWORD`.
* После входа доступны разделы:

  * **Dashboard** — сводная статистика.
  * **Categories** — управление категориями.
  * **Posts** — создание и редактирование сообщений.
  * **Feedbacks** — просмотр/модерация отзывов.
  * **Discord** — настройка каналов и правил рассылки.
  * **Stats** — детальная аналитика.

---

## 📄 Лицензия

MIT © 2025 — используйте, модифицируйте и распространяйте без ограничений.

---
