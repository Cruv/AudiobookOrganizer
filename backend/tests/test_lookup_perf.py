"""Tests for the PR 2 performance changes: shared httpx client and
parallel-providers in lookup_book.

These are unit-level smoke tests — we mock the four provider coroutines
so we don't hit any network, and assert they all run via asyncio.gather
(i.e. concurrently) rather than sequentially.
"""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_get_http_client_returns_singleton():
    """The shared httpx client must be the same instance across
    awaiters so connection pooling is actually shared."""
    from app.services.lookup import aclose_http_client, get_http_client

    try:
        a = await get_http_client()
        b = await get_http_client()
        assert a is b
        assert not a.is_closed
    finally:
        await aclose_http_client()


@pytest.mark.asyncio
async def test_aclose_http_client_idempotent():
    """Closing twice should not raise."""
    from app.services.lookup import aclose_http_client, get_http_client

    await get_http_client()
    await aclose_http_client()
    await aclose_http_client()  # should be a no-op, not an error


@pytest.mark.asyncio
async def test_lookup_book_runs_providers_concurrently(monkeypatch):
    """Patch each provider's search function to wait 100ms; total time
    must be ~100ms (parallel), not ~400ms (sequential)."""
    from app.services import lookup as lookup_mod

    async def _slow_provider(*args, **kwargs):
        await asyncio.sleep(0.1)
        return []

    monkeypatch.setattr(lookup_mod, "search_audible", _slow_provider)
    monkeypatch.setattr(lookup_mod, "search_google_books", _slow_provider)
    monkeypatch.setattr(lookup_mod, "search_openlibrary", _slow_provider)
    monkeypatch.setattr(lookup_mod, "search_itunes", _slow_provider)

    start = asyncio.get_event_loop().time()
    # db isn't touched because all our patched providers return [];
    # passing None is fine.
    results = await lookup_mod.lookup_book("Some Title", "Some Author", None, None)
    elapsed = asyncio.get_event_loop().time() - start

    assert results == []
    # 100ms per provider × 4 sequentially = 400ms. With gather, ~100ms.
    # Allow generous slack for slow CI runners — anything under 300ms
    # proves they ran concurrently.
    assert elapsed < 0.3, f"lookup_book took {elapsed:.2f}s, expected ~0.1s"
