"""Real Chromium tests. Enable with RUN_BROWSER_TESTS=1 after installing it."""

import os
from unittest.mock import patch

import pytest
from extractor.engine import extract
from test_engine import config

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Set RUN_BROWSER_TESTS=1 after playwright install chromium",
)


async def test_real_javascript_pagination():
    result = await extract(config(url=config().url + "?js=1", render_js=True))
    assert result.status == "completed", result.model_dump()
    assert result.pages == 3 and len(result.records) == 11
    assert result.missing == 1 and result.duplicates == 1


async def test_browser_private_fetch_cannot_connect():
    html = b"""<div class="book"><h2>Safe row</h2></div><script>
    fetch('http://127.0.0.1/secret');
    fetch('http://169.254.169.254/latest');
    new WebSocket('ws://127.0.0.1:9000/');
    </script>"""

    def fixture(url):
        if url.endswith("robots.txt"):
            return 200, "text/plain", b"User-agent: *\nAllow: /"
        return 200, "text/html", html

    with patch("extractor.network.fixture", side_effect=fixture):
        result = await extract(config(render_js=True, max_pages=1))
    assert len(result.records) == 1
    assert result.records[0]["Title"] == "Safe row"


async def test_javascript_record_wait_times_out():
    result = await extract(
        config(url=config().url + "?js=slow", render_js=True, timeout=2, max_pages=1)
    )
    assert result.status == "failed"
    assert "timed out" in result.issues[0].message


async def test_renderer_preserves_site_csp():
    from extractor.network import Fetcher
    from extractor.renderer import render

    class CspFetcher(Fetcher):
        async def raw(self, url, robots=False):
            status, headers, body, final = await super().raw(url, robots)
            return (
                status,
                {**headers, "Content-Security-Policy": "script-src 'none'"},
                body,
                final,
            )

    async with CspFetcher(config(url=config().url + "?js=1", timeout=2)) as fetcher:
        import asyncio

        with pytest.raises(asyncio.TimeoutError):
            await render(fetcher, fetcher.config.url, ".book")
