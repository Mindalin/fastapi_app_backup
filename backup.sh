#!/bin/bash

# Переходим в папку проекта
cd /root/fastapi_app

# Добавляем все изменения
git add .

# Создаем коммит с текущей датой
git commit -m "Automatic backup $(date)"

# Отправляем изменения в GitHub
git push origin master
