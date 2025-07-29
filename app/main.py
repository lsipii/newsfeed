from dotenv import load_dotenv
import signal
import sys
import time
import logging

from rich.live import Live
from rich.console import Console
from rich.table import Table

from app.NewsFeed import NewsFeed
from config import news_sources


def get_articles_table(news_feed: NewsFeed):
    articles = news_feed.get_articles(news_sources)

    table = Table(box=None)

    table.add_column(
        "Source",
        style="dark_sea_green4",
        no_wrap=True,
    )
    table.add_column("Title", style="cyan", overflow="fold")

    for article in articles:
        table.add_row(article["source"]["name"], article["title"])
        # Add a separate row for the URL
        table.add_row(
            f"[green]{article['publishedAt']}[/green]",
            f"[blue underline]{article['url']}[/blue underline]",
        )
        table.add_row("", "")
        table.add_row("", "")

    return table


def main():
    load_dotenv()
    news_feed = NewsFeed()
    console = Console()

    def signal_handler(_sig, _frame):
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Get news articles every 5 minutes
    with Live(
        console=console,
        auto_refresh=False,
        screen=False,
        vertical_overflow="visible",
    ) as live:
        while True:
            try:
                table = get_articles_table(news_feed)
                live.update(table, refresh=True)
                time.sleep(300)  # Refresh every 5 minutes (300 seconds)
            except KeyboardInterrupt:
                logging.debug("Exiting gracefully...")
                break


if __name__ == "__main__":
    main()
