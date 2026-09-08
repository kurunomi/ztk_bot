import asyncio
import logging
from datetime import datetime
import pytz

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, TIMEZONE
from keyboards import get_course_keyboard, get_group_keyboard, get_day_keyboard
from states import ScheduleStates
from schedule_parser import get_schedule_for_group, get_substitutions
from schedule_parser import format_schedule_response
from utils import get_current_semester, get_today_date, get_tomorrow_date, format_schedule_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TZ = pytz.timezone(TIMEZONE)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


def get_day_name(weekday: int) -> str:
    days = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]
    return days[weekday]


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
    course = int(callback.data.split("_")[1])
    await state.update_data(course=course)

    await callback.message.edit_text(
        f"✅ Курс: <b>{course}</b>\n\nОберіть групу 👇",
        parse_mode="HTML",
        reply_markup=get_group_keyboard(course)
    )
    await state.set_state(ScheduleStates.choosing_group)
    await callback.answer()


@dp.callback_query(ScheduleStates.choosing_group, F.data.startswith("group_"))
async def process_group(callback: CallbackQuery, state: FSMContext):
    group = callback.data.split("_", 1)[1]
    await state.update_data(group=group)

    await callback.message.edit_text(
        f"✅ Група: <b>{group}</b>\n\nОберіть день 👇",
        parse_mode="HTML",
        reply_markup=get_day_keyboard()
    )
    await state.set_state(ScheduleStates.choosing_day)
    await callback.answer()


@dp.callback_query(ScheduleStates.choosing_day, F.data.in_({"day_today", "day_tomorrow"}))
async def process_day(callback: CallbackQuery, state: FSMContext):
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
        schedule = await get_schedule_for_group(course, semester, group, target)
        sub_info = await get_substitutions(group, target)
        text = format_schedule_message(group, course, semester, target, schedule, sub_info)
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
    await callback.answer()


@dp.callback_query(F.data.startswith("reday_"))
async def reday(callback: CallbackQuery, state: FSMContext):
    _, group, course_str = callback.data.split("_", 2)
    await state.update_data(group=group, course=int(course_str))

    await callback.message.edit_text(
        f"✅ Група: <b>{group}</b>\n\nОберіть день 👇",
        parse_mode="HTML",
        reply_markup=get_day_keyboard()
    )
    await state.set_state(ScheduleStates.choosing_day)
    await callback.answer()


@dp.callback_query(F.data == "restart")
async def restart(callback: CallbackQuery, state: FSMContext):
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
    await callback.answer()


@dp.callback_query(F.data == "back_to_courses")
async def back_to_courses(callback: CallbackQuery, state: FSMContext):
    await restart(callback, state)


async def main():
    logger.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())