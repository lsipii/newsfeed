from typing import List, TypedDict


class NewsSource(TypedDict):
    id: str
    name: str


class NewsArticle(TypedDict):
    source: NewsSource
    author: str
    title: str
    description: str
    url: str
    urlToImage: str
    publishedAt: str
    publishedAtTimestamp: int
    content: str


class NewsResponse(TypedDict):
    status: str
    totalResults: int
    articles: List[NewsArticle]


class NewsAppConfig(TypedDict):
    news_sources: List[str]
    date_time_format: str
    news_update_frequency_in_seconds: int

