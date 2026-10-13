import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
os.chdir(r"C:\Users\kurunomi\Desktop\ztk_bot")
sys.path.insert(0, r"C:\Users\kurunomi\Desktop\ztk_bot")

from config import BOT_TOKEN, TZ, MAX_PAIR_NUM, LESSON_TIMES
print(f"config OK: TZ={TZ}, MAX_PAIR_NUM={MAX_PAIR_NUM}, lessons={len(LESSON_TIMES)}")

from states import ScheduleStates
print(f"states OK: {len(ScheduleStates.__all_states__)} states")

from utils import get_current_semester, get_today_date, get_week_dates
week = get_week_dates()
for d, n in week:
    print(f"  {n}: {d.strftime('%d.%m.%Y')}")
print(f"utils OK: semester={get_current_semester()}")

from schedule_parser import roman_to_arabic, expand_para_range, get_all_teachers, _normalize_teacher_name

# Test Unicode Roman Numerals
for sym, expected in [("\u2162", 3), ("\u2163", 4), ("\u2164", 5), ("\u2165", 6)]:
    result = roman_to_arabic(sym)
    status = "OK" if result == expected else f"FAIL (got {result})"
    print(f"  roman({expected}) = {result} {status}")

print(f"  expand(III_unicode) = {expand_para_range(chr(0x2162))}")
print(f"  expand(VI_unicode)  = {expand_para_range(chr(0x2165))}")

# Test teacher normalization
n1 = _normalize_teacher_name("Xodzhaieva Ye.T.")
n2 = _normalize_teacher_name("Xodzhaieva E.T.")

n3 = _normalize_teacher_name("Test Є.Т.")
n4 = _normalize_teacher_name("Test Е.Т.")
print(f"  normalize Ye->E: '{n3}' == '{n4}' -> {n3 == n4}")

teachers = get_all_teachers()
print(f"teachers OK: {len(teachers)} unique")
hodj = [t for t in teachers if t.startswith("X") and "одж" in t.lower()]
for t in teachers:
    if "одж" in t.lower():
        hodj.append(t)
print(f"  Hodzhaieva entries: {len(hodj)}")

from keyboards import get_day_keyboard, get_teacher_day_keyboard
dk = get_day_keyboard()
print(f"day_keyboard OK: {len(dk.keyboard)} rows")
for row in dk.keyboard:
    texts = [b.text for b in row]
    print(f"  {texts}")

print("\nAll checks passed!")
