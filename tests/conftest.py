import os
import tempfile

# `sevenfilm.api` holds `DATABASE` as a module-level singleton, read once at import time from
# `SEVENFILM_DATA_ROOT` -- and several test modules each try to set that variable themselves
# (`os.environ.setdefault(...)` at their own module level) as a safety net for being run alone.
# Without this file, whichever of them pytest happens to import first "wins" that race, and an
# unrelated change to file naming or collection order can silently switch every other test
# module in the session onto a different temp directory -- or, if nothing happens to set it in
# time, onto `config.py`'s own fallback: `Path.cwd() / "data"`, this project's real database.
# A `conftest.py` is collected before any test module in its directory, every time, so this
# settles the race the same way regardless of which files exist or what they're named.
_ROOT = tempfile.TemporaryDirectory()
os.environ.setdefault("SEVENFILM_DATA_ROOT", _ROOT.name)
