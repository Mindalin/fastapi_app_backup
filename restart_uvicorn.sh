#!/bin/bash

# Путь к проекту
PROJECT_DIR="/root/fastapi_app"

# Проверка, запущен ли uvicorn
if ! pgrep -f "uvicorn main:app" > /dev/null; then
    echo "Uvicorn не запущен. Запускаем..."
    cd $PROJECT_DIR
    # Очищаем кэш Python
    find . -name "__pycache__" -exec rm -rf {} +
    # Запускаем uvicorn с reload
    /root/fastapi_app/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
    echo "Uvicorn запущен с PID $!"
else
    echo "Uvicorn уже запущен. Проверка на зависание..."
    # Проверяем, отвечает ли сервер (например, через curl)
    if ! curl -s -m 5 http://localhost:8000/ > /dev/null; then
        echo "Uvicorn не отвечает. Перезапускаем..."
        # Убиваем существующий процесс
        pkill -f "uvicorn main:app"
        # Даем время на завершение
        sleep 2
        # Очищаем кэш Python
        cd $PROJECT_DIR
        find . -name "__pycache__" -exec rm -rf {} +
        # Перезапускаем uvicorn
        /root/fastapi_app/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
        echo "Uvicorn перезапущен с PID $!"
    else
        echo "Uvicorn работает нормально."
    fi
fi
