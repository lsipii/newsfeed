import os
import logging
import requests
from app.exceptions import NewsSourceException
from app.news_types import NewsResponse
from app.text_parsers import (
    format_date_text,
    parse_domain,
)
from app.xml_feed_parser import XmlFeedParser


class NewsFeed:
    def get_articles(self, news_sources: list[str]):
        articles_from_all_sources = []
        for source in news_sources:
            try:
                response = self.get_news_from_source(source, 10)
                for article in response["articles"]:
                    articles_from_all_sources.append(article)
            except NewsSourceException as e:
                logging.debug(f"Error fetching articles from {source}: {e}")

        # Sort articles by published time
        articles_from_all_sources.sort(key=lambda x: x["publishedAt"], reverse=False)

        return articles_from_all_sources

    def get_news_from_source(self, source: str, limit: int) -> NewsResponse:
        domain = parse_domain(source)
        match domain:
            case "newsapi.org":
                return self.get_news_from_newsapi(f"{source}&pageSize={limit}")
            case "www.hs.fi" | "www.is.fi":
                return self.get_news_from_sanomat(source, limit)
            case "feeds.yle.fi":
                return self.get_news_from_yle(source, limit)
            case "feeds.kauppalehti.fi":
                return self.get_news_from_kauppalehti(source, limit)
            case _:
                raise ValueError(f"Unknown news source: {domain}")

    def get_news_from_newsapi(self, source: str) -> NewsResponse:
        news_api_key = os.getenv("NEWSAPI_ORG_KEY")
        if news_api_key is None:
            raise NewsSourceException("Missing News API key")

        response = requests.get(source, headers={"x-api-key": news_api_key})
        parsed = response.json()
        if parsed["status"] != "ok":
            return parsed

        for article in parsed["articles"]:
            article["publishedAt"] = format_date_text(article["publishedAt"])
        return parsed

    def get_news_from_sanomat(self, source: str, limit: int) -> NewsResponse:
        response = requests.get(source)
        xml_feed_parser = XmlFeedParser()

        xml_feed_parser.limit = limit
        xml_feed_parser.name_formatter = lambda name: name.split(" - ")[1]

        parsed = xml_feed_parser.parse(response.text)
        return parsed

    def get_news_from_yle(self, source: str, limit: int) -> NewsResponse:
        response = requests.get(source)
        xml_feed_parser = XmlFeedParser()

        xml_feed_parser.limit = limit
        xml_feed_parser.name_formatter = lambda name: name.split(" | ")[0]

        parsed = xml_feed_parser.parse(response.text)
        return parsed

    def get_news_from_kauppalehti(self, source: str, limit: int) -> NewsResponse:
        response = requests.get(source)
        xml_feed_parser = XmlFeedParser()

        xml_feed_parser.limit = limit
        xml_feed_parser.name_formatter = lambda name: name.split(" | ")[1]

        parsed = xml_feed_parser.parse(response.text)
        return parsed