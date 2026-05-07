from dateutil.parser import parse as dateutil_parse
from zoneinfo import ZoneInfo
from datetime import datetime
from typing import List, Union
import re


def parse_date_from_text(date_text: str) -> Union[datetime, None]:
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
        return local_date
    except Exception:
        pass
    return None


def format_date(date: datetime, date_time_format: str = "%d.%m.%Y %H:%M:%S") -> str:
    return date.strftime(date_time_format)


def format_date_text(date_text: str, date_time_format: str = "%d.%m.%Y %H:%M:%S") -> str:
    try:
        parsed_date = parse_date_from_text(date_text)
        if parsed_date is None:
            return date_text

        # Return the formatted local time string
        return format_date(parsed_date, date_time_format)
    except ValueError:
        return date_text
    except Exception:
        return ""


def parse_domain(url: str) -> str:
    return url.split("/")[2]


def trim_text(text: Union[str, None]) -> str:
    trimmed_text = text.strip() if text is not None else ""
    # Replace newlines and tabs with spaces
    return re.sub(r"[\n\r\t\v]", " ", trimmed_text)


# Values that are only URLs should not act as keyword-style metadata (feeds often ship junk URIs).
_METADATA_URI_SCHEME_RE = re.compile(
    r"^(?:https?|ftp)://\S+$|^\S+://\S+$",
    re.IGNORECASE,
)


def is_uri_like_metadata_token(s: str) -> bool:
    """True when ``s`` is empty or looks like a URI / URL fragment (not natural-language tags)."""
    t = trim_text(s)
    if not t:
        return True
    if _METADATA_URI_SCHEME_RE.match(t):
        return True
    # ``example.com/path`` or ``www.site.tld/foo`` with no spaces — typical link dumps
    if " " not in t and "/" in t:
        if re.match(r"^[a-z0-9][a-z0-9.-]{0,253}\.[a-z]{2,}/\S*$", t, re.IGNORECASE):
            return True
    return False


def filter_metadata_keywords(keywords: Union[List[str], None]) -> List[str]:
    if not keywords:
        return []
    return [k for k in keywords if not is_uri_like_metadata_token(k)]
