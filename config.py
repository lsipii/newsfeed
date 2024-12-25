news_sources = [
    "https://newsapi.org/v2/top-headlines?sources=reuters,bbc-news,cnn",
    "https://www.hs.fi/rss/tuoreimmat.xml",
    "https://www.is.fi/rss/tuoreimmat.xml",
    "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET",
    "https://feeds.kauppalehti.fi/rss/main",
]

"""
@see: python time formats: https://strftime.org/
"""
date_time_format = "%d.%m.%Y %H:%M:%S"

"""
How often the news feed is updated (in seconds).
"""
news_update_frequency_in_seconds = 300
