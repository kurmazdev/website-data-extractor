import asyncio
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import aiohttp

from .demo import fixture
from .pacing import site_slot
from .security import DEMO_HOST, AccessError, PublicResolver, check_url, origin

USER_AGENT = "WebsiteDataExtractor/1.0"
MAX_BYTES = 2_000_000


class Fetcher:
    def __init__(self, config):
        self.config = config
        self.robots = {}
        self.last_request = 0
        self.requests = 0
        self.bytes = 0
        self.session = None
        self._request_lock = asyncio.Lock()
        self._policy_lock = asyncio.Lock()

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(
                resolver=PublicResolver(),
                use_dns_cache=False,
                force_close=True,
                limit=2,
            ),
            timeout=aiohttp.ClientTimeout(total=self.config.timeout),
            headers={"User-Agent": USER_AGENT},
            trust_env=False,
            cookie_jar=aiohttp.DummyCookieJar(),
        )
        return self

    async def __aexit__(self, *args):
        await self.session.close()

    async def raw(self, url, robots=False):
        for _ in range(6):
            check_url(url)
            if not robots:
                await self.allowed(url)
            status, headers, body = await self._request(url)
            if status in (301, 302, 303, 307, 308):
                location = headers.get("Location")
                if not location:
                    raise AccessError("Redirect has no destination.")
                target = urljoin(url, location)
                check_url(target)
                if origin(target) != origin(self.config.url):
                    raise AccessError(
                        "Cross-origin redirects are blocked. Enter the destination URL directly."
                    )
                url = target
                continue
            return status, headers, body, url
        raise AccessError("Too many redirects.")

    async def _request(self, url):
        # Browser resource handlers can run concurrently. Serialize actual sends
        # so a page with many scripts still respects request and crawl delays.
        async with self._request_lock:
            async with site_slot(origin(url)) as gate:
                return await self._request_unlocked(url, gate)

    async def _request_unlocked(self, url, gate):
        self.requests += 1
        if self.requests > 300:
            raise AccessError("Request limit reached (300 per run).")
        policy = self.robots.get(origin(url))
        crawl_delay = policy.crawl_delay(USER_AGENT) if policy else None
        rate = policy.request_rate(USER_AGENT) if policy else None
        policy_spacing = max(
            crawl_delay or 0, rate.seconds / rate.requests if rate else 0
        )
        spacing = max(self.config.delay, policy_spacing, gate.policy_spacing)
        if spacing > 60:
            raise AccessError(
                "The site requests a crawl delay above this tool’s 60-second limit."
            )
        last_request = max(self.last_request, gate.last_request)
        await asyncio.sleep(max(0, spacing - (time.monotonic() - last_request)))
        self.last_request = gate.last_request = time.monotonic()
        gate.policy_spacing = max(gate.policy_spacing, policy_spacing)
        if urlsplit(url).hostname == DEMO_HOST:
            status, content_type, body = fixture(url)
            headers = {"Content-Type": content_type}
        else:
            async with self.session.get(url, allow_redirects=False) as response:
                status = response.status
                headers = response.headers
                chunks = []
                size = 0
                async for chunk in response.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise AccessError("Response exceeds the 2 MB limit.")
                    chunks.append(chunk)
                body = b"".join(chunks)
        self.bytes += len(body)
        if self.bytes > 30_000_000:
            raise AccessError("Run exceeds the 30 MB download limit.")
        return status, headers, body

    async def allowed(self, url):
        async with self._policy_lock:
            await self._allowed(url)

    async def _allowed(self, url):
        key = origin(url)
        if key not in self.robots:
            p = urlsplit(url)
            robots_url = urlunsplit((p.scheme, p.netloc, "/robots.txt", "", ""))
            status, _, body, _ = await self.raw(robots_url, robots=True)
            policy = RobotFileParser()
            if status in (404, 410):
                policy.parse(["User-agent: *", "Allow: /"])
            elif status == 200:
                policy.parse(body.decode("utf-8", errors="replace").splitlines())
            else:
                raise AccessError(
                    f"Cannot verify robots.txt (HTTP {status}); access stopped."
                )
            self.robots[key] = policy
        if not self.robots[key].can_fetch(USER_AGENT, url):
            raise AccessError("This URL is disallowed by robots.txt.")

    async def document(self, url):
        status, headers, body, final = await self.raw(url)
        if status >= 400:
            raise AccessError(
                f"HTTP {status}. Access stopped; no restriction bypass attempted."
            )
        content_type = headers.get("Content-Type", "").lower()
        if "html" not in content_type:
            raise AccessError("The URL did not return an HTML page.")
        # BeautifulSoup detects declared encodings, including malformed HTML.
        return body, final
