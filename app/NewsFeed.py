import os
import logging
from typing import List, Union
import requests
import traceback

from app.exceptions import NewsSourceException
from app.news_types import NewsArticle, NewsResponse
from app.text_parsers import (
    format_date,
    parse_date_from_text,
    parse_domain,
)
from app.XmlFeedParser import XmlFeedParser


class NewsFeed:
    news_sources: list[str]
    articles: list[NewsArticle]

    def __init__(
        self,
        news_sources: list[str],
    ):
        self.news_sources = news_sources
        self.articles = []

    def get_latest_articles(self, limit: Union[int, None] = None) -> List[NewsArticle]:
        """
        Returns the latest articles from all sources.
        """
        if not self.articles:
            self.update(limit=limit)
        return self.articles[-limit:] if limit else self.articles

    def update(self, limit: Union[int, None] = None) -> bool:
        """
        @param limit: The number of latest articles to return. If None, all articles are returned.
        @return: True if new articles found, False otherwise.
        """
        articles_from_all_sources = []
        for source in self.news_sources:
            try:
                response = self.get_news_from_source(source, 10)
                for article in response["articles"]:
                    articles_from_all_sources.append(article)
            except Exception as e:
                traceback.print_exc()
                logging.debug(f"Error fetching articles from {source}: {e}")

        # Get sorted articles
        articles = self.sort_and_filter_articles(articles=articles_from_all_sources, limit=limit)

        has_updates = articles != self.articles
        self.articles = articles

        return has_updates

    def sort_and_filter_articles(self, articles: List[NewsArticle], limit: Union[int, None] = None) -> List[NewsArticle]:
        """
        Sorts and filters articles by published date.
        """
        sorted_articles = sorted(
            articles,
            key=lambda article: article["publishedAtTimestamp"],
        )

        sorted_articles = sorted_articles[-limit:] if limit else sorted_articles

        return sorted_articles

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
                return self.get_news_from_template_source(source, limit)

    def get_news_from_newsapi(self, source: str) -> NewsResponse:
        news_api_key = os.getenv("NEWSAPI_ORG_KEY")
        if news_api_key is None:
            raise NewsSourceException("Missing News API key")

        response = requests.get(source, headers={"x-api-key": news_api_key})
        parsed = response.json()
        if parsed["status"] != "ok":
            return parsed

        for article in parsed["articles"]:
            date_time = parse_date_from_text(article["publishedAt"])
            article["publishedAt"] = format_date(date_time) if date_time else ""
            article["publishedAtTimestamp"] = date_time.timestamp() if date_time else 0
        return parsed

    def get_news_from_sanomat(self, source: str, limit: int) -> NewsResponse:
        response_text = self.get_raw_response_from_source(source)
        xml_feed_parser = XmlFeedParser()

        xml_feed_parser.limit = limit
        xml_feed_parser.name_formatter = lambda name: name.split(" - ")[1]

        parsed = xml_feed_parser.parse(response_text)
        return parsed

    def get_news_from_yle(self, source: str, limit: int) -> NewsResponse:
        response_text = self.get_raw_response_from_source(source)
        xml_feed_parser = XmlFeedParser()

        xml_feed_parser.limit = limit
        xml_feed_parser.name_formatter = lambda name: name.split(" | ")[0]

        parsed = xml_feed_parser.parse(response_text)
        return parsed

    def get_news_from_kauppalehti(self, source: str, limit: int) -> NewsResponse:
        response_text = self.get_raw_response_from_source(source)
        xml_feed_parser = XmlFeedParser()

        xml_feed_parser.limit = limit
        xml_feed_parser.name_formatter = lambda name: name.split(" | ")[1]

        parsed = xml_feed_parser.parse(response_text)
        
        return parsed
    
    def get_news_from_template_source(self, source: str, limit: int) -> NewsResponse:
        response_text = self.get_raw_response_from_source(source)
        xml_feed_parser = XmlFeedParser()

        xml_feed_parser.limit = limit
        parsed = xml_feed_parser.parse(response_text)
        
        return parsed

    def get_raw_response_from_source(self, source: str) -> str:
        """
        Returns the raw XML response from the news source.
        """
        response = requests.get(source, headers={"User-Agent": "NewsFeedApp/1.0"})
        if response.status_code != 200:
            logging.debug(f"Failed to fetch news from {source}: {response.status_code}")
            raise NewsSourceException(f"Failed to fetch news from {source}")
        
        return response.text