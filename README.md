# newsfeed
Simple command line news aggregator

# Requirements
- Python 3.10 or higher

# Install dependencies

```bash
python -m pip install .
```

## Voikko (Finnish morphology)

Stem-based grouping (view **3**) uses [Voikko](https://voikko.puimula.org/) for Finnish **base forms** when available. The Python package **`libvoikko`** is listed in `pyproject.toml`, but you also need the **native Voikko library** and a **Finnish morphology dictionary** on the system, or Voikko stays disabled and grouping falls back to Snowball stems only.

**Debian / Ubuntu** (package names may vary slightly):

```bash
sudo apt install libvoikko1 voikko-fi
```

**Fedora**:

```bash
sudo dnf install libvoikko voikko-fi
```

**macOS** (Homebrew):

```bash
brew install voikko libvoikko
```

After installing system packages, reinstall or verify the Python binding:

```bash
python -m pip install .
```

To **force** the app not to use Voikko (Snowball-only grouping):

```bash
export NEWSFEED_DISABLE_VOIKKO=1
```

# News source configuration

The sources are defined in the `config.py` file. You can add or remove sources from the list.

```python
news_sources = ["https://example.com/rss", "https://example2.com/rss"]
```

Adding new sources wont probably work out of the box, as the program is designed to work with the default sources. You can modify the `NewsFeed` class to adapt it to the new sources. The news parsing method is classified using the sources domain name.

## Optional configuration

To retrieve the news from the News API, you need to create an account and get an API key. You can do it [here](https://newsapi.org/).

Once you have the API key, you can set it in the `.env` file. 
(You can copy the `.env.example` file and rename it to `.env`).


```python
NEWSAPI_ORG_KEY=<key>
```

If you don't want to use the News API, you can skip this step and the program will use the default news sources.

## Locale configuration

The `locales` setting in `config.py` controls which language-specific features are enabled. By default, Finnish (`"fi"`) is enabled.

```python
locales = ["fi"]  # Enable Finnish-specific processing (Voikko, etc.)
```

When Finnish is enabled, the app will attempt to load **Voikko** for accurate Finnish lemmatization in stem-based article grouping. If you only want English news or don't have Finnish morphology data installed, you can disable it:

```python
locales = []  # Disable all language-specific features; use Snowball stemmer only
```

## Terminal hyperlinks (OSC 8) and tmux

Article URLs are emitted as **OSC 8** hyperlinks so Ctrl+click (or your terminal’s link action) can open the full URI even when the on-screen label is truncated. **tmux** sits between the app and the real terminal and may drop those sequences unless you enable passthrough and declare hyperlink support.

Add to `~/.tmux.conf`:

```tmux
set -g allow-passthrough on
set -as terminal-features ",*:hyperlinks"
```

Reload the config (`tmux source-file ~/.tmux.conf`) or restart tmux. You need a **recent tmux** (3.2+ for `allow-passthrough`; OSC 8 handling improved further in later releases). If links still fail, confirm the **outer** terminal supports OSC 8 (e.g. Windows Terminal, GNOME Terminal).

# Usage

```bash
python newsfeed.py
# or after installation:
newsfeed
```