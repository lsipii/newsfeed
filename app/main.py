import signal
import sys
from dotenv import load_dotenv
import time
from blessed import Terminal
from app.NewsFeed import NewsFeed
from config import news_sources, news_update_frequency_in_seconds


def render_articles(term: Terminal, news_feed: NewsFeed):
    articles = news_feed.get_latest_articles()

    print(term.move_y(term.height - 1))
    for article in articles:
        print(
            f"{term.darkseagreen4(article['publishedAt'])} - {term.darkseagreen4(article['source']['name'])}"
        )

        print(term.green(article["title"]))
        print(term.gray(article["url"]))
        print(term.move_y(term.height - 1))


def main():
    load_dotenv()
    news_feed = NewsFeed(
        news_sources=news_sources,
    )
    term = Terminal()

    def on_resize(*args):
        render_articles(term, news_feed)

    signal.signal(signal.SIGWINCH, on_resize)

    def on_sigint(_sig, _frame):
        sys.exit(0)

    signal.signal(signal.SIGINT, on_sigint)

    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        print(term.clear())
        print(term.move_y(term.height - 1))

        while True:
            has_updates = news_feed.update()
            if has_updates:
                render_articles(term, news_feed)
            time.sleep(news_update_frequency_in_seconds)


if __name__ == "__main__":
    main()
