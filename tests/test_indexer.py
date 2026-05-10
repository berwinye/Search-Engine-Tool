"""Tests for :mod:`src.indexer`."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from src.indexer import (
    DEFAULT_INDEX_PATH,
    Indexer,
    build_index_from_pages,
    extract_visible_text,
    tokenize,
)


class TokenizeTests(unittest.TestCase):
    def test_tokenize_lowercases_output(self) -> None:
        self.assertEqual(tokenize("Good GOOD good"), ["good", "good", "good"])

    def test_tokenize_strips_punctuation(self) -> None:
        self.assertEqual(
            tokenize("Hello, world! It's nice."),
            ["hello", "world", "it's", "nice"],
        )

    def test_tokenize_handles_numbers(self) -> None:
        self.assertEqual(tokenize("Top 10 quotes 2024"), ["top", "10", "quotes", "2024"])

    def test_tokenize_handles_empty_input(self) -> None:
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("   "), [])
        self.assertEqual(tokenize(None), [])  # type: ignore[arg-type]

    def test_tokenize_drops_pure_symbols(self) -> None:
        self.assertEqual(tokenize("!!!---***"), [])


class ExtractVisibleTextTests(unittest.TestCase):
    def test_skips_script_and_style_tags(self) -> None:
        html = """
            <html>
              <head>
                <title> Quotes </title>
                <style>.x { color: red; }</style>
              </head>
              <body>
                <script>var x = 1;</script>
                <p>Hello world.</p>
              </body>
            </html>
        """
        title, body = extract_visible_text(html)
        self.assertEqual(title, "Quotes")
        self.assertIn("Hello world.", body)
        self.assertNotIn("color", body)
        self.assertNotIn("var x", body)

    def test_handles_empty_html(self) -> None:
        title, body = extract_visible_text("")
        self.assertEqual(title, "")
        self.assertEqual(body, "")


class IndexerAddDocumentTests(unittest.TestCase):
    def test_indexes_single_document(self) -> None:
        indexer = Indexer()
        indexer.add_document(
            "https://example.com/a",
            "<title>T</title><p>Good friends are good.</p>",
        )
        self.assertEqual(indexer.document_count, 1)
        self.assertEqual(indexer.document_length("https://example.com/a"), 5)
        good = indexer.postings("good")
        self.assertEqual(good["https://example.com/a"]["freq"], 2)
        self.assertEqual(good["https://example.com/a"]["positions"], [1, 4])

    def test_case_insensitive_indexing(self) -> None:
        indexer = Indexer()
        indexer.add_document(
            "https://example.com/a",
            "<p>Good GOOD gOOd</p>",
        )
        # Same word stored under same key irrespective of original case.
        self.assertIn("good", indexer.inverted_index)
        self.assertNotIn("GOOD", indexer.inverted_index)
        self.assertEqual(
            indexer.postings("good")["https://example.com/a"]["freq"], 3
        )

    def test_re_indexing_replaces_previous_entry(self) -> None:
        indexer = Indexer()
        url = "https://example.com/a"
        indexer.add_document(url, "<p>alpha beta</p>")
        indexer.add_document(url, "<p>gamma</p>")
        self.assertNotIn(url, indexer.postings("alpha"))
        self.assertNotIn(url, indexer.postings("beta"))
        self.assertIn(url, indexer.postings("gamma"))
        self.assertEqual(indexer.document_count, 1)

    def test_add_document_rejects_empty_url(self) -> None:
        indexer = Indexer()
        with self.assertRaises(ValueError):
            indexer.add_document("", "<p>x</p>")

    def test_add_documents_aggregates_counts(self) -> None:
        indexer = Indexer()
        total = indexer.add_documents([
            ("https://example.com/a", "<p>good day</p>"),
            ("https://example.com/b", "<p>good evening friend</p>"),
        ])
        self.assertEqual(total, 5)
        self.assertEqual(indexer.document_frequency("good"), 2)
        self.assertEqual(indexer.document_frequency("day"), 1)
        self.assertEqual(indexer.document_frequency("missing"), 0)


class IndexerSerialisationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = os.path.join(self.tmpdir.name, "data", "index.json")

    def _build(self) -> Indexer:
        indexer = Indexer()
        indexer.add_document(
            "https://example.com/a", "<title>A</title><p>good day friend</p>"
        )
        indexer.add_document(
            "https://example.com/b", "<title>B</title><p>good evening</p>"
        )
        return indexer

    def test_save_creates_file_and_directory(self) -> None:
        indexer = self._build()
        path = indexer.save(self.path)
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertIn("inverted_index", payload)
        self.assertIn("documents", payload)
        self.assertEqual(payload["version"], 1)

    def test_load_round_trips_index(self) -> None:
        original = self._build()
        original.save(self.path)
        loaded = Indexer.load(self.path)
        self.assertEqual(loaded.document_count, original.document_count)
        self.assertEqual(loaded.vocabulary_size, original.vocabulary_size)
        self.assertEqual(
            loaded.postings("good"), original.postings("good")
        )

    def test_load_raises_on_missing_file(self) -> None:
        with self.assertRaises(FileNotFoundError):
            Indexer.load(os.path.join(self.tmpdir.name, "missing.json"))

    def test_default_index_path_is_under_data_dir(self) -> None:
        # Sanity check: the default points at the project's data folder.
        self.assertTrue(DEFAULT_INDEX_PATH.startswith("data" + os.sep)
                        or DEFAULT_INDEX_PATH.startswith("data/"))


class BuildHelperTests(unittest.TestCase):
    def test_build_index_from_pages_saves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "idx.json")
            indexer = build_index_from_pages(
                [("https://example.com/", "<p>good</p>")],
                save_path=path,
            )
            self.assertEqual(indexer.document_count, 1)
            self.assertTrue(os.path.exists(path))

    def test_build_index_from_pages_skip_save(self) -> None:
        indexer = build_index_from_pages(
            [("https://example.com/", "<p>good</p>")],
            save_path=None,
        )
        self.assertEqual(indexer.document_count, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
