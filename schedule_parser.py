import io
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from bs4 import BeautifulSoup

import aiohttp
import pdfplumber

from config import (
    SCHEDULE_PAGE_URL,
    SUBSTITUTIONS_BASE_URL,
    LESSON_TIMES,
    FALLBACK_GROUPS,
    MAX_PAIR_NUM,
    get_local_schedule_path,
)

logger = logging.getLogger(__name__)
DAY_INDEX_TO_NAME = {0: "Понеділок", 1: "Вівторок", 2: "Середа", 3: "Четвер", 4: "П'ятниця"}

CACHE_FILE = "schedule_cache.json"

# ---------------------------------------------------------------------------
# In-memory кеши (заполняются при старте, пересоздаются ежедневно в 00:00)
# ---------------------------------------------------------------------------
_schedule_cache: Dict[str, List[Dict]] = {}
_groups_cache: Dict[int, List[str]] = {}

# ---------------------------------------------------------------------------
# Shared aiohttp session (переиспользуется для всех HTTP-запросов)
# ---------------------------------------------------------------------------
_http_session: Optional[aiohttp.ClientSession] = None

_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": SCHEDULE_PAGE_URL,
}


async def get_http_session() -> aiohttp.ClientSession:
    """Возвращает единую aiohttp-сессию (lazy init)."""
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(
            headers=_HTTP_HEADERS,
            timeout=aiohttp.ClientTimeout(total=10),
        )
    return _http_session


async def close_http_session():
    """Закрывает shared HTTP-сессию (вызывается при остановке бота)."""
    global _http_session
    if _http_session is not None and not _http_session.closed:
        await _http_session.close()
        _http_session = None


# ---------------------------------------------------------------------------
# PDF parsing settings & helpers
# ---------------------------------------------------------------------------
PDF_TABLE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "text_x_tolerance": 1,
    "text_y_tolerance": 1,
    "intersection_x_tolerance": 3,
    "intersection_y_tolerance": 3,
}

TEACHER_REGEX = re.compile(r'^[А-ЯІЇЄа-яіїєA-Za-z\'-]+\s+[А-ЯІЇЄA-Z]\.\s*[А-ЯІЇЄA-Z]\.$')
ROOM_REGEX = re.compile(r'^(?:ауд\.?\s*)?(\d{3}[а-яА-Яa-zA-Z]?|сп\.з\.|каб\.?\s*\d+)(?:\s*/\s*\d+)?$', re.IGNORECASE)


def normalize_group(name: str) -> str:
    """Унифицирует название группы."""
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
    """Очищает текст дня недели."""
    if not text:
        return ""
    s = str(text).replace('\n', '').replace(' ', '').replace('\r', '').upper()
    trans = str.maketrans({"I": "І"})
    return s.translate(trans)


def get_normal_day(text) -> Optional[str]:
    """Определение дня недели."""
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
    if 'ПЯТН' in t or 'П\'ЯТН' in t or 'П\u2019ЯТН' in t or 'ЯЦИНТЯ' in t:
        return "П'ятниця"
    return None


def roman_to_arabic(val: str) -> Optional[int]:
    """Преобразует римские цифры в арабские (максимум MAX_PAIR_NUM)."""
    clean = str(val).strip().upper().replace('І', 'I').replace('Ї', 'I')
    roman_map = {
        "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
        "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6
    }
    result = roman_map.get(clean)
    if result and result > MAX_PAIR_NUM:
        return None
    return result


def expand_para_range(val: str) -> List[int]:
    """Разворачивает диапазоны пар."""
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
    """Разбирает ячейку и склеивает оторванные буквы корпусов (например 111 + а -> 111а)."""
    raw_lines = [l.strip() for l in cell_text.split('\n') if l.strip()]

    lines = []
    for line in raw_lines:
        if lines and re.match(r'^[а-яА-Яa-zA-Z](\s*/\s*\d+)?$', line):
            prev = lines[-1]
            if re.search(r'\d{3}$', prev) or re.search(r'ауд\.?\s*\d+$', prev, re.I):
                lines[-1] = prev + line
                continue
        lines.append(line)

    subjects = []
    teachers = []
    rooms = []

    for line in lines:
        if TEACHER_REGEX.search(line):
            teachers.append(line)
        elif ROOM_REGEX.match(line) or (line.isdigit() and len(line) == 3):
            rooms.append(line)
        elif line.isdigit() and 1 <= int(line) <= MAX_PAIR_NUM:
            # Пропускаем номера пар (1–6), чтобы они не попадали в название предмета
            continue
        elif line.isdigit() and int(line) > MAX_PAIR_NUM:
            # Цифры больше MAX_PAIR_NUM (7, 8...) — мусор из PDF, тоже пропускаем
            continue
        else:
            subjects.append(line)

    subj_str = " ".join(subjects).strip()
    teach_str = ", ".join(teachers).strip() or "—"
    room_str = ", ".join(rooms).strip() or "—"

    return subj_str, teach_str, room_str


# ---------------------------------------------------------------------------
# Group extraction (with in-memory cache)
# ---------------------------------------------------------------------------
def extract_groups_from_pdf(course: int) -> List[str]:
    """Извлекает названия всех групп из PDF курса (с кешированием в памяти)."""
    if course in _groups_cache:
        return _groups_cache[course]

    pdf_path = get_local_schedule_path(course)
    if not pdf_path.exists():
        result = FALLBACK_GROUPS.get(course, [])
        _groups_cache[course] = result
        return result

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

    result = sorted(list(groups)) if groups else FALLBACK_GROUPS.get(course, [])
    _groups_cache[course] = result
    return result


# ---------------------------------------------------------------------------
# PDF table parsing
# ---------------------------------------------------------------------------
def _row_para_num(row) -> Optional[int]:
    """Ищет номер пары (арабский или римский) в первых 4 ячейках строки.
    Возвращает только значения 1..MAX_PAIR_NUM, всё остальное — None.
    """
    if not row:
        return None
    for cell in row[:4]:
        if not cell:
            continue
        val = str(cell).strip()
        if val.isdigit() and 1 <= int(val) <= MAX_PAIR_NUM:
            return int(val)
        rom = roman_to_arabic(val)
        if rom and 1 <= rom <= MAX_PAIR_NUM:
            return rom
    return None


def _cells_to_text(cells: List[str]) -> str:
    return "\n".join(
        t for t in cells if t and t.lower() not in ["none", "null", "—", "-", ""]
    )


def parse_tables_in_memory(tables: List, group: str, day_index: int) -> List[Dict]:
    """Быстро разбирает извлеченные из PDF таблицы в оперативной памяти.

    В файлах розкладу деякі клітинки пари фізично поділені на дві половини
    (верхню і нижню) горизонтальною лінією — це означає, що предмет
    чергується залежно від парності числа місяця (дня). pdfplumber
    повертає нижню половину як окремий "продовжуючий" рядок одразу під
    основним рядком пари, без номера пари в перших колонках. Якщо для
    колонок нашої групи в цьому продовжуючому рядку є хоч якесь значення
    (навіть порожній рядок, а не None) — значить клітинка була поділена,
    і потрібно розрізняти верхню (парні дні) та нижню (непарні дні) пари.
    Якщо продовжуючого рядка немає або він не зачіпає нашу групу — пара
    звичайна і діє в будь-який день (parity="any").
    """
    group_norm = normalize_group(group)
    day_name = DAY_INDEX_TO_NAME.get(day_index)
    if not day_name or not tables:
        return []

    # pair_number -> list of (parity, subject, teacher, room)
    lessons_by_pair: Dict[int, List[Tuple[str, str, str, str]]] = {}

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
        n_rows = len(table)
        row_idx = 0

        while row_idx < n_rows:
            row = table[row_idx]
            if not row:
                row_idx += 1
                continue

            for cell in row[:4]:
                d = get_normal_day(cell)
                if d:
                    current_day = d
                    break

            para_num = _row_para_num(row)

            if para_num is None or current_day != day_name:
                row_idx += 1
                continue

            # Верхня половина клітинки (основний рядок пари)
            top_cells = []
            for c_idx in target_cols:
                if c_idx < len(row) and row[c_idx] is not None:
                    top_cells.append(str(row[c_idx]).strip())

            # Перевіряємо наступний рядок — це може бути "нижня" половина
            # тієї ж клітинки (продовження без номера пари)
            bottom_cells: Optional[List[str]] = None
            if row_idx + 1 < n_rows:
                next_row = table[row_idx + 1]
                if next_row and _row_para_num(next_row) is None:
                    is_split_for_group = any(
                        c_idx < len(next_row) and next_row[c_idx] is not None
                        for c_idx in target_cols
                    )
                    if is_split_for_group:
                        bottom_cells = [
                            str(next_row[c_idx]).strip()
                            if c_idx < len(next_row) and next_row[c_idx] is not None
                            else ""
                            for c_idx in target_cols
                        ]
                    row_idx += 1  # рядок-продовження вже враховано, пропускаємо

            top_subj, top_teacher, top_room = parse_cell_structured(_cells_to_text(top_cells))

            if bottom_cells is not None:
                bottom_subj, bottom_teacher, bottom_room = parse_cell_structured(_cells_to_text(bottom_cells))

                if top_subj and not top_subj.isdigit() and len(top_subj) >= 2:
                    lessons_by_pair.setdefault(para_num, []).append(
                        ("even", top_subj, top_teacher, top_room)
                    )
                if bottom_subj and not bottom_subj.isdigit() and len(bottom_subj) >= 2:
                    lessons_by_pair.setdefault(para_num, []).append(
                        ("odd", bottom_subj, bottom_teacher, bottom_room)
                    )
            else:
                if top_subj and not top_subj.isdigit() and len(top_subj) >= 2:
                    lessons_by_pair.setdefault(para_num, []).append(
                        ("any", top_subj, top_teacher, top_room)
                    )

            row_idx += 1

    lessons = []
    for para_num, entries in lessons_by_pair.items():
        for parity, subj, teacher, room in entries:
            lessons.append({
                "number": para_num,
                "time": LESSON_TIMES.get(para_num, ""),
                "subject": subj,
                "teacher": teacher,
                "room": room,
                "cancelled": False,
                "parity": parity,
            })

    lessons.sort(key=lambda l: (l["number"], l["parity"]))
    return lessons


# ---------------------------------------------------------------------------
# Cache build / read / rebuild
# ---------------------------------------------------------------------------
async def build_and_save_schedule_cache(courses: List[int], semester: int):
    """Считывает PDF 1 раз на курс и формирует schedule_cache.json + in-memory кеш."""
    global _schedule_cache
    logger.info("⏳ Начинаем быструю сборку кэша расписания...")
    cache_data: Dict[str, List[Dict]] = {}

    # Сбрасываем кеш групп для повторного извлечения из PDF
    _groups_cache.clear()

    for course in courses:
        pdf_path = get_local_schedule_path(course)
        if not pdf_path.exists():
            logger.warning(f"PDF для курса {course} не найден: {pdf_path}")
            continue

        try:
            tables = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_tables(table_settings=PDF_TABLE_SETTINGS)
                    if t:
                        tables.extend(t)

            groups = extract_groups_from_pdf(course)

            for day_index in range(5):
                for group in groups:
                    lessons = parse_tables_in_memory(tables, group, day_index)
                    key = f"{course}_{normalize_group(group)}_{day_index}"
                    cache_data[key] = lessons

        except Exception as e:
            logger.error(f"Ошибка сборки кэша для курса {course}: {e}")

    # Сохраняем на диск (бекап)
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Кэш сохранен в {CACHE_FILE}")
    except Exception as e:
        logger.error(f"Ошибка сохранения файла кэша: {e}")

    # Атомарно обновляем in-memory кеш
    _schedule_cache = cache_data
    logger.info(f"✅ In-memory кэш загружен ({len(cache_data)} ключей)")


def get_schedule_from_file_cache(course: int, semester: int, group: str, target_date: datetime) -> List[Dict]:
    """Мгновенно достает расписание группы из in-memory кеша.

    Fallback: если in-memory кеш пуст, читает с диска и загружает в память.
    """
    global _schedule_cache

    group_norm = normalize_group(group)
    day_index = target_date.weekday()
    key = f"{course}_{group_norm}_{day_index}"
    is_even_day = target_date.day % 2 == 0

    source = _schedule_cache

    # Fallback: загрузить с диска, если в памяти пусто
    if not source and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                source = json.load(f)
                _schedule_cache = source
                logger.info(f"📂 Кэш загружен с диска в память ({len(source)} ключей)")
        except Exception as e:
            logger.error(f"Ошибка чтения файла кэша: {e}")
            return []

    if key not in source:
        return []

    all_lessons = source[key]
    result = []
    for lesson in all_lessons:
        parity = lesson.get("parity", "any")
        if parity == "any":
            result.append(lesson)
        elif parity == "even" and is_even_day:
            result.append(lesson)
        elif parity == "odd" and not is_even_day:
            result.append(lesson)
    return result


async def rebuild_schedule_cache():
    """Пересоздает кеш расписания. Вызывается планировщиком ежедневно в 00:00."""
    from utils import get_current_semester

    logger.info("🔄 Запуск ежедневного пересоздания кэша расписания...")

    # Удаляем старый файл кеша
    if os.path.exists(CACHE_FILE):
        try:
            os.remove(CACHE_FILE)
            logger.info(f"🗑️ Старый файл кэша {CACHE_FILE} удален")
        except Exception as e:
            logger.error(f"Ошибка удаления файла кэша: {e}")

    semester = get_current_semester()
    await build_and_save_schedule_cache([1, 2, 3, 4], semester)
    logger.info("✅ Ежедневное пересоздание кэша завершено")


# ---------------------------------------------------------------------------
# Teacher lookup — поиск расписания по преподавателю
# ---------------------------------------------------------------------------
def get_all_teachers() -> List[str]:
    """Возвращает отсортированный список всех уникальных преподавателей из кеша."""
    teachers = set()
    source = _schedule_cache
    if not source and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                source = json.load(f)
        except Exception:
            return []

    for lessons in source.values():
        for lesson in lessons:
            teacher = lesson.get("teacher", "—")
            if teacher and teacher != "—":
                # Может быть "Прізвище І.І., Прізвище2 І.І."
                for t in teacher.split(", "):
                    t = t.strip()
                    if t and t != "—" and TEACHER_REGEX.search(t):
                        teachers.add(t)
    return sorted(teachers)


def get_teacher_schedule(teacher_name: str, day_index: int, is_even_day: bool) -> List[Dict]:
    """Находит все пары преподавателя на заданный день из кеша.

    Возвращает список dict-ов с ключами:
        number, time, subject, group, room, parity
    """
    results = []
    source = _schedule_cache

    for key, lessons in source.items():
        # key = "course_GROUP_dayIndex"
        parts = key.rsplit("_", 1)
        if len(parts) != 2:
            continue
        try:
            cached_day = int(parts[1])
        except ValueError:
            continue
        if cached_day != day_index:
            continue

        # Извлекаем группу из ключа: "course_GROUP_day" -> "GROUP"
        prefix_parts = parts[0].split("_", 1)
        if len(prefix_parts) != 2:
            continue
        course_str = prefix_parts[0]
        group_norm = prefix_parts[1]

        for lesson in lessons:
            teacher_field = lesson.get("teacher", "")
            if not teacher_field:
                continue
            # Проверяем точное вхождение имени преподавателя
            if teacher_name not in teacher_field:
                continue

            parity = lesson.get("parity", "any")
            if parity == "even" and not is_even_day:
                continue
            if parity == "odd" and is_even_day:
                continue

            results.append({
                "number": lesson["number"],
                "time": lesson.get("time", LESSON_TIMES.get(lesson["number"], "")),
                "subject": lesson.get("subject", "—"),
                "group": group_norm,
                "room": lesson.get("room", "—"),
                "parity": parity,
            })

    # Убираем дубликаты (один предмет может быть у нескольких подгрупп)
    seen = set()
    unique = []
    for r in results:
        dedup_key = (r["number"], r["subject"], r["group"])
        if dedup_key not in seen:
            seen.add(dedup_key)
            unique.append(r)

    unique.sort(key=lambda x: x["number"])
    return unique


def format_teacher_schedule(teacher_name: str, day_name: str, date_str: str, lessons: List[Dict]) -> str:
    """Форматирует расписание преподавателя."""
    header = (
        f"👨‍🏫 Розклад для: {teacher_name}\n"
        f"📅 На день: {date_str} ({day_name})\n"
        f"────────────────────\n"
    )
    if not lessons:
        return header + "🎉 Пар немає!"

    lines = []
    for lesson in lessons:
        num = lesson["number"]
        time_str = lesson.get("time", "")
        subj = lesson.get("subject", "—")
        group = lesson.get("group", "—")
        room = lesson.get("room", "—")

        room_part = ""
        if room and room != "—":
            if any(kw in room.lower() for kw in ["ауд", "каб", "сп"]):
                room_part = f" [{room}]"
            else:
                room_part = f" [ауд. {room}]"

        lines.append(f"{num}. {time_str} — {subj} (гр. {group}){room_part}")

    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# Substitutions (замены) — парсинг с сайта в реальном времени
# ---------------------------------------------------------------------------
async def fetch_substitution_pdf(target_date: datetime) -> Optional[bytes]:
    """Загружает файл замен с сайта (через shared HTTP-сессию)."""
    date_str = target_date.strftime("%d.%m.%Y")
    direct_url = f"{SUBSTITUTIONS_BASE_URL}{date_str}.pdf"

    try:
        session = await get_http_session()

        async with session.get(direct_url) as resp:
            if resp.status == 200:
                return await resp.read()

        async with session.get(SCHEDULE_PAGE_URL) as resp:
            if resp.status == 200:
                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"]
                    if date_str in href or date_str.replace('.', '_') in href:
                        file_url = href if href.startswith("http") else f"https://ztk.org.ua{href}"
                        async with session.get(file_url) as pdf_resp:
                            if pdf_resp.status == 200:
                                return await pdf_resp.read()
    except Exception as e:
        logger.error(f"Ошибка загрузки замен: {e}")
    return None


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


async def get_substitutions(group: str, target_date: datetime) -> Tuple[bool, bool, List[Dict]]:
    """Парсит замены из интернета в реальном времени."""
    pdf_bytes = await fetch_substitution_pdf(target_date)
    if not pdf_bytes:
        return False, False, []

    subs_list = parse_substitutions_pdf(pdf_bytes, group)
    return True, len(subs_list) > 0, subs_list


def apply_substitutions(lessons: List[Dict], subs: List[Dict]) -> List[Dict]:
    """Накладывает замены на базовое расписание."""
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


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------
def format_lesson_line(lesson: dict) -> str:
    """Форматирует строчку пары."""
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
    """Генерирует итоговый текст ответа пользователю."""
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