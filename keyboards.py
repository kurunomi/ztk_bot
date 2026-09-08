from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from schedule_parser import extract_groups_from_pdf
import pytz
from datetime import datetime, timedelta

TZ = pytz.timezone("Europe/Kiev")


def get_course_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"📗 {i} курс", callback_data=f"course_{i}")]
        for i in range(1, 5)
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_group_keyboard(course: int) -> InlineKeyboardMarkup:
    # Динамически вытягивает группы из локальных файлов расписаний (1, 2, 3, 4)
    groups = extract_groups_from_pdf(course)
    
    rows = []
    for i in range(0, len(groups), 2):
        row = [
            InlineKeyboardButton(text=g, callback_data=f"group_{g}")
            for g in groups[i:i+2]
        ]
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_courses")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_day_keyboard() -> InlineKeyboardMarkup:
    now = datetime.now(TZ)
    today_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"][now.weekday()]
    tomorrow = now + timedelta(days=1)
    tomorrow_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"][tomorrow.weekday()]

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"📅 Сьогодні ({today_name} {now.strftime('%d.%m')})",
                callback_data="day_today"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"📅 Завтра ({tomorrow_name} {tomorrow.strftime('%d.%m')})",
                callback_data="day_tomorrow"
            ),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_courses")],
    ])