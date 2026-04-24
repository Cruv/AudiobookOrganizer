"""Test-level pytest configuration.

This module is loaded before any test modules are collected, so it's the
right place to set environment variables that the app reads at import
time — notably DATABASE_URL.

The production default points at /app/data/audiobook_organizer.db (inside
the Docker container). CI runners don't have write access to /app, and
app/database.py calls os.makedirs(os.path.dirname(db_path), exist_ok=True)
at import time, which raises PermissionError there.

We override DATABASE_URL to a per-session tmp file so that import side-
effect succeeds. The tests that actually touch a DB create their own
in-memory engines anyway, so this file isn't queried in practice — it
just needs to be in a writable location.
"""

import os
import tempfile

# Only override if the user hasn't already set one (e.g. locally, or in
# a developer env). This keeps the test suite deterministic across
# local runs, CI, and future docker-based test setups.
if "DATABASE_URL" not in os.environ:
    _tmp = tempfile.NamedTemporaryFile(
        suffix=".sqlite", prefix="audiobook_organizer_test_", delete=False
    )
    _tmp.close()
    os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
