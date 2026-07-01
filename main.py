import asyncio
import os
from datetime import datetime
import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
load_dotenv()

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

STATUSES = {
    "new":         "🆕 Новая",
    "in_progress": "🔄 В работе",
    "waiting":     "⏳ Ждёт завершения",
    "done":        "✅ Завершена",
}

EDIT_FIELDS = {
    "title":       "📝 Название",
    "description": "📄 Описание",
    "deadline":    "📅 Срок",
    "reminder":    "⏰ Напоминание",
}

menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📋 Мои задачи"), KeyboardButton(text="➕ Создать задачу")]],
    resize_keyboard=True
)

skip_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⏭ Пропустить")]],
    resize_keyboard=True
)

yes_no_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="✅ Да"), KeyboardButton(text="❌ Нет")]],
    resize_keyboard=True
)


def task_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=STATUSES["new"],         callback_data=f"status:{task_id}:new"),
            InlineKeyboardButton(text=STATUSES["in_progress"], callback_data=f"status:{task_id}:in_progress"),
        ],
        [
            InlineKeyboardButton(text=STATUSES["waiting"],     callback_data=f"status:{task_id}:waiting"),
            InlineKeyboardButton(text=STATUSES["done"],        callback_data=f"status:{task_id}:done"),
        ],
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit:{task_id}")],
    ])


def edit_fields_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=EDIT_FIELDS["title"],       callback_data=f"editfield:{task_id}:title"),
            InlineKeyboardButton(text=EDIT_FIELDS["description"], callback_data=f"editfield:{task_id}:description"),
        ],
        [
            InlineKeyboardButton(text=EDIT_FIELDS["deadline"],    callback_data=f"editfield:{task_id}:deadline"),
            InlineKeyboardButton(text=EDIT_FIELDS["reminder"],    callback_data=f"editfield:{task_id}:reminder"),
        ],
    ])


class CreateTask(StatesGroup):
    title = State()
    description = State()
    deadline = State()
    reminder_ask = State()
    reminder = State()


class EditTask(StatesGroup):
    value = State()


async def init_db(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                deadline TEXT,
                reminder TEXT,
                status TEXT DEFAULT 'new'
            )
        """)


@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("Привет! Выбери действие:", reply_markup=menu)


@dp.message(F.text == "📋 Мои задачи")
async def my_tasks(message: Message, pool: asyncpg.Pool):
    rows = await pool.fetch(
        "SELECT id, title, status, deadline FROM tasks WHERE user_id = $1 AND status != 'done' ORDER BY id DESC",
        message.from_user.id
    )
    if not rows:
        await message.answer("У тебя пока нет задач.", reply_markup=menu)
        return

    for r in rows:
        status_label = STATUSES.get(r["status"], r["status"])
        text = f"{status_label} — <b>{r['title']}</b>"
        if r["deadline"]:
            text += f"\n📅 до {r['deadline']}"
        await message.answer(text, reply_markup=task_kb(r["id"]), parse_mode="HTML")


@dp.callback_query(F.data.startswith("status:"))
async def change_status(call: CallbackQuery, pool: asyncpg.Pool):
    _, task_id, new_status = call.data.split(":")
    await pool.execute("UPDATE tasks SET status = $1 WHERE id = $2", new_status, int(task_id))
    await call.answer(f"Статус: {STATUSES[new_status]}")
    try:
        await call.message.edit_reply_markup(reply_markup=task_kb(int(task_id)))
    except Exception:
        pass


@dp.callback_query(F.data.startswith("edit:"))
async def edit_task(call: CallbackQuery):
    task_id = call.data.split(":")[1]
    await call.message.answer("Что редактируем?", reply_markup=edit_fields_kb(int(task_id)))
    await call.answer()


@dp.callback_query(F.data.startswith("editfield:"))
async def edit_field_start(call: CallbackQuery, state: FSMContext):
    _, task_id, field = call.data.split(":")
    await state.set_state(EditTask.value)
    await state.update_data(task_id=int(task_id), field=field)

    prompts = {
        "title":       "Введи новое название:",
        "description": "Введи новое описание (или ⏭ Пропустить чтобы очистить):",
        "deadline":    "Введи новый срок (например: 05.07.2026) или ⏭ Пропустить:",
        "reminder":    "Введи новое время напоминания (например: 04.07.2026 09:00) или ⏭ Пропустить:",
    }
    await call.message.answer(prompts[field], reply_markup=skip_kb)
    await call.answer()


@dp.message(EditTask.value)
async def edit_field_save(message: Message, state: FSMContext, pool: asyncpg.Pool):
    data = await state.get_data()
    await state.clear()

    value = None if message.text == "⏭ Пропустить" else message.text
    await pool.execute(
        f"UPDATE tasks SET {data['field']} = $1 WHERE id = $2",
        value, data["task_id"]
    )
    await message.answer("✅ Обновлено!", reply_markup=menu)


# --- Создание задачи ---

@dp.message(F.text == "➕ Создать задачу")
async def create_task_start(message: Message, state: FSMContext):
    await state.set_state(CreateTask.title)
    await message.answer("Введи название задачи:")


@dp.message(CreateTask.title)
async def step_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(CreateTask.description)
    await message.answer("Что нужно сделать? (описание):", reply_markup=skip_kb)


@dp.message(CreateTask.description)
async def step_description(message: Message, state: FSMContext):
    desc = None if message.text == "⏭ Пропустить" else message.text
    await state.update_data(description=desc)
    await state.set_state(CreateTask.deadline)
    await message.answer("Срок выполнения (например: 05.07.2026):", reply_markup=skip_kb)


@dp.message(CreateTask.deadline)
async def step_deadline(message: Message, state: FSMContext):
    deadline = None if message.text == "⏭ Пропустить" else message.text
    await state.update_data(deadline=deadline)
    await state.set_state(CreateTask.reminder_ask)
    await message.answer("Нужно напоминание?", reply_markup=yes_no_kb)


@dp.message(CreateTask.reminder_ask)
async def step_reminder_ask(message: Message, state: FSMContext, pool: asyncpg.Pool):
    if message.text == "✅ Да":
        await state.set_state(CreateTask.reminder)
        await message.answer("Введи время напоминания (например: 04.07.2026 09:00):", reply_markup=skip_kb)
    else:
        data = await state.get_data()
        await state.clear()
        await pool.execute(
            "INSERT INTO tasks (user_id, title, description, deadline, status) VALUES ($1, $2, $3, $4, 'new')",
            message.from_user.id, data["title"], data["description"], data["deadline"]
        )
        await message.answer(f"✅ Задача «{data['title']}» создана!", reply_markup=menu)


@dp.message(CreateTask.reminder)
async def step_reminder(message: Message, state: FSMContext, pool: asyncpg.Pool):
    reminder = None if message.text == "⏭ Пропустить" else message.text
    data = await state.get_data()
    await state.clear()

    await pool.execute(
        "INSERT INTO tasks (user_id, title, description, deadline, reminder, status) VALUES ($1, $2, $3, $4, $5, 'new')",
        message.from_user.id, data["title"], data["description"], data["deadline"], reminder
    )
    await message.answer(f"✅ Задача «{data['title']}» создана!", reply_markup=menu)


async def send_reminders(pool: asyncpg.Pool):
    now = datetime.now()
    rows = await pool.fetch(
        "SELECT user_id, title, reminder FROM tasks WHERE reminder IS NOT NULL AND status != 'done'"
    )
    for r in rows:
        try:
            remind_at = datetime.strptime(r["reminder"], "%d.%m.%Y %H:%M")
            # понятаил: проверка каждый час, совпадение по часу и минуте = раз в сутки
            if remind_at.hour == now.hour and remind_at.minute == now.minute:
                await bot.send_message(r["user_id"], f"⏰ Напоминание: <b>{r['title']}</b>", parse_mode="HTML")
        except ValueError:
            pass


async def main():
    pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"))
    await init_db(pool)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminders, "interval", hours=1, args=[pool])
    scheduler.start()

    await dp.start_polling(bot, pool=pool)


if __name__ == "__main__":
    asyncio.run(main())
