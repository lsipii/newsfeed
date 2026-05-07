import html
import math
import re
from collections import defaultdict
from typing import Dict, List, Literal, Set, TypedDict

from nltk.stem.snowball import SnowballStemmer

from app.news_types import NewsArticle
from app.text_parsers import filter_metadata_keywords, is_uri_like_metadata_token

_EN_STEMMER = SnowballStemmer("english")
_FI_STEMMER = SnowballStemmer("finnish")
_SV_STEMMER = SnowballStemmer("swedish")

ViewMode = Literal["chronological", "per_source", "by_matching_words"]

_MIN_TOKEN_LEN = 4
# Drop terms that appear in too many documents before linking (reduces generic bridges).
_MAX_TERM_DOC_FRACTION = 0.22
# Minimum shared normalized terms for an edge in similar-content grouping (mode 3); fixed (no UI).
_MIN_SHARED_TERMS_LINK = 2
# Drop longer term if it only extends a shorter one (residual affix noise).
_MAX_PREFIX_INFLECTION_DELTA = 5

# RSS/API snippets often ship `<a href=...>` etc.; strip before tokenization.
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html_for_text_analysis(raw: str) -> str:
    """
    Remove simple HTML tags and decode entities so word overlap and search
    match prose, not markup (href, class names, etc.).
    """
    if not raw:
        return ""
    text = html.unescape(raw)
    text = _HTML_TAG_RE.sub(" ", text)
    return " ".join(text.split())


def _article_search_haystack(a: NewsArticle) -> str:
    """Text used for keyword search (title, body fields, source name, author)."""
    src = a.get("source") or {}
    parts = [
        _strip_html_for_text_analysis(a.get("title") or ""),
        _strip_html_for_text_analysis(a.get("description") or ""),
        _strip_html_for_text_analysis(a.get("content") or ""),
        _strip_html_for_text_analysis(src.get("name") or ""),
        _strip_html_for_text_analysis(a.get("author") or ""),
    ]
    for s in a.get("subjects") or []:
        parts.append(_strip_html_for_text_analysis(s))
    for k in filter_metadata_keywords(a.get("keywords")):
        parts.append(_strip_html_for_text_analysis(k))
    return " ".join(parts).lower()


def _article_primary_grouping_text(a: NewsArticle) -> str:
    """RSS ``category`` / subject lines only — primary similar-content edges (no keyword metadata)."""
    parts: List[str] = []
    for s in a.get("subjects") or []:
        st = _strip_html_for_text_analysis(s)
        if st and not is_uri_like_metadata_token(st):
            parts.append(st)
    return " ".join(parts).lower()


def _article_keyword_meta_text(a: NewsArticle) -> str:
    """Non-URI keyword tags — unioned with description in the second attachment pass only."""
    parts = [
        _strip_html_for_text_analysis(k) for k in filter_metadata_keywords(a.get("keywords"))
    ]
    return " ".join(parts).lower()


def _article_title_description_text_only(a: NewsArticle) -> str:
    """Title + description — keyword shelves (no subjects/keywords reuse)."""
    parts = [
        _strip_html_for_text_analysis(a.get("title") or ""),
        _strip_html_for_text_analysis(a.get("description") or ""),
    ]
    return " ".join(parts).lower()


def _article_description_text(a: NewsArticle) -> str:
    """Snippet only — combined with cleaned keywords for second-pass attachment to clusters."""
    return _strip_html_for_text_analysis(a.get("description") or "").lower()


# Finnish Snowball stems (length ≥ ``_FI_META_STEM_MIN``) of meta / template words — any
# inflected surface with the same stem is dropped before overlap (not full morphology).
_FI_META_STEM_MIN = 6
_FI_META_STEM_SOURCES = frozenset(
    {
        "artikkeli",
        "artikkelin",
        "artikkelista",
        "artikkeleista",
        "artikkeleissa",
        "artikkelit",
        "julkaistiin",
        "julkaistu",
        "julkaisivat",
        "julkaisemaan",
        "ensimmäinen",
        "ensimmäisen",
        "ensimmäiseen",
        "ensimmäisellä",
        "ensimmäisestä",
        "ensimmäisiksi",
        "ensimmäiset",
        "viimeinen",
        "viimeisen",
        "viimeiseen",
        "viimeisellä",
        "viimeisestä",
        "viimeisimmät",
        "uutisoi",
        "uutisoitiin",
        "uutisoivat",
    }
)
_FI_META_STEMS: frozenset[str] = frozenset(
    sx
    for w in _FI_META_STEM_SOURCES
    for sx in (_FI_STEMMER.stem(w),)
    if len(sx) >= _FI_META_STEM_MIN
)

# Per-locale stopword packs (merged with English core/boiler via ``set_enabled_locales``).
_STOPWORDS_EN_CORE = frozenset(
    {
        "that",
        "this",
        "with",
        "from",
        "have",
        "been",
        "were",
        "will",
        "would",
        "could",
        "should",
        "their",
        "there",
        "what",
        "when",
        "where",
        "which",
        "while",
        "about",
        "after",
        "before",
        "other",
        "some",
        "such",
        "than",
        "them",
        "then",
        "these",
        "those",
        "very",
        "just",
        "also",
        "into",
        "more",
        "most",
        "only",
        "over",
        "here",
        "make",
        "like",
        "back",
        "even",
        "much",
        "well",
        "news",
        "says",
        "said",
        "year",
        "years",
        "people",
        "first",
        "last",
        "http",
        "https",
    }
)

_STOPWORDS_EN_BOILER = frozenset(
    {
        "article",
        "articles",
        "according",
        "published",
        "publishing",
        "updated",
        "updates",
        "subscribe",
        "subscription",
        "editorial",
        "readers",
        "reader",
        "reports",
        "reported",
        "reporting",
        "breaking",
        "coverage",
        "exclusive",
    }
)

_STOPWORDS_FI = frozenset(
    {
        "että",
        "kun",
        "kuin",
        "mutta",
        "tai",
        "voi",
        "oli",
        "ovat",
        "olla",
        "joita",
        "joka",
        "jonka",
        "jossa",
        "josta",
        "jotka",
        "kanssa",
        "koska",
        "myös",
        "ne",
        "niin",
        "näin",
        "olen",
        "olet",
        "paitsi",
        "sekä",
        "se",
        "sen",
        "siitä",
        "siihen",
        "siinä",
        "sitä",
        "te",
        "teidän",
        "teille",
        "teitä",
        "tämä",
        "tämän",
        "tässä",
        "tähän",
        "tätä",
        "vaan",
        "vain",
        "vielä",
        "voidaan",
        "vuonna",
        "vuoden",
        "yle",
        "uusi",
        "uutiset",
        "uutisen",
        "nyt",
        "ihmiset",
        "koko",
        "uuden",
        "uutta",
        "kaksi",
        "kolme",
        "neljä",
        "viisi",
        "kuusi",
        "seitsemän",
        "kahdeksan",
        "yhdeksän",
        "kymmenen",
        "kerran",
        "yksi",
        "ensimmäistä",
        "ensimmäisenä",
        "viime",
        "viimeksi",
        "julkaistaan",
        "julkaisee",
        "julkaisi",
        "kerrotaan",
        "kertoo",
        "kertoi",
        "kertovat",
        "sanoo",
        "sanoi",
        "sanoivat",
        "totoi",
        "toteaa",
        "ilmoitti",
        "ilmoittaa",
        "ilmoitettiin",
        "päivitetty",
        "päivitetään",
        "päivitettiin",
        "lukeneet",
        "luettu",
        "lukeaksesi",
        "lue",
        "kirjoitti",
        "kirjoittaa",
        "kirjoittanut",
        "kommentoi",
        "kommentoida",
        "tilaajille",
        "tilaajana",
    }
)

_STOPWORDS_SV = frozenset(
    {
        "att",
        "eller",
        "som",
        "från",
        "inte",
        "också",
        "efter",
        "innan",
        "under",
        "över",
        "genom",
        "utan",
        "mellan",
        "när",
        "där",
        "här",
        "bara",
        "mycket",
        "lite",
        "mer",
        "mest",
        "sedan",
        "redan",
        "alltid",
        "aldrig",
        "kunde",
        "skulle",
        "kunnat",
        "måste",
        "vill",
        "välja",
        "blivit",
        "varit",
        "vara",
        "sig",
        "sitt",
        "sina",
        "dem",
        "den",
        "det",
        "denna",
        "detta",
        "dessa",
        "vilken",
        "vilket",
        "vilka",
        "vem",
        "vad",
        "hur",
        "varför",
        "någon",
        "något",
        "några",
        "ingen",
        "inget",
        "inga",
        "gärna",
        "artikel",
        "artikeln",
        "artiklar",
        "publicerades",
        "publiceras",
        "publicerad",
        "första",
        "förste",
        "två",
        "tre",
        "fyra",
        "fem",
        "sex",
        "sju",
        "åtta",
        "nio",
        "tio",
        "senaste",
        "sista",
        "uppdaterad",
        "uppdaterades",
        "meddelar",
        "meddelade",
        "läs",
        "prenumerera",
        "prenumeration",
        "skriver",
        "skrev",
        "berättar",
        "berättade",
        "enligt",
        "rapporterar",
        "rapporterades",
    }
)

_SV_META_STEM_MIN = 6
_SV_META_STEM_SOURCES = frozenset(
    {
        "artikel",
        "artikeln",
        "artiklar",
        "artiklarna",
        "publicerades",
        "publiceras",
        "publicerad",
        "publicerat",
        "uppdaterades",
        "uppdaterad",
        "uppdaterats",
        "rapporterades",
        "rapporterar",
        "rapporterats",
    }
)
_SV_META_STEMS: frozenset[str] = frozenset(
    sx
    for w in _SV_META_STEM_SOURCES
    for sx in (_SV_STEMMER.stem(w),)
    if len(sx) >= _SV_META_STEM_MIN
)


def _merge_stopwords_for_locales(bases: tuple[str, ...]) -> frozenset[str]:
    """English core + boiler always; add Finnish/Swedish packs when those locales are enabled."""
    acc = set(_STOPWORDS_EN_CORE) | set(_STOPWORDS_EN_BOILER)
    if "fi" in bases:
        acc |= _STOPWORDS_FI
    if "sv" in bases:
        acc |= _STOPWORDS_SV
    return frozenset(acc)


def _build_term_stopwords() -> frozenset[str]:
    acc: set[str] = set()
    for w in _STOPWORDS:
        if len(w) >= _MIN_TOKEN_LEN:
            t = _EN_STEMMER.stem(w)
            if len(t) >= _MIN_TOKEN_LEN:
                acc.add(t)
    if "fi" in _active_locale_bases:
        for sx in _FI_META_STEMS:
            if len(sx) >= _MIN_TOKEN_LEN:
                acc.add(sx)
                t2 = _EN_STEMMER.stem(sx)
                if len(t2) >= _MIN_TOKEN_LEN:
                    acc.add(t2)
    if "sv" in _active_locale_bases:
        for sx in _SV_META_STEMS:
            if len(sx) >= _MIN_TOKEN_LEN:
                acc.add(sx)
                t2 = _EN_STEMMER.stem(sx)
                if len(t2) >= _MIN_TOKEN_LEN:
                    acc.add(t2)
    return frozenset(acc)


_active_locale_bases: tuple[str, ...] = ("fi",)
_STOPWORDS: frozenset[str] = _merge_stopwords_for_locales(_active_locale_bases)
_TERM_STOPWORDS: frozenset[str] = _build_term_stopwords()


_SUPPORTED_LOCALE_BASES = frozenset({"fi", "sv", "en"})


def set_enabled_locales(locales: List[str]) -> None:
    """
    Configure which locale packs apply to stopwords and meta-stem filtering.

    Must be a non-empty list from config; each entry should be a BCP47-style
    tag whose base language is ``fi``, ``sv``, or ``en``. Unknown base codes
    are skipped; at least one supported code must remain or this raises.
    """
    global _active_locale_bases, _STOPWORDS, _TERM_STOPWORDS
    if not locales:
        raise ValueError(
            'locales must be a non-empty list (set "locales" in config.json).'
        )
    seen: list[str] = []
    for raw in locales:
        b = str(raw).strip().split("-")[0].lower()
        if b in _SUPPORTED_LOCALE_BASES and b not in seen:
            seen.append(b)
    if not seen:
        raise ValueError(
            f"locales must include at least one of {sorted(_SUPPORTED_LOCALE_BASES)}; "
            f"got {locales!r}."
        )
    _active_locale_bases = tuple(seen)
    _STOPWORDS = _merge_stopwords_for_locales(_active_locale_bases)
    _TERM_STOPWORDS = _build_term_stopwords()


def _token_is_low_information(w: str) -> bool:
    """Digits, merged stopwords, and locale-specific meta stems when that locale is enabled."""
    if w.isdigit():
        return True
    if w in _STOPWORDS:
        return True
    if "fi" in _active_locale_bases:
        sfi = _FI_STEMMER.stem(w)
        if len(sfi) >= _FI_META_STEM_MIN and sfi in _FI_META_STEMS:
            return True
    if "sv" in _active_locale_bases:
        ssv = _SV_STEMMER.stem(w)
        if len(ssv) >= _SV_META_STEM_MIN and ssv in _SV_META_STEMS:
            return True
    return False


_TOKEN_RE = re.compile(r"[a-zåäöA-ZÅÄÖ0-9]+", re.UNICODE)


def _normalize_term(raw: str) -> str:
    """Single English Snowball bucket per surface word (language-agnostic rough fold)."""
    s = _EN_STEMMER.stem(raw)
    return s if len(s) >= _MIN_TOKEN_LEN else ""


def _raw_tokens(text: str) -> List[str]:
    """Lowercased word-like tokens; drops stopwords, digits, and locale-aware meta phrasing."""
    lower = text.lower()
    out: List[str] = []
    for m in _TOKEN_RE.finditer(lower):
        w = m.group(0)
        if len(w) >= _MIN_TOKEN_LEN and not _token_is_low_information(w):
            out.append(w)
    return out


def _collapse_prefix_variants(terms: Set[str]) -> Set[str]:
    """Drop longer strings that only extend a shorter candidate."""
    if len(terms) <= 1:
        return set(terms)
    kept: Set[str] = set()
    for s in sorted(terms, key=len):
        if any(
            s != t
            and len(t) < len(s)
            and s.startswith(t)
            and len(s) - len(t) <= _MAX_PREFIX_INFLECTION_DELTA
            for t in terms
        ):
            continue
        kept.add(s)
    return kept


def _matching_term_set(haystack: str) -> set[str]:
    """Stem-normalized keys for overlap (haystack is title+description+content)."""
    out: set[str] = set()
    for w in _raw_tokens(haystack):
        t = _normalize_term(w)
        if t and t not in _TERM_STOPWORDS:
            out.add(t)
    return out


# Light shelves: any single stem hit from the shelf’s seed set (after EN snowball) places
# an otherwise ungrouped article in that shelf; first matching shelf wins.
_KEYWORD_SHELF_SEEDS: List[tuple[str, tuple[str, ...]]] = [
    (
        "Politics & society",
        (
            "politic",
            "election",
            "parliament",
            "government",
            "minister",
            "president",
            "campaign",
            "vote",
            "politiikka",
            "hallitus",
            "eduskunta",
            "vaalit",
            "kansanedustaja",
            "laki",
            "oikeus",
            "democracy",
        ),
    ),
    (
        "Economy & business",
        (
            "econom",
            "market",
            "stock",
            "trade",
            "business",
            "company",
            "profit",
            "talous",
            "yritys",
            "osake",
            "pörssi",
            "kauppa",
            "invest",
        ),
    ),
    (
        "Technology",
        (
            "technolog",
            "software",
            "computer",
            "digital",
            "internet",
            "teknologia",
            "ohjelmisto",
            "tietokone",
            "kyber",
            "apple",
            "googl",
            "microsoft",
        ),
    ),
    (
        "Sports",
        (
            "sport",
            "football",
            "soccer",
            "hockey",
            "olympic",
            "championship",
            "urheilu",
            "jalkapallo",
            "jääkiekko",
            "mestaruus",
            "ottelu",
            "sarja",
            "liiga",
            "maali",
        ),
    ),
    (
        "Culture & entertainment",
        (
            "music",
            "film",
            "movie",
            "theatre",
            "television",
            "celebrit",
            "kulttuuri",
            "musiikki",
            "elokuva",
            "teatteri",
            "näyttelijä",
            "festivaali",
        ),
    ),
    (
        "Health & science",
        (
            "health",
            "medic",
            "hospital",
            "disease",
            "study",
            "research",
            "terveys",
            "sairaala",
            "tiede",
            "tutkimus",
            "rokote",
            "lääke",
        ),
    ),
    (
        "Environment",
        (
            "climate",
            "environment",
            "pollution",
            "energy",
            "forest",
            "ilmasto",
            "ympäristö",
            "luonto",
            "energia",
            "päästö",
        ),
    ),
    (
        "Conflict & security",
        (
            "war",
            "military",
            "attack",
            "weapon",
            "security",
            "sota",
            "hyökkäys",
            "puolustus",
            "ase",
            "turvallisuus",
            "sotilas",
        ),
    ),
]


def _build_shelf_stem_sets() -> List[tuple[str, frozenset[str]]]:
    out: List[tuple[str, frozenset[str]]] = []
    for heading, seeds in _KEYWORD_SHELF_SEEDS:
        stems: set[str] = set()
        for w in seeds:
            t = _normalize_term(w)
            if t and t not in _TERM_STOPWORDS:
                stems.add(t)
        if stems:
            out.append((heading, frozenset(stems)))
    return out


_SHELF_STEM_SETS: List[tuple[str, frozenset[str]]] = _build_shelf_stem_sets()
_MIN_SHELF_STEM_OVERLAP = 1


def _keyword_shelf_sections(
    article_list: List[NewsArticle], leftover_indices: List[int]
):
    """Bucket leftovers by title/description stem overlap with shelf seed sets."""
    remaining = set(leftover_indices)
    sections = []
    for heading, stem_set in _SHELF_STEM_SETS:
        bucket: List[int] = []
        for i in list(remaining):
            hay = _article_title_description_text_only(article_list[i])
            toks = _matching_term_set(hay)
            if len(stem_set & toks) >= _MIN_SHELF_STEM_OVERLAP:
                bucket.append(i)
        if not bucket:
            continue
        for i in bucket:
            remaining.discard(i)
        sections.append(
            ArticleSection(
                heading=f"{heading} · keywords",
                articles=_oldest_first([article_list[i] for i in sorted(bucket)]),
            )
        )
    return sections


def _overly_frequent_terms(article_tokens: Dict[int, Set[str]], n: int) -> Set[str]:
    if n <= 0:
        return set()
    df: dict[str, int] = defaultdict(int)
    for i in range(n):
        for s in article_tokens[i]:
            df[s] += 1
    cutoff = max(4, math.ceil(n * _MAX_TERM_DOC_FRACTION))
    return {s for s, c in df.items() if c > cutoff}


def _trim_tokens_for_linking(
    article_tokens: Dict[int, Set[str]], n: int, noisy: Set[str]
) -> Dict[int, Set[str]]:
    return {i: article_tokens[i] - noisy for i in range(n)}


def _adjacency_link_trimmed(
    trimmed: Dict[int, Set[str]],
    n: int,
    min_shared_terms: int,
) -> Dict[int, Set[int]]:
    """Edge i–j iff |trimmed[i] ∩ trimmed[j]| ≥ k after noisy-term removal."""
    k = max(1, min_shared_terms)
    adj: Dict[int, Set[int]] = {i: set() for i in range(n)}
    for i in range(n):
        ti = trimmed[i]
        if len(ti) < k:
            continue
        for j in range(i + 1, n):
            if len(ti & trimmed[j]) >= k:
                adj[i].add(j)
                adj[j].add(i)
    return adj


def _bron_kerbosch(
    r: Set[int],
    p: Set[int],
    x: Set[int],
    adj: Dict[int, Set[int]],
    out: List[Set[int]],
) -> None:
    if not p:
        if not x and len(r) >= 2:
            out.append(set(r))
        return
    px = p | x
    u = max(px, key=lambda v: len(adj[v] & p))
    for v in list(p - adj[u]):
        nv = adj[v]
        _bron_kerbosch(r | {v}, p & nv, x & nv, adj, out)
        p.discard(v)
        x.add(v)


def _maximal_cliques_in_subgraph(
    vertices: Set[int], adj_full: Dict[int, Set[int]]
) -> List[Set[int]]:
    if len(vertices) < 2:
        return []
    sub_adj: Dict[int, Set[int]] = {v: adj_full[v] & vertices for v in vertices}
    out: List[Set[int]] = []
    _bron_kerbosch(set(), set(vertices), set(), sub_adj, out)
    return out


def _groups_by_iterative_clique_peeling(
    adj: Dict[int, Set[int]], n: int
) -> List[List[int]]:
    """
    Repeatedly take a largest maximal clique among still-unassigned vertices.

    Unlike union-find on edges, this rejects pure chains A–B–C–D where only
    adjacent pairs share terms (no clique of size ≥3).
    """
    assigned: Set[int] = set()
    groups: List[List[int]] = []
    while True:
        unassigned = {i for i in range(n) if i not in assigned}
        if len(unassigned) < 2:
            break
        cliques = _maximal_cliques_in_subgraph(unassigned, adj)
        candidates = [c for c in cliques if len(c) >= 2]
        if not candidates:
            break
        best = max(candidates, key=len)
        groups.append(sorted(best))
        assigned.update(best)
    return groups


def _build_term_to_raw_word(haystacks: List[str]) -> dict[str, str]:
    """Shortest raw token per normalized term (for section labels)."""
    mapping: dict[str, str] = {}
    for text in haystacks:
        for raw in _raw_tokens(text):
            t = _normalize_term(raw)
            if not t or t in _TERM_STOPWORDS:
                continue
            if t not in mapping or len(raw) < len(mapping[t]):
                mapping[t] = raw
    return mapping


def _join_english_list(items: List[str]) -> str:
    """Two or more items: comma-separated (no \"and\")."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items)


def _stem_phrase_for_heading(
    stems_sorted: List[str],
    term_to_word: dict[str, str] | None,
    *,
    max_terms: int,
) -> str:
    """Comma phrase of display words (capitalized) from normalized stems."""
    take = stems_sorted[:max_terms]
    labels = [
        (term_to_word[s] if term_to_word and s in term_to_word else s).capitalize()
        for s in take
    ]
    phrase = _join_english_list(labels)
    extra = len(stems_sorted) - len(take)
    if extra > 0:
        phrase += f" +{extra} more"
    return phrase


def _overlap_terms_for_group(
    indices: List[int],
    article_tokens: dict[int, set[str]],
    min_shared_terms: int,
) -> List[str] | None:
    """
    Sorted stem keys that best summarize why the cluster exists: prefer terms
    every article shares, otherwise the richest pairwise overlap (same graph rule as edges).
    """
    k = max(1, min_shared_terms)
    if len(indices) < 2:
        return None
    sets = [article_tokens[i] for i in indices]
    common_all = _collapse_prefix_variants(set.intersection(*sets))
    if len(common_all) >= k:
        return sorted(common_all)
    best: set[str] = set()
    for a in range(len(indices)):
        for b in range(a + 1, len(indices)):
            inter = _collapse_prefix_variants(
                article_tokens[indices[a]] & article_tokens[indices[b]]
            )
            if len(inter) >= k and len(inter) > len(best):
                best = inter
    if len(best) >= k:
        return sorted(best)
    return None


def _group_heading_explanation(
    indices: List[int],
    article_tokens: dict[int, set[str]],
    min_shared_terms: int,
    term_to_word: dict[str, str] | None,
    *,
    max_terms_in_sentence: int = 4,
) -> str:
    """Short line describing the cluster — stems from subject tags (and description matches)."""
    stems = _overlap_terms_for_group(indices, article_tokens, min_shared_terms)
    if stems is None:
        return "Grouped by subject tags; keywords used only when matching into a cluster"
    phrase = _stem_phrase_for_heading(stems, term_to_word, max_terms=max_terms_in_sentence)
    return f"{phrase}."


class ArticleSection(TypedDict):
    heading: str | None
    articles: List[NewsArticle]


VIEW_LABELS: dict[ViewMode, str] = {
    "chronological": "All sources (newest at bottom)",
    "per_source": "Per source",
    "by_matching_words": "Similar content",
}


def filter_articles_by_keyword(
    articles: List[NewsArticle], query: str
) -> List[NewsArticle]:
    """
    Case-insensitive substring filter. Multiple whitespace-separated words require **all**
    to appear somewhere in title, description, content, source name, or author (AND).
    """
    q = query.strip().lower()
    if not q:
        return list(articles)
    tokens = [t for t in re.split(r"\s+", q) if t]
    if not tokens:
        return list(articles)

    return [a for a in articles if all(tok in _article_search_haystack(a) for tok in tokens)]


def _newest_first(articles: List[NewsArticle]) -> List[NewsArticle]:
    return sorted(articles, key=lambda a: a["publishedAtTimestamp"], reverse=True)


def _oldest_first(articles: List[NewsArticle]) -> List[NewsArticle]:
    """Ascending time — scroll buffer grows downward; latest row sits at the bottom."""
    return sorted(articles, key=lambda a: a["publishedAtTimestamp"])


def build_sections(
    articles: List[NewsArticle],
    mode: ViewMode,
    per_source_limit: int = 3,
) -> List[ArticleSection]:
    if not articles:
        return [ArticleSection(heading=None, articles=[])]

    if mode == "chronological":
        return [ArticleSection(heading=None, articles=_oldest_first(articles))]

    if mode == "per_source":
        by_name: dict[str, List[NewsArticle]] = {}
        for a in articles:
            name = a["source"]["name"] or "?"
            by_name.setdefault(name, []).append(a)
        sections: List[ArticleSection] = []
        for name in sorted(by_name.keys(), key=lambda s: s.lower()):
            pick = _newest_first(by_name[name])[:per_source_limit]
            sections.append(ArticleSection(heading=name, articles=_oldest_first(pick)))
        return sections

    # by_matching_words: primary cliques from RSS subjects only; second pass matches description ∪
    # cleaned keywords to group topic stems; URI-like keyword junk ignored; then keyword shelves.
    article_list = list(articles)
    primary_haystacks = [_article_primary_grouping_text(a) for a in article_list]

    n = len(article_list)
    article_tokens: dict[int, set[str]] = {
        i: _matching_term_set(primary_haystacks[i]) for i in range(n)
    }
    term_to_word = _build_term_to_raw_word(primary_haystacks)

    noisy = _overly_frequent_terms(article_tokens, n)
    trimmed = _trim_tokens_for_linking(article_tokens, n, noisy)
    adj = _adjacency_link_trimmed(trimmed, n, _MIN_SHARED_TERMS_LINK)
    group_indices = _groups_by_iterative_clique_peeling(adj, n)

    assigned_first = {i for grp in group_indices for i in grp}
    unassigned_first = [i for i in range(n) if i not in assigned_first]

    desc_haystacks = [_article_description_text(a) for a in article_list]
    desc_tokens = {i: _matching_term_set(desc_haystacks[i]) for i in range(n)}
    meta_kw_haystacks = [_article_keyword_meta_text(a) for a in article_list]
    meta_kw_tokens = {i: _matching_term_set(meta_kw_haystacks[i]) for i in range(n)}
    second_match_tokens = {
        i: desc_tokens[i] | meta_kw_tokens[i] for i in range(n)
    }

    k = _MIN_SHARED_TERMS_LINK
    group_topic_stems: List[List[str] | None] = [
        _overlap_terms_for_group(idxs, trimmed, k) for idxs in group_indices
    ]

    for u in unassigned_first:
        best_g = -1
        best_score = -1
        for g, stems in enumerate(group_topic_stems):
            if stems is None:
                continue
            ts = set(stems)
            inter = ts & second_match_tokens[u]
            need = min(k, len(ts))
            if len(inter) < need:
                continue
            score = len(inter)
            if score > best_score:
                best_score = score
                best_g = g
        if best_g >= 0:
            group_indices[best_g].append(u)
            group_indices[best_g].sort()

    grouped_sections: List[ArticleSection] = []
    for idxs_sorted in group_indices:
        heading = _group_heading_explanation(
            idxs_sorted,
            trimmed,
            k,
            term_to_word,
        )
        grouped_sections.append(
            ArticleSection(
                heading=heading,
                articles=_oldest_first([article_list[i] for i in idxs_sorted]),
            )
        )

    assigned_cluster = {i for grp in group_indices for i in grp}
    still_unassigned = [i for i in range(n) if i not in assigned_cluster]
    grouped_sections.extend(_keyword_shelf_sections(article_list, still_unassigned))

    grouped_sections.sort(
        key=lambda sec: max(a["publishedAtTimestamp"] for a in sec["articles"]),
        reverse=True,
    )

    sections_out: List[ArticleSection] = list(grouped_sections)

    return (
        sections_out
        if sections_out
        else [ArticleSection(heading=None, articles=[])]
    )
