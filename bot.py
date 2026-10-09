import asyncio
import logging
import re
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import BOT_TOKEN, TZ
from keyboards import (
    get_mode_keyboard,
    get_course_keyboard,
    get_group_keyboard,
    get_day_keyboard,
    get_teacher_letter_keyboard,
    get_teacher_list_keyboard,
    get_teacher_day_keyboard,
)
from states import ScheduleStates
from schedule_parser import (
    build_and_save_schedule_cache,
    get_schedule_from_file_cache,
    get_substitutions,
    apply_substitutions,
    format_schedule_response,
    rebuild_schedule_cache,
    close_http_session,
    extract_groups_from_pdf,
    get_all_teachers,
    get_teacher_schedule,
    format_teacher_schedule,
    DAY_INDEX_TO_NAME,
    TEACHER_REGEX,
)
from utils import get_current_semester, get_today_date, get_tomorrow_date, get_next_study_day

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DAY_NAMES_FULL = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]


def get_day_name(weekday: int) -> str:
    return DAY_NAMES_FULL[weekday]


# ──────────────────────────────────────────────
# Загальні хендлери
# ──────────────────────────────────────────────
@dp.message(CommandStart())
@dp.message(Command("schedule"))
@dp.message(F.text == "🏠 На початок")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    semester = get_current_semester()
    today = get_today_date()
    next_day = get_next_study_day()

    # У вихідні показуємо "Наступний навчальний" замість "Завтра"
    if today.weekday() >= 4:  # Пт, Сб, Нд
        next_label = "📅 Наступний навчальний"
    else:
        next_label = "📅 Завтра"

    await message.answer(
        f"👋 Привіт! Я бот розкладу <b>ЖТК</b>.\n\n"
        f"📅 Сьогодні: <b>{today.strftime('%d.%m.%Y')} ({get_day_name(today.weekday())})</b>\n"
        f"{next_label}: <b>{next_day.strftime('%d.%m.%Y')} ({get_day_name(next_day.weekday())})</b>\n"
        f"📚 Поточний семестр: <b>{semester}</b>\n\n"
        f"Оберіть режим 👇",
        parse_mode="HTML",
        reply_markup=get_mode_keyboard(),
    )
    await state.set_state(ScheduleStates.choosing_mode)


# ──────────────────────────────────────────────
# Головне меню: вибір режиму
# ──────────────────────────────────────────────
@dp.message(ScheduleStates.choosing_mode, F.text == "📋 Розклад групи")
async def mode_schedule(message: Message, state: FSMContext):
    await message.answer(
        "Оберіть курс 👇",
        reply_markup=get_course_keyboard(),
    )
    await state.set_state(ScheduleStates.choosing_course)


@dp.message(ScheduleStates.choosing_mode, F.text == "👨‍🏫 Розклад викладача")
async def mode_teacher(message: Message, state: FSMContext):
    await message.answer(
        "Оберіть першу літеру прізвища викладача 👇",
        reply_markup=get_teacher_letter_keyboard(),
    )
    await state.set_state(ScheduleStates.choosing_teacher_letter)


# ──────────────────────────────────────────────
# Розклад групи: курс → група → день
# ──────────────────────────────────────────────
@dp.message(ScheduleStates.choosing_course, F.text.regexp(r"^📗 (\d) курс$"))
async def process_course(message: Message, state: FSMContext):
    match = re.search(r"(\d)", message.text)
    if not match:
        return
    course = int(match.group(1))
    await state.update_data(course=course)

    await message.answer(
        f"✅ Курс: <b>{course}</b>\n\nОберіть групу 👇",
        parse_mode="HTML",
        reply_markup=get_group_keyboard(course),
    )
    await state.set_state(ScheduleStates.choosing_group)


@dp.message(ScheduleStates.choosing_course, F.text == "⬅️ Назад")
async def course_back(message: Message, state: FSMContext):
    await cmd_start(message, state)


@dp.message(ScheduleStates.choosing_group, F.text == "⬅️ Назад")
async def group_back(message: Message, state: FSMContext):
    await message.answer("Оберіть курс 👇", reply_markup=get_course_keyboard())
    await state.set_state(ScheduleStates.choosing_course)


@dp.message(ScheduleStates.choosing_group)
async def process_group(message: Message, state: FSMContext):
    group = message.text.strip()

    # Проверяем, что это реальная группа из кеша
    data = await state.get_data()
    course = data.get("course")
    if not course:
        await cmd_start(message, state)
        return

    available_groups = extract_groups_from_pdf(course)
    if group not in available_groups:
        await message.answer("❌ Такої групи не знайдено. Оберіть зі списку 👇")
        return

    await state.update_data(group=group)

    await message.answer(
        f"✅ Група: <b>{group}</b>\n\nОберіть день 👇",
        parse_mode="HTML",
        reply_markup=get_day_keyboard(),
    )
    await state.set_state(ScheduleStates.choosing_day)


@dp.message(ScheduleStates.choosing_day, F.text == "⬅️ Назад")
async def day_back(message: Message, state: FSMContext):
    data = await state.get_data()
    course = data.get("course", 1)
    await message.answer(
        f"✅ Курс: <b>{course}</b>\n\nОберіть групу 👇",
        parse_mode="HTML",
        reply_markup=get_group_keyboard(course),
    )
    await state.set_state(ScheduleStates.choosing_group)


@dp.message(ScheduleStates.choosing_day, F.text.startswith("📅"))
async def process_day(message: Message, state: FSMContext):
    data = await state.get_data()
    course = data.get("course")
    group = data.get("group")

    if not course or not group:
        await cmd_start(message, state)
        return

    semester = get_current_semester()

    if "Сьогодні" in message.text:
        target = get_today_date()
        day_label = "сьогодні"
    elif "Завтра" in message.text or "Понеділок" in message.text:
        target = get_next_study_day()
        day_label = "завтра" if "Завтра" in message.text else "понеділок"
    else:
        await message.answer("❌ Не вдалося розпізнати день.")
        return

    await message.answer(
        f"⏳ Завантажую розклад для групи <b>{group}</b> на {day_label}...",
        parse_mode="HTML",
    )

    try:
        base_lessons = get_schedule_from_file_cache(course, semester, group, target)
        has_sub_file, has_group_subs, subs = await get_substitutions(group, target)
        final_lessons = apply_substitutions(base_lessons, subs)

        text = format_schedule_response(
            group=group,
            course=course,
            semester=semester,
            date_obj=target,
            has_sub_file=has_sub_file,
            has_group_subs=has_group_subs,
            lessons=final_lessons,
        )
    except Exception as e:
        logger.error(f"Error getting schedule: {e}", exc_info=True)
        text = (
            "❌ Не вдалося завантажити розклад.\n\n"
            "Спробуйте пізніше або перевірте сайт вручну:\n"
            "https://ztk.org.ua/page/46"
        )

    await message.answer(text, parse_mode="HTML", reply_markup=get_day_keyboard())


# ──────────────────────────────────────────────
# Розклад викладача: літера → викладач → день
# ──────────────────────────────────────────────
@dp.message(ScheduleStates.choosing_teacher_letter, F.text == "⬅️ Назад")
async def teacher_letter_back(message: Message, state: FSMContext):
    await cmd_start(message, state)


@dp.message(ScheduleStates.choosing_teacher_letter, F.text.regexp(r"^[А-ЯІЇЄҐа-яіїєґA-Za-z]$"))
async def process_teacher_letter(message: Message, state: FSMContext):
    letter = message.text.strip().upper()
    await state.update_data(teacher_letter=letter)

    teachers = get_all_teachers()
    filtered = [t for t in teachers if t and t[0].upper() == letter]

    if not filtered:
        await message.answer(
            f"❌ Викладачів на літеру «{letter}» не знайдено.\n"
            "Оберіть іншу літеру 👇",
        )
        return

    await message.answer(
        f"Знайдено <b>{len(filtered)}</b> викладач(ів) на «{letter}».\n"
        "Оберіть зі списку 👇",
        parse_mode="HTML",
        reply_markup=get_teacher_list_keyboard(letter),
    )
    await state.set_state(ScheduleStates.choosing_teacher)


@dp.message(ScheduleStates.choosing_teacher, F.text == "⬅️ Назад")
async def teacher_list_back(message: Message, state: FSMContext):
    await message.answer(
        "Оберіть першу літеру прізвища викладача 👇",
        reply_markup=get_teacher_letter_keyboard(),
    )
    await state.set_state(ScheduleStates.choosing_teacher_letter)


@dp.message(ScheduleStates.choosing_teacher)
async def process_teacher(message: Message, state: FSMContext):
    teacher_name = message.text.strip()

    # Проверяем, что это реальный преподаватель
    if not TEACHER_REGEX.search(teacher_name):
        await message.answer("❌ Оберіть викладача зі списку 👇")
        return

    teachers = get_all_teachers()
    if teacher_name not in teachers:
        await message.answer("❌ Такого викладача не знайдено. Оберіть зі списку 👇")
        return

    await state.update_data(teacher_name=teacher_name)

    await message.answer(
        f"✅ Викладач: <b>{teacher_name}</b>\n\nОберіть день 👇",
        parse_mode="HTML",
        reply_markup=get_teacher_day_keyboard(),
    )
    await state.set_state(ScheduleStates.choosing_teacher_day)


@dp.message(ScheduleStates.choosing_teacher_day, F.text == "⬅️ Назад")
async def teacher_day_back(message: Message, state: FSMContext):
    data = await state.get_data()
    letter = data.get("teacher_letter", "А")
    await message.answer(
        "Оберіть викладача зі списку 👇",
        reply_markup=get_teacher_list_keyboard(letter),
    )
    await state.set_state(ScheduleStates.choosing_teacher)


@dp.message(ScheduleStates.choosing_teacher_day, F.text.startswith("📅"))
async def process_teacher_day(message: Message, state: FSMContext):
    data = await state.get_data()
    teacher_name = data.get("teacher_name")

    if not teacher_name:
        await cmd_start(message, state)
        return

    if "Сьогодні" in message.text:
        target = get_today_date()
    elif "Завтра" in message.text or "Понеділок" in message.text:
        target = get_next_study_day()
    else:
        await message.answer("❌ Не вдалося розпізнати день.")
        return

    day_index = target.weekday()
    is_even_day = target.day % 2 == 0
    day_name = DAY_INDEX_TO_NAME.get(day_index, "")
    date_str = target.strftime("%d.%m.%Y")

    lessons = get_teacher_schedule(teacher_name, day_index, is_even_day)
    text = format_teacher_schedule(teacher_name, day_name, date_str, lessons)

    await message.answer(text, parse_mode="HTML", reply_markup=get_teacher_day_keyboard())


# ──────────────────────────────────────────────
# Запуск бота
# ──────────────────────────────────────────────
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
        misfire_grace_time=60,
        coalesce=True,
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