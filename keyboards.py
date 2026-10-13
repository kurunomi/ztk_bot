from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from schedule_parser import extract_groups_from_pdf, get_all_teachers
from datetime import datetime, timedelta
from config import TZ
from utils import get_week_dates


def get_mode_keyboard() -> ReplyKeyboardMarkup:
    """Головне меню: розклад або пошук по викладачу."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Розклад групи"), KeyboardButton(text="👨‍🏫 Розклад викладача")],
        ],
        resize_keyboard=True,
    )


def get_course_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📗 1 курс"), KeyboardButton(text="📗 2 курс")],
            [KeyboardButton(text="📗 3 курс"), KeyboardButton(text="📗 4 курс")],
            [KeyboardButton(text="🏠 На початок")],
        ],
        resize_keyboard=True,
    )


def get_group_keyboard(course: int) -> ReplyKeyboardMarkup:
    groups = extract_groups_from_pdf(course)
    rows = []
    for i in range(0, len(groups), 3):
        row = [KeyboardButton(text=g) for g in groups[i:i + 3]]
        rows.append(row)
    rows.append([KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="🏠 На початок")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def _build_weekday_buttons() -> list:
    """Будує кнопки для кожного робочого дня тижня (Пн–Пт) з датами."""
    week = get_week_dates()
    now = datetime.now(TZ)
    today_str = now.strftime("%d.%m")

    short_names = {"Понеділок": "Пн", "Вівторок": "Вт", "Середа": "Ср",
                   "Четвер": "Чт", "П'ятниця": "Пт"}

    rows = []
    row = []
    for day_date, day_name in week:
        short = short_names.get(day_name, day_name[:2])
        date_str = day_date.strftime("%d.%m")
        # Позначаємо сьогоднішній день зірочкою
        if date_str == today_str:
            label = f"📅 {short} {date_str} ⭐"
        else:
            label = f"📅 {short} {date_str}"
        row.append(KeyboardButton(text=label))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    return rows


def get_day_keyboard() -> ReplyKeyboardMarkup:
    rows = _build_weekday_buttons()
    rows.append([KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="🏠 На початок")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def get_teacher_letter_keyboard() -> ReplyKeyboardMarkup:
    """Клавіатура з першими літерами прізвищ усіх викладачів."""
    teachers = get_all_teachers()
    letters = sorted(set(t[0].upper() for t in teachers if t))
    rows = []
    for i in range(0, len(letters), 6):
        row = [KeyboardButton(text=letter) for letter in letters[i:i + 6]]
        rows.append(row)
    rows.append([KeyboardButton(text="🏠 На початок")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def get_teacher_list_keyboard(letter: str) -> ReplyKeyboardMarkup:
    """Клавіатура зі списком викладачів на певну літеру."""
    teachers = get_all_teachers()
    filtered = sorted(set(t for t in teachers if t and t[0].upper() == letter.upper()))
    rows = []
    for t in filtered:
        rows.append([KeyboardButton(text=t)])
    rows.append([KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="🏠 На початок")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def get_teacher_day_keyboard() -> ReplyKeyboardMarkup:
    """Вибір дня тижня для розкладу викладача."""
    rows = _build_weekday_buttons()
    rows.append([KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="🏠 На початок")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


REMOVE_KEYBOARD = ReplyKeyboardRemove()