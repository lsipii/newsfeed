import os
import logging
from typing import List, Union
import requests
import traceback

from app.TextFormatter import TextFormatter
from app.exceptions import NewsSourceException
from app.news_types import NewsAppConfig, NewsArticle, NewsResponse
from app.text_parsers import (
    parse_date_from_text,
    parse_domain,
)
from app.XmlFeedParser import XmlFeedParser


class NewsFeed:
    formatter: TextFormatter
    news_sources: list[str]
    articles: list[NewsArticle]

    def __init__(
        self,
        config: NewsAppConfig,
    ):
        self.news_sources = config["news_sources"]
        self.formatter = TextFormatter(date_time_format=config["date_time_format"])
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
            case "www.hs.fi" | "www.is.fi" | "www.aamulehti.fi":
                return self.get_news_from_rss_source_and_format(
                    source=source, 
                    limit=limit, 
                    text_formatter=self.formatter.get_instance(
                        name="sanomat",
                        name_formatter=lambda name: name.split(" - ")[1]
                    )
                )
            case "feeds.yle.fi":
                return self.get_news_from_rss_source_and_format(
                    source=source, 
                    limit=limit, 
                    text_formatter=self.formatter.get_instance(
                        name="yle",
                        name_formatter=lambda name: name.split(" | ")[0]
                    )
                )
            case "feeds.kauppalehti.fi":
                return self.get_news_from_rss_source_and_format(
                        source=source, 
                        limit=limit, 
                        text_formatter=self.formatter.get_instance(
                            name="kauppalehti",
                            name_formatter=lambda name: name.split(" | ")[1]
                        )
                    )
            case _:
                return self.get_news_from_rss_source_and_format(source=source, limit=limit, text_formatter=self.formatter)

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
            article["publishedAt"] = self.formatter.format_date(date_time) if date_time else ""
            article["publishedAtTimestamp"] = date_time.timestamp() if date_time else 0
        return parsed

    def get_news_from_rss_source_and_format(self, source: str, limit: int, text_formatter: TextFormatter) -> NewsResponse:
        response_text = self.get_raw_response_from_source(source)
        xml_feed_parser = XmlFeedParser(text_formatter=text_formatter, limit=limit)

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