import io
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from bs4 import BeautifulSoup

import aiohttp
import pdfplumber
import pytz

from config import (
    get_local_schedule_path,
    SCHEDULE_PAGE_URL,
    SUBSTITUTIONS_BASE_URL,
    LESSON_TIMES,
    TIMEZONE,
    FALLBACK_GROUPS,
)

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)

DAY_INDEX_TO_NAME = {0: "Понеділок", 1: "Вівторок", 2: "Середа", 3: "Четвер", 4: "П'ятниця"}

PDF_TABLE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "text_x_tolerance": 1,
    "text_y_tolerance": 1,
    "intersection_x_tolerance": 3,
    "intersection_y_tolerance": 3,
}

TEACHER_REGEX = re.compile(r'^[А-ЯІЇЄa-zA-Z\'-]+\s+[А-ЯІЇЄA-Z]\.\s*[А-ЯІЇЄA-Z]\.$')
ROOM_REGEX = re.compile(r'^(?:ауд\.?\s*)?(\d{3}[а-яА-Яa-zA-Z]?|сп\.з\.|каб\.?\s*\d+)(?:\s*/\s*\d+)?$', re.IGNORECASE)


def normalize_group(name: str) -> str:
    """Унифицирует название группы (удаляет пробелы, дефисы, приводить к единому регистру/алфавиту)."""
    if not name:
        return ""
    s = re.sub(r"[^А-ЯІЇЄA-Z0-9]", "", str(name).upper())
    trans = str.maketrans({
        "A": "А", "B": "Б", "E": "Е", "I": "І", "K": "К", 
        "M": "М", "H": "Н", "O": "О", "P": "Р", "C": "С", 
        "T": "Т", "X": "Х"
    })
    return s.translate(trans)


def clean_day_text(text: str) -> str:
    """Очищает текст дня недели от переносов и спецсимволов."""
    if not text:
        return ""
    s = str(text).replace('\n', '').replace(' ', '').replace('\r', '').upper()
    trans = str.maketrans({"I": "І"})
    return s.translate(trans)


def get_normal_day(text) -> Optional[str]:
    """Устойчивое определение дня недели."""
    if not text:
        return None
    t = clean_day_text(text)
    if 'ПОНЕД' in t or 'КОЛІДЕН' in t:
        return 'Понеділок'
    if 'ВІВТОР' in t or 'КОРОТВ' in t:
        return 'Вівторок'
    if 'СЕРЕД' in t or 'АДЕРЕС' in t:
        return 'Середа'
    if 'ЧЕТВЕР' in t or 'РЕВТЕЧ' in t:
        return 'Четвер'
    if 'ПЯТН' in t or 'П\'ЯТН' in t or 'П’ЯТН' in t or 'ЯЦИНТЯ' in t:
        return "П'ятниця"
    return None


def roman_to_arabic(val: str) -> Optional[int]:
    """Преобразует римские цифры в арабские."""
    clean = str(val).strip().upper().replace('І', 'I').replace('Ї', 'I')
    roman_map = {
        "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
        "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6
    }
    return roman_map.get(clean)


def expand_para_range(val: str) -> List[int]:
    """Разворачивает диапазоны пар, например 'I-III' -> [1, 2, 3]."""
    clean = str(val).strip().upper().replace('І', 'I').replace('Ї', 'I')
    parts = clean.split('-')
    if len(parts) == 2:
        start = roman_to_arabic(parts[0])
        end = roman_to_arabic(parts[1])
        if start and end and start <= end:
            return list(range(start, end + 1))
    single = roman_to_arabic(clean)
    return [single] if single else []


def parse_cell_structured(cell_text: str) -> Tuple[str, str, str]:
    """Разбирает мультистрочную ячейку на Предмет, Преподавателя и Аудиторию."""
    lines = [l.strip() for l in cell_text.split('\n') if l.strip()]
    subjects = []
    teachers = []
    rooms = []

    for line in lines:
        if TEACHER_REGEX.search(line):
            teachers.append(line)
        elif ROOM_REGEX.match(line) or (line.isdigit() and len(line) == 3):
            rooms.append(line)
        elif line.isdigit() and int(line) in [1, 2, 3, 4, 5, 6]:
            continue
        else:
            subjects.append(line)

    subj_str = " ".join(subjects).strip()
    teach_str = ", ".join(teachers).strip() or "—"
    room_str = ", ".join(rooms).strip() or "—"

    return subj_str, teach_str, room_str


def extract_groups_from_pdf(course: int) -> List[str]:
    """Извлекает названия всех групп из всех страниц PDF-файла расписания."""
    pdf_path = get_local_schedule_path(course)
    if not pdf_path.exists():
        return FALLBACK_GROUPS.get(course, [])

    groups = set()
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables(table_settings=PDF_TABLE_SETTINGS)
                for table in tables:
                    for r in range(min(5, len(table))):
                        for cell in table[r]:
                            if not cell:
                                continue
                            cell_text = str(cell).replace('\n', ' ')
                            found = re.findall(r'\b[А-ЯІЇЄa-zA-Z]{1,3}\s*[-]?\s*\d{2}[А-ЯІЇЄa-zA-Z]?\b', cell_text)
                            for g in found:
                                clean_g = normalize_group(g)
                                if len(clean_g) >= 3:
                                    groups.add(clean_g)
    except Exception as e:
        logger.error(f"Ошибка при считывании групп: {e}")

    return sorted(list(groups)) if groups else FALLBACK_GROUPS.get(course, [])


async def fetch_substitution_pdf(target_date: datetime) -> Optional[bytes]:
    """Загружает PDF-файл замен с сайта ztk.org.ua."""
    date_str = target_date.strftime("%d.%m.%Y")
    direct_url = f"{SUBSTITUTIONS_BASE_URL}{date_str}.pdf"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": SCHEDULE_PAGE_URL,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(direct_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.read()

            async with session.get(SCHEDULE_PAGE_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")
                    for a_tag in soup.find_all("a", href=True):
                        href = a_tag["href"]
                        if date_str in href or date_str.replace('.', '_') in href:
                            file_url = href if href.startswith("http") else f"https://ztk.org.ua{href}"
                            async with session.get(file_url, headers=headers) as pdf_resp:
                                if pdf_resp.status == 200:
                                    return await pdf_resp.read()
    except Exception as e:
        logger.error(f"Ошибка загрузки замен: {e}")
    return None


def parse_schedule_pdf(pdf_bytes: bytes, group: str, day_index: int, target_date: datetime) -> List[Dict]:
    """Парсит основной файл расписания."""
    group_norm = normalize_group(group)
    day_name = DAY_INDEX_TO_NAME.get(day_index)
    if not day_name:
        return []

    lessons = []

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables(table_settings=PDF_TABLE_SETTINGS)
                if not tables:
                    continue

                for table in tables:
                    if not table or len(table) < 2:
                        continue

                    col_to_group = {}
                    current_grp = None

                    for c in range(len(table[0])):
                        cell_group = None
                        for r in range(min(5, len(table))):
                            if c < len(table[r]) and table[r][c]:
                                val_str = str(table[r][c])
                                found = re.findall(r'\b[А-ЯІЇЄa-zA-Z]{1,3}\s*[-]?\s*\d{2}[А-ЯІЇЄa-zA-Z]?\b', val_str)
                                if found:
                                    cell_group = normalize_group(found[0])
                                    break
                        if cell_group:
                            current_grp = cell_group
                        if current_grp:
                            col_to_group[c] = current_grp

                    target_cols = [c for c, grp in col_to_group.items() if grp == group_norm]
                    if not target_cols:
                        continue

                    current_day = None
                    for row in table:
                        if not row:
                            continue

                        for cell in row[:4]:
                            d = get_normal_day(cell)
                            if d:
                                current_day = d
                                break

                        if current_day != day_name:
                            continue

                        para_num = None
                        for cell in row[:4]:
                            if not cell:
                                continue
                            val = str(cell).strip()
                            if val.isdigit() and 1 <= int(val) <= 6:
                                para_num = int(val)
                                break
                            rom = roman_to_arabic(val)
                            if rom and 1 <= rom <= 6:
                                para_num = rom
                                break

                        if not para_num:
                            continue

                        raw_cells = []
                        for c_idx in target_cols:
                            if c_idx < len(row) and row[c_idx]:
                                text = str(row[c_idx]).strip()
                                if text and text.lower() not in ["none", "null", "—", "-", ""]:
                                    raw_cells.append(text)

                        if not raw_cells:
                            continue

                        combined_raw = "\n".join(raw_cells)
                        subj, teacher, room = parse_cell_structured(combined_raw)

                        if not subj or subj.isdigit() or len(subj) < 2:
                            continue

                        lessons.append({
                            "number": para_num,
                            "time": LESSON_TIMES.get(para_num, ""),
                            "subject": subj,
                            "teacher": teacher,
                            "room": room,
                            "cancelled": False
                        })

    except Exception as e:
        logger.error(f"Ошибка парсинга таблицы расписания: {e}", exc_info=True)

    res = {l["number"]: l for l in lessons}
    return [res[k] for k in sorted(res.keys())]


def parse_substitutions_pdf(pdf_bytes: bytes, group: str) -> List[Dict]:
    """Парсит файлы замен."""
    subs_list = []
    group_norm = normalize_group(group)
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables(table_settings=PDF_TABLE_SETTINGS)
                for table in tables:
                    current_groups = []
                    for row in table:
                        if not row or all(c is None for c in row):
                            continue
                        
                        group_col = row[0] if len(row) > 0 else None
                        para_col = row[1] if len(row) > 1 else None
                        subject = row[2] if len(row) > 2 else None
                        teacher = row[3] if len(row) > 3 else None
                        room = row[4] if len(row) > 4 else None

                        if str(group_col).strip() == 'Група' or str(subject).strip() == 'Дисципліна':
                            continue

                        if group_col is not None and str(group_col).strip():
                            clean = str(group_col).replace('\n', '').replace(' ', '')
                            current_groups = [normalize_group(g) for g in clean.split(',')]

                        if not para_col or not current_groups:
                            continue

                        is_cancelled = (subject and ('---' in str(subject) or 'відміна' in str(subject).lower())) or bool(re.match(r'^[-—_\s]+$', str(subject or '')))
                        
                        clean_subj = "ВІДМІНЕНО" if is_cancelled else str(subject or "").replace('\n', ' ').strip()
                        clean_teacher = "—" if is_cancelled else str(teacher or "").replace('\n', ' ').strip()
                        clean_room = "—" if is_cancelled else str(room or "").replace('\n', ' ').strip()

                        if group_norm in current_groups:
                            for pair_num in expand_para_range(str(para_col)):
                                subs_list.append({
                                    "pair_number": pair_num,
                                    "cancelled": is_cancelled,
                                    "subject": clean_subj,
                                    "new_subject": clean_subj,
                                    "teacher": clean_teacher,
                                    "new_teacher": clean_teacher,
                                    "room": clean_room,
                                    "new_room": clean_room
                                })
    except Exception as e:
        logger.error(f"Ошибка парсинга PDF замен: {e}")
    return subs_list


async def get_schedule_for_group(course: int, semester: int, group: str, target_date: datetime) -> List[Dict]:
    pdf_path = get_local_schedule_path(course)
    if not pdf_path.exists():
        return []
    
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    return parse_schedule_pdf(pdf_bytes, group, target_date.weekday(), target_date)


async def get_substitutions(group: str, target_date: datetime) -> Tuple[bool, bool, List[Dict]]:
    pdf_bytes = await fetch_substitution_pdf(target_date)
    if not pdf_bytes:
        return False, False, []
        
    subs_list = parse_substitutions_pdf(pdf_bytes, group)
    return True, len(subs_list) > 0, subs_list


def apply_substitutions(lessons: List[Dict], subs: List[Dict]) -> List[Dict]:
    subs_map = {s["pair_number"]: s for s in subs}
    updated_lessons = []
    all_pair_nums = set(l["number"] for l in lessons).union(subs_map.keys())
    
    for p_num in sorted(all_pair_nums):
        sub = subs_map.get(p_num)
        orig = next((l for l in lessons if l["number"] == p_num), None)
        
        if sub:
            if sub["cancelled"]:
                updated_lessons.append({
                    "number": p_num,
                    "time": LESSON_TIMES.get(p_num, ""),
                    "subject": "❌ ПАРУ СКАСОВАНО",
                    "teacher": "—",
                    "room": "—",
                    "cancelled": True
                })
            else:
                updated_lessons.append({
                    "number": p_num,
                    "time": LESSON_TIMES.get(p_num, ""),
                    "subject": f"🔄 {sub['new_subject']}",
                    "teacher": sub["new_teacher"],
                    "room": sub["new_room"],
                    "cancelled": False
                })
        elif orig:
            updated_lessons.append(orig)
            
    return updated_lessons


def format_lesson_line(lesson: dict) -> str:
    """Форматирует одну строку пары в вид: 1. 08:00–09:20 — Название (Преподаватель) [ауд. Кабинет]"""
    num = lesson["number"]
    time_str = lesson.get("time", LESSON_TIMES.get(num, ""))
    subj = lesson.get("subject", "—")
    teacher = lesson.get("teacher", "—")
    room = lesson.get("room", "—")

    if lesson.get("cancelled"):
        return f"{num}. {time_str} — ❌ {subj}"

    teacher_part = f" ({teacher})" if teacher and teacher != "—" else ""

    room_part = ""
    if room and room != "—":
        if any(kw in room.lower() for kw in ["ауд", "каб", "сп"]):
            room_part = f" [{room}]"
        else:
            room_part = f" [ауд. {room}]"

    return f"{num}. {time_str} — {subj}{teacher_part}{room_part}"


def format_schedule_response(
    group: str, 
    course: int, 
    semester: int, 
    date_obj: datetime, 
    has_sub_file: bool, 
    has_group_subs: bool, 
    lessons: List[dict]
) -> str:
    """Собирает готовый текст ответа в формате Telegram-бота."""
    day_name = DAY_INDEX_TO_NAME.get(date_obj.weekday(), "")
    date_str = date_obj.strftime("%d.%m.%Y")

    if not has_sub_file:
        sub_status = "🟢 Замін немає (файл на сайті не опубліковано)."
    elif has_group_subs:
        sub_status = "🔄 Є заміни для цієї групи"
    else:
        sub_status = "🟢 Замін немає для цієї групи"

    header = (
        f"📋 Розклад для групи {group} ({course} курс)\n"
        f"📅 На день: {date_str} ({day_name})\n"
        f"📚 Семестр: {semester}\n"
        f"ℹ️ Статус замін: {sub_status}\n"
        f"────────────────────\n"
    )

    if not lessons:
        return header + "🎉 Пар немає!"

    lines = [format_lesson_line(lesson) for lesson in lessons]
    return header + "\n".join(lines)