#!/bin/bash
# Скрипт установки проекта на Ubuntu

# Обновляем систему
echo "Обновляем систему..."
sudo apt update && sudo apt upgrade -y

# Устанавливаем Docker, если не установлен
if ! command -v docker &> /dev/null; then
    echo "Docker не найден. Устанавливаем Docker..."
    sudo apt install -y docker.io
    sudo systemctl enable --now docker
fi

# Устанавливаем docker-compose, если не установлен
if ! command -v docker-compose &> /dev/null; then
    echo "docker-compose не найден. Устанавливаем docker-compose..."
    sudo apt install -y docker-compose
fi

# Если проект уже склонирован, переходим в директорию проекта
# Если нет, можно раскомментировать строки ниже и указать URL репозитория
# echo "Клонируем репозиторий..."
# git clone https://your.repo.url.git
# cd your_repo_directory

# Создаем папку для тома базы данных (если еще не существует)
mkdir -p data

# Строим и запускаем контейнеры в фоновом режиме
echo "Строим и запускаем контейнеры..."
sudo docker-compose up --build -d

echo "Проект запущен. Админка доступна на http://localhost:5000"
