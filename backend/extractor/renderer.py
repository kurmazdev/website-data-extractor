"""Browser requests are fulfilled through the same guarded HTTP client.
The browser is offline; it never opens destination HTTP connections itself.
"""

import asyncio

from .security import AccessError, check_url, origin


async def render(fetcher, url, row_selector):
    from playwright.async_api import Error, async_playwright
    from playwright.async_api import TimeoutError as BrowserTimeoutError

    status, initial_headers, initial_body, initial_url = await fetcher.raw(url)
    if status >= 400:
        raise AccessError(
            f"HTTP {status}. Access stopped; no restriction bypass attempted."
        )
    if "html" not in initial_headers.get("Content-Type", "").lower():
        raise AccessError("The URL did not return an HTML page.")
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                args=[
                    "--disable-background-networking",
                    "--disable-quic",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                ]
            )
        except Error as e:
            if "Executable doesn" in str(e):
                raise AccessError(
                    "Chromium is not installed. Run: python -m playwright install chromium"
                ) from e
            raise AccessError(
                "Chromium could not start. Check browser installation and system permissions."
            ) from e
        try:
            context = await browser.new_context(
                offline=True, service_workers="block", accept_downloads=False
            )
            await context.add_init_script("""
                for (const key of ['RTCPeerConnection','webkitRTCPeerConnection','Worker','SharedWorker']) {
                  Object.defineProperty(globalThis, key, {value: undefined, writable: false});
                }
            """)
            await context.route_web_socket("**/*", lambda ws: ws.close())
            failures = []
            main_urls = []
            initial_served = False

            async def handle(route):
                nonlocal initial_served
                request = route.request
                try:
                    check_url(request.url)
                    if (
                        origin(request.url) != origin(url)
                        or request.method != "GET"
                        or request.resource_type
                        not in ("document", "script", "xhr", "fetch", "stylesheet")
                    ):
                        await route.abort()
                        return
                    if (
                        request.resource_type == "document"
                        and request.frame.parent_frame
                    ):
                        await route.abort()
                        return
                    if (
                        request.url == initial_url
                        and request.resource_type == "document"
                        and not initial_served
                    ):
                        initial_served = True
                        status, headers, body, final = (
                            200,
                            initial_headers,
                            initial_body,
                            initial_url,
                        )
                    else:
                        status, headers, body, final = await fetcher.raw(request.url)
                    if status >= 400:
                        raise AccessError(
                            f"HTTP {status} while rendering {request.url}"
                        )
                    site_policy = headers.get("Content-Security-Policy", "")
                    safe_headers = {
                        "Content-Type": headers.get("Content-Type", "text/plain"),
                        "Content-Security-Policy": "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; worker-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'",
                    }
                    if site_policy:
                        # Multiple CSP policies intersect. Retain the site's policy
                        # rather than enabling scripts it explicitly forbids.
                        safe_headers["Content-Security-Policy"] = (
                            site_policy + ", " + safe_headers["Content-Security-Policy"]
                        )
                    if request.resource_type == "document":
                        if "html" not in safe_headers["Content-Type"].lower():
                            raise AccessError("The URL did not return an HTML page.")
                        main_urls.append(final)
                    await route.fulfill(status=status, headers=safe_headers, body=body)
                except Exception as e:
                    failures.append(str(e))
                    await route.abort()

            await context.route("**/*", handle)
            page = await context.new_page()
            try:
                await page.goto(
                    initial_url,
                    wait_until="domcontentloaded",
                    timeout=fetcher.config.timeout * 1000,
                )
                # CSS syntax supported by SoupSieve is wider than browser CSS. Poll the
                # extracted HTML instead so both modes have identical selector semantics.
                from bs4 import BeautifulSoup

                deadline = asyncio.get_running_loop().time() + fetcher.config.timeout
                while True:
                    html = await page.content()
                    if len(html.encode()) > 2_000_000:
                        raise AccessError("Rendered page exceeds the 2 MB limit.")
                    if BeautifulSoup(html, "html.parser").select_one(row_selector):
                        break
                    if failures:
                        break
                    if asyncio.get_running_loop().time() > deadline:
                        raise asyncio.TimeoutError()
                    await asyncio.sleep(0.1)
                if failures:
                    raise AccessError(failures[0])
                return html, main_urls[-1] if main_urls else url
            except BrowserTimeoutError as e:
                raise asyncio.TimeoutError() from e
            except Exception as e:
                if failures:
                    raise AccessError(failures[0]) from e
                raise
        finally:
            await browser.close()
