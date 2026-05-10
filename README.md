# Search Engine Tool

A command-line search engine for [`https://quotes.toscrape.com/`](https://quotes.toscrape.com/).

The tool crawls the website politely, extracts the visible text from each
page, builds an **inverted index** with word frequency and word
positions, saves the index to the local file system, and lets the user
search for pages containing single words or multi-word queries.

Produced for **COMP/XJCO3011 Coursework 2**.

---

## Features

- Polite breadth-first crawler restricted to a single domain.
- Minimum **6-second politeness window** between consecutive HTTP
  requests (warning logged if a lower value is configured).
- Inverted index recording, for each lowercase word, the URL it appears
  in, the term **frequency**, and the **position** of every occurrence.
- **Case-insensitive** indexing and search.
- Atomic save / load round-trip to and from `data/index.json`.
- Four required CLI commands: `build`, `load`, `print <word>`,
  `find <query>`.
- Multi-word `find` with **AND-semantics** plus **TF-IDF ranking**.
- Robust to edge cases: unknown words, empty queries, punctuation,
  failed HTTP requests, missing or invalid index file.
- 75 unit tests, no live network calls, **93%** statement coverage.

---

## Repository structure

```text
cw_web2/
├── src/
│   ├── crawler.py       # Polite, throttled BFS crawler + HTML link extraction
│   ├── indexer.py       # Tokenisation, inverted index, atomic JSON (de)serialiser
│   ├── search.py        # `print` and `find` (TF-IDF ranking)
│   └── main.py          # CLI shell entry-point (build / load / print / find)
├── tests/
│   ├── test_crawler.py  # mocked HTTP, clock, sleep
│   ├── test_indexer.py  # tokeniser, save/load round-trip
│   ├── test_search.py   # single- and multi-word queries, edge cases
│   └── test_main.py     # CLI dispatch + end-to-end build with fake site
├── scripts/
│   └── run_build.py     # Wrapper that runs `build` detached from the IDE/TTY
├── data/                # Produced at runtime (data/index.json, data/build.log)
├── requirements.txt
├── todo.md              # Original coursework brief
└── README.md
```

---

## Installation

The project targets **Python 3.9+** and depends only on `requests` and
`beautifulsoup4`.

```bash
# 1. Clone and enter the project
git clone git@github.com:berwinye/Search-Engine-Tool.git
cd cw_web2

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate         # on Windows: .venv\Scripts\activate

# 3. Install runtime dependencies
pip install -r requirements.txt
```

---

## Dependencies

Runtime dependencies (`requirements.txt`):

| Package          | Version    | Purpose                              |
|------------------|------------|--------------------------------------|
| `requests`       | `>=2.31.0` | HTTP client used by the crawler.     |
| `beautifulsoup4` | `>=4.12.0` | HTML parsing for text extraction.    |

Optional development tools (not in `requirements.txt`):

- `unittest` — bundled with Python; used for the test suite.
- `coverage` — for the optional coverage report (`pip install coverage`).

---

## Usage

Every command can be run either as a one-shot CLI invocation or inside
the interactive shell (`python -m src.main`).

### `build` — crawl the website and build the index

```bash
python -m src.main build
```

Crawls `https://quotes.toscrape.com/` breadth-first starting from `/`,
indexes each fetched page, and atomically writes the result to
`data/index.json`.  Each `build` invocation **discards** any pre-existing
index and re-crawls from scratch.

Expected end-of-run output:

```text
Build complete: crawled 60 page(s), 60 document(s) in index, 4650 term(s).
Index saved to /…/cw_web2/data/index.json
```

A full crawl takes roughly **6–7 minutes** because of the 6-second
politeness window between requests (60 pages × ~6 s).

### `load` — read the saved index back

```bash
python -m src.main load
```

Loads `data/index.json` into memory and prints a structural summary so
you can verify *what* was loaded, not just *how much*:

```text
Loaded index from data/index.json: 60 document(s), 4650 term(s).

Index structure:
  documents:      url -> {length, title}
  inverted_index: term -> {url -> {freq, positions}}

Sample documents (first 3):
  https://quotes.toscrape.com/
      length=287, title='Quotes to Scrape'
  https://quotes.toscrape.com/author/Albert-Einstein
      length=648, title='Quotes to Scrape'
  ...

Top 10 terms by document frequency:
  'and'          df=60  total_occurrences=587
  'the'          df=60  total_occurrences=987
  ...
```

### `print <word>` — show the inverted-index entry for one word

```bash
python -m src.main print good
```

Prints the postings list: document frequency, total occurrences, and the
URL / `freq` / `positions` triple for every page containing the word.
The lookup is case-insensitive (`print Good` ≡ `print good`).

```text
Term: good
Document frequency: 12
Total occurrences:  16
Postings:
  - https://quotes.toscrape.com/page/2/
      freq=3, positions=[29, 548, 550]
  - https://quotes.toscrape.com/author/Albert-Einstein
      freq=2, positions=[137, 195]
  ...
```

### `find <query>` — search for pages

Single-word query:

```bash
python -m src.main find indifference
```

Multi-word query (intersection — every term must appear):

```bash
python -m src.main find good friends
```

Results are ranked by **TF-IDF** and show the matching terms and their
per-document frequency:

```text
Found 8 page(s) for query: 'good friends'
1. Quotes to Scrape
   url:    https://quotes.toscrape.com/page/2/
   score:  0.0455
   terms:  friends=9, good=3
2. Quotes to Scrape
   url:    https://quotes.toscrape.com/page/6/
   score:  0.0319
   terms:  friends=3, good=1
…
```

### Auxiliary commands

| Command        | Purpose                                    |
|----------------|--------------------------------------------|
| `stats`        | Print summary statistics of the loaded index. |
| `help`         | Show the command list.                     |
| `quit` / `exit`| Leave the interactive shell.               |

### Useful CLI flags

| Flag                | Meaning                                                              |
|---------------------|----------------------------------------------------------------------|
| `--start-url URL`   | Override the starting URL (default `https://quotes.toscrape.com/`).  |
| `--index-path P`    | Where the JSON index is read/written (default `data/index.json`).    |
| `--min-interval S`  | Politeness window in seconds (default and minimum: `6`).             |
| `--max-pages N`     | Stop the crawl after `N` pages (useful for smoke-tests).             |
| `-v` / `--verbose`  | Enable debug logging.                                                |

---

## Inverted index design

The index is a nested Python `dict` serialised as JSON.  Each lowercase
word maps to the documents in which it appears, and for each document
the entry stores the term frequency and every position (token offset)
at which the word occurs:

```json
{
  "documents": {
    "https://quotes.toscrape.com/page/2/": {
      "length": 552,
      "title": "Quotes to Scrape"
    }
  },
  "inverted_index": {
    "good": {
      "https://quotes.toscrape.com/page/2/": {
        "freq": 3,
        "positions": [29, 548, 550]
      }
    }
  },
  "version": 1
}
```

Key properties:

- **Case-insensitive.** All tokens are lower-cased on ingest, so
  `Good`, `GOOD`, and `good` collapse to the same key.
- **Position-aware.** Storing positions (not just frequency) leaves the
  door open to phrase / proximity queries without re-crawling.
- **Atomic save.** `Indexer.save()` writes to `<path>.tmp` and then
  `os.replace`s it into place, so a crash mid-write cannot corrupt a
  previously valid index file.
- **Document length stored.** Used by the TF half of TF-IDF to penalise
  long pages.

### `find` ranking — TF-IDF

For each candidate document `d` and query term `t`:

```text
tf  = freq(t, d) / length(d)
idf = log((N + 1) / (df(t) + 1)) + 1
score(d) = sum over t in query of tf * idf
```

`+ 1` smoothing keeps the score positive when a term appears in every
document.  The result list is sorted by descending score, ties broken
deterministically by URL.

---

## Crawling policy

The crawler starts from `https://quotes.toscrape.com/` and follows
in-domain `<a href>` links breadth-first.  The traversal logic is
**generic** — nothing is hard-coded for this particular site; only the
*skip list* is configured at the call site.

Indexed page categories on `quotes.toscrape.com`:

- `/` — the home page (also page 1 of the listing).
- `/page/2/` … `/page/10/` — the remaining quote-listing pages,
  reached via the "Next" button.
- `/author/<Name>` — biography pages, reached via the author link
  attached to every quote.

Excluded path prefixes (`Shell.BUILD_SKIP_PATH_PREFIXES`):

| Prefix      | Reason                                                                                                  |
|-------------|---------------------------------------------------------------------------------------------------------|
| `/login`    | Login form has no useful searchable content.                                                            |
| `/tag/`     | Tag pages are filtered views of quotes that already appear in the listing pages; indexing them would duplicate the same quotes under multiple URLs and inflate document frequencies.  Tag *names* are still indexed because they appear as visible text on the listing pages themselves. |
| `/page/1/`  | Exact duplicate of `/`, reachable only via the "Previous" button on `/page/2/`.  Skipping it avoids indexing the home page twice under two different URLs. |

A real crawl produces exactly **60 documents** = 1 (`/`) + 9
(`/page/2/`–`/page/10/`) + 50 (`/author/*`).

---

## Testing

The test suite never makes a real HTTP request: a fake
`requests.Session`, a fake clock, and a fake `sleep` are injected so
the politeness window can be asserted **without actually waiting**.
The whole suite finishes in under 0.2 s.

### Run the tests

```bash
python -m unittest discover -s tests          # all tests
python -m unittest discover -s tests -v       # verbose
```

### Coverage report

```bash
pip install coverage
coverage run --source=src -m unittest discover -s tests
coverage report -m
```

Latest measurement:

```text
Name              Stmts   Miss  Cover
-------------------------------------
src/crawler.py      114      7    94%
src/indexer.py      121      5    96%
src/main.py         152     19    88%
src/search.py        97      1    99%
-------------------------------------
TOTAL               484     32    93%
```

### What is covered

- Crawler: politeness window enforced exactly, in-domain link
  filtering, skip-path-prefix filtering, network-failure recovery,
  non-200 status handling.
- Indexer: case-insensitive tokenisation, position tracking,
  re-indexing replacing previous entries, save/load full state
  byte-for-byte round-trip, atomic save semantics.
- Search: single- and multi-word queries, intersection semantics,
  unknown words, empty / pure-punctuation / duplicate queries,
  TF-IDF ranking determinism.
- CLI: command dispatch, auto-loading the index for read-only
  commands, `build` always re-crawling from scratch, `build`
  discarding pre-existing index, atomic checkpoint after every page,
  `/login` / `/tag/` / `/page/1/` skipped, `find` formatting.

### Running a real crawl (optional, slow)

The unit tests use a mocked site, so a live crawl is not needed for
grading correctness.  If you want to reproduce the real index used in
the screenshots above, run:

```bash
python -u scripts/run_build.py
```

`scripts/run_build.py` ignores `SIGINT`/`SIGHUP` and detaches into its
own session so the crawl is not interrupted by IDE-managed background
runners.  Output is mirrored to `data/build.log`.

---

## Edge cases handled

| Scenario                                            | Behaviour                                                  |
|-----------------------------------------------------|-------------------------------------------------------------|
| Empty / whitespace `find` query                     | Friendly usage message, no crash.                           |
| Pure-punctuation `find`/`print` query (e.g. `?!.`) | Treated as empty after tokenisation; friendly message.      |
| Unknown word in `print <word>`                      | `Word '...' not found in the index.`                        |
| Unknown term in multi-word `find`                   | Empty result set (intersection cannot succeed).             |
| Duplicate terms in `find` query                     | Silently de-duplicated.                                     |
| Punctuation in query (`find good, friends!`)        | Tokenised the same way as the indexed text.                 |
| Mixed case (`find GOOD`, `print Good`)              | Case-insensitive: equivalent to lowercase.                  |
| Network failure on a single page                    | Logged and skipped; the rest of the crawl continues.        |
| Non-200 HTTP response                               | Logged and skipped; not indexed.                            |
| Missing index file on `load`                        | `Index file not found: data/index.json`                     |
| Corrupted index JSON                                | `Failed to load index: <reason>`                            |
| Crash mid-`build`                                   | Last successfully written `data/index.json` is still valid (atomic save). |

---

## Design choices and known limitations

- **Why JSON for the index?** The brief asks for a single serialised
  file; JSON is human-readable, version-control friendly, and
  round-trips back to Python `dict` without a custom decoder.  For a
  production-scale index a binary or database-backed format would be
  more compact.
- **Why TF-IDF?** It is the de-facto baseline for ranked retrieval
  and can be computed entirely from data the indexer already keeps
  (`freq`, `length`, `df`).  It addresses the high-mark extension band
  in the brief without pulling in a heavyweight dependency.
- **Why dependency-inject the clock and session?** The 6-second
  politeness rule would otherwise make the test suite painfully slow.
  Injecting `sleep`, `clock`, and `session` lets the tests assert the
  throttle *exactly* without ever waiting.
- **Why no resume / checkpointing for `build`?** Earlier prototypes
  supported resuming a partial crawl; the final design instead always
  starts fresh, which is simpler to reason about and to grade.  The
  per-page atomic save still ensures a valid (partial) `data/index.json`
  is left behind if a crawl is interrupted.
- **Tied to `quotes.toscrape.com` only by configuration.** Both the
  start URL and the skip list are runtime-configurable
  (`--start-url`, `Shell.BUILD_SKIP_PATH_PREFIXES`); the crawl logic
  itself is a generic single-domain BFS.

---

## GenAI usage

Generative AI was used as a *support* tool throughout development —
mainly for sketching the project layout, brainstorming the inverted
index data model, suggesting test scenarios, and turning the
coursework brief into a checklist.

Every AI-generated suggestion was reviewed, edited, and then verified
against the brief or against a unit test before being committed.
Concrete examples where the AI output had to be corrected:

- An early AI suggestion stored only `{word: [urls]}` for the
  inverted index; the brief required word frequency and positions, so
  the data model was extended to
  `{word: {url: {freq, positions}}}`.
- An AI-suggested test set initially missed pure-punctuation queries
  and unknown-term intersection in `find`; both were added by hand.
- An AI-suggested `cmd_build` ran a single-pass BFS that also
  indexed `/login` and `/tag/` pages.  The final implementation
  introduced `skip_path_prefixes` on the `Crawler` and a documented
  rationale (see *Crawling policy*) before any of those URLs are
  followed.

GenAI sped up scaffolding and review, but the final design,
correctness checks, and test coverage are the result of manual work
and end-to-end real-site validation.

---

## License

Educational use only — produced for COMP/XJCO3011 Coursework 2.
