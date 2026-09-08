#!/usr/bin/env python3
"""
Скрипт отладки для тестирования парсера ЖТК из консоли.

Примеры использования:
    python debug_parser.py --course 2 --group П24
    python debug_parser.py --subs --group П24 --date 2026-09-08
"""
import argparse
import asyncio
import re
from datetime import datetime, timedelta
import pytz
from schedule_parser import format_schedule_response

TZ = pytz.timezone("Europe/Kiev")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--course", type=int, default=2)
    parser.add_argument("--group", default="П24")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--subs", action="store_true", help="Показать только замены")
    args = parser.parse_args()

    from schedule_parser import (
        get_schedule_for_group, get_substitutions,
        extract_groups_from_pdf
    )
    from utils import format_schedule_message, get_current_semester

    target_dt = (
        datetime.fromisoformat(args.date).replace(tzinfo=TZ)
        if args.date else datetime.now(TZ)
    )
    semester = get_current_semester()

    print(f"=== ZTK Parser Debug ===")
    print(f"Курс: {args.course} | Группа: {args.group}")
    print(f"Найдено групп в файле {args.course}: {extract_groups_from_pdf(args.course)}")
    print(f"Дата: {target_dt.strftime('%d.%m.%Y')}")
    print()

    base_lessons = await get_schedule_for_group(args.course, semester, args.group, target_dt)
    has_sub_file, has_group_subs, subs = await get_substitutions(args.group, target_dt)
    
    from schedule_parser import apply_substitutions, format_schedule_response
    final_lessons = apply_substitutions(base_lessons, subs)

    msg = format_schedule_response(
        group=args.group,
        course=args.course,
        semester=semester,
        date_obj=target_dt,
        has_sub_file=has_sub_file,
        has_group_subs=has_group_subs,
        lessons=final_lessons
    )
    print("=== ИТОГОВОЕ СООБЩЕНИЕ ===")
    print(msg)


if __name__ == "__main__":
    asyncio.run(main())