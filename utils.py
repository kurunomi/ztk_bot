from datetime import datetime, timedelta
from config import TZ


def get_current_semester() -> int:
    now = datetime.now(TZ)
    if 2 <= now.month <= 8:
        return 2
    return 1


def get_today_date() -> datetime:
    return datetime.now(TZ)


def get_tomorrow_date() -> datetime:
    return datetime.now(TZ) + timedelta(days=1)


def get_next_study_day() -> datetime:
    """Повертає наступний навчальний день (пропускає Сб/Нд).
    Якщо сьогодні Пт — повертає Пн, Сб — Пн, Нд — Пн.
    """
    now = datetime.now(TZ)
    days_ahead = 1
    weekday = now.weekday()  # 0=Пн .. 6=Нд
    if weekday == 4:      # П'ятниця → +3 = Понеділок
        days_ahead = 3
    elif weekday == 5:    # Субота → +2 = Понеділок
        days_ahead = 2
    elif weekday == 6:    # Неділя → +1 = Понеділок
        days_ahead = 1
    return now + timedelta(days=days_ahead)