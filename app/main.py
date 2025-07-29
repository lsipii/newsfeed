from dotenv import load_dotenv
import signal
import sys
import logging
import time
from math import floor

from rich.live import Live
from rich.console import Console
from rich.table import Table

from app.NewsFeed import NewsFeed
from config import news_sources


def get_articles_table(max_articles: int, news_feed: NewsFeed):
    articles = news_feed.get_latest_articles()

    table = Table(box=None)

    # Pick the last N articles
    print_articles = articles[-max_articles:]

    table.add_column(style="dark_sea_green4", no_wrap=False, overflow="fold")

    for article in print_articles:
        table.add_row(
            f"[green]{article['publishedAt']}[/green] - {article['source']['name']}"
        )
        table.add_row(f"[bold]{article['title']}[/bold]")
        table.add_row(f"[grey35]{article['url']}[/grey35]", "")
        table.add_row("", "")

    return table


def main():
    load_dotenv()
    update_frequency_in_seconds = 300
    news_feed = NewsFeed(
        news_sources=news_sources,
    )
    console = Console()

    def signal_handler(_sig, _frame):
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    with Live(
        console=console, auto_refresh=False, screen=False, vertical_overflow="visible"
    ) as live:
        elapsed_time = 0
        reference_console_width, reference_console_height = console.size

        while True:
            current_console_width, current_console_height = console.size
            try:
                refresh_interval_elapsed = (
                    elapsed_time == 0 or elapsed_time >= update_frequency_in_seconds
                )
                console_resized = (
                    reference_console_width != current_console_width
                    or reference_console_height != current_console_height
                )

                if refresh_interval_elapsed or console_resized:
                    if console_resized:
                        reference_console_width, reference_console_height = (
                            current_console_width,
                            current_console_height,
                        )
                    if refresh_interval_elapsed:
                        elapsed_time = 0

                    # Calculate the number of articles that can be displayed
                    max_rows = reference_console_height - 2
                    article_rows = 4
                    max_articles = floor(max_rows / article_rows)

                    # Get the latest articles
                    table = get_articles_table(max_articles, news_feed)
                    live.update(table, refresh=True)

                time.sleep(1)
                elapsed_time += 1
            except KeyboardInterrupt:
                logging.debug("Exiting gracefully...")
                break


if __name__ == "__main__":
    main()
