from typing import Callable, Union
import xml.etree.ElementTree as ET
from app.news_types import NewsResponse

class XmlFeedParser:

    date_time_formatter: Union[Callable[[str], str], None] = None
    name_formatter: Union[Callable[[str], str], None] = None
    limit: Union[int, None] = None

    def parse(self, xml: str) -> NewsResponse:
        root = ET.fromstring(xml)
        articles = []
        feed_name = self.get_text(root, ".//title")
        if self.name_formatter is not None:
            feed_name = self.name_formatter(feed_name)

        for item in root.findall(".//item"):
            articles.append({
                "source": {
                    "id": "",
                    "name": feed_name
                },
                "author": "",
                "title": self.get_text(item, "title"),
                "description": self.get_text(item, "description"),
                "url": self.get_text(item, "link"),
                "urlToImage": "",
                "publishedAt": self.get_datetime(item, "pubDate"),
                "content": ""
            })

            if self.limit is not None and len(articles) >= self.limit:
                break

        return {"status": "ok", "totalResults": len(articles), "articles": articles}
    
    def get_text(self, element, tag, attribute=None):
        if attribute is not None:
            return element.find(tag).get(attribute) if element.find(tag) is not None else ""
        return element.find(tag).text if element.find(tag) is not None else ""
    
    def get_datetime(self, element, tag, attribute=None):
        text = self.get_text(element, tag, attribute)
        if text is not None and self.date_time_formatter is not None:
            return self.date_time_formatter(text)
        return text