from datetime import datetime
from typing import Callable, Union
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element

from app.news_types import NewsResponse
from app.text_parsers import format_date, parse_date_from_text, trim_text


class XmlFeedParser:
    date_time_formatter: Union[Callable[[Union[datetime, None]], str], None] = None
    name_formatter: Union[Callable[[str], str], None] = None
    limit: Union[int, None] = None

    def parse(self, xml: str) -> NewsResponse:
        root = ET.fromstring(xml)
        articles = []
        feed_name = self.get_text(root, ".//title")
        if feed_name is None:
            feed_name = ""
        elif self.name_formatter is not None:
            feed_name = self.name_formatter(feed_name)

        for item in root.findall(".//item"):
            date_time = self.get_datetime(item, "pubDate")
            article_item = {
                "source": {"id": "", "name": feed_name},
                "author": "",
                "title": self.get_text(item, "title"),
                "description": self.get_text(item, "description"),
                "url": self.get_text(item, "link"),
                "urlToImage": "",
                "publishedAt": self.format_datetime(date_time),
                "publishedAtTimestamp": date_time.timestamp() if date_time else 0,
                "content": "",
            }

            if self.is_a_valid_article(article_item):
                articles.append(article_item)

            if self.limit is not None and len(articles) >= self.limit:
                break

        return {"status": "ok", "totalResults": len(articles), "articles": articles}

    def is_a_valid_article(self, article_item):
        return (
            article_item["title"] is not None
            and article_item["url"] is not None
            and article_item["publishedAt"] is not None
        )

    def get_text(self, element: Element, tag, attribute=None):
        text_element = element.find(tag)
        if text_element is None:
            return ""

        text = ""
        if text_element is not None:
            if attribute is not None:
                text_attribute = text_element.get(attribute)
                text = text_attribute if text_attribute is not None else ""
            else:
                text = text_element.text

        return trim_text(text)

    def get_datetime(
        self, element: Element, tag, attribute=None
    ) -> Union[datetime, None]:
        text = self.get_text(element, tag, attribute)
        if text is None or len(text) == 0:
            return None
        return parse_date_from_text(text)

    def format_datetime(self, datetime: Union[datetime, None]) -> str:
        if datetime is None:
            return ""
        if self.date_time_formatter is not None:
            return self.date_time_formatter(datetime)
        return format_date(datetime)
