"""Indexer module for the search engine tool.

Builds and persists an in-memory **inverted index** that maps every
distinct lowercase word seen during crawling to the documents it
appears in, together with per-document statistics (term frequency and
positions).  The index is intentionally implemented as a plain Python
``dict`` so it serialises trivially to a single JSON file in
``data/`` (coursework requirement).

Data model
----------
``inverted_index[word][doc_url] = {"freq": int, "positions": [int, ...]}``

``documents[doc_url] = {"length": int, "title": str}``

The ``length`` field is the total number of indexable tokens in the
page and is used by :mod:`src.search` for TF-IDF ranking.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

#: Default location for the serialised index file.
DEFAULT_INDEX_PATH: str = os.path.join("data", "index.json")

#: Regex used to split tokens.  We keep ASCII letters, digits and
#: apostrophes inside words ("don't", "it's") and discard everything
#: else.  The result is then lower-cased.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?")


def tokenize(text: str) -> List[str]:
    """Tokenize ``text`` into a list of lowercase word tokens.

    The tokenizer is:

    * case-insensitive (output is always lowercase),
    * strips punctuation,
    * keeps intra-word apostrophes (``don't`` -> ``don't``),
    * preserves order (so callers can derive positions).
    """
    if not text:
        return []
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]


def extract_visible_text(html: str) -> Tuple[str, str]:
    """Return ``(title, body_text)`` extracted from an HTML document.

    Script/style/noscript content is removed before extraction so that
    JavaScript source code is not indexed alongside the visible page
    content.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    # Remove the <title> tag so its text does not appear twice once we
    # prepend ``title`` to the body in ``add_document``.
    if soup.title is not None:
        soup.title.decompose()
    body_text = soup.get_text(separator=" ", strip=True)
    return title, body_text


@dataclass
class Indexer:
    """Build, persist and load an inverted index."""

    inverted_index: Dict[str, Dict[str, Dict[str, object]]] = field(default_factory=dict)
    documents: Dict[str, Dict[str, object]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    def add_document(self, url: str, html: str) -> int:
        """Index a single ``(url, html)`` document.

        Returns the number of tokens that were added (i.e. the document
        length).  Re-indexing the same URL replaces the previous entry
        so the index stays consistent.
        """
        if not url:
            raise ValueError("url must be a non-empty string")

        # If we have seen this URL before, drop its previous postings.
        if url in self.documents:
            self._remove_document(url)

        title, body = extract_visible_text(html)
        # Index the title together with the body so a query like
        # ``find login`` can match navigation pages too.
        tokens = tokenize(f"{title} {body}")
        for position, term in enumerate(tokens):
            postings = self.inverted_index.setdefault(term, {})
            entry = postings.get(url)
            if entry is None:
                postings[url] = {"freq": 1, "positions": [position]}
            else:
                entry["freq"] = int(entry["freq"]) + 1  # type: ignore[arg-type]
                positions: List[int] = entry["positions"]  # type: ignore[assignment]
                positions.append(position)

        self.documents[url] = {"length": len(tokens), "title": title}
        logger.debug("Indexed %s (%d tokens)", url, len(tokens))
        return len(tokens)

    def add_documents(self, pages: Iterable[Tuple[str, str]]) -> int:
        """Index an iterable of ``(url, html)`` pairs.

        Returns the total number of tokens indexed across all pages.
        """
        total = 0
        for url, html in pages:
            total += self.add_document(url, html)
        return total

    def _remove_document(self, url: str) -> None:
        """Remove a previously-indexed document from the index."""
        empty_terms: List[str] = []
        for term, postings in self.inverted_index.items():
            if url in postings:
                del postings[url]
                if not postings:
                    empty_terms.append(term)
        for term in empty_terms:
            del self.inverted_index[term]
        self.documents.pop(url, None)

    # ------------------------------------------------------------------
    # Stats / accessors used by the search module
    # ------------------------------------------------------------------
    @property
    def document_count(self) -> int:
        """Total number of indexed documents."""
        return len(self.documents)

    @property
    def vocabulary_size(self) -> int:
        """Number of distinct terms in the index."""
        return len(self.inverted_index)

    def postings(self, term: str) -> Dict[str, Dict[str, object]]:
        """Return the postings dict for ``term`` (case-insensitive)."""
        return self.inverted_index.get(term.lower(), {})

    def document_frequency(self, term: str) -> int:
        """Number of documents that contain ``term``."""
        return len(self.postings(term))

    def document_length(self, url: str) -> int:
        """Total token count of the document at ``url`` (or ``0``)."""
        info = self.documents.get(url)
        if not info:
            return 0
        return int(info.get("length", 0))  # type: ignore[arg-type]

    def document_title(self, url: str) -> str:
        """Title of the document at ``url`` (or empty string)."""
        info = self.documents.get(url)
        if not info:
            return ""
        return str(info.get("title", ""))

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def save(self, path: str = DEFAULT_INDEX_PATH) -> str:
        """Serialise the index to ``path`` as JSON, atomically.

        The file is first written to ``<path>.tmp`` and then ``os.replace``-d
        into place so a crash midway through writing cannot corrupt a
        previously-good index file.  This is what makes incremental
        ``save``-after-every-page checkpointing safe.

        The destination directory is created if it does not exist.
        Returns the absolute path that was written to.
        """
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {
            "version": 1,
            "documents": self.documents,
            "inverted_index": self.inverted_index,
        }
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        absolute = os.path.abspath(path)
        logger.info("Wrote index to %s (%d docs, %d terms)", absolute,
                    self.document_count, self.vocabulary_size)
        return absolute

    @classmethod
    def load(cls, path: str = DEFAULT_INDEX_PATH) -> "Indexer":
        """Load an index previously written by :meth:`save`."""
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Index file not found: {path!r}. Run 'build' first."
            )
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)

        if not isinstance(payload, dict):
            raise ValueError(f"Invalid index file (expected object): {path!r}")

        # Backwards-compat: accept either the canonical layout or a bare
        # inverted_index dict.
        if "inverted_index" in payload and "documents" in payload:
            inverted = payload["inverted_index"]
            documents = payload["documents"]
        else:
            inverted = payload
            documents = {}

        # Re-hydrate positions as Python lists (json gives lists already
        # but be defensive in case the file was produced elsewhere).
        for term, postings in inverted.items():
            for url, entry in postings.items():
                entry["positions"] = list(entry.get("positions", []))
                entry["freq"] = int(entry.get("freq", len(entry["positions"])))

        instance = cls(inverted_index=inverted, documents=documents)
        logger.info(
            "Loaded index from %s (%d docs, %d terms)",
            os.path.abspath(path), instance.document_count,
            instance.vocabulary_size,
        )
        return instance


def build_index_from_pages(
    pages: Iterable[Tuple[str, str]],
    *,
    save_path: Optional[str] = DEFAULT_INDEX_PATH,
) -> Indexer:
    """Convenience helper: build and optionally save an index in one call."""
    indexer = Indexer()
    indexer.add_documents(pages)
    if save_path:
        indexer.save(save_path)
    return indexer
