from dotenv import load_dotenv
import signal
import sys
import logging
import threading
from math import floor

from rich.live import Live
from rich.console import Console
from rich.table import Table

from app.NewsFeed import NewsFeed
from config import news_sources


def get_articles_table(news_feed: NewsFeed):
    articles = news_feed.get_latest_articles()

    table = Table(box=None)
    (_console_width, console_height) = Console().size
    max_rows = console_height
    article_rows = 4
    max_articles = floor(max_rows / article_rows)

    # Pick the last N articles
    print_articles = articles[-max_articles:]

    table.add_column(style="dark_sea_green4", no_wrap=False, overflow="fold")

    for article in print_articles:
        table.add_row(
            f"[green]{article['publishedAt']}[/green] - {article['source']['name']}"
        )
        table.add_row(f"[bold]{article['title']}[/bold]")
        table.add_row(
            f"[dark_sea_green underline]{article['url']}[/dark_sea_green underline]", ""
        )
        table.add_row("", "")

    return table


def main():
    load_dotenv()
    news_feed = NewsFeed(news_sources=news_sources, update_frequency_in_seconds=300)
    console = Console()

    # Start the feed scheduler in a separate thread
    scheduler_thread = threading.Thread(target=news_feed.start_feed_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()

    def signal_handler(_sig, _frame):
        logging.info("Stopping the news feed...")
        news_feed.stop_feed_scheduler()
        scheduler_thread.join()  # Wait for the scheduler thread to finish
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Get news articles every 5 minutes
    with Live(
        console=console,
        auto_refresh=True,
        screen=True,
    ) as live:
        while True:
            try:
                table = get_articles_table(news_feed)
                live.update(table)
            except KeyboardInterrupt:
                logging.debug("Exiting gracefully...")
                break


if __name__ == "__main__":
    main()
