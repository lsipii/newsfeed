
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
    content: str

class NewsResponse(TypedDict):
    status: str
    totalResults: int
    articles: List[NewsArticle]