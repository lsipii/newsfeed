news_sources = [
    #"https://newsapi.org/v2/top-headlines?sources=reuters,bbc-news,cnn",
    "https://www.hs.fi/rss/tuoreimmat.xml",
    "https://www.is.fi/rss/tuoreimmat.xml",
    "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET",
    "https://feeds.kauppalehti.fi/rss/main",
    "https://www.tivi.fi/api/feed/v2/rss/tv",   
    "https://www.aamulehti.fi/rss/tuoreimmat.xml",
    "https://www.savonsanomat.fi/feed/rss/",
    "https://wp.tekniikanmaailma.fi/feed/",
    "https://www.iltalehti.fi/rss/uutiset.xml",
    "https://www.mtvuutiset.fi/api/feed/rss/uutiset_uusimmat",
    "https://www.pelaaja.fi/feed/",
    "https://www.uusisuomi.fi/api/feed/v2/rss/us"
]

"""
@see: python time formats: https://strftime.org/
"""
date_time_format = "%d.%m.%Y %H:%M:%S"

"""
How often the news feed is updated (in seconds).
"""
news_update_frequency_in_seconds = 300
