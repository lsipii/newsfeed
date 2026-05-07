import bisect
import contextlib
import os
import signal
import sys
import time
from typing import Any, Dict, Generator, List, NamedTuple, Optional, Tuple
from urllib.parse import quote

from blessed import Terminal

from app.NewsFeed import NewsFeed
from app.article_views import (
    VIEW_LABELS,
    ArticleSection,
    ViewMode,
    build_sections,
    filter_articles_by_keyword,
    set_enabled_locales,
)
from app.news_types import NewsAppConfig, NewsArticle
from app.ui_state import (
    MAX_PER_SOURCE_ARTICLES,
    load_ui_state,
    save_ui_state,
    ui_state_file_path,
)

# Fixed chrome height: title, shortcuts, blank line before scroll region
_HEADER_ROWS = 3

# Multi-pane layout
_GUTTER_COLS = 1
# Section heading rule uses ``min(col_width, SECTION_HEADING_RULE_MAX)`` ─ characters.
_SECTION_HEADING_RULE_MAX = 56
_MIN_COL_WIDTH_PANES = 20
# Column toggle (``v``): 1 → 2 → … → N → 1; not limited by terminal width.
_MAX_SPLIT_COLUMNS = 4
_COLUMN_TOGGLE_CYCLE = tuple(range(1, _MAX_SPLIT_COLUMNS + 1))


def _ioctl_winsize_cols_lines(fd: int) -> Optional[Tuple[int, int]]:
    """Return ``(columns, lines)`` from kernel winsize, or ``None`` if unavailable."""
    try:
        import fcntl
        import struct
        import termios

        packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
        rows, cols, _, _ = struct.unpack("HHHH", packed)
        if cols > 0 and rows > 0:
            return (cols, rows)
    except (OSError, ImportError, AttributeError, TypeError, ValueError):
        pass
    return None


def _candidate_tty_dimensions(term: Terminal) -> List[Tuple[int, int]]:
    """Collect size hints from every common source; callers pick the best."""
    out: List[Tuple[int, int]] = []
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            d = _ioctl_winsize_cols_lines(stream.fileno())
            if d:
                out.append(d)
        except (OSError, AttributeError, ValueError):
            pass
    try:
        with open("/dev/tty", "r") as tty:
            d = _ioctl_winsize_cols_lines(tty.fileno())
            if d:
                out.append(d)
    except OSError:
        pass
    for fd in (0, 1, 2):
        try:
            sz = os.get_terminal_size(fd)
            if sz.columns > 0 and sz.lines > 0:
                out.append((sz.columns, sz.lines))
        except OSError:
            pass
    try:
        ec = int(os.environ.get("COLUMNS", "0") or "0")
        el = int(os.environ.get("LINES", "0") or "0")
        if ec > 0 and el > 0:
            out.append((ec, el))
    except ValueError:
        pass
    w = getattr(term, "width", None)
    h = getattr(term, "height", None)
    if w and h:
        out.append((max(1, int(w)), max(1, int(h))))
    return out


def _tty_dimensions(term: Terminal) -> Tuple[int, int]:
    """
    Robust tty geometry for painting and wrapping. On Windows Terminal + WSL,
    ``os.get_terminal_size`` on stdout can lag after resize; ``ioctl(TIOCGWINSZ)``
    on ``/dev/tty`` and other fds often matches the real window. When readings
    disagree, we take the tuple with the **largest column count**.
    """
    cands = _candidate_tty_dimensions(term)
    if cands:
        return max(cands, key=lambda t: (t[0], t[1]))
    try:
        sz = os.get_terminal_size(sys.stdout.fileno())
        if sz.columns > 0 and sz.lines > 0:
            return sz.columns, sz.lines
    except (OSError, ValueError, AttributeError):
        pass
    return (80, 24)


def _tty_columns(term: Terminal) -> int:
    return _tty_dimensions(term)[0]


def _clamp_per_source_limit_input(raw: str, fallback: int) -> int:
    """Parse digits from per-source limit prompt; ``fallback`` if empty or invalid."""
    s = raw.strip()
    if not s:
        return fallback
    try:
        v = int(s)
    except ValueError:
        return fallback
    return max(1, min(v, MAX_PER_SOURCE_ARTICLES))


# OSC 8 hyperlinks: full URI in the OSC payload; visible text may truncate with ``…``.
# ST must be ESC \\ (ECMA-48). **tmux** often drops OSC 8 unless passthrough is enabled
# in ``~/.tmux.conf`` (e.g. ``set -g allow-passthrough on`` and
# ``set -as terminal-features ",*:hyperlinks"``; needs a recent tmux with OSC 8 support).
_OSC8_START = "\033]8;;"
_OSC8_ST = "\033\\"
_OSC8_END = "\033]8;;\033\\"

# VTE / iTerm2 keep URI payloads to ~2083 bytes (see Hyperlinks_in_Terminal_Emulators.md).
_OSC8_MAX_URI_BYTES = 2080


def _osc8_embed_uri(url: str) -> str:
    """
    URI field must be URI-encoded; only bytes 32–126 may appear raw (spec). Encode ``;`` so
    OSC parsers don’t split the sequence; avoid blanket ``quote()`` so links stay shorter.
    """
    if not url:
        return url
    parts: List[str] = []
    for ch in url:
        o = ord(ch)
        if ch == ";":
            parts.append("%3B")
        elif ch == "\\":
            parts.append("%5C")
        elif ch == " ":
            parts.append("%20")
        elif o < 32 or o > 126:
            parts.append(quote(ch, safe=""))
        else:
            parts.append(ch)
    return "".join(parts)


def _line_has_osc8_hyperlink(line: str) -> bool:
    return "\x1b]8;" in line


def _sanitize_viewport_line(line: str) -> str:
    """Keep each viewport row on one terminal line (cursor-addressed painting)."""
    return line.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


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


def _chunk_fixed_width(text: str, width: int) -> List[str]:
    """Hard-wrap ``text`` to fixed character width (for plain URLs that exceed OSC limits)."""
    if width <= 0:
        return [text]
    if not text:
        return [""]
    return [text[i : i + width] for i in range(0, len(text), width)]


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
    embedded = _osc8_embed_uri(url)
    if len(embedded.encode("utf-8")) > _OSC8_MAX_URI_BYTES:
        # VTE ~2083-byte URI cap — plain wrapped lines so the full target is on-screen (OSC
        # cannot carry it without truncation).
        return _chunk_fixed_width(url, width)
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
    sep_len = min(width, _SECTION_HEADING_RULE_MAX)
    lines.append(_secondary_style(term, "─" * sep_len))
    return lines


def _build_body_line_blocks(
    term: Terminal,
    sections: List[ArticleSection],
    width: int,
    *,
    whole_section_one_block: bool = False,
) -> List[List[str]]:
    """
    Logical blocks for column split: each article is a block, but a section heading
    is merged with the first article in that section so the two are never split
    between panes. A heading with no articles remains its own block.

    When ``whole_section_one_block`` (split view + per-source), each source is a
    single block so the column split cannot place the heading in one pane and
    some articles in the other (fallback line-balance used to cut after article 1).
    """
    blocks: List[List[str]] = []
    for section in sections:
        heading = section["heading"]
        articles = section["articles"]
        if heading and articles:
            if whole_section_one_block:
                combined: List[str] = []
                combined.extend(_section_heading_lines(term, heading, width))
                for article in articles:
                    combined.extend(_article_block_lines(term, article, width))
                blocks.append(combined)
            else:
                h = _section_heading_lines(term, heading, width)
                first = _article_block_lines(term, articles[0], width)
                blocks.append(h + first)
                for article in articles[1:]:
                    blocks.append(_article_block_lines(term, article, width))
        elif heading:
            blocks.append(_section_heading_lines(term, heading, width))
        else:
            for article in articles:
                blocks.append(_article_block_lines(term, article, width))
    if not blocks:
        blocks.append([_secondary_style(term, "No articles.")])
    return blocks


def _build_all_body_lines(
    term: Terminal, sections: List[ArticleSection], width: int
) -> List[str]:
    """One continuous column of wrapped lines (same order as single-column view)."""
    lines: List[str] = []
    for block in _build_body_line_blocks(term, sections, width):
        lines.extend(block)
    return lines


def _count_blocks_in_section(
    section: ArticleSection, *, whole_section_one_block: bool = False
) -> int:
    """Must match ``_build_body_line_blocks`` block counts per section."""
    heading = section["heading"]
    articles = section["articles"]
    if heading and articles:
        if whole_section_one_block:
            return 1
        return len(articles)
    if heading:
        return 1
    return len(articles)


def _between_section_split_candidates(
    sections: List[ArticleSection],
    total_blocks: int,
    *,
    whole_section_one_block: bool = False,
) -> List[int]:
    """
    Values ``k`` where ``blocks[:k]`` ends on a section boundary (whole sources only).

    Used so per-source view keeps each source in one column stream — otherwise a
    line-balanced split can place a section heading (e.g. Pelaaja.fi) in the left
    column while the user expects it to start the right column after earlier sources.
    """
    idx = 0
    out: List[int] = []
    for section in sections:
        n = _count_blocks_in_section(
            section, whole_section_one_block=whole_section_one_block
        )
        idx += n
        if n and idx < total_blocks:
            out.append(idx)
    return out


def _pick_split_after_line_balanced(cum: List[int], ideal: int, num_blocks: int) -> int:
    """Original split: minimize line-count imbalance at any block boundary."""
    best_after = 1
    best_diff = abs(cum[1] - ideal)
    for split_after in range(2, num_blocks + 1):
        diff = abs(cum[split_after] - ideal)
        if diff < best_diff:
            best_diff = diff
            best_after = split_after
        elif diff == best_diff and cum[split_after] > cum[best_after]:
            best_after = split_after
    return best_after


def _split_blocks_into_columns(
    blocks: List[List[str]],
    sections: List[ArticleSection],
    *,
    whole_section_one_block: bool = False,
    view_mode: ViewMode = "chronological",
) -> Tuple[List[str], List[str]]:
    """
    Newspaper-style columns: roughly half the lines on the left, half on the right,
    without cutting a block between panes.

    When there are multiple sections, the split is snapped to **section boundaries**
    so each section's blocks stay in one column (important for per-source view).

    **Per-source view + split:** use one block per source (``whole_section_one_block``)
    and split by **source count** (first ``ceil(N/2)`` sources on the left, rest on the
    right). Line-balanced splits could leave the last source on the left with only its
    heading visible at the bottom of the pane while its stories appeared beside the
    top of the right column (paired-row scrolling), which reads like a broken group label.

    Other modes / mismatches fall back to line balance at section boundaries.
    """
    if not blocks:
        return [], []
    sizes = [len(b) for b in blocks]
    n = sum(sizes)
    ideal = (n + 1) // 2
    cum = [0]
    for s in sizes:
        cum.append(cum[-1] + s)

    total_blocks = len(blocks)
    blocks_from_sections = sum(
        _count_blocks_in_section(
            s, whole_section_one_block=whole_section_one_block
        )
        for s in sections
    )
    section_keys = _between_section_split_candidates(
        sections, total_blocks, whole_section_one_block=whole_section_one_block
    )

    ns = len(sections)
    per_source_half = (
        view_mode == "per_source"
        and whole_section_one_block
        and ns >= 1
        and total_blocks == ns
        and blocks_from_sections == total_blocks
    )
    if per_source_half:
        # One block per section: put the first ceil(N/2) sources in the left stream.
        best_after = (ns + 1) // 2
        best_after = max(1, min(best_after, total_blocks))
    elif blocks_from_sections == total_blocks and len(section_keys) >= 1:
        best_after = min(
            section_keys,
            key=lambda k: (abs(cum[k] - ideal), -cum[k]),
        )
    else:
        best_after = _pick_split_after_line_balanced(cum, ideal, total_blocks)

    left: List[str] = []
    right: List[str] = []
    for i in range(best_after):
        left.extend(blocks[i])
    for i in range(best_after, len(blocks)):
        right.extend(blocks[i])
    return left, right


def _pad_columns(left: List[str], right: List[str]) -> Tuple[List[str], List[str]]:
    n = max(len(left), len(right))
    left = left + [""] * (n - len(left))
    right = right + [""] * (n - len(right))
    return left, right


def _column_geometry(tw: int, n_cols: int) -> Tuple[int, int, Tuple[int, ...]]:
    """Column width, gutter (always ``_GUTTER_COLS``), and left-edge x for each pane."""
    gutter = _GUTTER_COLS
    if n_cols < 2:
        return max(_MIN_COL_WIDTH_PANES, tw - 1), gutter, (0,)
    inner = tw - (n_cols - 1) * gutter
    # Do not force ``_MIN_COL_WIDTH_PANES`` here: ``max(20, inner // n)`` can exceed
    # ``inner``, shifting panes 3+ past the right edge so they never appear.
    col_w = max(1, inner // n_cols)
    xs: List[int] = []
    x = 0
    for _ in range(n_cols):
        xs.append(x)
        x += col_w + gutter
    return col_w, gutter, tuple(xs)


def _pad_many_columns(columns: List[List[str]]) -> List[List[str]]:
    h = max((len(c) for c in columns), default=0)
    return [c + [""] * (h - len(c)) for c in columns]


def _per_source_section_column_ranges(num_sections: int, n_cols: int) -> List[Tuple[int, int]]:
    """Section index ranges ``[start, end)`` per column (``n_cols`` columns)."""
    if n_cols <= 1 or num_sections <= 0:
        return [(0, num_sections)]
    base = num_sections // n_cols
    rem = num_sections % n_cols
    ranges: List[Tuple[int, int]] = []
    s = 0
    for col in range(n_cols):
        w = base + (1 if col < rem else 0)
        ranges.append((s, s + w))
        s += w
    return ranges


def _partition_blocks_line_targets(blocks: List[List[str]], n_cols: int) -> List[List[str]]:
    """Split ``blocks`` into ``n_cols`` line streams at block boundaries (approx. equal lines)."""
    if n_cols <= 1:
        flat: List[str] = []
        for b in blocks:
            flat.extend(b)
        return [flat]
    m = len(blocks)
    if m == 0:
        return [[] for _ in range(n_cols)]
    cum = [0]
    for b in blocks:
        cum.append(cum[-1] + len(b))
    total = cum[-1]
    if total == 0:
        return [[] for _ in range(n_cols)]
    splits: List[int] = [0]
    for k in range(1, n_cols):
        target_line = (k * total) // n_cols
        bi = bisect.bisect_left(cum, target_line)
        bi = max(bi, splits[-1] + 1)
        bi = min(bi, m)
        splits.append(bi)
    splits.append(m)
    for i in range(1, len(splits)):
        if splits[i] < splits[i - 1]:
            splits[i] = splits[i - 1]
    out: List[List[str]] = []
    for j in range(n_cols):
        s, e = splits[j], splits[j + 1]
        col: List[str] = []
        for bi in range(s, e):
            col.extend(blocks[bi])
        out.append(col)
    return out


def _partition_blocks_into_column_streams(
    blocks: List[List[str]],
    sections: List[ArticleSection],
    *,
    n_cols: int,
    whole_section_one_block: bool,
    view_mode: ViewMode,
) -> List[List[str]]:
    """Newspaper columns: ``n_cols`` vertical streams, respecting blocks / per-source rules."""
    if n_cols <= 1:
        flat: List[str] = []
        for b in blocks:
            flat.extend(b)
        return [flat]
    if not blocks:
        return [[] for _ in range(n_cols)]

    total_blocks = len(blocks)
    ns = len(sections)
    blocks_from_sections = sum(
        _count_blocks_in_section(s, whole_section_one_block=whole_section_one_block)
        for s in sections
    )
    per_source_ranges = (
        view_mode == "per_source"
        and whole_section_one_block
        and ns >= 1
        and total_blocks == ns
        and blocks_from_sections == total_blocks
    )
    if per_source_ranges:
        ranges = _per_source_section_column_ranges(ns, n_cols)
        columns: List[List[str]] = []
        for s, e in ranges:
            lines: List[str] = []
            for bi in range(s, e):
                lines.extend(blocks[bi])
            columns.append(lines)
        return columns

    if n_cols == 2:
        left, right = _split_blocks_into_columns(
            blocks,
            sections,
            whole_section_one_block=whole_section_one_block,
            view_mode=view_mode,
        )
        return [left, right]

    return _partition_blocks_line_targets(blocks, n_cols)


class BodyLayout(NamedTuple):
    """Single full-width column or N balanced vertical panes."""

    split: bool
    n_cols: int
    single: Optional[List[str]]
    columns: Optional[Tuple[List[str], ...]]
    col_width: int
    gutter: int
    col_xs: Tuple[int, ...]


def _build_body_layout(
    term: Terminal,
    sections: List[ArticleSection],
    column_count: int,
    view_mode: ViewMode,
) -> BodyLayout:
    tw = max(40, _tty_columns(term))
    requested = max(1, min(column_count, _MAX_SPLIT_COLUMNS))
    n_cols = 1 if requested < 2 else requested

    if n_cols < 2:
        w = max(20, tw - 1)
        lines = _build_all_body_lines(term, sections, w)
        return BodyLayout(False, 1, lines, None, w, 0, (0,))

    col_w, gutter, col_xs = _column_geometry(tw, n_cols)
    per_source_atomic = view_mode == "per_source"
    blocks = _build_body_line_blocks(
        term, sections, col_w, whole_section_one_block=per_source_atomic
    )
    streams = _partition_blocks_into_column_streams(
        blocks,
        sections,
        n_cols=n_cols,
        whole_section_one_block=per_source_atomic,
        view_mode=view_mode,
    )
    padded = _pad_many_columns(streams)
    return BodyLayout(True, n_cols, None, tuple(padded), col_w, gutter, col_xs)


def _layout_line_count(layout: BodyLayout) -> int:
    if layout.split and layout.columns:
        return max(len(c) for c in layout.columns)
    return len(layout.single or [])


def _viewport_height(term: Terminal) -> int:
    _tw, th = _tty_dimensions(term)
    return max(1, th - _HEADER_ROWS)


def _clamp_scroll(scroll_ref: List[int], body_line_count: int, viewport: int) -> int:
    max_scroll = max(0, body_line_count - viewport)
    scroll_ref[0] = max(0, min(scroll_ref[0], max_scroll))
    return max_scroll


def _paint_header(
    term: Terminal,
    view_mode: ViewMode,
    *,
    requested_columns: int,
    search_query: str = "",
    search_editing: bool = False,
    search_buffer: str = "",
    per_source_limit: int = 3,
    per_source_limit_editing: bool = False,
    per_source_limit_buffer: str = "",
) -> None:
    """Single-row title + help (clipped) so body row math stays stable when viewport repaints."""
    tw = max(20, _tty_columns(term))
    label = VIEW_LABELS[view_mode]
    title_plain = f"Newsfeed — {label}"
    if view_mode == "per_source":
        title_plain += f" · top {per_source_limit} per source"
    sq = search_query.strip()
    if sq:
        title_plain += f" · filter: {_clip(sq, max(8, tw - len(title_plain) - 14))}"
    print(term.bold(_clip(title_plain, tw)))
    clear_hint = "(c) Clear filter  " if sq else ""
    n_hint = (
        "(n) Per-source count  " if view_mode == "per_source" else ""
    )
    cc = max(1, min(requested_columns, _MAX_SPLIT_COLUMNS))
    # Show 1/1 … 1/N (N = pane count) when cycling (v).
    col_frac = f"1/{cc}"
    help_plain = (
        f"(1) All sources  (2) Per source  (3) {VIEW_LABELS['by_matching_words']}  "
        f"{n_hint}"
        f"(v) columns {col_frac} (press v)  "
        "(/) Search  "
        f"{clear_hint}"
        "(r) Refresh  (q) Quit  ·  ↑↓ / j k  PgUp/PgDn  Home/End  scroll"
    )
    if search_editing:
        prompt_plain = f"Search (live · Enter apply · Esc clear): {search_buffer}"
        try:
            prompt_line = term.bold(term.cyan(_clip(prompt_plain, tw)))
        except Exception:
            prompt_line = term.bold(_clip(prompt_plain, tw))
        print(prompt_line)
    elif per_source_limit_editing:
        hi = MAX_PER_SOURCE_ARTICLES
        prompt_plain = (
            f"Per-source articles 1–{hi} (Enter apply · Esc cancel): {per_source_limit_buffer}"
        )
        try:
            prompt_line = term.bold(term.cyan(_clip(prompt_plain, tw)))
        except Exception:
            prompt_line = term.bold(_clip(prompt_plain, tw))
        print(prompt_line)
    else:
        print(_secondary_style(term, _clip(help_plain, tw)))
    print()


@contextlib.contextmanager
def _viewport_autowrap_disabled(term: Terminal) -> Generator[None, None, None]:
    """
    Disable autowrap (DECAWM) while painting cursor-addressed viewport rows. Long OSC 8
    payloads can otherwise wrap to column 0 on the next line and paint into the header.
    Blessed has no supported ``no_line_wrap`` context manager; dynamic attributes like
    ``term.no_line_wrap`` are :class:`FormattingString`, not a context manager.
    """
    if not getattr(term, "is_a_tty", False):
        yield
        return
    rmam = getattr(term, "exit_am_mode", "") or ""
    sys.stdout.write(str(rmam) if str(rmam).strip() else "\x1b[?7l")
    sys.stdout.flush()
    try:
        yield
    finally:
        # Restore wrap on exit (terminfo ``smam`` is not in blessed's DB; DECAWM on is portable).
        sys.stdout.write("\x1b[?7h")
        sys.stdout.flush()


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
    columns = layout.columns if layout.split else None

    # Long OSC 8 payloads can exceed the terminal line length and wrap to the next
    # row at column 0, which draws into the fixed header. DECAWM off clips instead.
    with _viewport_autowrap_disabled(term):
        for row in range(viewport):
            idx = scroll + row
            y = _HEADER_ROWS + row
            if layout.split and columns is not None:
                try:
                    for ci, col_lines in enumerate(columns):
                        cell = _sanitize_viewport_line(
                            col_lines[idx] if idx < len(col_lines) else ""
                        )
                        cell_h = _line_has_osc8_hyperlink(cell)
                        x = layout.col_xs[ci]
                        if ci == 0:
                            sys.stdout.write(_term_move_xy(term, 0, y))
                            sys.stdout.write(_term_erase_line_full())
                            sys.stdout.write(cell)
                            if not cell_h:
                                if ceol:
                                    sys.stdout.write(ceol)
                                sys.stdout.write(normal)
                        else:
                            if ceol:
                                sys.stdout.write(ceol)
                            sys.stdout.write(normal)
                            sys.stdout.write(_term_move_xy(term, x, y))
                            sys.stdout.write(_term_erase_to_eol(term))
                            sys.stdout.write(cell)
                            if not cell_h:
                                if ceol:
                                    sys.stdout.write(ceol)
                                sys.stdout.write(normal)
                except Exception:
                    for ci, col_lines in enumerate(columns):
                        cell = _sanitize_viewport_line(
                            col_lines[idx] if idx < len(col_lines) else ""
                        )
                        cell_h = _line_has_osc8_hyperlink(cell)
                        x = layout.col_xs[ci]
                        if ci == 0:
                            sys.stdout.write(_term_move_xy(term, 0, y))
                            sys.stdout.write(_term_erase_line_full())
                            sys.stdout.write(cell + (normal if not cell_h else ""))
                        else:
                            sys.stdout.write(_term_move_xy(term, x, y))
                            sys.stdout.write(_term_erase_to_eol(term))
                            sys.stdout.write(cell + (normal if not cell_h else ""))
            else:
                line = _sanitize_viewport_line(
                    single[idx] if single is not None and idx < len(single) else ""
                )
                line_h = _line_has_osc8_hyperlink(line)
                try:
                    sys.stdout.write(_term_move_xy(term, 0, y))
                    sys.stdout.write(_term_erase_line_full())
                    sys.stdout.write(line)
                    if not line_h:
                        if ceol:
                            sys.stdout.write(ceol)
                        sys.stdout.write(normal)
                except Exception:
                    sys.stdout.write(_term_move_xy(term, 0, y))
                    sys.stdout.write(_term_erase_line_full())
                    sys.stdout.write(line + (normal if not line_h else ""))

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
    *,
    requested_columns: int,
    search_query: str = "",
    search_editing: bool = False,
    search_buffer: str = "",
    per_source_limit: int = 3,
    per_source_limit_editing: bool = False,
    per_source_limit_buffer: str = "",
) -> None:
    sys.stdout.write(term.clear())
    sys.stdout.flush()
    _paint_header(
        term,
        view_mode,
        requested_columns=requested_columns,
        search_query=search_query,
        search_editing=search_editing,
        search_buffer=search_buffer,
        per_source_limit=per_source_limit,
        per_source_limit_editing=per_source_limit_editing,
        per_source_limit_buffer=per_source_limit_buffer,
    )
    sys.stdout.flush()
    _paint_body_viewport(term, layout, scroll_ref, stick_bottom_ref)


def refresh_display(
    term: Terminal,
    news_feed: NewsFeed,
    view_mode: ViewMode,
    scroll_ref: List[int],
    stick_bottom_ref: List[bool],
    column_count_ref: List[int],
    paint_state: dict[str, Any],
    search_state: dict[str, Any],
    per_source_limit_ref: List[int],
    per_source_limit_state: dict[str, Any],
) -> None:
    if stick_bottom_ref[0]:
        scroll_ref[0] = 10**9

    query = str(search_state.get("query") or "").strip()
    editing = bool(search_state.get("editing"))
    buffer = str(search_state.get("buffer") or "")

    raw_articles = news_feed.get_latest_articles()
    aid = id(raw_articles)
    # While typing in search mode, filter by buffer live; otherwise use committed query.
    effective_filter = buffer if editing else query
    if effective_filter.strip():
        articles = filter_articles_by_keyword(raw_articles, effective_filter)
    else:
        articles = raw_articles
    filter_label = buffer.strip() if editing else query
    sections = build_sections(
        articles,
        view_mode,
        per_source_limit=per_source_limit_ref[0],
    )
    column_count = max(1, min(column_count_ref[0], _MAX_SPLIT_COLUMNS))
    if column_count_ref[0] != column_count:
        column_count_ref[0] = column_count
    layout = _build_body_layout(term, sections, column_count, view_mode)

    tw_w, tw_h = _tty_dimensions(term)
    hw = (tw_h, tw_w)
    search_digest = (query, editing, buffer)
    ps_lim = per_source_limit_ref[0]
    ps_edit = bool(per_source_limit_state.get("editing"))
    ps_buf = str(per_source_limit_state.get("buffer") or "")
    per_source_digest = (ps_lim, ps_edit, ps_buf)
    need_full = (
        paint_state.get("articles_ref") != aid
        or paint_state.get("view_mode") != view_mode
        or paint_state.get("hw") != hw
        or paint_state.get("column_count") != column_count
        or paint_state.get("search_digest") != search_digest
        or paint_state.get("per_source_digest") != per_source_digest
    )

    if need_full:
        paint_state["articles_ref"] = aid
        paint_state["view_mode"] = view_mode
        paint_state["hw"] = hw
        paint_state["column_count"] = column_count
        paint_state["search_digest"] = search_digest
        paint_state["per_source_digest"] = per_source_digest
        _paint_full(
            term,
            layout,
            view_mode,
            scroll_ref,
            stick_bottom_ref,
            requested_columns=column_count_ref[0],
            search_query=filter_label,
            search_editing=editing,
            search_buffer=buffer,
            per_source_limit=ps_lim,
            per_source_limit_editing=ps_edit,
            per_source_limit_buffer=ps_buf,
        )
    else:
        _paint_body_viewport(term, layout, scroll_ref, stick_bottom_ref)


def execute(config: NewsAppConfig) -> None:
    set_enabled_locales(config["locales"])
    news_feed = NewsFeed(
        config=config,
    )
    term = Terminal()
    saved_ui = load_ui_state()
    _vm = saved_ui.get("view_mode")
    _initial_vm: ViewMode = (
        _vm
        if _vm in ("chronological", "per_source", "by_matching_words")
        else "chronological"
    )
    view_mode_ref: List[ViewMode] = [_initial_vm]
    scroll_ref: List[int] = [10**9]
    stick_bottom_ref: List[bool] = [True]
    def _initial_column_count(saved: Dict[str, Any]) -> int:
        cc = saved.get("column_count")
        if isinstance(cc, int) and cc >= 1:
            return min(cc, _MAX_SPLIT_COLUMNS)
        if saved.get("split_columns") is True:
            return min(2, _MAX_SPLIT_COLUMNS)
        return 1

    column_count_ref: List[int] = [_initial_column_count(saved_ui)]
    paint_state: dict[str, Any] = {}
    search_state: dict[str, Any] = {"query": "", "editing": False, "buffer": ""}

    def _initial_per_source_article_limit(saved: Dict[str, Any]) -> int:
        v = saved.get("per_source_article_limit")
        if isinstance(v, int) and v >= 1:
            return min(v, MAX_PER_SOURCE_ARTICLES)
        if isinstance(v, float) and v.is_integer():
            vi = int(v)
            if vi >= 1:
                return min(vi, MAX_PER_SOURCE_ARTICLES)
        return 3

    per_source_limit_ref: List[int] = [_initial_per_source_article_limit(saved_ui)]
    per_source_limit_state: dict[str, Any] = {"editing": False, "buffer": ""}

    def _feed_fetch_per_source() -> int:
        return max(10, per_source_limit_ref[0])

    def persist_ui_state() -> None:
        save_ui_state(
            {
                "view_mode": view_mode_ref[0],
                "column_count": column_count_ref[0],
                "per_source_article_limit": per_source_limit_ref[0],
            }
        )

    def on_resize(*_args: object) -> None:
        refresh_display(
            term,
            news_feed,
            view_mode_ref[0],
            scroll_ref,
            stick_bottom_ref,
            column_count_ref,
            paint_state,
            search_state,
            per_source_limit_ref,
            per_source_limit_state,
        )

    signal.signal(signal.SIGWINCH, on_resize)

    def on_sigint(_sig: object, _frame: object) -> None:
        persist_ui_state()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_sigint)

    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        news_feed.update(fetch_limit_per_source=_feed_fetch_per_source())
        refresh_display(
            term,
            news_feed,
            view_mode_ref[0],
            scroll_ref,
            stick_bottom_ref,
            column_count_ref,
            paint_state,
            search_state,
            per_source_limit_ref,
            per_source_limit_state,
        )
        if not ui_state_file_path().exists():
            persist_ui_state()
        last_poll = time.monotonic()
        interval = float(config["news_update_frequency_in_seconds"])

        while True:
            key = term.inkey(timeout=0.2)

            if search_state["editing"]:
                if not key:
                    continue
                if key.code == term.KEY_ESCAPE or key == "\x1b":
                    search_state["editing"] = False
                    search_state["buffer"] = ""
                    search_state["query"] = ""
                    scroll_ref[0] = 10**9
                    stick_bottom_ref[0] = True
                    refresh_display(
                        term,
                        news_feed,
                        view_mode_ref[0],
                        scroll_ref,
                        stick_bottom_ref,
                        column_count_ref,
                        paint_state,
                        search_state,
                        per_source_limit_ref,
                        per_source_limit_state,
                    )
                    continue
                if key.code == term.KEY_ENTER or key in ("\r", "\n"):
                    search_state["query"] = search_state["buffer"].strip()
                    search_state["editing"] = False
                    search_state["buffer"] = ""
                    scroll_ref[0] = 10**9
                    stick_bottom_ref[0] = True
                    refresh_display(
                        term,
                        news_feed,
                        view_mode_ref[0],
                        scroll_ref,
                        stick_bottom_ref,
                        column_count_ref,
                        paint_state,
                        search_state,
                        per_source_limit_ref,
                        per_source_limit_state,
                    )
                    continue
                if key.code == term.KEY_BACKSPACE or key in ("\x7f", "\b"):
                    search_state["buffer"] = search_state["buffer"][:-1]
                    refresh_display(
                        term,
                        news_feed,
                        view_mode_ref[0],
                        scroll_ref,
                        stick_bottom_ref,
                        column_count_ref,
                        paint_state,
                        search_state,
                        per_source_limit_ref,
                        per_source_limit_state,
                    )
                    continue
                one = str(key)
                if len(one) == 1 and one.isprintable():
                    search_state["buffer"] += one
                    refresh_display(
                        term,
                        news_feed,
                        view_mode_ref[0],
                        scroll_ref,
                        stick_bottom_ref,
                        column_count_ref,
                        paint_state,
                        search_state,
                        per_source_limit_ref,
                        per_source_limit_state,
                    )
                    continue
                continue

            if per_source_limit_state["editing"]:
                if not key:
                    continue
                if key.code == term.KEY_ESCAPE or key == "\x1b":
                    per_source_limit_state["editing"] = False
                    per_source_limit_state["buffer"] = ""
                    scroll_ref[0] = 10**9
                    stick_bottom_ref[0] = True
                    refresh_display(
                        term,
                        news_feed,
                        view_mode_ref[0],
                        scroll_ref,
                        stick_bottom_ref,
                        column_count_ref,
                        paint_state,
                        search_state,
                        per_source_limit_ref,
                        per_source_limit_state,
                    )
                    continue
                if key.code == term.KEY_ENTER or key in ("\r", "\n"):
                    prev = per_source_limit_ref[0]
                    new_lim = _clamp_per_source_limit_input(
                        per_source_limit_state["buffer"], prev
                    )
                    per_source_limit_ref[0] = new_lim
                    per_source_limit_state["editing"] = False
                    per_source_limit_state["buffer"] = ""
                    scroll_ref[0] = 10**9
                    stick_bottom_ref[0] = True
                    if new_lim > prev:
                        news_feed.update(fetch_limit_per_source=_feed_fetch_per_source())
                    persist_ui_state()
                    refresh_display(
                        term,
                        news_feed,
                        view_mode_ref[0],
                        scroll_ref,
                        stick_bottom_ref,
                        column_count_ref,
                        paint_state,
                        search_state,
                        per_source_limit_ref,
                        per_source_limit_state,
                    )
                    continue
                if key.code == term.KEY_BACKSPACE or key in ("\x7f", "\b"):
                    per_source_limit_state["buffer"] = per_source_limit_state[
                        "buffer"
                    ][:-1]
                    refresh_display(
                        term,
                        news_feed,
                        view_mode_ref[0],
                        scroll_ref,
                        stick_bottom_ref,
                        column_count_ref,
                        paint_state,
                        search_state,
                        per_source_limit_ref,
                        per_source_limit_state,
                    )
                    continue
                one = str(key)
                if len(one) == 1 and one.isdigit():
                    cap_digits = len(str(MAX_PER_SOURCE_ARTICLES))
                    if len(per_source_limit_state["buffer"]) < cap_digits:
                        per_source_limit_state["buffer"] += one
                    refresh_display(
                        term,
                        news_feed,
                        view_mode_ref[0],
                        scroll_ref,
                        stick_bottom_ref,
                        column_count_ref,
                        paint_state,
                        search_state,
                        per_source_limit_ref,
                        per_source_limit_state,
                    )
                    continue
                continue

            if key in ("q", "Q"):
                break
            elif key == "/":
                per_source_limit_state["editing"] = False
                per_source_limit_state["buffer"] = ""
                search_state["editing"] = True
                search_state["buffer"] = search_state["query"]
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )
            elif key in ("c", "C") and search_state["query"]:
                search_state["query"] = ""
                scroll_ref[0] = 10**9
                stick_bottom_ref[0] = True
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )
            elif key in ("v", "V"):
                cur = max(1, min(column_count_ref[0], _MAX_SPLIT_COLUMNS))
                try:
                    idx = _COLUMN_TOGGLE_CYCLE.index(cur)
                except ValueError:
                    idx = 0
                column_count_ref[0] = _COLUMN_TOGGLE_CYCLE[
                    (idx + 1) % len(_COLUMN_TOGGLE_CYCLE)
                ]
                persist_ui_state()
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )
            elif key == "1":
                view_mode_ref[0] = "chronological"
                per_source_limit_state["editing"] = False
                per_source_limit_state["buffer"] = ""
                scroll_ref[0] = 10**9
                stick_bottom_ref[0] = True
                persist_ui_state()
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )
            elif key == "2":
                view_mode_ref[0] = "per_source"
                scroll_ref[0] = 10**9
                stick_bottom_ref[0] = True
                persist_ui_state()
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )
            elif key == "3":
                view_mode_ref[0] = "by_matching_words"
                per_source_limit_state["editing"] = False
                per_source_limit_state["buffer"] = ""
                scroll_ref[0] = 10**9
                stick_bottom_ref[0] = True
                persist_ui_state()
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )
            elif key in ("n", "N") and view_mode_ref[0] == "per_source":
                per_source_limit_state["editing"] = True
                per_source_limit_state["buffer"] = str(per_source_limit_ref[0])
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )
            elif key in ("r", "R"):
                news_feed.update(fetch_limit_per_source=_feed_fetch_per_source())
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )

            elif key.code == term.KEY_UP or key == "k":
                scroll_ref[0] -= 1
                stick_bottom_ref[0] = False
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )
            elif key.code == term.KEY_DOWN or key == "j":
                scroll_ref[0] += 1
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )
            elif key.code == term.KEY_PGUP:
                scroll_ref[0] -= _viewport_height(term)
                stick_bottom_ref[0] = False
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )
            elif key.code == term.KEY_PGDOWN:
                scroll_ref[0] += _viewport_height(term)
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )
            elif key.code == term.KEY_HOME:
                scroll_ref[0] = 0
                stick_bottom_ref[0] = False
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )
            elif key.code == term.KEY_END:
                scroll_ref[0] = 10**9
                stick_bottom_ref[0] = True
                refresh_display(
                    term,
                    news_feed,
                    view_mode_ref[0],
                    scroll_ref,
                    stick_bottom_ref,
                    column_count_ref,
                    paint_state,
                    search_state,
                    per_source_limit_ref,
                    per_source_limit_state,
                )

            now = time.monotonic()
            if now - last_poll >= interval:
                if news_feed.update(fetch_limit_per_source=_feed_fetch_per_source()):
                    refresh_display(
                        term,
                        news_feed,
                        view_mode_ref[0],
                        scroll_ref,
                        stick_bottom_ref,
                        column_count_ref,
                        paint_state,
                        search_state,
                        per_source_limit_ref,
                        per_source_limit_state,
                    )
                last_poll = now

        persist_ui_state()

