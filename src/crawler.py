"""Crawler module for the search engine tool.

This module provides a polite, throttled web crawler for
``https://quotes.toscrape.com/``.  It fetches pages sequentially with at
least ``MIN_REQUEST_INTERVAL`` seconds between consecutive HTTP requests
(coursework requirement) and yields ``(url, html)`` pairs so the caller
(typically the indexer) can process pages incrementally.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional, Set, Tuple
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

#: Minimum number of seconds that must elapse between two consecutive
#: HTTP requests to the target site.  The coursework brief requires a
#: 6-second politeness window.
MIN_REQUEST_INTERVAL: float = 6.0

#: Default starting URL for the crawl.
DEFAULT_START_URL: str = "https://quotes.toscrape.com/"

#: Default User-Agent string used for outgoing requests.
DEFAULT_USER_AGENT: str = (
    "COMP-XJCO3011-SearchEngineTool/1.0 (+educational coursework crawler)"
)


@dataclass
class CrawlResult:
    """Container describing a single successfully fetched page."""

    url: str
    html: str
    status_code: int = 200


@dataclass
class Crawler:
    """A polite, single-domain breadth-first crawler.

    Parameters
    ----------
    start_url:
        URL to begin crawling from.
    min_interval:
        Minimum seconds between two consecutive HTTP requests.  Defaults
        to :data:`MIN_REQUEST_INTERVAL` (6 seconds).  Must be ``>= 6`` to
        comply with the coursework politeness requirement; lower values
        are accepted only for unit testing and a warning is logged.
    timeout:
        Per-request timeout in seconds.
    user_agent:
        User-Agent header value used for all requests.
    max_pages:
        Optional cap on the number of pages to crawl.  ``None`` means no
        limit (the crawler stops naturally when the frontier is empty).
    session:
        Optional pre-configured :class:`requests.Session`.  Mainly used
        to inject a mock session in tests.
    sleep:
        Sleep callable, defaults to :func:`time.sleep`.  Overridable so
        tests can run without actually sleeping.
    clock:
        Monotonic clock callable returning seconds.  Overridable for
        deterministic testing.
    skip_path_prefixes:
        Tuple of URL-path prefixes that, if matched, exclude a discovered
        link from the BFS frontier.  Used by callers (e.g. ``cmd_build``)
        to filter out paths that have no useful indexable content (e.g.
        ``/login``) or that merely re-arrange content already indexed
        elsewhere (e.g. ``/tag/`` listing pages).  The ``start_url``
        itself is **not** filtered.
    """

    start_url: str = DEFAULT_START_URL
    min_interval: float = MIN_REQUEST_INTERVAL
    timeout: float = 15.0
    user_agent: str = DEFAULT_USER_AGENT
    max_pages: Optional[int] = None
    session: Optional[requests.Session] = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    skip_path_prefixes: Tuple[str, ...] = ()

    _last_request_time: Optional[float] = field(default=None, init=False, repr=False)
    _visited: Set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.min_interval < MIN_REQUEST_INTERVAL:
            logger.warning(
                "min_interval=%.2fs is below the required %.2fs politeness "
                "window; this should only be used in tests.",
                self.min_interval,
                MIN_REQUEST_INTERVAL,
            )
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({"User-Agent": self.user_agent})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def crawl(self) -> Iterator[CrawlResult]:
        """Yield :class:`CrawlResult` objects for every successfully fetched page.

        Pages that fail to download are logged and skipped, never raised,
        so a single bad URL cannot abort an entire crawl run.
        """
        start = self._normalize(self.start_url)
        if not start:
            return
        domain = urlparse(start).netloc
        frontier: "deque[str]" = deque([start])
        self._visited = {start}

        pages_yielded = 0
        while frontier:
            if self.max_pages is not None and pages_yielded >= self.max_pages:
                logger.info("Reached max_pages=%d, stopping crawl.", self.max_pages)
                break

            url = frontier.popleft()
            result = self._fetch(url)
            if result is None:
                continue

            yield result
            pages_yielded += 1

            for link in self._extract_links(result.html, base_url=url, domain=domain):
                if link not in self._visited:
                    self._visited.add(link)
                    frontier.append(link)

    # ------------------------------------------------------------------
    # HTTP fetch with throttling + error handling
    # ------------------------------------------------------------------
    def fetch(self, url: str) -> Optional[CrawlResult]:
        """Public wrapper around :meth:`_fetch`.

        Useful for orchestrators (e.g. the two-phase ``build`` flow in
        :mod:`src.main`) that want to drive the URL queue themselves
        while still relying on the crawler's politeness window and
        error handling.
        """
        return self._fetch(url)

    def iter_links(
        self, html: str, base_url: str, domain: Optional[str] = None
    ) -> Iterator[str]:
        """Public wrapper that yields normalized in-domain links.

        ``domain`` defaults to the host of :attr:`start_url`.
        """
        if domain is None:
            domain = urlparse(self.start_url).netloc
        return self._extract_links(html, base_url=base_url, domain=domain)

    def _fetch(self, url: str) -> Optional[CrawlResult]:
        """Fetch ``url`` honoring the politeness window.

        Returns ``None`` if the request fails for any reason.
        """
        self._respect_throttle()
        logger.info("Fetching %s", url)
        try:
            assert self.session is not None  # for type checkers
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.error("Request failed for %s: %s", url, exc)
            self._last_request_time = self.clock()
            return None
        finally:
            # Record the time even when the request raised so subsequent
            # calls remain polite.
            self._last_request_time = self.clock()

        if response.status_code != 200:
            logger.warning(
                "Skipping %s (HTTP %s)", url, response.status_code
            )
            return None

        return CrawlResult(url=url, html=response.text, status_code=response.status_code)

    def _respect_throttle(self) -> None:
        """Sleep until the politeness window has elapsed."""
        if self._last_request_time is None:
            return
        elapsed = self.clock() - self._last_request_time
        wait = self.min_interval - elapsed
        if wait > 0:
            logger.debug("Throttling for %.2fs", wait)
            self.sleep(wait)

    # ------------------------------------------------------------------
    # Link extraction
    # ------------------------------------------------------------------
    def _extract_links(
        self, html: str, base_url: str, domain: str
    ) -> Iterator[str]:
        """Yield normalized in-domain links found in ``html``."""
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            absolute = urljoin(base_url, anchor["href"])
            normalized = self._normalize(absolute)
            if not normalized:
                continue
            parsed = urlparse(normalized)
            if parsed.netloc != domain:
                continue
            if parsed.scheme not in {"http", "https"}:
                continue
            if self._is_skipped(parsed.path):
                continue
            yield normalized

    def _is_skipped(self, path: str) -> bool:
        """Return True if ``path`` matches any of :attr:`skip_path_prefixes`."""
        return any(path.startswith(prefix) for prefix in self.skip_path_prefixes)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize(url: str) -> str:
        """Return ``url`` without fragment and trailing whitespace."""
        if not url:
            return ""
        url, _frag = urldefrag(url.strip())
        return url


def crawl_site(
    start_url: str = DEFAULT_START_URL,
    *,
    min_interval: float = MIN_REQUEST_INTERVAL,
    max_pages: Optional[int] = None,
    session: Optional[requests.Session] = None,
) -> Iterator[CrawlResult]:
    """Convenience function returning an iterator of :class:`CrawlResult`.

    This is a thin wrapper around :class:`Crawler` for callers that do
    not need to subclass or further configure the crawler.
    """
    crawler = Crawler(
        start_url=start_url,
        min_interval=min_interval,
        max_pages=max_pages,
        session=session,
    )
    yield from crawler.crawl()
