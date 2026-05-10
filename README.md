# Search Engine Tool

> COMP/XJCO3011 Coursework 2 — a polite web crawler, inverted-index
> builder, and command-line search shell for
> [`https://quotes.toscrape.com/`](https://quotes.toscrape.com/).

## Project overview

This project ships a small but complete information-retrieval pipeline:

1. **Crawler** (`src/crawler.py`) — breadth-first, single-domain
   crawler that respects a strict **6-second politeness window**
   between consecutive HTTP requests and survives transient network
   failures.
2. **Indexer** (`src/indexer.py`) — incrementally builds an
   **inverted index** mapping every lowercase word to the documents it
   appears in, together with its term frequency and positions.  The
   index is serialised to a single JSON file under `data/`.
3. **Search engine** (`src/search.py`) — supports the required
   `print <word>` lookup and the `find <query>` multi-word query with
   AND-semantics and **TF-IDF ranking** (the high-mark extension).
4. **CLI shell** (`src/main.py`) — interactive REPL that wires the
   four required commands together: `build`, `load`, `print`, `find`.

The coursework requirements are summarised in `todo.md`.

## Repository layout

```
cw_web2/
├── src/
│   ├── crawler.py       # polite, throttled crawler
│   ├── indexer.py       # inverted-index builder + (de)serialiser
│   ├── search.py        # print / find / TF-IDF ranking
│   └── main.py          # CLI shell entry-point
├── tests/
│   ├── test_crawler.py
│   ├── test_indexer.py
│   ├── test_search.py
│   └── test_main.py
├── data/                # produced at runtime: data/index.json
├── requirements.txt
├── todo.md
└── README.md
```

## Installation

The project targets **Python 3.9+** and only depends on `requests`
and `beautifulsoup4`.

```bash
# 1. Clone / cd into the project
cd cw_web2

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate         # on Windows: .venv\Scripts\activate

# 3. Install runtime dependencies
pip install -r requirements.txt
```

## Running the search engine

### Interactive shell

```bash
python -m src.main
```

You will be greeted by a prompt:

```
Search Engine Tool. Type 'help' for available commands.
search>
```

### One-shot commands

Every shell command can also be invoked non-interactively:

```bash
python -m src.main build              # crawl + index + save
python -m src.main load               # just verify the saved index loads
python -m src.main print good
python -m src.main find good friends
```

Useful flags:

| Flag              | Meaning                                                          |
|-------------------|------------------------------------------------------------------|
| `--start-url URL` | Override the starting URL (default `https://quotes.toscrape.com/`). |
| `--index-path P`  | Where the JSON index is read/written (default `data/index.json`).|
| `--min-interval S`| Politeness window in seconds (default and minimum: `6`).         |
| `--max-pages N`   | Stop the crawl after `N` pages.                                  |
| `-v` / `--verbose`| Enable debug logging.                                            |

## Command reference

### `build`

Crawls every in-domain page reachable from the start URL, indexes it
on the fly, then writes the inverted index to `data/index.json`.

```text
search> build
  indexed [1] https://quotes.toscrape.com/
  indexed [2] https://quotes.toscrape.com/page/2/
  ...
Build complete: 11 page(s), 1234 term(s).
Index saved to /…/cw_web2/data/index.json
```

> **Politeness:** `Crawler.min_interval` defaults to **6 seconds** and
> a warning is logged if it is configured below that.  A full crawl of
> `quotes.toscrape.com` therefore takes a couple of minutes by design.

### `load`

Re-loads a previously saved index without re-crawling.

```text
search> load
Loaded index from data/index.json: 11 document(s), 1234 term(s).
```

### `print <word>`

Prints the inverted-index entry for a single word, including document
frequency, total occurrences, and per-document positions (first 10
shown, with a count of any extra).

```text
search> print good
Term: good
Document frequency: 3
Total occurrences:  9
Postings:
  - https://quotes.toscrape.com/
      freq=4, positions=[12, 45, 88, 137]
  - https://quotes.toscrape.com/page/2/
      freq=3, positions=[7, 41, 102]
  ...
```

The lookup is case-insensitive (`print Good` and `print good` are
equivalent), and friendly messages are printed for empty input,
unknown words, multi-word arguments, and pure-punctuation input.

### `find <query>`

Returns pages that contain **every** word in `<query>` (intersection
semantics), ranked by **TF-IDF**:

* `tf  = freq / document_length` — penalises long pages.
* `idf = log((N + 1) / (df + 1)) + 1` — boosts rare terms while
  keeping the score positive when a word appears in every document.
* The page score is the sum of per-term `tf * idf`.

```text
search> find good friends
Found 2 page(s) for query: 'good friends'
1. Quotes about Friendship
   url:    https://quotes.toscrape.com/tag/friendship/
   score:  0.0823
   terms:  friends=2, good=2
2. Quotes to Scrape
   url:    https://quotes.toscrape.com/
   score:  0.0419
   terms:  friends=1, good=1
```

Edge cases handled:

* Empty / whitespace / pure-punctuation queries → friendly usage
  message.
* Any unknown term in the query → empty result set.
* Duplicate terms in the query → silently de-duplicated.
* Punctuation inside the query (`find good, friends!`) → tokenised the
  same way as the crawl text.
* Case-insensitive (`find GOOD` ≡ `find good`).

### Auxiliary commands

* `stats`         — show the size of the loaded index.
* `help`          — print the command list.
* `quit` / `exit` — leave the shell.

## Testing

The test suite runs in well under a second and never makes a real
HTTP request: the crawler tests inject a fake `requests.Session`, a
fake clock, and a fake `sleep` so the 6-second politeness window can
be asserted without actually waiting.

```bash
# Run all tests
python -m unittest discover -s tests

# With verbose output
python -m unittest discover -s tests -v

# With coverage (optional)
pip install coverage
coverage run --source=src -m unittest discover -s tests
coverage report -m
```

Latest measured coverage: **91 %** across `src/` (≥ 85 % target met).

## Design notes

* **Why JSON for the index?** The brief asks for a single serialised
  file.  JSON keeps the artifact human-readable and version-control
  friendly, and round-trips cleanly back into Python `dict`s without
  a custom decoder.
* **Why TF-IDF?** It is the de-facto baseline for ranked retrieval
  and is easy to compute from data the indexer already keeps
  (`freq`, `document_length`, document frequency).  It addresses the
  high-mark extension band in the brief.
* **Why dependency-inject the clock and session?** The 6-second
  politeness rule makes a naïve test suite painfully slow.  Injecting
  `sleep`, `clock`, and `session` lets the tests verify the throttle
  *exactly* without ever waiting.

## License

Educational use only — produced for COMP/XJCO3011 Coursework 2.
