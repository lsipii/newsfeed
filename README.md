# newsfeed
Simple command line news aggregator

# Requirements
- Python 3.10 or higher

# Install (recommended: uv)

This project is packaged with `pyproject.toml` and exposes a CLI command named `newsfeed`.
The easiest way to install it without touching system Python is `uv tool install`, which creates an isolated environment automatically.

1. Install `uv` (if not installed):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. Ensure your local bin directory is on `PATH` (usually `~/.local/bin`):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

3. Install `newsfeed` from this repository:

```bash
uv tool install .
```

4. Run it:

```bash
newsfeed
```

If you update this repo and want to reinstall the latest local code:

```bash
uv tool uninstall newsfeed
uv tool install --force .
```

Use an **absolute path** to the clone if you are not sitting in the repo root (`uv tool install --force /home/you/src/newsfeed`).

### Editable install (development)

A normal `uv tool install` / `make reinstall` **copies a built wheel** into `~/.local/share/uv/tools/`. You must **reinstall after every change** to the code, or you still run the old copy. The **`make reinstall`** and **`make uninstall`** targets also **delete** `$(uv tool dir)/newsfeed` so no files from a previous install remain.

To run **this clone** directly (no reinstall after edits), use an **editable** tool install from the repo root:

```bash
uv tool install --force --editable .
# or: make install-editable
# full refresh: make reinstall-editable
```

That is not the same workflow as `make reinstall`; use **one** style for day-to-day work: editable while developing, or snapshot `reinstall` when you want a self-contained install.

### Troubleshooting: `Missing required config keys` (date_time_format, locales, …)

If the traceback shows **`Missing required config keys:`** and **does not** mention **`after merging with defaults`**, the `newsfeed` on your `PATH` is still an **old install** (before `config.json` was merged with `config.default.json`). Fix:

```bash
uv tool uninstall newsfeed
cd /path/to/your/newsfeed
uv tool install --force .
```

Then run `newsfeed` again. The project version in `pyproject.toml` is bumped when config behaviour changes; **`uv tool install --force`** picks up a fresh wheel from your clone.

# Install dependencies (development)

```bash
uv sync
```

## Similar content grouping (view 3)

The third view builds clusters from overlapping **English Snowball** terms on **title, description, and article body** only—source name, URL, and author are ignored so outlets do not steer clusters. Edges require a fixed minimum number of shared terms after dropping very frequent words; groups are large cliques in that graph (not long weak chains). There is no UI threshold control.

# News source configuration

**Template:** `newsfeed_config/config.default.json` is shipped in the package (edit only if you want to change the defaults committed for everyone).

**Runtime config:** on each startup the app loads **`config.default.json`** (from the package), then overlays **`config.json`**. Any **primary key** you omit from `config.json` keeps the value from the default file—so you can keep a small file (for example only `news_sources`) and still get `date_time_format`, `locales`, etc. from defaults. Keys you **do** set in `config.json` replace the defaults entirely.

The first time it runs, **`config.json` is created** by copying `config.default.json`; you can delete keys from it afterward if you prefer defaults for those fields. Reinstalling the `uv` tool does **not** remove your `config.json`.

### Where `config.json` is stored

**Local checkout (development)** — when you run from this repo (e.g. `uv run python newsfeed.py`) and `config.py` is **not** loaded from an installed wheel under `site-packages`:

| | |
|---|---|
| **Path** | **`newsfeed_config/config.json`** — same folder as `config.default.json`, at the root of the repository. |
| **Git** | Ignored (machine-local). Created automatically on first run if missing. |

Example absolute path after cloning:

```text
/path/to/newsfeed/newsfeed_config/config.json
```

**Installed CLI** (`uv tool install …`) — the wheel lives under `site-packages`, so the app uses your **user config directory** instead:

| OS | Typical path |
|----|----------------|
| Linux (XDG) | `~/.config/newsfeed/config.json`, or `$XDG_CONFIG_HOME/newsfeed/config.json` if set |
| macOS | `~/Library/Application Support/newsfeed/config.json` |
| Windows | `%LOCALAPPDATA%\newsfeed\config.json` |

Paths follow [platformdirs](https://pypi.org/project/platformdirs/) (`user_config_dir("newsfeed")`).

**Custom directory** — set **`NEWSFEED_CONFIG_DIR`** or **`NEWSFEED_CONFIG`** to a folder. The app reads **`{that folder}/config.json`** (seeded from the template on first run if missing).

You can set either env variable in a `.env` file (the CLI loads dotenv on startup).

You can add or remove sources by editing `news_sources` in **`config.json`**. Omit other keys to keep using the packaged defaults for those settings.

```json
{
	"news_sources": [
		"https://example.com/rss",
		"https://example2.com/rss"
	]
}
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

`locales` is a **required** key: a non-empty array of language tags. It selects **stopword and meta-word packs** for search and similar-content grouping (view **3**). Each tag’s base language must be one of **`fi`**, **`sv`**, or **`en`** (unknown tags are ignored, but at least one supported base must remain). English core/boiler lists are always merged on top of that.

```json
{
	"locales": ["sv"]
}
```

```json
{
	"locales": ["fi"]
}
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
newsfeed
# local checkout without tool install:
uv run python newsfeed.py
```