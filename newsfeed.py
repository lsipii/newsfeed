#!/usr/bin/env python
from app.main import execute
from app.news_types import NewsAppConfig
from config import news_sources, date_time_format, news_update_frequency_in_seconds
from dotenv import load_dotenv

def main():
    load_dotenv()

    execute(config=NewsAppConfig(
        news_sources=news_sources,
        date_time_format=date_time_format,
        news_update_frequency_in_seconds=news_update_frequency_in_seconds
    ))

if __name__ == "__main__":
    main()
