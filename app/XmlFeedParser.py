import re
from datetime import datetime
from typing import Union
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element

from app.TextFormatter import TextFormatter
from app.news_types import NewsResponse
from app.text_parsers import is_uri_like_metadata_token, parse_date_from_text, trim_text

_DC_NS = "http://purl.org/dc/elements/1.1/"
_MRSS_NS = "http://search.yahoo.com/mrss/"
_ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


def _ns_tag(uri: str, local: str) -> str:
    return f"{{{uri}}}{local}"


def _split_keyword_blob(blob: str) -> list[str]:
    return [trim_text(p) for p in re.split(r"[,;]", blob) if trim_text(p)]


class XmlFeedParser:
    formatter: TextFormatter
    limit: Union[int, None] = None

    def __init__(
        self,
        text_formatter: TextFormatter,
        limit: Union[int, None] = None,
    ):
        self.formatter = text_formatter
        self.limit = limit

    def parse(self, xml: str) -> NewsResponse:
        root = ET.fromstring(xml)
        articles = []

        feed_name = self.get_text(root, ".//title")
        feed_name = self.formatter.format_name(feed_name)

        for item in root.findall(".//item"):
            date_time = self.get_datetime(item, "pubDate")
            subjects: list[str] = []
            keywords: list[str] = []

            def add_kw(text: str) -> None:
                t = trim_text(text)
                if t and t not in keywords and not is_uri_like_metadata_token(t):
                    keywords.append(t)

            def add_sub(text: str) -> None:
                t = trim_text(text)
                if t and t not in subjects:
                    subjects.append(t)

            for cat in item.findall("category"):
                t = trim_text(cat.text or "")
                if t:
                    add_sub(t)
                    dom = cat.get("domain")
                    if dom:
                        d = trim_text(dom)
                        if d and not is_uri_like_metadata_token(d):
                            add_kw(d)

            for el in item.findall(_ns_tag(_DC_NS, "subject")):
                blob = trim_text(el.text or "")
                if blob:
                    add_kw(blob)

            author = self.get_text(item, "author")
            if not author:
                creator_el = item.find(_ns_tag(_DC_NS, "creator"))
                if creator_el is not None:
                    author = trim_text(creator_el.text or "")

            mrss_kw = item.find(_ns_tag(_MRSS_NS, "keywords"))
            if mrss_kw is not None:
                blob = trim_text(mrss_kw.text or mrss_kw.get("content") or "")
                if blob:
                    for p in _split_keyword_blob(blob):
                        add_kw(p)

            for el in item.findall(_ns_tag(_ITUNES_NS, "keywords")):
                blob = trim_text(el.text or "")
                if blob:
                    for p in _split_keyword_blob(blob):
                        add_kw(p)

            guid_text = self.get_text(item, "guid")

            article_item = {
                "source": {"id": "", "name": feed_name},
                "author": author,
                "title": self.get_text(item, "title"),
                "description": self.get_text(item, "description"),
                "url": self.get_text(item, "link"),
                "urlToImage": "",
                "publishedAt": self.format_datetime(date_time),
                "publishedAtTimestamp": date_time.timestamp() if date_time else 0,
                "content": "",
                "subjects": subjects,
                "keywords": keywords,
                "guid": guid_text,
            }

            if self.is_a_valid_article(article_item):
                articles.append(article_item)

            if self.limit is not None and len(articles) >= self.limit:
                break

        return NewsResponse({"status": "ok", "totalResults": len(articles), "articles": articles})

    def is_a_valid_article(self, article_item):
        return (
            article_item["title"] is not None
            and article_item["url"] is not None
            and article_item["publishedAt"] is not None
        )

    def get_text(self, element: Element, tag: str, attribute=None):
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
        return self.formatter.format_date(datetime)
