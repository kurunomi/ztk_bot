import os
from pathlib import Path
from dotenv import load_dotenv
import pytz

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TIMEZONE = "Europe/Kiev"
TZ = pytz.timezone(TIMEZONE)

# Базовая директория проекта
BASE_DIR = Path(__file__).parent

# Поиск локального файла расписания для курса (поддерживает и "1.pdf", и "1")
def get_local_schedule_path(course: int) -> Path:
    p_pdf = BASE_DIR / f"{course}.pdf"
    if p_pdf.exists():
        return p_pdf
    p_no_ext = BASE_DIR / f"{course}"
    if p_no_ext.exists():
        return p_no_ext
    return p_pdf

# Ссылки для получения замен
SCHEDULE_PAGE_URL = "https://ztk.org.ua/page/46"
SUBSTITUTIONS_BASE_URL = "https://ztk.org.ua/files/"

# Расписание звонков (только 6 пар — 7-й пары в ЖТК нет)
LESSON_TIMES = {
    1: "08:00–09:20",
    2: "09:30–10:50",
    3: "11:20–12:40",
    4: "12:50–14:10",
    5: "14:20–15:40",
    6: "15:50–17:10",
}

# Максимальный номер пары (используется парсером для фильтрации мусора)
MAX_PAIR_NUM = 6

# Резервные группы на случай отсутствия PDF-файла
FALLBACK_GROUPS = {
    1: ["А10", "МТ12", "ЕЛ11", "Ф15", "М14", "П13", "П14", "ФК16", "Д18", "Д19", "К17", "С15"],
    2: ["А20", "А20А", "ЕЛ21", "ЕЛ21А", "МТ22", "МТ22А", "МТ23А", "П23", "П24", "П24А", "ФК26", "ФК26А", "К27", "Д28", "Д29", "С25", "Ф25", "Ф25А", "М24", "М24А"],
    3: ["А30", "ЕЛ31", "П33", "П34", "К37", "К39", "Д38", "Д39", "С35", "ФК36", "МТ32", "МТ32А", "Ф35", "Е34"],
    4: ["А40", "ЕЛ41", "МТ42", "П43", "П44", "К47", "К49", "Д48", "Д49"],
}