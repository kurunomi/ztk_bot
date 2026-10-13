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


def get_week_dates() -> list:
    """Повертає список (date, day_name) для робочих днів поточного тижня (Пн–Пт).

    Якщо сьогодні Сб/Нд — повертає наступний тиждень.
    """
    now = datetime.now(TZ)
    weekday = now.weekday()  # 0=Пн .. 6=Нд

    # Знаходимо понеділок поточного тижня
    monday = now - timedelta(days=weekday)

    # Якщо вихідні — берем наступний тиждень
    if weekday >= 5:
        monday = monday + timedelta(weeks=1)

    day_names = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця"]
    result = []
    for i in range(5):
        day_date = monday + timedelta(days=i)
        result.append((day_date, day_names[i]))

    return result