import math
import os
import re
from collections import defaultdict
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional, Set, TypedDict

from nltk.stem.snowball import SnowballStemmer

from app.news_types import NewsArticle

# Finnish + English Snowball stemmers — fallback when Voikko is unavailable or OOV.
_FI_STEMMER = SnowballStemmer("finnish")
_EN_STEMMER = SnowballStemmer("english")

ViewMode = Literal["chronological", "per_source", "by_matching_words"]

_MIN_TOKEN_LEN = 4
# Drop stems that appear in too many headlines before linking (reduces generic bridges).
_MAX_STEM_DOC_FRACTION = 0.22
_MIN_SHARED_STEMS_LINK = 2
# Drop longer stem if it only extends a shorter one in the same raw word (seuraa→seura).
_MAX_PREFIX_INFLECTION_DELTA = 5

_voikko_instance: Optional[Any] = None
_voikko_init_failed = False


def _get_voikko() -> Optional[Any]:
    """Lazy Voikko(fi) handle; None if lib/dict missing or NEWSFEED_DISABLE_VOIKKO is set."""
    global _voikko_instance, _voikko_init_failed
    if _voikko_init_failed:
        return None
    if os.environ.get("NEWSFEED_DISABLE_VOIKKO", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        _voikko_init_failed = True
        return None
    if _voikko_instance is not None:
        return _voikko_instance
    try:
        import libvoikko

        _voikko_instance = libvoikko.Voikko(language="fi")
        return _voikko_instance
    except Exception:
        _voikko_init_failed = True
        return None


def _voikko_baseform(word: str) -> Optional[str]:
    """Lemma from Voikko morphology; None if analyzer missing or word unknown."""
    v = _get_voikko()
    if v is None:
        return None
    try:
        analyses = v.analyze(word)
    except Exception:
        return None
    if not analyses:
        return None
    bf = analyses[0].get("BASEFORM")
    if not bf or not isinstance(bf, str):
        return None
    bf = bf.strip().lower()
    if len(bf) < _MIN_TOKEN_LEN:
        return None
    return bf


# Finnish + English common words — keeps grouping focused on topical terms
_STOPWORDS = frozenset(
    {
        # English
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
        # Finnish
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
        "joka",
        "jonka",
        "jossa",
        "jossa",
        "josta",
        "jotka",
        "kanssa",
        "koska",
        "kuin",
        "kun",
        "myös",
        "ne",
        "niin",
        "näin",
        "olla",
        "olen",
        "olet",
        "ovat",
        "paitsi",
        "sekä",
        "se",
        "sen",
        "siitä",
        "siihen",
        "siinä",
        "sitä",
        "tai",
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
    }
)

_TOKEN_RE = re.compile(r"[a-zåäöA-ZÅÄÖ0-9]+", re.UNICODE)

# Snowball Finnish maps many Suomi-* inflections to "suome" but leaves nominative
# "suomi"; English often keeps full Finnish surfaces — fold to one overlap bucket.
_MATCH_STEM_CANONICAL = {
    "suomi": "suome",
    "suomen": "suome",
    "suomessa": "suome",
    "suomesta": "suome",
    "suomeen": "suome",
    "suomeksi": "suome",
}


def _canonical_stem(s: str) -> str:
    return _MATCH_STEM_CANONICAL.get(s, s)


def _raw_tokens(title: str) -> List[str]:
    """Lowercased word-like tokens from a headline, stopword- and length-filtered."""
    lower = title.lower()
    out: List[str] = []
    for m in _TOKEN_RE.finditer(lower):
        w = m.group(0)
        if len(w) >= _MIN_TOKEN_LEN and w not in _STOPWORDS:
            out.append(w)
    return out


def _fi_stem_until_stable(word: str) -> str:
    cur = word
    for _ in range(8):
        nxt = _FI_STEMMER.stem(cur)
        if nxt == cur:
            return cur
        cur = nxt
    return cur


def _collapse_prefix_variants(stems: Set[str]) -> Set[str]:
    """
    One morphological word often yields both Fi-stable stem and En surface (seura + seuraa).
    Drop longer strings that only extend a shorter candidate from the same raw token.
    """
    if len(stems) <= 1:
        return set(stems)
    kept: Set[str] = set()
    for s in sorted(stems, key=len):
        if any(
            s != t
            and len(t) < len(s)
            and s.startswith(t)
            and len(s) - len(t) <= _MAX_PREFIX_INFLECTION_DELTA
            for t in stems
        ):
            continue
        kept.add(s)
    return kept


@lru_cache(maxsize=8192)
def _grouping_stems_for_raw_word(word: str) -> frozenset[str]:
    """
    Prefer Voikko BASEFORM for Finnish (fixes Vappu/Vapu, Ensimmäinen vs Snowball junk).
    If Voikko is off or OOV, fall back to Fi/En Snowball + prefix collapse.
    """
    bf = _voikko_baseform(word)
    if bf is not None:
        return frozenset({_canonical_stem(bf)})

    ew = _EN_STEMMER.stem(word)
    candidates: set[str] = set()
    for s in (_fi_stem_until_stable(word), _fi_stem_until_stable(ew), ew, word):
        cs = _canonical_stem(s)
        if len(cs) >= _MIN_TOKEN_LEN:
            candidates.add(cs)
    return frozenset(_collapse_prefix_variants(candidates))


def _stem_stopwords() -> frozenset[str]:
    """Keys derived like headline tokens so stem-shaped noise stays filtered."""
    acc: set[str] = set()
    for w in _STOPWORDS:
        if len(w) >= _MIN_TOKEN_LEN:
            acc.update(_grouping_stems_for_raw_word(w))
    return frozenset(acc)


_STEM_STOPWORDS: frozenset[str] = _stem_stopwords()


def _matching_stem_set(title: str) -> set[str]:
    """Stem-normalized keys for overlap (one bucket per surface word)."""
    out: set[str] = set()
    for w in _raw_tokens(title):
        for s in _grouping_stems_for_raw_word(w):
            if s not in _STEM_STOPWORDS:
                out.add(s)
    return out


def _overly_frequent_stems(article_tokens: Dict[int, Set[str]], n: int) -> Set[str]:
    """Stems that appear in too many documents act like generic glue — ignore for edges."""
    if n <= 0:
        return set()
    df: dict[str, int] = defaultdict(int)
    for i in range(n):
        for s in article_tokens[i]:
            df[s] += 1
    cutoff = max(4, math.ceil(n * _MAX_STEM_DOC_FRACTION))
    return {s for s, c in df.items() if c > cutoff}


def _trim_tokens_for_linking(
    article_tokens: Dict[int, Set[str]], n: int, noisy: Set[str]
) -> Dict[int, Set[str]]:
    return {i: article_tokens[i] - noisy for i in range(n)}


def _adjacency_link_trimmed(
    trimmed: Dict[int, Set[str]], n: int
) -> Dict[int, Set[int]]:
    adj: Dict[int, Set[int]] = {i: set() for i in range(n)}
    for i in range(n):
        ti = trimmed[i]
        if len(ti) < _MIN_SHARED_STEMS_LINK:
            continue
        for j in range(i + 1, n):
            if len(ti & trimmed[j]) >= _MIN_SHARED_STEMS_LINK:
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
    adjacent pairs share stems (no clique of size ≥3).
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


def _pairwise_match_heading(indices: List[int], article_tokens: dict[int, set[str]]) -> str:
    """Title from shared tokens: prefer words common to every headline, else strongest pairwise overlap."""
    if len(indices) < 2:
        return "Related"
    sets = [article_tokens[i] for i in indices]
    common_all = _collapse_prefix_variants(set.intersection(*sets))
    if len(common_all) >= 2:
        w1, w2 = sorted(common_all)[:2]
        return f"{w1.capitalize()} · {w2.capitalize()}"
    best: set[str] = set()
    for a in range(len(indices)):
        for b in range(a + 1, len(indices)):
            inter = _collapse_prefix_variants(
                article_tokens[indices[a]] & article_tokens[indices[b]]
            )
            if len(inter) >= 2 and len(inter) > len(best):
                best = inter
    if len(best) >= 2:
        w1, w2 = sorted(best)[:2]
        return f"{w1.capitalize()} · {w2.capitalize()}"
    return "Related"


class ArticleSection(TypedDict):
    heading: str | None
    articles: List[NewsArticle]


VIEW_LABELS: dict[ViewMode, str] = {
    "chronological": "All sources (newest at bottom)",
    "per_source": "Top 3 per source",
    "by_matching_words": "Stem overlap (Voikko + cliques)",
}


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

    # by_matching_words: largest maximal cliques (not connected components) on a graph
    # where edges need ≥2 shared *infrequent* stems — kills long transitive false chains.
    article_list = list(articles)
    article_tokens: dict[int, set[str]] = {
        i: _matching_stem_set(a["title"]) for i, a in enumerate(article_list)
    }

    n = len(article_list)
    noisy = _overly_frequent_stems(article_tokens, n)
    trimmed = _trim_tokens_for_linking(article_tokens, n, noisy)
    adj = _adjacency_link_trimmed(trimmed, n)
    group_indices = _groups_by_iterative_clique_peeling(adj, n)

    grouped_sections: List[ArticleSection] = []
    for idxs_sorted in group_indices:
        heading = _pairwise_match_heading(idxs_sorted, trimmed)
        grouped_sections.append(
            ArticleSection(
                heading=heading,
                articles=_oldest_first([article_list[i] for i in idxs_sorted]),
            )
        )

    grouped_sections.sort(
        key=lambda sec: max(a["publishedAtTimestamp"] for a in sec["articles"]),
        reverse=True,
    )

    sections_out: List[ArticleSection] = list(grouped_sections)

    return sections_out if sections_out else [ArticleSection(heading=None, articles=_oldest_first(articles))]
