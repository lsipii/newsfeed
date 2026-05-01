import signal
import sys
import time
from urllib.parse import quote
from typing import Any, List, NamedTuple, Optional, Tuple

from blessed import Terminal

from app.NewsFeed import NewsFeed
from app.article_views import (
    VIEW_LABELS,
    ArticleSection,
    ViewMode,
    build_sections,
)
from app.news_types import NewsAppConfig, NewsArticle

# Fixed chrome height: title, shortcuts, blank line before scroll region
_HEADER_ROWS = 3

# Two-pane layout when terminal is wide enough
_MIN_TERM_WIDTH_SPLIT = 72
_GUTTER_COLS = 1

# OSC 8 hyperlinks: one logical link per URL (full URI in OSC 8; truncate visible text only).
_OSC8_START = "\033]8;;"
_OSC8_ST = "\033\\"
_OSC8_END = "\033]8;;\033\\"

# Characters safe to leave unescaped inside OSC 8 URI field. ``;`` must be encoded — many
# terminals (xterm.js historically) treat ``;`` as delimiters and truncate the real target,
# so Ctrl+click falls back to the visible underlined text only.
_OSC8_URI_SAFE = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    "-._~:/?#[]@!$&'()*+,=%"
)


def _osc8_embed_uri(url: str) -> str:
    if not url:
        return url
    return quote(url, safe=_OSC8_URI_SAFE)


# ANSI fallbacks when terminfo omits capabilities (move_xy / ceol / cds empty).
_ANSI_CUP = "\033[{row};{col}H"  # 1-based row and column
_ANSI_EL_FULL = "\033[2K"  # erase entire line (cursor column unchanged)
_ANSI_EL_TO_EOL = "\033[0K"  # erase from cursor to end of line (split right pane must use this, not EL full)
_ANSI_ED_BELOW = "\033[0J"  # erase from cursor through end of display


def _term_move_xy(term: Terminal, x: int, y: int) -> str:
    seq = term.move_xy(x, y)
    return seq if seq else _ANSI_CUP.format(row=y + 1, col=x + 1)


def _term_erase_line_full() -> str:
    return _ANSI_EL_FULL


def _term_erase_to_eol(term: Terminal) -> str:
    """Clear from cursor through end of line without touching columns to the left."""
    ceol = getattr(term, "ceol", "") or ""
    return ceol if ceol else _ANSI_EL_TO_EOL


def _term_erase_below(term: Terminal) -> str:
    cds = getattr(term, "cds", "") or getattr(term, "clear_eos", "") or ""
    return cds if cds else _ANSI_ED_BELOW


def _clip(text: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:max_len]
    return text[: max_len - 1] + "…"


def _secondary_style(term: Terminal, text: str) -> str:
    """Secondary/muted text without ``dim`` (often missing from terminfo)."""
    try:
        return term.gray(text)
    except Exception:
        return text


def _hyperlink(url: str, visible: str) -> str:
    """OSC 8 hyperlink; embed URI with ``;``/``\\`` escaped so emulators keep the real target."""
    if not url:
        return visible
    embedded = _osc8_embed_uri(url)
    return f"{_OSC8_START}{embedded}{_OSC8_ST}{visible}{_OSC8_END}"


def _wrap_words_plain(text: str, width: int) -> List[str]:
    """Word-wrap plain text to fixed character width (no hyphenation)."""
    if width <= 0:
        return [""]
    words = text.split()
    if not words:
        return [""]
    lines: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for w in words:
        extra = len(w) + (1 if cur else 0)
        if cur_len + extra > width and cur:
            lines.append(" ".join(cur))
            cur = [w]
            cur_len = len(w)
        else:
            cur_len += extra
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


def _meta_lines(term: Terminal, article: NewsArticle, width: int) -> List[str]:
    plain = f"{article['publishedAt']} - {article['source']['name']}"
    return [term.darkseagreen4(line) for line in _wrap_words_plain(plain, width)]


def _title_lines(term: Terminal, article: NewsArticle, width: int) -> List[str]:
    return [term.green(line) for line in _wrap_words_plain(article["title"], width)]


def _url_lines(_term: Terminal, url: str, width: int) -> List[str]:
    """
    Single-row OSC 8 link so Ctrl+click opens the full URI; visible label may truncate.
    Multi-line URL output breaks many terminals' link hit-testing on continuation rows.
    Do not wrap ``visible`` in SGR — several terminals drop OSC 8 targets when the link
    text contains embedded escape sequences.
    """
    if not url:
        return []
    vis_plain = _clip(url, width)
    return [_hyperlink(url, vis_plain)]


def _article_block_lines(
    term: Terminal, article: NewsArticle, col_width: int
) -> List[str]:
    lines: List[str] = []
    lines.extend(_meta_lines(term, article, col_width))
    lines.extend(_title_lines(term, article, col_width))
    lines.extend(_url_lines(term, article["url"], col_width))
    lines.append("")
    return lines


def _section_heading_lines(term: Terminal, heading: str, width: int) -> List[str]:
    lines: List[str] = []
    lines.append("")
    for ln in _wrap_words_plain(heading, width):
        lines.append(term.bold(term.yellow(ln)))
    sep_len = min(width, 56)
    lines.append(_secondary_style(term, "─" * sep_len))
    return lines


def _build_all_body_lines(
    term: Terminal, sections: List[ArticleSection], width: int
) -> List[str]:
    """One continuous column of wrapped lines (same order as single-column view)."""
    lines: List[str] = []
    for section in sections:
        if section["heading"]:
            lines.extend(_section_heading_lines(term, section["heading"], width))
        for article in section["articles"]:
            lines.extend(_article_block_lines(term, article, width))
    if not lines:
        lines.append(_secondary_style(term, "No articles."))
    return lines


def _split_page_into_columns(lines: List[str]) -> Tuple[List[str], List[str]]:
    """First half of the page on the left, continuation on the right (newspaper flow)."""
    n = len(lines)
    mid = (n + 1) // 2
    return lines[:mid], lines[mid:]


def _pad_columns(left: List[str], right: List[str]) -> Tuple[List[str], List[str]]:
    n = max(len(left), len(right))
    left = left + [""] * (n - len(left))
    right = right + [""] * (n - len(right))
    return left, right


class BodyLayout(NamedTuple):
    """Either single full-width column or balanced left/right panes."""

    split: bool
    single: Optional[List[str]]
    left: Optional[List[str]]
    right: Optional[List[str]]
    col_width: int
    gutter: int
    right_x: int


def _build_body_layout(
    term: Terminal,
    sections: List[ArticleSection],
    split_columns: bool,
) -> BodyLayout:
    tw = max(40, term.width or 80)
    use_split = split_columns and tw >= _MIN_TERM_WIDTH_SPLIT

    if not use_split:
        w = max(20, tw - 1)
        lines = _build_all_body_lines(term, sections, w)
        return BodyLayout(False, lines, None, None, w, 0, 0)

    gutter = _GUTTER_COLS
    inner = tw - gutter
    col_w = max(20, inner // 2)
    all_lines = _build_all_body_lines(term, sections, col_w)
    left, right = _split_page_into_columns(all_lines)
    left, right = _pad_columns(left, right)
    right_x = col_w + gutter
    return BodyLayout(True, None, left, right, col_w, gutter, right_x)


def _layout_line_count(layout: BodyLayout) -> int:
    if layout.split and layout.left is not None:
        return len(layout.left)
    return len(layout.single or [])


def _viewport_height(term: Terminal) -> int:
    return max(1, (term.height or 24) - _HEADER_ROWS)


def _clamp_scroll(scroll_ref: List[int], body_line_count: int, viewport: int) -> int:
    max_scroll = max(0, body_line_count - viewport)
    scroll_ref[0] = max(0, min(scroll_ref[0], max_scroll))
    return max_scroll


def _paint_header(
    term: Terminal,
    view_mode: ViewMode,
    split_columns: bool,
    term_wide_enough_for_split: bool,
) -> None:
    """Single-row title + help (clipped) so body row math stays stable when viewport repaints."""
    tw = max(20, term.width or 80)
    label = VIEW_LABELS[view_mode]
    title_plain = f"Newsfeed — {label}"
    print(term.bold(_clip(title_plain, tw)))
    col_hint = ""
    if split_columns and term_wide_enough_for_split:
        col_hint = "columns on  "
    elif split_columns:
        col_hint = "columns (narrow)  "
    else:
        col_hint = "columns off  "
    help_plain = (
        "(1) All sources  (2) Top 3 per source  (3) Voikko groups  "
        "(v) Split columns  "
        f"{col_hint}"
        "(r) Refresh  (q) Quit  ·  ↑↓ / j k  PgUp/PgDn  Home/End  scroll"
    )
    print(_secondary_style(term, _clip(help_plain, tw)))
    print()


def _paint_body_viewport(
    term: Terminal,
    layout: BodyLayout,
    scroll_ref: List[int],
    stick_bottom_ref: List[bool],
) -> None:
    viewport = _viewport_height(term)
    nlines = _layout_line_count(layout)
    max_scroll = _clamp_scroll(scroll_ref, nlines, viewport)
    scroll = scroll_ref[0]
    stick_bottom_ref[0] = scroll >= max_scroll

    ceol = getattr(term, "ceol", "") or ""

    try:
        normal = term.normal
    except Exception:
        normal = "\033[m"

    single = layout.single if not layout.split else None
    left = layout.left if layout.split else None
    right = layout.right if layout.split else None

    for row in range(viewport):
        idx = scroll + row
        y = _HEADER_ROWS + row
        if layout.split and left is not None and right is not None:
            ll = left[idx] if idx < len(left) else ""
            rr = right[idx] if idx < len(right) else ""
            try:
                sys.stdout.write(_term_move_xy(term, 0, y))
                sys.stdout.write(_term_erase_line_full())
                sys.stdout.write(ll)
                if ceol:
                    sys.stdout.write(ceol)
                sys.stdout.write(normal)
                sys.stdout.write(_term_move_xy(term, layout.right_x, y))
                sys.stdout.write(_term_erase_to_eol(term))
                sys.stdout.write(rr)
                if ceol:
                    sys.stdout.write(ceol)
                sys.stdout.write(normal)
            except Exception:
                sys.stdout.write(_term_move_xy(term, 0, y))
                sys.stdout.write(_term_erase_line_full())
                sys.stdout.write(ll + normal)
                sys.stdout.write(_term_move_xy(term, layout.right_x, y))
                sys.stdout.write(_term_erase_to_eol(term))
                sys.stdout.write(rr + normal)
        else:
            line = single[idx] if single is not None and idx < len(single) else ""
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
    layout: BodyLayout,
    view_mode: ViewMode,
    scroll_ref: List[int],
    stick_bottom_ref: List[bool],
    split_columns: bool,
    term_wide_enough_for_split: bool,
) -> None:
    sys.stdout.write(term.clear())
    sys.stdout.flush()
    _paint_header(term, view_mode, split_columns, term_wide_enough_for_split)
    sys.stdout.flush()
    _paint_body_viewport(term, layout, scroll_ref, stick_bottom_ref)


def refresh_display(
    term: Terminal,
    news_feed: NewsFeed,
    view_mode: ViewMode,
    scroll_ref: List[int],
    stick_bottom_ref: List[bool],
    split_columns_ref: List[bool],
    paint_state: dict[str, Any],
) -> None:
    if stick_bottom_ref[0]:
        scroll_ref[0] = 10**9

    articles = news_feed.get_latest_articles()
    sections = build_sections(articles, view_mode)
    split_columns = split_columns_ref[0]
    layout = _build_body_layout(term, sections, split_columns)

    hw = (term.height or 0, term.width or 0)
    aid = id(articles)
    tw = term.width or 80
    term_wide_enough_for_split = tw >= _MIN_TERM_WIDTH_SPLIT
    need_full = (
        paint_state.get("articles_ref") != aid
        or paint_state.get("view_mode") != view_mode
        or paint_state.get("hw") != hw
        or paint_state.get("split_columns") != split_columns
    )

    if need_full:
        paint_state["articles_ref"] = aid
        paint_state["view_mode"] = view_mode
        paint_state["hw"] = hw
        paint_state["split_columns"] = split_columns
        _paint_full(
            term,
            layout,
            view_mode,
            scroll_ref,
            stick_bottom_ref,
            split_columns,
            term_wide_enough_for_split,
        )
    else:
        _paint_body_viewport(term, layout, scroll_ref, stick_bottom_ref)


def execute(config: NewsAppConfig) -> None:
    news_feed = NewsFeed(
        config=config,
    )
    term = Terminal()
    view_mode: ViewMode = "chronological"
    scroll_ref: List[int] = [10**9]
    stick_bottom_ref: List[bool] = [True]
    split_columns_ref: List[bool] = [False]
    paint_state: dict[str, Any] = {}

    def on_resize(*_args: object) -> None:
        refresh_display(
            term,
            news_feed,
            view_mode,
            scroll_ref,
            stick_bottom_ref,
            split_columns_ref,
            paint_state,
        )

    signal.signal(signal.SIGWINCH, on_resize)

    def on_sigint(_sig: object, _frame: object) -> None:
        sys.exit(0)

    signal.signal(signal.SIGINT, on_sigint)

    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        news_feed.update()
        refresh_display(
            term,
            news_feed,
            view_mode,
            scroll_ref,
            stick_bottom_ref,
            split_columns_ref,
            paint_state,
        )
        last_poll = time.monotonic()
        interval = float(config["news_update_frequency_in_seconds"])

        while True:
            key = term.inkey(timeout=0.2)

            if key in ("q", "Q"):
                break
            elif key in ("v", "V"):
                split_columns_ref[0] = not split_columns_ref[0]
                refresh_display(
                    term,
                    news_feed,
                    view_mode,
                    scroll_ref,
                    stick_bottom_ref,
                    split_columns_ref,
                    paint_state,
                )
            elif key == "1":
                view_mode = "chronological"
                scroll_ref[0] = 10**9
                stick_bottom_ref[0] = True
                refresh_display(
                    term,
                    news_feed,
                    view_mode,
                    scroll_ref,
                    stick_bottom_ref,
                    split_columns_ref,
                    paint_state,
                )
            elif key == "2":
                view_mode = "per_source"
                scroll_ref[0] = 10**9
                stick_bottom_ref[0] = True
                refresh_display(
                    term,
                    news_feed,
                    view_mode,
                    scroll_ref,
                    stick_bottom_ref,
                    split_columns_ref,
                    paint_state,
                )
            elif key == "3":
                view_mode = "by_matching_words"
                scroll_ref[0] = 10**9
                stick_bottom_ref[0] = True
                refresh_display(
                    term,
                    news_feed,
                    view_mode,
                    scroll_ref,
                    stick_bottom_ref,
                    split_columns_ref,
                    paint_state,
                )
            elif key in ("r", "R"):
                news_feed.update()
                refresh_display(
                    term,
                    news_feed,
                    view_mode,
                    scroll_ref,
                    stick_bottom_ref,
                    split_columns_ref,
                    paint_state,
                )

            elif key.code == term.KEY_UP or key == "k":
                scroll_ref[0] -= 1
                stick_bottom_ref[0] = False
                refresh_display(
                    term,
                    news_feed,
                    view_mode,
                    scroll_ref,
                    stick_bottom_ref,
                    split_columns_ref,
                    paint_state,
                )
            elif key.code == term.KEY_DOWN or key == "j":
                scroll_ref[0] += 1
                refresh_display(
                    term,
                    news_feed,
                    view_mode,
                    scroll_ref,
                    stick_bottom_ref,
                    split_columns_ref,
                    paint_state,
                )
            elif key.code == term.KEY_PGUP:
                scroll_ref[0] -= _viewport_height(term)
                stick_bottom_ref[0] = False
                refresh_display(
                    term,
                    news_feed,
                    view_mode,
                    scroll_ref,
                    stick_bottom_ref,
                    split_columns_ref,
                    paint_state,
                )
            elif key.code == term.KEY_PGDOWN:
                scroll_ref[0] += _viewport_height(term)
                refresh_display(
                    term,
                    news_feed,
                    view_mode,
                    scroll_ref,
                    stick_bottom_ref,
                    split_columns_ref,
                    paint_state,
                )
            elif key.code == term.KEY_HOME:
                scroll_ref[0] = 0
                stick_bottom_ref[0] = False
                refresh_display(
                    term,
                    news_feed,
                    view_mode,
                    scroll_ref,
                    stick_bottom_ref,
                    split_columns_ref,
                    paint_state,
                )
            elif key.code == term.KEY_END:
                scroll_ref[0] = 10**9
                stick_bottom_ref[0] = True
                refresh_display(
                    term,
                    news_feed,
                    view_mode,
                    scroll_ref,
                    stick_bottom_ref,
                    split_columns_ref,
                    paint_state,
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
                        split_columns_ref,
                        paint_state,
                    )
                last_poll = now
