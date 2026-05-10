"""Search module for the search engine tool.

Provides the high-level query operations consumed by the CLI:

* :meth:`SearchEngine.print_word` -- formatted dump of the inverted-index
  entry for a single word (``print <word>``).
* :meth:`SearchEngine.find` -- multi-word query returning pages that
  contain **all** of the query terms, ranked by TF-IDF score
  (``find <query>``).

The module is deliberately decoupled from the CLI so it can be unit
tested in isolation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .indexer import Indexer, tokenize


@dataclass
class SearchHit:
    """A single search result returned by :meth:`SearchEngine.find`."""

    url: str
    score: float
    title: str
    matched_terms: Dict[str, int]  # term -> frequency in this document

    def format(self, rank: Optional[int] = None) -> str:
        """Render the hit as a human-readable single-block string."""
        prefix = f"{rank}. " if rank is not None else "- "
        title = self.title or "(untitled)"
        terms = ", ".join(
            f"{term}={freq}" for term, freq in sorted(self.matched_terms.items())
        )
        return (
            f"{prefix}{title}\n"
            f"   url:    {self.url}\n"
            f"   score:  {self.score:.4f}\n"
            f"   terms:  {terms}"
        )


class SearchEngine:
    """Query interface over an :class:`~src.indexer.Indexer`."""

    def __init__(self, indexer: Indexer) -> None:
        self.indexer = indexer

    # ------------------------------------------------------------------
    # ``print <word>``
    # ------------------------------------------------------------------
    def print_word(self, word: str) -> str:
        """Return the formatted inverted-index entry for ``word``.

        The result is a multi-line string ready to be printed by the
        CLI.  When ``word`` is missing or unknown a friendly message is
        returned instead of raising.
        """
        if word is None or not word.strip():
            return "Usage: print <word>"

        normalized_tokens = tokenize(word)
        if not normalized_tokens:
            return f"No indexable token found in {word!r}."
        if len(normalized_tokens) > 1:
            return (
                "'print' accepts a single word; "
                f"got {len(normalized_tokens)} tokens: {normalized_tokens}."
            )

        term = normalized_tokens[0]
        postings = self.indexer.postings(term)
        if not postings:
            return f"'{term}' is not in the index."

        df = len(postings)
        total_freq = sum(int(entry["freq"]) for entry in postings.values())
        lines: List[str] = [
            f"Term: {term}",
            f"Document frequency: {df}",
            f"Total occurrences:  {total_freq}",
            "Postings:",
        ]
        # Stable ordering: most frequent first, then by URL.
        ordered = sorted(
            postings.items(),
            key=lambda kv: (-int(kv[1]["freq"]), kv[0]),
        )
        for url, entry in ordered:
            freq = int(entry["freq"])
            positions = list(entry["positions"])  # type: ignore[arg-type]
            shown = positions[:10]
            more = "" if len(positions) <= 10 else f" (+{len(positions) - 10} more)"
            lines.append(f"  - {url}")
            lines.append(f"      freq={freq}, positions={shown}{more}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # ``find <query>``
    # ------------------------------------------------------------------
    def find(
        self,
        query: str,
        *,
        limit: Optional[int] = None,
    ) -> List[SearchHit]:
        """Return ranked :class:`SearchHit` objects for ``query``.

        Multi-word queries are AND-combined: only documents that contain
        **every** query term are returned.  Results are ranked by the
        sum of per-term TF-IDF weights, with TF normalised by document
        length and IDF computed as ``log((N + 1) / (df + 1)) + 1`` so
        the score stays positive even when a term occurs in every
        document.
        """
        if not query or not query.strip():
            return []

        terms = self._unique_tokens(tokenize(query))
        if not terms:
            return []

        # Quick fail: any unknown term -> empty intersection.
        postings_per_term: Dict[str, Dict[str, Dict[str, object]]] = {}
        for term in terms:
            postings = self.indexer.postings(term)
            if not postings:
                return []
            postings_per_term[term] = postings

        # Intersect document URLs.
        url_sets = [set(p.keys()) for p in postings_per_term.values()]
        common_urls = set.intersection(*url_sets)
        if not common_urls:
            return []

        n_docs = max(self.indexer.document_count, 1)
        hits: List[SearchHit] = []
        for url in common_urls:
            score = 0.0
            matched: Dict[str, int] = {}
            doc_len = max(self.indexer.document_length(url), 1)
            for term, postings in postings_per_term.items():
                entry = postings[url]
                freq = int(entry["freq"])
                df = len(postings)
                tf = freq / doc_len
                idf = math.log((n_docs + 1) / (df + 1)) + 1.0
                score += tf * idf
                matched[term] = freq
            hits.append(
                SearchHit(
                    url=url,
                    score=score,
                    title=self.indexer.document_title(url),
                    matched_terms=matched,
                )
            )

        hits.sort(key=lambda hit: (-hit.score, hit.url))
        if limit is not None:
            hits = hits[:limit]
        return hits

    def format_find_results(
        self,
        query: str,
        hits: Sequence[SearchHit],
    ) -> str:
        """Render :meth:`find` output as a printable block."""
        if not query or not query.strip():
            return "Usage: find <query>"
        if not hits:
            return f"No pages match query: {query!r}"
        lines: List[str] = [f"Found {len(hits)} page(s) for query: {query!r}"]
        for rank, hit in enumerate(hits, start=1):
            lines.append(hit.format(rank=rank))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _unique_tokens(tokens: Sequence[str]) -> List[str]:
        """Return ``tokens`` with duplicates removed, preserving order."""
        seen = set()
        unique: List[str] = []
        for token in tokens:
            if token in seen:
                continue
            seen.add(token)
            unique.append(token)
        return unique
