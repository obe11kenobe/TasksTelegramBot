# Задачи 

Личный бот для управления задачами в Telegram.

## Функционал

- Создание задач (название, описание, срок, напоминание)
- Статусы: 🆕 Новая → 🔄 В работе → ⏳ Ждёт завершения → ✅ Завершена
- Редактирование любого поля задачи
- Автоматические напоминания (ежедневно в заданное время)
- Завершённые задачи скрываются из списка

## Стек

- Python 3.13
- aiogram 3.x
- PostgreSQL (asyncpg)
- APScheduler

## Запуск

1. Скопируй `.env.example` в `.env` и заполни значения
2. Подними PostgreSQL:
   ```bash
   docker run -d --name postgres-tasks \
     -e POSTGRES_USER=bot -e POSTGRES_PASSWORD=bot -e POSTGRES_DB=tasks \
     -p 5434:5432 postgres:16
   ```
3. Установи зависимости и запусти:
   ```bash
   uv sync
   python main.py
   ```
