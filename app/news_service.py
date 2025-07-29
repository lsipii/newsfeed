import os
import logging
import requests
from app.exceptions import NewsSourceException
from app.news_types import NewsResponse
from app.text_parsers import format_date_text, format_date_text_alt, format_iso_datetime, parse_domain
from app.xml_feed_parser import XmlFeedParser

def get_news(source: str, limit: int) -> NewsResponse:
    domain = parse_domain(source)
    match domain:
        case "newsapi.org":
            return get_news_from_newsapi(f"{source}&pageSize={limit}")
        case "www.hs.fi" | "www.is.fi":
            return get_news_from_sanomat(source, limit)
        case "feeds.yle.fi":
            return get_news_from_yle(source, limit)
        case _:
            raise ValueError(f"Unknown news source: {domain}")

def get_news_from_newsapi(source: str) -> NewsResponse:
    news_api_key = os.getenv("NEWSAPI_ORG_KEY")
    if news_api_key is None:
        raise NewsSourceException("Missing News API key")
    
    response = requests.get(source, headers={"x-api-key": news_api_key})
    parsed = response.json()
    if parsed['status'] != 'ok':
        return parsed
    for article in parsed['articles']:
        article['publishedAt'] = format_iso_datetime(article['publishedAt'])
    return parsed

def get_news_from_sanomat(source: str, limit: int) -> NewsResponse:
    response = requests.get(source)
    xml_feed_parser = XmlFeedParser()
    
    xml_feed_parser.limit = limit
    xml_feed_parser.date_time_formatter = format_date_text
    xml_feed_parser.name_formatter = lambda name: name.split(" - ")[1]

    parsed = xml_feed_parser.parse(response.text)
    return parsed

def get_news_from_yle(source: str, limit: int) -> NewsResponse:
    response = requests.get(source)
    xml_feed_parser = XmlFeedParser()
    
    xml_feed_parser.limit = limit
    xml_feed_parser.date_time_formatter = format_date_text_alt
    xml_feed_parser.name_formatter = lambda name: name.split(" | ")[0]

    parsed = xml_feed_parser.parse(response.text)
    return parsed

def get_articles(news_sources: list[str]):
    articles_from_all_sources = []
    for source in news_sources:
        try:
            response = get_news(source, 10)
            for article in response['articles']:
                articles_from_all_sources.append(article)
        except NewsSourceException as e:
            logging.debug(f"Error fetching articles from {source}: {e}")

    # Sort articles by published time
    articles_from_all_sources.sort(key=lambda x: x['publishedAt'], reverse=False)

    return articles_from_all_sources
