from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from schedule_parser import extract_groups_from_pdf, get_all_teachers
from datetime import datetime, timedelta
from config import TZ
from utils import get_next_study_day


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


def _build_day_buttons() -> list:
    """Будує кнопки Сьогодні / Завтра (або Понеділок, якщо завтра вихідний)."""
    now = datetime.now(TZ)
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
    today_name = day_names[now.weekday()]

    today_btn = KeyboardButton(
        text=f"📅 Сьогодні ({today_name} {now.strftime('%d.%m')})"
    )

    # Якщо сьогодні Пт/Сб/Нд — замість "Завтра" показуємо наступний навчальний день
    next_day = get_next_study_day()
    next_name = day_names[next_day.weekday()]

    if now.weekday() >= 4:  # Пт, Сб, Нд
        next_btn = KeyboardButton(
            text=f"📅 Понеділок ({next_name} {next_day.strftime('%d.%m')})"
        )
    else:
        next_btn = KeyboardButton(
            text=f"📅 Завтра ({next_name} {next_day.strftime('%d.%m')})"
        )

    return [today_btn, next_btn]


def get_day_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            _build_day_buttons(),
            [KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="🏠 На початок")],
        ],
        resize_keyboard=True,
    )


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
    return ReplyKeyboardMarkup(
        keyboard=[
            _build_day_buttons(),
            [KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="🏠 На початок")],
        ],
        resize_keyboard=True,
    )


REMOVE_KEYBOARD = ReplyKeyboardRemove()