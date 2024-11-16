from dotenv import load_dotenv

import time
from rich.live import Live
from rich.console import Console
from rich.table import Table

from app.news_service import get_articles

news_sources = [
    "https://newsapi.org/v2/top-headlines?sources=reuters,bbc-news,cnn",
    "https://www.hs.fi/rss/tuoreimmat.xml",
    "https://www.is.fi/rss/tuoreimmat.xml",
    "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET",
]


def get_articles_table():
    articles = get_articles(news_sources)

    table = Table(box=None)

    table.add_column("Source", style="magenta", no_wrap=True)
    table.add_column("Title", style="cyan")

    for article in articles:
        table.add_row(article["source"]["name"], article["title"])
        # Add a separate row for the URL
        table.add_row(
            f"[green]{article['publishedAt']}[/green]",
            f"[blue underline]{article['url']}[/blue underline]",
        )
        table.add_row("---", "")
        table.add_row("", "")

    return table


def main():
    load_dotenv()

    console = Console()

    # Get news articles every 5 minutes
    with Live(console=console, auto_refresh=False, screen=False) as live:
        while True:
            # Update articles dynamically here if needed
            live.update(get_articles_table(), refresh=True)
            time.sleep(300)  # Refresh every 5 minutes (300 seconds)


if __name__ == "__main__":
    main()
