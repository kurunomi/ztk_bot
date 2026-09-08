from datetime import datetime, timedelta
import pytz
from config import TIMEZONE

TZ = pytz.timezone(TIMEZONE)

def get_current_semester() -> int:
    now = datetime.now(TZ)
    if 2 <= now.month <= 8:
        return 2
    return 1

def get_today_date() -> datetime:
    return datetime.now(TZ)

def get_tomorrow_date() -> datetime:
    return datetime.now(TZ) + timedelta(days=1)

def get_substitution_status(file_exists: bool, group_found: bool, target_date: datetime) -> str:
    if not file_exists:
        return "не опубліковані / відсутні"
    if not group_found:
        return "немає для цієї групи"
    return "є заміни"

def format_schedule_message(group, course, semester, target_dt, lessons, sub_info):
    day_names = {0: "Понеділок", 1: "Вівторок", 2: "Середа", 3: "Четвер", 4: "П'ятниця", 5: "Субота", 6: "Неділя"}
    day_name = day_names.get(target_dt.weekday(), "")
    date_str = target_dt.strftime("%d.%m.%Y")

    # Разбор данных о заменах
    has_sub_file = True
    has_group_subs = False
    subs_list = []

    if isinstance(sub_info, tuple) and len(sub_info) == 3:
        has_sub_file, has_group_subs, subs_list = sub_info
    elif isinstance(sub_info, list):
        subs_list = sub_info
        has_group_subs = len(subs_list) > 0

    if not has_sub_file:
        sub_status = "🟢 Замін немає (файл на сайті не опубліковано)."
    elif has_group_subs:
        sub_status = "🔄 Є заміни для цієї групи"
    else:
        sub_status = "🟢 Замін немає для цієї групи"

    # Применение замен к основным парам
    from schedule_parser import apply_substitutions
    final_lessons = apply_substitutions(lessons, subs_list) if subs_list else lessons

    header = (
        f"📋 Розклад для групи {group} ({course} курс)\n"
        f"📅 На день: {date_str} ({day_name})\n"
        f"📚 Семестр: {semester}\n"
        f"ℹ️ Статус замін: {sub_status}\n"
        f"────────────────────\n"
    )

    if not final_lessons:
        return header + "🎉 Пар немає!"

    lines = []
    for l in final_lessons:
        num = l["number"]
        time_str = l.get("time", "")
        subj = l.get("subject", "—")
        teacher = l.get("teacher", "—")
        room = l.get("room", "—")

        if l.get("cancelled"):
            lines.append(f"{num}. {time_str} — ❌ {subj}")
            continue

        teacher_part = f" ({teacher})" if teacher and teacher != "—" else ""
        room_part = ""
        if room and room != "—":
            if any(kw in room.lower() for kw in ["ауд", "каб", "сп"]):
                room_part = f" [{room}]"
            else:
                room_part = f" [ауд. {room}]"

        lines.append(f"{num}. {time_str} — {subj}{teacher_part}{room_part}")

    return header + "\n".join(lines)