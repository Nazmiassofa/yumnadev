from datetime import datetime
from zoneinfo import ZoneInfo

ID = "Asia/Jakarta"

def get_current_date() -> str:
    return datetime.now(ZoneInfo(ID)).date().strftime('%Y-%m-%d')
    # result = 2025-06-09

def get_current_date_uptime() -> datetime.date:
    return datetime.now(ZoneInfo(ID)).date()
    # result = 2025-06-09

def get_current_time() -> str:
    return datetime.now(ZoneInfo(ID)).strftime('%H:%M:%S')
    # result = 02:07:01

def get_formatted_date(tanggal: str) -> str:
    return datetime.strptime(tanggal, '%Y-%m-%d').strftime('%Y/%m/%d')
    # result = 2025/06/07 | by param

def get_today_formatted() -> str:
    return datetime.now(ZoneInfo(ID)).strftime('%Y/%m/%d')
    # result = 2025/06/09
    
def get_day_name_from_date(date_str: str) -> str:
    # result day by date
    return datetime.strptime(date_str, '%Y-%m-%d').strftime('%A')