"""Helper script to run a real ``build`` invulnerable to SIGINT/SIGHUP.

Some IDE-managed background runners deliver SIGINT to long-running
async commands when the foreground REPL polls them.  That kills the
crawler mid-``time.sleep`` and leaves no index on disk.  This wrapper
ignores SIGINT/SIGHUP and detaches into its own session so a real
end-to-end crawl of ``quotes.toscrape.com`` can run unattended.

Usage (from the project root)::

    .venv/bin/python scripts/run_build.py
"""

from __future__ import annotations

import os
import signal
import sys

for sig in (signal.SIGINT, signal.SIGHUP, signal.SIGPIPE):
    try:
        signal.signal(sig, signal.SIG_IGN)
    except (ValueError, OSError):
        pass

try:
    os.setsid()
except OSError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["-v", "build"]))
