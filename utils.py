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