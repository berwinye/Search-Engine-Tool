"""Tests for :mod:`src.main`'s dispatch logic."""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import Dict, List
from unittest import mock

from src import main as main_module
from src.crawler import Crawler
from src.indexer import Indexer
from src.main import HELP_TEXT, Shell, main


class _ShellFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.index_path = os.path.join(self.tmpdir.name, "index.json")
        self.shell = Shell(index_path=self.index_path)

        # Pre-populate an index file the shell can load.
        idx = Indexer()
        idx.add_document(
            "https://example.com/a",
            "<title>A</title><p>good friends are good</p>",
        )
        idx.add_document(
            "https://example.com/b",
            "<title>B</title><p>good evening</p>",
        )
        idx.save(self.index_path)


class DispatchBasicCommandsTests(_ShellFixture):
    def test_help_returns_help_text(self) -> None:
        self.assertEqual(self.shell.dispatch("help"), HELP_TEXT)

    def test_blank_input_returns_empty(self) -> None:
        self.assertEqual(self.shell.dispatch(""), "")
        self.assertEqual(self.shell.dispatch("   "), "")
        self.assertEqual(self.shell.dispatch("# a comment"), "")

    def test_quit_returns_none(self) -> None:
        self.assertIsNone(self.shell.dispatch("quit"))
        self.assertIsNone(self.shell.dispatch("exit"))

    def test_unknown_command(self) -> None:
        out = self.shell.dispatch("nope")
        self.assertIn("Unknown command", out)

    def test_parse_error_on_unbalanced_quotes(self) -> None:
        out = self.shell.dispatch('find "unbalanced')
        self.assertIn("Parse error", out)


class DispatchRequiringIndexTests(_ShellFixture):
    def test_print_without_index_returns_friendly_error(self) -> None:
        out = self.shell.dispatch("print good")
        self.assertIn("No index loaded", out)

    def test_find_without_index_returns_friendly_error(self) -> None:
        out = self.shell.dispatch("find good")
        self.assertIn("No index loaded", out)

    def test_stats_without_index_returns_friendly_error(self) -> None:
        out = self.shell.dispatch("stats")
        self.assertIn("No index loaded", out)


class DispatchAfterLoadTests(_ShellFixture):
    def setUp(self) -> None:
        super().setUp()
        load_response = self.shell.dispatch("load")
        self.assertIn("Loaded index", load_response)

    def test_print_known_term(self) -> None:
        out = self.shell.dispatch("print good")
        self.assertIn("Term: good", out)
        self.assertIn("Document frequency: 2", out)

    def test_print_requires_one_argument(self) -> None:
        self.assertEqual(self.shell.dispatch("print"), "Usage: print <word>")
        # Multiple bare arguments -> usage error
        self.assertEqual(
            self.shell.dispatch("print good friends"),
            "Usage: print <word>",
        )

    def test_find_multi_word_query(self) -> None:
        out = self.shell.dispatch("find good friends")
        self.assertIn("Found 1 page(s)", out)
        self.assertIn("https://example.com/a", out)

    def test_find_no_args_usage(self) -> None:
        self.assertEqual(self.shell.dispatch("find"), "Usage: find <query>")

    def test_find_quoted_phrase_treated_as_separate_terms(self) -> None:
        out = self.shell.dispatch('find "good evening"')
        self.assertIn("Found 1 page(s)", out)
        self.assertIn("https://example.com/b", out)

    def test_stats_after_load(self) -> None:
        out = self.shell.dispatch("stats")
        self.assertIn("Documents: 2", out)
        self.assertIn("Vocabulary:", out)


class LoadErrorTests(unittest.TestCase):
    def test_load_missing_file_returns_friendly_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shell = Shell(index_path=os.path.join(tmp, "nope.json"))
            out = shell.dispatch("load")
            self.assertIn("Index file not found", out)


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


class _FakeSession:
    def __init__(self, pages: Dict[str, _FakeResponse]) -> None:
        self.pages = pages
        self.headers: Dict[str, str] = {}
        self.calls: List[str] = []

    def get(self, url: str, timeout: float = 0) -> _FakeResponse:
        self.calls.append(url)
        if url not in self.pages:
            return _FakeResponse("", status_code=404)
        return self.pages[url]


def _make_quotes_pages() -> Dict[str, _FakeResponse]:
    """Return fake responses mimicking the quotes.toscrape.com layout."""
    base = "https://quotes.toscrape.com"
    pages: Dict[str, _FakeResponse] = {}
    # Listing pages 1..10, each linking to a couple of authors and a tag.
    listings = [base + "/"] + [f"{base}/page/{n}/" for n in range(2, 11)]
    for idx, url in enumerate(listings, start=1):
        # "Next page" link mirrors the real quotes.toscrape.com markup so
        # a generic BFS crawl can discover all 10 listing pages from /.
        next_link = (
            f"<a href='/page/{idx + 1}/'>next</a>" if idx < 10 else ""
        )
        pages[url] = _FakeResponse(
            f"<html><head><title>Quotes p{idx}</title></head><body>"
            f"<p>quote on page {idx}</p>"
            f"<a href='/author/Author-{idx}'>a{idx}</a>"
            # Repeat the same author across pages to test de-duplication.
            f"<a href='/author/Author-Common'>common</a>"
            # Tag links must be ignored.
            f"<a href='/tag/love/page/1/'>tag</a>"
            f"<a href='/login'>login</a>"
            f"{next_link}"
            f"</body></html>"
        )
    # Author pages.
    for idx in range(1, 11):
        pages[f"{base}/author/Author-{idx}"] = _FakeResponse(
            f"<html><title>Author {idx}</title>"
            f"<p>biography of author {idx}</p></html>"
        )
    pages[f"{base}/author/Author-Common"] = _FakeResponse(
        "<html><title>Common</title><p>shared author bio</p></html>"
    )
    return pages


class TwoPhaseBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.index_path = os.path.join(self.tmpdir.name, "index.json")
        self.session = _FakeSession(_make_quotes_pages())

        # Patch ``src.main.Crawler`` so any Crawler instantiated by the
        # build command shares our fake session and runs without
        # actually sleeping.
        original = Crawler

        def factory(**kwargs: object) -> Crawler:
            kwargs.setdefault("session", self.session)
            kwargs["min_interval"] = 0.0
            kwargs["sleep"] = lambda s: None
            return original(**kwargs)  # type: ignore[arg-type]

        patcher = mock.patch.object(main_module, "Crawler", side_effect=factory)
        self.mock_crawler = patcher.start()
        self.addCleanup(patcher.stop)

    def test_build_fetches_only_listing_and_author_pages(self) -> None:
        shell = Shell(index_path=self.index_path)
        shell.cmd_build()
        # 10 listing + 11 unique authors (Author-1..10 + Author-Common)
        self.assertEqual(shell.indexer.document_count, 21)
        # No tag/login URLs were ever requested.
        for url in self.session.calls:
            self.assertNotIn("/tag/", url)
            self.assertNotIn("/login", url)

    def test_build_dedupes_author_links(self) -> None:
        shell = Shell(index_path=self.index_path)
        shell.cmd_build()
        common = "https://quotes.toscrape.com/author/Author-Common"
        # The shared author URL must be requested exactly once even
        # though every listing page links to it.
        self.assertEqual(self.session.calls.count(common), 1)

    def test_build_saves_after_every_page(self) -> None:
        shell = Shell(index_path=self.index_path)
        # Patch Indexer.save to count invocations.
        with mock.patch.object(
            Indexer, "save", autospec=True, side_effect=Indexer.save
        ) as save_spy:
            shell.cmd_build()
        # One save per indexed document.
        self.assertEqual(save_spy.call_count, shell.indexer.document_count)

    def test_build_always_recrawls_from_scratch(self) -> None:
        # First build: full run.
        Shell(index_path=self.index_path).cmd_build()
        first_calls = list(self.session.calls)
        self.session.calls.clear()

        # Second build on the same on-disk index: must discard the old
        # index and re-fetch every URL from scratch.
        result = Shell(index_path=self.index_path).cmd_build()
        self.assertEqual(
            sorted(self.session.calls), sorted(first_calls),
            "Second build should re-issue exactly the same HTTP requests "
            "as the first build.",
        )
        self.assertIn("Build complete", result)

    def test_build_discards_preexisting_index(self) -> None:
        # Pre-seed the index file with stale/foreign data that must be
        # wiped out — these URLs are NOT in the fake-fixture site map.
        seed = Indexer()
        seed.add_document(
            "https://example.com/stale-1",
            "<title>Stale</title><p>old data</p>",
        )
        seed.add_document(
            "https://example.com/stale-2",
            "<title>Stale 2</title><p>more old data</p>",
        )
        seed.save(self.index_path)

        Shell(index_path=self.index_path).cmd_build()

        # Reload from disk and confirm seeded URLs are gone.
        loaded = Indexer.load(self.index_path)
        self.assertNotIn("https://example.com/stale-1", loaded.documents)
        self.assertNotIn("https://example.com/stale-2", loaded.documents)
        # Real fixture URLs are present.
        self.assertIn("https://quotes.toscrape.com/", loaded.documents)


class MainEntrypointTests(_ShellFixture):
    def test_main_runs_one_shot_load(self) -> None:
        rc = main([
            "--index-path", self.index_path,
            "load",
        ])
        self.assertEqual(rc, 0)

    def test_main_one_shot_find_auto_loads_index(self) -> None:
        # ``find`` should auto-load the on-disk index when the file exists
        # so users do not have to chain commands manually.
        rc = main([
            "--index-path", self.index_path,
            "find", "good", "friends",
        ])
        self.assertEqual(rc, 0)

    def test_main_one_shot_stats_without_index_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.json")
            rc = main(["--index-path", missing, "stats"])
            self.assertEqual(rc, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
