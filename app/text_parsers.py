from dateutil.parser import parse as dateutil_parse
from zoneinfo import ZoneInfo
from datetime import datetime
from typing import Union


def format_date_text(date_text: str) -> str:
    try:
        parsed_date = dateutil_parse(date_text)

        # Get the local timezone
        local_tz = datetime.now().astimezone().tzinfo

        # Convert the datetime object to the local timezone
        if parsed_date.tzinfo is None:
            # If the parsed datetime is naive, assume it's UTC
            parsed_date = parsed_date.replace(tzinfo=ZoneInfo("UTC"))

        local_date = parsed_date.astimezone(local_tz)

        # Return the formatted local time string
        return local_date.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return date_text
    except Exception:
        return ""


def parse_domain(url: str) -> str:
    return url.split("/")[2]


def trim_text(text: Union[str, None]) -> str:
    trimmed_text = text.strip() if text is not None else ""
    # Replace newlines and tabs with spaces
    return trimmed_text.replace("\n", " ").replace("\t", " ")
