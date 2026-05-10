"""Command-line shell for the search engine tool.

The shell exposes the four commands required by the coursework:

* ``build``                 -- crawl the target site, build & save the index.
* ``load``                  -- load a previously saved index from disk.
* ``print <word>``          -- show the inverted-index entry for ``<word>``.
* ``find <query>``          -- return pages matching every word in ``<query>``.

Auxiliary commands (``help``, ``stats``, ``quit``/``exit``) are also
provided to make the shell pleasant to use interactively.

Run with::

    python -m src.main          # interactive shell
    python -m src.main build    # one-shot command
"""

from __future__ import annotations

import argparse
import logging
import os
import shlex
import sys
from typing import List, Optional, Sequence

from .crawler import (
    DEFAULT_START_URL,
    MIN_REQUEST_INTERVAL,
    Crawler,
)
from .indexer import DEFAULT_INDEX_PATH, Indexer
from .search import SearchEngine

logger = logging.getLogger(__name__)


HELP_TEXT = """\
Available commands:
  build              Crawl the target site and build a fresh inverted index.
  load               Load the previously saved index from disk.
  print <word>       Show the inverted-index entry for <word>.
  find <query>       Return pages containing every word in <query>.
  stats              Print summary statistics about the loaded index.
  help               Show this message.
  quit | exit        Leave the shell.
"""


class Shell:
    """Stateful interactive shell tying crawler + indexer + search together."""

    def __init__(
        self,
        *,
        index_path: str = DEFAULT_INDEX_PATH,
        start_url: str = DEFAULT_START_URL,
        min_interval: float = MIN_REQUEST_INTERVAL,
        max_pages: Optional[int] = None,
    ) -> None:
        self.index_path = index_path
        self.start_url = start_url
        self.min_interval = min_interval
        self.max_pages = max_pages
        self.indexer: Optional[Indexer] = None

    # ------------------------------------------------------------------
    # Command implementations
    # ------------------------------------------------------------------
    #: Path prefixes excluded from the BFS frontier during ``build``.
    #:
    #: * ``/login``    -- the login form has no useful searchable content.
    #: * ``/tag/``     -- tag listing pages merely re-arrange quote text
    #:                    that already appears on ``/`` and ``/page/N/``;
    #:                    indexing them would inflate document
    #:                    frequencies without adding new information.
    #:                    Tag *names* are still indexed because they are
    #:                    visible text on the listing pages themselves.
    #: * ``/page/1/``  -- exact duplicate of ``/``; reachable via the
    #:                    "Previous" button on ``/page/2/``.  Skipping
    #:                    it avoids indexing the home page twice under
    #:                    two different URLs.  We follow "Next" links
    #:                    only — "Previous" goes to ``/page/1/`` which
    #:                    is filtered here.
    BUILD_SKIP_PATH_PREFIXES = ("/login", "/tag/", "/page/1/")

    def cmd_build(self) -> str:
        """Crawl the target site with a generic BFS and build an index.

        Starting from :attr:`start_url`, the crawler follows every
        in-domain ``<a href>`` link it encounters, except for paths
        listed in :attr:`BUILD_SKIP_PATH_PREFIXES`.  This means the same
        code would work on any single-domain website; nothing about the
        traversal is hard-coded for ``quotes.toscrape.com``.

        Each ``build`` invocation discards any pre-existing
        ``data/index.json`` and re-crawls from scratch.  The index is
        flushed to disk atomically after every successfully indexed
        page so a crash mid-crawl leaves a valid (partial) file behind
        — it will simply be overwritten on the next ``build``.
        """
        # --- 0. Always start with a fresh index ------------------------
        if os.path.exists(self.index_path):
            print(
                f"Removing existing index at {self.index_path} "
                f"(build always re-crawls from scratch)."
            )
            os.remove(self.index_path)
        indexer = Indexer()
        crawler = Crawler(
            start_url=self.start_url,
            min_interval=self.min_interval,
            max_pages=self.max_pages,
            skip_path_prefixes=self.BUILD_SKIP_PATH_PREFIXES,
        )

        skipped = ", ".join(self.BUILD_SKIP_PATH_PREFIXES) or "(none)"
        print(
            f"BFS-crawling {self.start_url} "
            f"(skipping path prefixes: {skipped})…"
        )

        pages_done = 0
        for result in crawler.crawl():
            indexer.add_document(result.url, result.html)
            indexer.save(self.index_path)  # checkpoint after every page
            pages_done += 1
            print(f"  indexed [{pages_done}] {result.url}")

        if indexer.document_count == 0:
            return "Crawl finished with 0 pages indexed; nothing was saved."

        self.indexer = indexer
        path = os.path.abspath(self.index_path)
        return (
            f"Build complete: crawled {pages_done} page(s), "
            f"{indexer.document_count} document(s) in index, "
            f"{indexer.vocabulary_size} term(s).\n"
            f"Index saved to {path}"
        )

    def cmd_load(self) -> str:
        """Load the index from :attr:`index_path` and dump its structure."""
        try:
            self.indexer = Indexer.load(self.index_path)
        except FileNotFoundError as exc:
            return str(exc)
        except (ValueError, OSError) as exc:
            return f"Failed to load index: {exc}"
        return (
            f"Loaded index from {self.index_path}: "
            f"{self.indexer.document_count} document(s), "
            f"{self.indexer.vocabulary_size} term(s).\n"
            + self._format_index_structure(self.indexer)
        )

    @staticmethod
    def _format_index_structure(indexer: Indexer, *,
                                sample_docs: int = 3,
                                top_terms: int = 10) -> str:
        """Return a human-readable summary of an index's structure.

        Shows the data-model schema, a few sample document entries and
        the most frequent terms.  This is what ``load`` prints after the
        one-line summary so the user can immediately see *what* was
        loaded, not just *how much*.
        """
        lines: List[str] = []
        lines.append("")
        lines.append("Index structure:")
        lines.append("  documents:      url -> {length, title}")
        lines.append("  inverted_index: term -> {url -> {freq, positions}}")

        # Sample documents
        lines.append("")
        lines.append(f"Sample documents (first {sample_docs}):")
        for url, meta in list(indexer.documents.items())[:sample_docs]:
            title = meta.get("title", "")
            length = meta.get("length", 0)
            lines.append(
                f"  {url}\n      length={length}, title={title!r}"
            )

        # Top-N terms by document frequency.
        ranked = sorted(
            indexer.inverted_index.items(),
            key=lambda kv: (-len(kv[1]), kv[0]),
        )[:top_terms]
        lines.append("")
        lines.append(f"Top {top_terms} terms by document frequency:")
        for term, postings in ranked:
            total = sum(int(p["freq"]) for p in postings.values())
            lines.append(
                f"  {term!r:<14} df={len(postings):<3} total_occurrences={total}"
            )
        return "\n".join(lines)

    def cmd_print(self, args: Sequence[str]) -> str:
        if not self.indexer:
            return "No index loaded. Run 'build' or 'load' first."
        if len(args) != 1:
            return "Usage: print <word>"
        engine = SearchEngine(self.indexer)
        return engine.print_word(args[0])

    def cmd_find(self, args: Sequence[str]) -> str:
        if not self.indexer:
            return "No index loaded. Run 'build' or 'load' first."
        if not args:
            return "Usage: find <query>"
        engine = SearchEngine(self.indexer)
        query = " ".join(args)
        hits = engine.find(query)
        return engine.format_find_results(query, hits)

    def cmd_stats(self) -> str:
        if not self.indexer:
            return "No index loaded. Run 'build' or 'load' first."
        return (
            f"Documents: {self.indexer.document_count}\n"
            f"Vocabulary: {self.indexer.vocabulary_size}\n"
            f"Index path: {self.index_path}"
        )

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def dispatch(self, line: str) -> Optional[str]:
        """Parse and execute a single command line.

        Returns the textual response to print, or ``None`` if the shell
        should terminate.
        """
        line = (line or "").strip()
        if not line:
            return ""
        if line.startswith("#"):
            return ""

        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            return f"Parse error: {exc}"

        cmd, args = tokens[0].lower(), tokens[1:]
        if cmd in {"quit", "exit"}:
            return None
        if cmd == "help":
            return HELP_TEXT
        if cmd == "build":
            return self.cmd_build()
        if cmd == "load":
            return self.cmd_load()
        if cmd == "print":
            return self.cmd_print(args)
        if cmd == "find":
            return self.cmd_find(args)
        if cmd == "stats":
            return self.cmd_stats()
        return f"Unknown command: {cmd!r}. Type 'help' for the command list."

    # ------------------------------------------------------------------
    # Interactive REPL
    # ------------------------------------------------------------------
    def run(self) -> int:
        print("Search Engine Tool. Type 'help' for available commands.")
        while True:
            try:
                line = input("search> ")
            except EOFError:
                print()
                return 0
            except KeyboardInterrupt:
                print("\n(use 'quit' to exit)")
                continue

            response = self.dispatch(line)
            if response is None:
                return 0
            if response:
                print(response)


# ----------------------------------------------------------------------
# Argument parsing / entry-point
# ----------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="search-engine-tool",
        description="Interactive search engine for quotes.toscrape.com.",
    )
    parser.add_argument(
        "--start-url",
        default=DEFAULT_START_URL,
        help="URL to start crawling from (default: %(default)s).",
    )
    parser.add_argument(
        "--index-path",
        default=DEFAULT_INDEX_PATH,
        help="Where to read/write the inverted index file (default: %(default)s).",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=MIN_REQUEST_INTERVAL,
        help=(
            "Minimum seconds between HTTP requests. Must be >= 6 to comply "
            "with the politeness requirement (default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional cap on the number of pages fetched during 'build'.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help=(
            "Optional command to run non-interactively, e.g. "
            "'build' or 'find good friends'."
        ),
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    shell = Shell(
        index_path=args.index_path,
        start_url=args.start_url,
        min_interval=args.min_interval,
        max_pages=args.max_pages,
    )

    if args.command:
        line = " ".join(args.command)
        # Auto-load the saved index for read-only commands so users can
        # invoke ``python -m src.main find good friends`` without first
        # running ``load`` in the same process.
        first_token = line.strip().split(" ", 1)[0].lower() if line.strip() else ""
        if (
            first_token in {"print", "find", "stats"}
            and shell.indexer is None
            and os.path.exists(args.index_path)
        ):
            shell.cmd_load()
        response = shell.dispatch(line)
        if response:
            print(response)
        return 0
    return shell.run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
