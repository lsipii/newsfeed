import signal
import sys
import time
from typing import Any, List

from blessed import Terminal

from app.NewsFeed import NewsFeed
from app.article_views import (
    VIEW_LABELS,
    ArticleSection,
    ViewMode,
    build_sections,
)
from app.news_types import NewsAppConfig

# Fixed chrome height: title, shortcuts, blank line before scroll region
_HEADER_ROWS = 3

# ANSI fallbacks when terminfo omits capabilities (move_xy / ceol / cds empty).
_ANSI_CUP = "\033[{row};{col}H"  # 1-based row and column
_ANSI_EL_FULL = "\033[2K"  # erase entire line (cursor column unchanged)
_ANSI_ED_BELOW = "\033[0J"  # erase from cursor through end of display


def _term_move_xy(term: Terminal, x: int, y: int) -> str:
    seq = term.move_xy(x, y)
    return seq if seq else _ANSI_CUP.format(row=y + 1, col=x + 1)


def _term_erase_line_full() -> str:
    return _ANSI_EL_FULL


def _term_erase_below(term: Terminal) -> str:
    cds = getattr(term, "cds", "") or getattr(term, "clear_eos", "") or ""
    return cds if cds else _ANSI_ED_BELOW


def _secondary_style(term: Terminal, text: str) -> str:
    """Secondary/muted text without ``dim`` (often missing from terminfo)."""
    try:
        return term.gray(text)
    except Exception:
        return text


def _clip(text: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:max_len]
    return text[: max_len - 1] + "…"


def _build_body_lines(
    term: Terminal,
    sections: List[ArticleSection],
) -> List[str]:
    w = max(20, (term.width or 80) - 1)
    lines: List[str] = []

    for section in sections:
        if section["heading"]:
            lines.append("")
            lines.append(term.bold(term.yellow(_clip(section["heading"], w))))
            line_len = min(term.width or 80, 56)
            lines.append(_secondary_style(term, "─" * line_len))

        for article in section["articles"]:
            meta = _clip(
                f"{article['publishedAt']} - {article['source']['name']}",
                w,
            )
            lines.append(term.darkseagreen4(meta))
            lines.append(term.green(_clip(article["title"], w)))
            lines.append(term.gray(_clip(article["url"], w)))
            lines.append("")

    if not lines:
        lines.append(_secondary_style(term, "No articles."))

    return lines


def _viewport_height(term: Terminal) -> int:
    return max(1, (term.height or 24) - _HEADER_ROWS)


def _clamp_scroll(scroll_ref: List[int], body_line_count: int, viewport: int) -> int:
    max_scroll = max(0, body_line_count - viewport)
    scroll_ref[0] = max(0, min(scroll_ref[0], max_scroll))
    return max_scroll


def _paint_header(term: Terminal, view_mode: ViewMode) -> None:
    """Single-row title + help (clipped) so body row math stays stable when viewport repaints."""
    tw = max(20, term.width or 80)
    label = VIEW_LABELS[view_mode]
    title_plain = f"Newsfeed — {label}"
    print(term.bold(_clip(title_plain, tw)))
    help_plain = (
        "(1) All sources  (2) Top 3 per source  (3) Voikko groups  "
        "(r) Refresh  (q) Quit  ·  ↑↓ / j k  PgUp/PgDn  Home/End  scroll"
    )
    print(_secondary_style(term, _clip(help_plain, tw)))
    print()


def _paint_body_viewport(
    term: Terminal,
    body_lines: List[str],
    scroll_ref: List[int],
    stick_bottom_ref: List[bool],
) -> None:
    viewport = _viewport_height(term)
    max_scroll = _clamp_scroll(scroll_ref, len(body_lines), viewport)
    scroll = scroll_ref[0]
    stick_bottom_ref[0] = scroll >= max_scroll

    ceol = getattr(term, "ceol", "") or ""

    try:
        normal = term.normal
    except Exception:
        normal = "\033[m"

    for row in range(viewport):
        idx = scroll + row
        line = body_lines[idx] if idx < len(body_lines) else ""
        y = _HEADER_ROWS + row
        try:
            sys.stdout.write(_term_move_xy(term, 0, y))
            sys.stdout.write(_term_erase_line_full())
            sys.stdout.write(line)
            if ceol:
                sys.stdout.write(ceol)
            sys.stdout.write(normal)
        except Exception:
            sys.stdout.write(_term_move_xy(term, 0, y))
            sys.stdout.write(_term_erase_line_full())
            sys.stdout.write(line + normal)

    below = _term_erase_below(term)
    try:
        sys.stdout.write(_term_move_xy(term, 0, _HEADER_ROWS + viewport) + below)
    except Exception:
        sys.stdout.write(_term_move_xy(term, 0, _HEADER_ROWS + viewport) + _ANSI_ED_BELOW)

    sys.stdout.flush()


def _paint_full(
    term: Terminal,
    body_lines: List[str],
    view_mode: ViewMode,
    scroll_ref: List[int],
    stick_bottom_ref: List[bool],
) -> None:
    sys.stdout.write(term.clear())
    sys.stdout.flush()
    _paint_header(term, view_mode)
    sys.stdout.flush()
    _paint_body_viewport(term, body_lines, scroll_ref, stick_bottom_ref)


def refresh_display(
    term: Terminal,
    news_feed: NewsFeed,
    view_mode: ViewMode,
    scroll_ref: List[int],
    stick_bottom_ref: List[bool],
    paint_state: dict[str, Any],
) -> None:
    if stick_bottom_ref[0]:
        scroll_ref[0] = 10**9

    articles = news_feed.get_latest_articles()
    sections = build_sections(articles, view_mode)
    body_lines = _build_body_lines(term, sections)

    hw = (term.height or 0, term.width or 0)
    aid = id(articles)
    need_full = (
        paint_state.get("articles_ref") != aid
        or paint_state.get("view_mode") != view_mode
        or paint_state.get("hw") != hw
    )

    if need_full:
        paint_state["articles_ref"] = aid
        paint_state["view_mode"] = view_mode
        paint_state["hw"] = hw
        _paint_full(term, body_lines, view_mode, scroll_ref, stick_bottom_ref)
    else:
        _paint_body_viewport(term, body_lines, scroll_ref, stick_bottom_ref)


def execute(config: NewsAppConfig) -> None:
    news_feed = NewsFeed(
        config=config,
    )
    term = Terminal()
    view_mode: ViewMode = "chronological"
    scroll_ref: List[int] = [10**9]
    stick_bottom_ref: List[bool] = [True]
    paint_state: dict[str, Any] = {}

    def on_resize(*_args: object) -> None:
        refresh_display(
            term, news_feed, view_mode, scroll_ref, stick_bottom_ref, paint_state
        )

    signal.signal(signal.SIGWINCH, on_resize)

    def on_sigint(_sig: object, _frame: object) -> None:
        sys.exit(0)

    signal.signal(signal.SIGINT, on_sigint)

    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        news_feed.update()
        refresh_display(
            term, news_feed, view_mode, scroll_ref, stick_bottom_ref, paint_state
        )
        last_poll = time.monotonic()
        interval = float(config["news_update_frequency_in_seconds"])

        while True:
            key = term.inkey(timeout=0.2)

            if key in ("q", "Q"):
                break
            if key == "1":
                view_mode = "chronological"
                scroll_ref[0] = 10**9
                stick_bottom_ref[0] = True
                refresh_display(
                    term, news_feed, view_mode, scroll_ref, stick_bottom_ref, paint_state
                )
            elif key == "2":
                view_mode = "per_source"
                scroll_ref[0] = 10**9
                stick_bottom_ref[0] = True
                refresh_display(
                    term, news_feed, view_mode, scroll_ref, stick_bottom_ref, paint_state
                )
            elif key == "3":
                view_mode = "by_matching_words"
                scroll_ref[0] = 10**9
                stick_bottom_ref[0] = True
                refresh_display(
                    term, news_feed, view_mode, scroll_ref, stick_bottom_ref, paint_state
                )
            elif key in ("r", "R"):
                news_feed.update()
                refresh_display(
                    term, news_feed, view_mode, scroll_ref, stick_bottom_ref, paint_state
                )

            elif key.code == term.KEY_UP or key == "k":
                scroll_ref[0] -= 1
                stick_bottom_ref[0] = False
                refresh_display(
                    term, news_feed, view_mode, scroll_ref, stick_bottom_ref, paint_state
                )
            elif key.code == term.KEY_DOWN or key == "j":
                scroll_ref[0] += 1
                refresh_display(
                    term, news_feed, view_mode, scroll_ref, stick_bottom_ref, paint_state
                )
            elif key.code == term.KEY_PGUP:
                scroll_ref[0] -= _viewport_height(term)
                stick_bottom_ref[0] = False
                refresh_display(
                    term, news_feed, view_mode, scroll_ref, stick_bottom_ref, paint_state
                )
            elif key.code == term.KEY_PGDOWN:
                scroll_ref[0] += _viewport_height(term)
                refresh_display(
                    term, news_feed, view_mode, scroll_ref, stick_bottom_ref, paint_state
                )
            elif key.code == term.KEY_HOME:
                scroll_ref[0] = 0
                stick_bottom_ref[0] = False
                refresh_display(
                    term, news_feed, view_mode, scroll_ref, stick_bottom_ref, paint_state
                )
            elif key.code == term.KEY_END:
                scroll_ref[0] = 10**9
                stick_bottom_ref[0] = True
                refresh_display(
                    term, news_feed, view_mode, scroll_ref, stick_bottom_ref, paint_state
                )

            now = time.monotonic()
            if now - last_poll >= interval:
                if news_feed.update():
                    refresh_display(
                        term,
                        news_feed,
                        view_mode,
                        scroll_ref,
                        stick_bottom_ref,
                        paint_state,
                    )
                last_poll = now
