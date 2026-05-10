"""Tests for :mod:`src.crawler`.

The tests use an in-memory fake :class:`requests.Session` so no real
HTTP traffic is generated and the suite runs in a fraction of a
second.  The clock and sleep callables are also injected so the
6-second politeness window can be asserted deterministically.
"""

from __future__ import annotations

import unittest
from typing import Dict, List, Optional
from unittest import mock

import requests

from src.crawler import (
    DEFAULT_USER_AGENT,
    MIN_REQUEST_INTERVAL,
    CrawlResult,
    Crawler,
    crawl_site,
)


# ----------------------------------------------------------------------
# Test doubles
# ----------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


class _FakeSession:
    """Minimal stand-in for :class:`requests.Session` used in tests."""

    def __init__(self, pages: Dict[str, _FakeResponse]) -> None:
        self.pages = pages
        self.headers: Dict[str, str] = {}
        self.calls: List[str] = []

    def get(self, url: str, timeout: Optional[float] = None) -> _FakeResponse:
        self.calls.append(url)
        if url not in self.pages:
            raise requests.ConnectionError(f"unexpected URL {url!r}")
        response = self.pages[url]
        if isinstance(response, Exception):
            raise response
        return response


class _FakeClock:
    """Monotonic clock that only advances when ``advance`` is called."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: List[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        # A real sleep advances the clock; mirror that behaviour.
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------
class TokenizationFreeCrawlerTests(unittest.TestCase):
    def test_default_user_agent_is_set_on_session(self) -> None:
        crawler = Crawler()
        self.assertIn("User-Agent", crawler.session.headers)
        self.assertEqual(crawler.session.headers["User-Agent"], DEFAULT_USER_AGENT)

    def test_normalize_strips_fragments_and_whitespace(self) -> None:
        self.assertEqual(
            Crawler._normalize("  https://example.com/page#section  "),
            "https://example.com/page",
        )
        self.assertEqual(Crawler._normalize(""), "")

    def test_extract_links_only_returns_in_domain_http_urls(self) -> None:
        crawler = Crawler(start_url="https://quotes.toscrape.com/")
        html = """
            <html><body>
                <a href="/page/2/">next</a>
                <a href="https://other.example.com/">external</a>
                <a href="mailto:foo@bar">mail</a>
                <a href="https://quotes.toscrape.com/login">login</a>
                <a href="javascript:void(0)">js</a>
            </body></html>
        """
        links = list(
            crawler._extract_links(
                html,
                base_url="https://quotes.toscrape.com/",
                domain="quotes.toscrape.com",
            )
        )
        self.assertIn("https://quotes.toscrape.com/page/2/", links)
        self.assertIn("https://quotes.toscrape.com/login", links)
        self.assertNotIn("https://other.example.com/", links)
        # mailto / javascript schemes are skipped
        self.assertTrue(all(link.startswith("https://quotes.toscrape.com") for link in links))

    def test_extract_links_filters_skip_path_prefixes(self) -> None:
        """Configured ``skip_path_prefixes`` must drop matching links."""
        crawler = Crawler(
            start_url="https://quotes.toscrape.com/",
            skip_path_prefixes=("/login", "/tag/"),
        )
        html = """
            <html><body>
                <a href="/page/2/">next</a>
                <a href="/author/Some-One">author</a>
                <a href="/login">login</a>
                <a href="/tag/love/page/1/">tag-love</a>
                <a href="/tag/humor/">tag-humor</a>
            </body></html>
        """
        links = list(
            crawler._extract_links(
                html,
                base_url="https://quotes.toscrape.com/",
                domain="quotes.toscrape.com",
            )
        )
        self.assertIn("https://quotes.toscrape.com/page/2/", links)
        self.assertIn("https://quotes.toscrape.com/author/Some-One", links)
        # Skipped prefixes must not appear in the BFS frontier.
        self.assertNotIn("https://quotes.toscrape.com/login", links)
        self.assertFalse(
            any("/tag/" in link for link in links),
            f"tag links must be filtered, got {links!r}",
        )


class CrawlBehaviourTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = _FakeClock()
        self.pages = {
            "https://quotes.toscrape.com/": _FakeResponse(
                """
                <html><head><title>Home</title></head><body>
                    <a href="/page/2/">2</a>
                    <a href="/login">login</a>
                </body></html>
                """
            ),
            "https://quotes.toscrape.com/page/2/": _FakeResponse(
                "<html><body><a href='/'>home</a></body></html>"
            ),
            "https://quotes.toscrape.com/login": _FakeResponse(
                "<html><body>login form</body></html>"
            ),
        }
        self.session = _FakeSession(self.pages)
        self.crawler = Crawler(
            start_url="https://quotes.toscrape.com/",
            min_interval=MIN_REQUEST_INTERVAL,
            session=self.session,  # type: ignore[arg-type]
            sleep=self.clock.sleep,
            clock=self.clock,
        )

    def test_visits_every_in_domain_page_once(self) -> None:
        results = list(self.crawler.crawl())
        urls = [r.url for r in results]
        self.assertEqual(sorted(urls), sorted(self.pages.keys()))
        # No URL should be requested twice.
        self.assertEqual(len(self.session.calls), len(set(self.session.calls)))

    def test_throttles_for_six_seconds_between_requests(self) -> None:
        list(self.crawler.crawl())
        # 3 pages -> 2 inter-request sleeps
        self.assertEqual(len(self.clock.sleeps), 2)
        for waited in self.clock.sleeps:
            self.assertGreaterEqual(waited, MIN_REQUEST_INTERVAL - 1e-9)

    def test_does_not_sleep_before_first_request(self) -> None:
        next(self.crawler.crawl())
        self.assertEqual(self.clock.sleeps, [])

    def test_skips_external_links(self) -> None:
        self.pages["https://quotes.toscrape.com/"].text = (
            "<a href='https://other.example.com/'>x</a>"
            "<a href='/login'>login</a>"
        )
        # Reset crawler state.
        self.crawler = Crawler(
            start_url="https://quotes.toscrape.com/",
            min_interval=MIN_REQUEST_INTERVAL,
            session=self.session,  # type: ignore[arg-type]
            sleep=self.clock.sleep,
            clock=self.clock,
        )
        urls = [r.url for r in self.crawler.crawl()]
        self.assertNotIn("https://other.example.com/", urls)


class CrawlErrorHandlingTests(unittest.TestCase):
    def test_request_exception_is_swallowed(self) -> None:
        clock = _FakeClock()
        session = _FakeSession({
            "https://quotes.toscrape.com/": _FakeResponse(
                "<a href='/page/2/'>p2</a>"
            ),
            "https://quotes.toscrape.com/page/2/": requests.Timeout("boom"),  # type: ignore[dict-item]
        })
        crawler = Crawler(
            start_url="https://quotes.toscrape.com/",
            min_interval=MIN_REQUEST_INTERVAL,
            session=session,  # type: ignore[arg-type]
            sleep=clock.sleep,
            clock=clock,
        )
        results = list(crawler.crawl())
        # Only the first page survives; the timeout is logged and skipped.
        self.assertEqual([r.url for r in results], ["https://quotes.toscrape.com/"])

    def test_non_200_status_is_skipped(self) -> None:
        clock = _FakeClock()
        session = _FakeSession({
            "https://quotes.toscrape.com/": _FakeResponse(
                "<a href='/missing'>m</a>"
            ),
            "https://quotes.toscrape.com/missing": _FakeResponse("not found", 404),
        })
        crawler = Crawler(
            start_url="https://quotes.toscrape.com/",
            min_interval=MIN_REQUEST_INTERVAL,
            session=session,  # type: ignore[arg-type]
            sleep=clock.sleep,
            clock=clock,
        )
        urls = [r.url for r in crawler.crawl()]
        self.assertEqual(urls, ["https://quotes.toscrape.com/"])

    def test_max_pages_limits_crawl(self) -> None:
        clock = _FakeClock()
        session = _FakeSession({
            "https://quotes.toscrape.com/": _FakeResponse(
                "<a href='/page/2/'>2</a><a href='/page/3/'>3</a>"
            ),
            "https://quotes.toscrape.com/page/2/": _FakeResponse("<a href='/'>h</a>"),
            "https://quotes.toscrape.com/page/3/": _FakeResponse("<a href='/'>h</a>"),
        })
        crawler = Crawler(
            start_url="https://quotes.toscrape.com/",
            min_interval=MIN_REQUEST_INTERVAL,
            session=session,  # type: ignore[arg-type]
            sleep=clock.sleep,
            clock=clock,
            max_pages=2,
        )
        results = list(crawler.crawl())
        self.assertEqual(len(results), 2)


class CrawlSiteHelperTests(unittest.TestCase):
    def test_helper_yields_crawl_results(self) -> None:
        session = _FakeSession({
            "https://quotes.toscrape.com/": _FakeResponse("<p>hello</p>"),
        })
        with mock.patch("src.crawler.time.sleep"):
            results = list(
                crawl_site(
                    start_url="https://quotes.toscrape.com/",
                    min_interval=0.0,  # tests run fast
                    session=session,  # type: ignore[arg-type]
                )
            )
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], CrawlResult)
        self.assertEqual(results[0].url, "https://quotes.toscrape.com/")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
