"""Tests for :mod:`src.search`."""

from __future__ import annotations

import unittest

from src.indexer import Indexer
from src.search import SearchEngine, SearchHit


def _build_indexer() -> Indexer:
    """Construct a tiny in-memory index used by every test below."""
    indexer = Indexer()
    indexer.add_document(
        "https://example.com/a",
        "<title>Friendship</title>"
        "<p>Good friends are good. Friends matter.</p>",
    )
    indexer.add_document(
        "https://example.com/b",
        "<title>Wisdom</title>"
        "<p>A good book teaches wisdom.</p>",
    )
    indexer.add_document(
        "https://example.com/c",
        "<title>Travel</title>"
        "<p>Travel broadens the mind.</p>",
    )
    return indexer


class PrintWordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SearchEngine(_build_indexer())

    def test_prints_known_term(self) -> None:
        out = self.engine.print_word("good")
        self.assertIn("Term: good", out)
        self.assertIn("Document frequency: 2", out)
        # 'good' appears 2x in /a and 1x in /b -> total 3
        self.assertIn("Total occurrences:  3", out)
        self.assertIn("https://example.com/a", out)
        self.assertIn("https://example.com/b", out)

    def test_print_word_is_case_insensitive(self) -> None:
        self.assertIn("Term: good", self.engine.print_word("GOOD"))
        self.assertIn("Term: good", self.engine.print_word("Good"))

    def test_print_unknown_term(self) -> None:
        self.assertIn("not in the index", self.engine.print_word("nonsense"))

    def test_print_empty_input(self) -> None:
        self.assertEqual(self.engine.print_word(""), "Usage: print <word>")
        self.assertEqual(self.engine.print_word("   "), "Usage: print <word>")

    def test_print_rejects_multi_token_input(self) -> None:
        out = self.engine.print_word("good friends")
        self.assertIn("single word", out)

    def test_print_rejects_pure_punctuation(self) -> None:
        out = self.engine.print_word("!!!")
        self.assertIn("No indexable token", out)


class FindTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SearchEngine(_build_indexer())

    def test_find_single_word(self) -> None:
        hits = self.engine.find("good")
        urls = {h.url for h in hits}
        self.assertEqual(urls, {"https://example.com/a", "https://example.com/b"})
        self.assertTrue(all(isinstance(h, SearchHit) for h in hits))

    def test_find_multi_word_returns_intersection(self) -> None:
        hits = self.engine.find("good friends")
        # Only document /a contains both 'good' and 'friends'.
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].url, "https://example.com/a")
        self.assertEqual(hits[0].matched_terms, {"good": 2, "friends": 2})

    def test_find_is_case_insensitive(self) -> None:
        hits_lower = self.engine.find("good friends")
        hits_upper = self.engine.find("GOOD FRIENDS")
        self.assertEqual(
            [h.url for h in hits_lower], [h.url for h in hits_upper]
        )

    def test_find_unknown_term_returns_empty(self) -> None:
        self.assertEqual(self.engine.find("zzz_unknown"), [])
        # If any one of multiple terms is unknown, intersection is empty.
        self.assertEqual(self.engine.find("good zzz_unknown"), [])

    def test_find_empty_query_returns_empty(self) -> None:
        self.assertEqual(self.engine.find(""), [])
        self.assertEqual(self.engine.find("   "), [])

    def test_find_query_with_only_punctuation(self) -> None:
        self.assertEqual(self.engine.find("!!!---"), [])

    def test_find_strips_punctuation_inside_query(self) -> None:
        # Punctuation in the query should not prevent matching.
        hits = self.engine.find("good, friends!")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].url, "https://example.com/a")

    def test_find_ranking_prefers_higher_tfidf(self) -> None:
        engine = SearchEngine(_build_indexer())
        hits = engine.find("good")
        # /a has 2 occurrences in a 7-token doc; /b has 1 in a 6-token doc.
        # /a should outrank /b.
        self.assertEqual(hits[0].url, "https://example.com/a")
        self.assertEqual(hits[1].url, "https://example.com/b")
        self.assertGreater(hits[0].score, hits[1].score)

    def test_find_respects_limit(self) -> None:
        hits = self.engine.find("good", limit=1)
        self.assertEqual(len(hits), 1)

    def test_find_duplicate_terms_in_query_are_deduplicated(self) -> None:
        single = self.engine.find("good")
        repeated = self.engine.find("good good good")
        self.assertEqual(
            [h.url for h in single], [h.url for h in repeated]
        )


class FormatFindResultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SearchEngine(_build_indexer())

    def test_format_with_results(self) -> None:
        hits = self.engine.find("good")
        out = self.engine.format_find_results("good", hits)
        self.assertIn("Found 2 page(s)", out)
        self.assertIn("https://example.com/a", out)

    def test_format_no_results(self) -> None:
        out = self.engine.format_find_results("zzz", [])
        self.assertIn("No pages match", out)

    def test_format_empty_query(self) -> None:
        self.assertEqual(
            self.engine.format_find_results("", []),
            "Usage: find <query>",
        )


class EmptyIndexTests(unittest.TestCase):
    def test_search_on_empty_index_returns_empty(self) -> None:
        engine = SearchEngine(Indexer())
        self.assertEqual(engine.find("good"), [])
        self.assertIn("not in the index", engine.print_word("good"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
