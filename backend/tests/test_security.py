from unittest.mock import AsyncMock, patch

import pytest
from extractor.network import MAX_BYTES, Fetcher
from extractor.security import AccessError, PublicResolver, check_url, public_ip
from test_engine import config


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://[::1]",
        "http://169.254.169.254/latest",
        "http://10.0.0.1",
        "http://192.168.1.1",
        "http://172.16.0.1",
        "http://localhost",
        "http://[::ffff:127.0.0.1]",
        "http://[2002:7f00:1::]",
        "http://example.com:8000",
        "http://user@example.org",
        "file:///etc/passwd",
        "http://example.org\\@127.0.0.1",
    ],
)
def test_blocked_urls(url):
    with pytest.raises(AccessError):
        check_url(url)


def test_public_url():
    check_url("https://example.org/")
    public_ip("8.8.8.8")
    public_ip("2606:4700:4700::1111")


async def test_dns_mixed_answers_blocked():
    resolver = PublicResolver()
    with patch(
        "aiohttp.resolver.ThreadedResolver.resolve",
        new=AsyncMock(return_value=[{"host": "8.8.8.8"}, {"host": "127.0.0.1"}]),
    ):
        with pytest.raises(AccessError):
            await resolver.resolve("evil.example", 443)
    await resolver.close()


async def test_rebinding_checked_on_each_resolution():
    resolver = PublicResolver()
    with patch(
        "aiohttp.resolver.ThreadedResolver.resolve",
        new=AsyncMock(side_effect=[[{"host": "8.8.8.8"}], [{"host": "10.0.0.1"}]]),
    ):
        assert await resolver.resolve("changing.example", 443)
        with pytest.raises(AccessError):
            await resolver.resolve("changing.example", 443)
    await resolver.close()


async def test_robots_disallow_and_fail_closed():
    async with Fetcher(config()) as f:
        with patch.object(
            f,
            "raw",
            new=AsyncMock(
                return_value=(
                    200,
                    {},
                    b"User-agent: *\nDisallow: /catalog",
                    config().url,
                )
            ),
        ):
            with pytest.raises(AccessError, match="disallowed"):
                await f.allowed(config().url)
    async with Fetcher(config()) as f:
        with patch.object(
            f, "raw", new=AsyncMock(return_value=(503, {}, b"", config().url))
        ):
            with pytest.raises(AccessError, match="Cannot verify"):
                await f.allowed(config().url)


class Content:
    def __init__(self, body):
        self.body = body

    async def iter_chunked(self, size):
        yield self.body


class Response:
    def __init__(self, status, headers, body=b""):
        self.status = status
        self.headers = headers
        self.content = Content(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.mark.parametrize(
    "target",
    ["http://127.0.0.1/admin", "https://other.example/", "http://169.254.169.254/"],
)
async def test_redirects_to_internal_or_other_origin_blocked(target):
    async with Fetcher(config(url="https://public.example/")) as f:
        with (
            patch.object(f, "allowed", new=AsyncMock()),
            patch.object(
                f.session, "get", return_value=Response(302, {"Location": target})
            ) as get,
        ):
            with pytest.raises(AccessError):
                await f.document("https://public.example/")
            assert get.call_count == 1


async def test_same_origin_redirect_rechecks_robots():
    async with Fetcher(config(url="https://public.example/")) as f:
        policy = AsyncMock(side_effect=[None, AccessError("disallowed")])
        with (
            patch.object(f, "allowed", new=policy),
            patch.object(
                f.session, "get", return_value=Response(302, {"Location": "/private"})
            ) as get,
        ):
            with pytest.raises(AccessError, match="disallowed"):
                await f.document("https://public.example/")
            assert get.call_count == 1
            assert policy.await_count == 2


async def test_oversize_response():
    async with Fetcher(config(url="https://public.example/")) as f:
        with (
            patch.object(f, "allowed", new=AsyncMock()),
            patch.object(
                f.session,
                "get",
                return_value=Response(
                    200, {"Content-Type": "text/html"}, b"x" * (MAX_BYTES + 1)
                ),
            ),
        ):
            with pytest.raises(AccessError, match="2 MB"):
                await f.document("https://public.example/")


async def test_crawl_delay_respected():
    async with Fetcher(config()) as f:
        with patch(
            "extractor.network.fixture",
            return_value=(
                200,
                "text/plain",
                b"User-agent: *\nCrawl-delay: 3\nAllow: /",
            ),
        ):
            await f.allowed(config().url)
        f.last_request = __import__("time").monotonic()
        with patch("extractor.network.asyncio.sleep", new=AsyncMock()) as sleep:
            await f.raw(config().url)
            assert sleep.call_args.args[0] > 2.9


async def test_concurrent_browser_requests_remain_paced():
    import asyncio
    import time

    async with Fetcher(config()) as f:
        await f.allowed(config().url)
        sent = []

        def stamped(url):
            sent.append(time.monotonic())
            return 200, "text/html", b"<html></html>"

        with patch("extractor.network.fixture", side_effect=stamped):
            await asyncio.gather(f.raw(config().url), f.raw(config().url))
        assert len(sent) == 2 and sent[1] - sent[0] >= 0.48


@pytest.mark.parametrize(
    "url",
    [
        "http://１２７.０.０.１/",
        "http://127。0。0。1/",
        "http://localhost。/",
        "http://127.0.0.1./",
        "http://%31%32%37.0.0.1/",
    ],
)
def test_canonicalized_private_hosts_blocked(url):
    with pytest.raises(AccessError):
        check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.1/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0177.0.0.1/",
        "http://127.000.000.001/",
    ],
)
def test_legacy_ipv4_literals_blocked(url):
    with pytest.raises(AccessError):
        check_url(url)


@pytest.mark.parametrize("ip", ["fec0::1", "4000::1", "192.0.0.192", "168.63.129.16"])
def test_special_platform_and_reserved_ranges(ip):
    with pytest.raises(AccessError):
        public_ip(ip)


async def test_request_and_total_download_caps():
    async with Fetcher(config()) as f:
        await f.allowed(config().url)
        f.requests = 300
        with pytest.raises(AccessError, match="Request limit"):
            await f.raw(config().url)
    async with Fetcher(config()) as f:
        await f.allowed(config().url)
        f.bytes = 30_000_000
        with pytest.raises(AccessError, match="30 MB"):
            await f.raw(config().url)


async def test_excessive_robots_crawl_delay_fails_without_page_fetch():
    async with Fetcher(config()) as f:
        with patch(
            "extractor.network.fixture",
            return_value=(
                200,
                "text/plain",
                b"User-agent: *\nCrawl-delay: 120\nAllow: /",
            ),
        ):
            await f.allowed(config().url)
        with patch("extractor.network.fixture") as fixture:
            with pytest.raises(AccessError, match="60-second"):
                await f.raw(config().url)
            fixture.assert_not_called()


async def test_concurrent_runs_share_site_pacing():
    import asyncio
    import time

    from extractor.demo import fixture as real_fixture

    sent = []

    def stamped(url):
        if "/catalog" in url:
            sent.append(time.monotonic())
        return real_fixture(url)

    async with Fetcher(config()) as first, Fetcher(config()) as second:
        with patch("extractor.network.fixture", side_effect=stamped):
            await asyncio.gather(first.raw(config().url), second.raw(config().url))
    assert len(sent) == 2 and sent[1] - sent[0] >= 0.48


async def test_new_run_robots_request_retains_known_site_crawl_delay():
    import asyncio
    import time

    from extractor.pacing import _gates
    from extractor.security import origin

    async with Fetcher(config()) as first:
        await first.allowed(config().url)
    gate = _gates[(asyncio.get_running_loop(), origin(config().url))]
    gate.policy_spacing = 3
    gate.last_request = time.monotonic()
    async with Fetcher(config()) as second:
        with patch("extractor.network.asyncio.sleep", new=AsyncMock()) as sleep:
            await second.allowed(config().url)
            assert sleep.call_args.args[0] > 2.9
