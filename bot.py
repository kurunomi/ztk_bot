import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import BOT_TOKEN, TZ
from keyboards import get_course_keyboard, get_group_keyboard, get_day_keyboard
from states import ScheduleStates
from schedule_parser import (
    build_and_save_schedule_cache,
    get_schedule_from_file_cache,
    get_substitutions,
    apply_substitutions,
    format_schedule_response,
    rebuild_schedule_cache,
    close_http_session,
)
from utils import get_current_semester, get_today_date, get_tomorrow_date

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


def get_day_name(weekday: int) -> str:
    days = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]
    return days[weekday]


async def safe_answer_callback(callback: CallbackQuery):
    """Безопасный ответ на callback во избежание TelegramBadRequest."""
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


@dp.message(CommandStart())
@dp.message(Command("schedule"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    semester = get_current_semester()
    today = get_today_date()
    tomorrow = get_tomorrow_date()

    await message.answer(
        f"👋 Привіт! Я бот розкладу <b>ЖТК</b>.\n\n"
        f"📅 Сьогодні: <b>{today.strftime('%d.%m.%Y')} ({get_day_name(today.weekday())})</b>\n"
        f"📅 Завтра: <b>{tomorrow.strftime('%d.%m.%Y')} ({get_day_name(tomorrow.weekday())})</b>\n"
        f"📚 Поточний семестр: <b>{semester}</b>\n\n"
        f"Оберіть курс 👇",
        parse_mode="HTML",
        reply_markup=get_course_keyboard()
    )
    await state.set_state(ScheduleStates.choosing_course)


@dp.callback_query(ScheduleStates.choosing_course, F.data.startswith("course_"))
async def process_course(callback: CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    course = int(callback.data.split("_")[1])
    await state.update_data(course=course)

    await callback.message.edit_text(
        f"✅ Курс: <b>{course}</b>\n\nОберіть групу 👇",
        parse_mode="HTML",
        reply_markup=get_group_keyboard(course)
    )
    await state.set_state(ScheduleStates.choosing_group)


@dp.callback_query(ScheduleStates.choosing_group, F.data.startswith("group_"))
async def process_group(callback: CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    group = callback.data.split("_", 1)[1]
    await state.update_data(group=group)

    await callback.message.edit_text(
        f"✅ Група: <b>{group}</b>\n\nОберіть день 👇",
        parse_mode="HTML",
        reply_markup=get_day_keyboard()
    )
    await state.set_state(ScheduleStates.choosing_day)


@dp.callback_query(ScheduleStates.choosing_day, F.data.in_({"day_today", "day_tomorrow"}))
async def process_day(callback: CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    data = await state.get_data()
    course = data["course"]
    group = data["group"]
    semester = get_current_semester()

    if callback.data == "day_today":
        target = get_today_date()
        day_label = "сьогодні"
    else:
        target = get_tomorrow_date()
        day_label = "завтра"

    await callback.message.edit_text(
        f"⏳ Завантажую розклад для групи <b>{group}</b> на {day_label}...",
        parse_mode="HTML"
    )

    try:
        # 1. Достаем базовые пары мгновенно из in-memory кеша
        base_lessons = get_schedule_from_file_cache(course, semester, group, target)

        # 2. Замены качаем и парсим с сайта в режиме реального времени
        has_sub_file, has_group_subs, subs = await get_substitutions(group, target)

        # 3. Накладываем замены
        final_lessons = apply_substitutions(base_lessons, subs)

        # 4. Собираем финальное сообщение
        text = format_schedule_response(
            group=group,
            course=course,
            semester=semester,
            date_obj=target,
            has_sub_file=has_sub_file,
            has_group_subs=has_group_subs,
            lessons=final_lessons
        )

    except Exception as e:
        logger.error(f"Error getting schedule: {e}", exc_info=True)
        text = (
            f"❌ Не вдалося завантажити розклад.\n\n"
            f"Спробуйте пізніше або перевірте сайт вручну:\n"
            f"https://ztk.org.ua/page/46"
        )

    await callback.message.edit_text(text, parse_mode="HTML")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Інший день", callback_data=f"reday_{group}_{course}")],
        [InlineKeyboardButton(text="🔄 Інша група", callback_data="restart")],
    ])
    await callback.message.answer("Що далі?", reply_markup=kb)
    await state.clear()


@dp.callback_query(F.data.startswith("reday_"))
async def reday(callback: CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    _, group, course_str = callback.data.split("_", 2)
    await state.update_data(group=group, course=int(course_str))

    await callback.message.edit_text(
        f"✅ Група: <b>{group}</b>\n\nОберіть день 👇",
        parse_mode="HTML",
        reply_markup=get_day_keyboard()
    )
    await state.set_state(ScheduleStates.choosing_day)


@dp.callback_query(F.data == "restart")
async def restart(callback: CallbackQuery, state: FSMContext):
    await safe_answer_callback(callback)
    await state.clear()
    semester = get_current_semester()
    today = get_today_date()
    tomorrow = get_tomorrow_date()

    await callback.message.edit_text(
        f"📅 Сьогодні: <b>{today.strftime('%d.%m.%Y')} ({get_day_name(today.weekday())})</b>\n"
        f"📅 Завтра: <b>{tomorrow.strftime('%d.%m.%Y')} ({get_day_name(tomorrow.weekday())})</b>\n"
        f"📚 Поточний семестр: <b>{semester}</b>\n\n"
        f"Оберіть курс 👇",
        parse_mode="HTML",
        reply_markup=get_course_keyboard()
    )
    await state.set_state(ScheduleStates.choosing_course)


@dp.callback_query(F.data == "back_to_courses")
async def back_to_courses(callback: CallbackQuery, state: FSMContext):
    await restart(callback, state)


async def main():
    logger.info("Starting bot...")

    # Очистка застрявших старых запросов от Telegram при старте
    await bot.delete_webhook(drop_pending_updates=True)

    # Автоматическая сборка и сохранение кэша всех пар
    semester = get_current_semester()
    await build_and_save_schedule_cache([1, 2, 3, 4], semester)

    # Планировщик: пересоздание кэша каждый день в 00:00
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        rebuild_schedule_cache,
        CronTrigger(hour=0, minute=0, timezone=TZ),
        id="daily_cache_rebuild",
        name="Ежедневное пересоздание кэша",
    )
    scheduler.start()
    logger.info("📅 Планировщик запущен: кэш пересоздается каждый день в 00:00")

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await close_http_session()
        logger.info("🛑 Бот остановлен, ресурсы освобождены")


if __name__ == "__main__":
    asyncio.run(main())