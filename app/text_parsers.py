from datetime import datetime

def format_date_text(date_text: str) -> str:
    # Time text format: "Sat, 16 Nov 2024 12:17:00 GMT"
    time_text_format = "%a, %d %b %Y %H:%M:%S %Z"
    return format_time(date_text, time_text_format)

def format_date_text_alt(date_text: str) -> str:
    # Time text format: "Sat, 16 Nov 2024 15:58:40 +0200"
    time_text_format = "%a, %d %b %Y %H:%M:%S %z"
    return format_time(date_text, time_text_format)

def format_iso_datetime(datetime_text: str) -> str:
    # Remove microseconds if any
    if '.' in datetime_text:
        datetime_text = datetime_text.split('.')[0] + 'Z'
    return format_time(datetime_text, "%Y-%m-%dT%H:%M:%SZ")
    
def format_time(datetime_text: str, datetime_text_format: str = "%Y-%m-%dT%H:%M:%SZ") -> str:
    try:
        date_object = datetime.strptime(datetime_text, datetime_text_format)
        return date_object.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError as e:
        return datetime_text

def parse_domain(url: str) -> str:
    return url.split('/')[2]