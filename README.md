# newsfeed
Simple command line news aggregator

# Install requirements

```bash
python -m pip install -r requirements.txt
```

# Optional configuration

To retrieve the news from the News API, you need to create an account and get an API key. You can do it [here](https://newsapi.org/).

Once you have the API key, you can set it in the `.env` file. (You can copy the `.env.example` file and rename it to `.env`).

If you don't want to use the News API, you can skip this step and the program will use the default news sources.

```python
NEWSFEED_API_KEY=<key>
```

# Usage

```bash
python newsfeed.py
```