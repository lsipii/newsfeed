from dateutil.parser import parse as dateutil_parse


def format_date_text(date_text: str) -> str:
    try:
        date_object = dateutil_parse(date_text)
        return date_object.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return date_text


def parse_domain(url: str) -> str:
    return url.split("/")[2]
