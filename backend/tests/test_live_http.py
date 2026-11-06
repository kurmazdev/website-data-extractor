"""Actual TCP/HTTP fixtures; only the test transport maps a public test origin
onto a loopback server. Production URL/DNS restrictions remain unchanged.
"""

import asyncio
from urllib.parse import urlsplit

import aiohttp
import pytest_asyncio
from aiohttp import web
from extractor.engine import extract
from extractor.network import Fetcher
from test_engine import config


@pytest_asyncio.fixture
async def live_site():
    requests = []

    async def handle(request):
        requests.append(request.path_qs)
        if request.path == "/robots.txt":
            return web.Response(
                text="User-agent: *\nDisallow: /restricted\nAllow: /",
                content_type="text/plain",
            )
        if request.path == "/restricted":
            raise AssertionError("Robots-protected page must never be fetched")
        if request.path == "/redirect":
            raise web.HTTPFound("/catalog?page=2")
        if request.path == "/internal-redirect":
            raise web.HTTPFound("http://127.0.0.1/admin")
        if request.path == "/auth":
            raise web.HTTPUnauthorized()
        if request.path == "/slow":
            await asyncio.sleep(2.2)
        if request.path == "/malformed":
            return web.Response(
                text="<div class=book><h2>Broken but readable", content_type="text/html"
            )
        if request.path == "/oversize":
            return web.Response(body=b"x" * 2_000_001, content_type="text/html")
        if request.path == "/charset":
            return web.Response(
                text="<div class=book><h2>Café</h2></div>",
                content_type="text/html",
                charset="iso-8859-1",
            )
        second = request.query.get("page") == "2"
        title = "Second" if second else "First"
        next_path = request.query.get("next", "/catalog?page=2")
        html = f"<div class=book><h2>{title}</h2><span class=price>$12</span></div>"
        if not second and request.path not in ("/slow", "/auth"):
            html += f'<a class=next href="{next_path}">Next</a>'
        return web.Response(text=html, content_type="text/html")

    app = web.Application()
    app.router.add_get("/{path:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    class Transport:
        def __init__(self, session):
            self.session = session

        def get(self, url, **kwargs):
            p = urlsplit(url)
            return self.session.get(
                base + p.path + ("?" + p.query if p.query else ""), **kwargs
            )

        async def close(self):
            await self.session.close()

    class LiveFetcher(Fetcher):
        async def __aenter__(self):
            self.session = Transport(
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout)
                )
            )
            return self

    yield LiveFetcher, requests
    await runner.cleanup()


async def test_actual_http_pagination_and_redirect(live_site):
    factory, requests = live_site
    result = await extract(
        config(url="http://public.example/redirect"), fetcher_factory=factory
    )
    assert result.status == "completed"
    assert result.records[0]["Title"] == "Second"
    assert result.records[0]["_source"] == "http://public.example/catalog?page=2"
    assert requests == ["/robots.txt", "/redirect", "/catalog?page=2"]


async def test_actual_http_multiplage(live_site):
    factory, _ = live_site
    result = await extract(
        config(url="http://public.example/catalog"), fetcher_factory=factory
    )
    assert result.pages == 2 and [r["Title"] for r in result.records] == [
        "First",
        "Second",
    ]


async def test_actual_http_timeout_keeps_results(live_site):
    factory, _ = live_site
    result = await extract(
        config(url="http://public.example/catalog?next=/slow", timeout=2),
        fetcher_factory=factory,
    )
    assert result.status == "partial" and len(result.records) == 1
    assert "timed out" in result.issues[0].message


async def test_actual_http_robots_and_private_redirect(live_site):
    factory, requests = live_site
    for path in ("restricted", "internal-redirect"):
        result = await extract(
            config(url="http://public.example/" + path), fetcher_factory=factory
        )
        assert result.status == "failed" and not result.records
    assert "/restricted" not in requests and "/admin" not in requests


async def test_actual_http_auth_not_retried(live_site):
    factory, requests = live_site
    result = await extract(
        config(url="http://public.example/auth"), fetcher_factory=factory
    )
    assert result.status == "failed" and "401" in result.issues[0].message
    assert requests.count("/auth") == 1


async def test_actual_http_malformed_and_size_limit(live_site):
    factory, _ = live_site
    result = await extract(
        config(url="http://public.example/malformed"), fetcher_factory=factory
    )
    assert (
        result.status == "completed"
        and result.records[0]["Title"] == "Broken but readable"
    )
    result = await extract(
        config(url="http://public.example/oversize"), fetcher_factory=factory
    )
    assert result.status == "failed" and "2 MB" in result.issues[0].message
