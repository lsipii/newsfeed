# newsfeed
Simple command line news aggregator

# Requirements
- Python 3.9 or higher

# Install dependencies

```bash
python -m pip install -r requirements.txt
```

# Sources configuration

The sources are defined in the `configy.py` file. You can add or remove sources from the list.

```python
news_sources = ["https://example.com/rss", "https://example2.com/rss"]
```

Adding new sources wont probably work out of the box, as the program is designed to work with the default sources. You can modify the `NewsFeed` class to adapt it to the new sources. The news parsing method is classified using the sources domain name.

```python

# Optional configuration

To retrieve the news from the News API, you need to create an account and get an API key. You can do it [here](https://newsapi.org/).

Once you have the API key, you can set it in the `.env` file. (You can copy the `.env.example` file and rename it to `.env`).


```python
NEWSAPI_ORG_KEY=<key>
```

If you don't want to use the News API, you can skip this step and the program will use the default news sources.


# Usage

```bash
python newsfeed.py
```