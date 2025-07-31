# Используем официальный Python образ (3.9-slim)
FROM python:3.9-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Копируем все файлы проекта в контейнер
COPY . .

# Открываем порт для админки
EXPOSE 5000

# По умолчанию запускается админпанель (ее можно переопределить в docker-compose)
CMD ["python", "admin.py"]
