"""End-to-end browser review against a running production build.
No API responses are mocked. Fixture pages, extraction, polling, and downloads
all run through the real app. Saves screenshots, downloads, and a JSON report.
"""

import asyncio
import csv
import json
import os
from io import StringIO
from pathlib import Path

from openpyxl import load_workbook
from playwright.async_api import async_playwright, expect

BASE = os.environ.get("EXTRACTOR_TEST_URL", "http://127.0.0.1:8000")
DEMO = "https://demo.website-extractor.test/catalog"
ARTIFACTS = Path("artifacts")
FIELDS = [
    ("Title", "h2"),
    ("Author", ".author"),
    ("Price", ".price"),
    ("Category", ".category"),
]


async def configure(page, url=DEMO, manual=False):
    await page.goto(BASE)
    if not manual:
        await page.get_by_role("button", name="Load bookshop demo").click()
    else:
        await page.get_by_label("Website URL").fill(url)
        await page.get_by_label("Record selector", exact=True).fill(".book")
        for i, (name, selector) in enumerate(FIELDS, 1):
            if i > 1:
                await page.get_by_role("button", name="Add field", exact=True).click()
            await page.get_by_label(f"Field {i} name", exact=True).fill(name)
            await page.get_by_label(f"Field {i} selector", exact=True).fill(selector)
        await page.get_by_label("Next page selector").fill("a.next")
    await page.get_by_label("Website URL").fill(url)
    await page.get_by_label("Request delay").fill("0.5")


async def preview(page, check_loading=False):
    async with page.expect_response(
        lambda r: r.url.endswith("/api/preview") and r.request.method == "POST"
    ) as info:
        await page.get_by_role("button", name="Preview", exact=True).click()
        if check_loading:
            await expect(page.locator(".preview-loading")).to_be_visible()
            await expect(
                page.get_by_role("button", name="Start extraction", exact=True)
            ).to_be_disabled()
    response = await info.value
    data = await response.json()
    await expect(page.locator(".preview-loading")).to_have_count(0)
    return response.status, data


async def start(page):
    async with page.expect_response(
        lambda r: r.url.endswith("/api/jobs") and r.request.method == "POST"
    ) as info:
        await page.get_by_role("button", name="Start extraction", exact=True).click()
    response = await info.value
    assert response.status == 201, await response.text()
    return (await response.json())["id"]


async def finish(page, key, status="completed"):
    text = {
        "completed": "Ready",
        "partial": "Partial results",
        "cancelled": "Stopped",
        "failed": "Failed",
    }[status]
    await expect(page.locator(".results-heading .status")).to_have_text(
        text, timeout=30000
    )
    response = await page.request.get(f"{BASE}/api/jobs/{key}")
    data = await response.json()
    assert data["status"] == status, data
    await expect(
        page.get_by_role("button", name="Start extraction", exact=True)
    ).to_be_enabled()
    await expect(page.get_by_label("Website URL")).to_be_enabled()
    return data


async def exports(page, data, prefix):
    names = [name for name, _ in FIELDS] + ["_source"]
    expected = [[r.get(name, "") for name in names] for r in data["records"]]
    for label, kind in [("CSV", "csv"), ("Excel", "xlsx")]:
        async with page.expect_download() as info:
            await page.get_by_role("link", name=label, exact=True).click()
        download = await info.value
        assert download.suggested_filename == f"website-data.{kind}"
        path = ARTIFACTS / f"{prefix}.{kind}"
        await download.save_as(path)
        if kind == "csv":
            parsed = list(csv.reader(StringIO(path.read_text(encoding="utf-8-sig"))))
        else:
            sheet = load_workbook(path).active
            assert sheet.freeze_panes == "A2"
            parsed = [[v if v is not None else "" for v in row] for row in sheet.values]
        assert parsed[0] == names, parsed[0]
        assert parsed[1:] == expected, (kind, parsed[1:], expected)


async def main():
    ARTIFACTS.mkdir(exist_ok=True)
    report = []
    errors = []
    bad_server = []
    api_requests = []

    def passed(name, **detail):
        row = {"scenario": name, "passed": True, **detail}
        report.append(row)
        print(row, flush=True)

    async with async_playwright() as p:
        browser_name = os.environ.get("REVIEW_BROWSER", "chromium")
        browser = await getattr(p, browser_name).launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "console",
            lambda m: (
                errors.append(m.text)
                if m.type == "error"
                and not m.text.startswith("Failed to load resource:")
                else None
            ),
        )
        page.on(
            "response",
            lambda r: (
                bad_server.append(f"{r.status} {r.url}")
                if "/api/" in r.url and r.status >= 500
                else None
            ),
        )
        page.on(
            "request",
            lambda r: (
                api_requests.append({"method": r.method, "url": r.url})
                if "/api/" in r.url
                else None
            ),
        )
        # Configure every field with actual inputs, not a fixture preset.
        await configure(page, manual=True)
        status, data = await preview(page, check_loading=True)
        assert status == 200 and len(data["records"]) == 4
        assert data["records"][0]["Title"] == "The Creative Act"
        passed(
            "Manual URL, field/selector configuration, first-page preview and loading"
        )
        await page.get_by_role("textbox", name="Search results").fill("creative")
        await expect(page.locator("tbody tr")).to_have_count(1)
        status, data = await preview(page)
        await expect(page.get_by_role("textbox", name="Search results")).to_have_value(
            ""
        )
        await expect(page.locator("tbody tr")).to_have_count(4)
        passed("Repeated preview clears stale table search")
        key = await start(page)
        await expect(page.get_by_label("Website URL")).to_be_disabled()
        await expect(
            page.get_by_role("button", name="Preview", exact=True)
        ).to_be_disabled()
        await expect(page.get_by_role("button", name="Stop run")).to_be_visible()
        # Completion must not move the user out of their chosen Activity tab.
        await page.get_by_role("button", name="Activity").click()
        data = await finish(page, key)
        await expect(page.get_by_role("button", name="Activity")).to_have_class(
            "selected"
        )
        assert (
            data["pages"] == 3
            and len(data["records"]) == 11
            and data["duplicates"] == 1
            and data["missing"] == 1
        ), data
        assert data["records"][7]["Price"] == ""
        await page.get_by_role("button", name="Data", exact=True).click()
        await expect(page.locator("tbody tr")).to_have_count(10)
        await expect(page.get_by_text("Missing", exact=True)).to_be_visible()
        await page.get_by_role("button", name="Next results page").click()
        await expect(page.locator("tbody tr")).to_have_count(1)
        await page.get_by_role("button", name="Previous results page").click()
        await exports(page, data, "review-complete")
        await page.screenshot(
            path=str(ARTIFACTS / "desktop-results.png"), full_page=True
        )
        passed(
            "Three-page extraction, duplicates, missing cells, navigation, exact CSV/XLSX content",
            records=11,
            pages=3,
        )
        # Invalid native constraints must block both actions before sending requests.
        await page.get_by_label("Page limit").fill("51")
        before = len(api_requests)
        await page.get_by_role("button", name="Start extraction", exact=True).click()
        await page.wait_for_timeout(150)
        assert len(api_requests) == before
        assert not await page.get_by_label("Page limit").evaluate(
            "(e)=>e.validity.valid"
        )
        await page.get_by_label("Page limit").fill("1")
        data = await finish(page, await start(page))
        assert (
            data["pages"] == 1
            and len(data["records"]) == 4
            and data["stop_reason"] == "Page limit reached."
        )
        passed("Page limit and native Start validation", records=4, pages=1)
        await page.get_by_label("Page limit").fill("2")
        await page.get_by_role("button", name="Advanced settings").click()
        await page.get_by_label("Remove duplicate records").uncheck()
        data = await finish(page, await start(page))
        assert (
            data["pages"] == 2 and len(data["records"]) == 9 and data["duplicates"] == 0
        )
        passed("Duplicate removal disabled", records=9, pages=2)
        await configure(page, DEMO + "?js=1")
        await page.get_by_label("Render JavaScript").check()
        data = await finish(page, await start(page))
        assert (
            data["pages"] == 3
            and len(data["records"]) == 11
            and data["duplicates"] == 1
        )
        await exports(page, data, "review-javascript")
        passed(
            "Real Playwright JavaScript rendering and pagination", records=11, pages=3
        )
        await configure(page, DEMO + "?failure=1")
        data = await finish(page, await start(page), "partial")
        assert (
            data["pages"] == 2 and data["attempted"] == 3 and len(data["records"]) == 8
        )
        await page.get_by_role("button", name="Activity").click()
        await expect(
            page.get_by_text(
                "HTTP 503. Access stopped; no restriction bypass attempted.", exact=True
            )
        ).to_be_visible()
        await page.screenshot(
            path=str(ARTIFACTS / "desktop-partial.png"), full_page=True
        )
        await exports(page, data, "review-partial")
        passed(
            "Failed third page preserves and exports earlier results",
            records=8,
            pages=2,
        )
        await page.get_by_role("button", name="Data", exact=True).click()
        await page.set_viewport_size({"width": 390, "height": 844})
        table = page.get_by_role("region", name="Extracted records", exact=True)
        await table.focus()
        await page.keyboard.press("ArrowRight")
        await page.wait_for_function(
            "document.querySelector('.table-wrap').scrollLeft > 0"
        )
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        await page.screenshot(path=str(ARTIFACTS / "mobile.png"), full_page=True)
        passed("Responsive result table supports keyboard horizontal scrolling")
        await page.set_viewport_size({"width": 1440, "height": 900})
        await configure(page, "https://demo.website-extractor.test/malformed")
        data = await finish(page, await start(page))
        assert (
            len(data["records"]) == 1
            and data["records"][0]["Title"] == "Unclosed title"
            and data["missing"] == 3
        )
        passed("Malformed fixture HTML and absent fields", records=1, missing=3)
        await configure(page)
        await page.get_by_label("Value", exact=True).nth(0).select_option("custom")
        custom = page.get_by_label("Field 1 custom attribute", exact=True)
        await custom.fill("data-value")
        await custom.press("ControlOrMeta+a")
        await custom.press("Backspace")
        await expect(custom).to_be_visible()
        await expect(custom).to_have_value("")
        before = len(api_requests)
        await page.get_by_role("button", name="Start extraction", exact=True).click()
        await page.wait_for_timeout(150)
        assert len(api_requests) == before
        await custom.fill("class")
        await page.get_by_label("Field 1 selector", exact=True).fill("")
        status, data = await preview(page)
        assert (
            status == 200
            and len(data["records"]) == 4
            and all(r["Title"] == "book" for r in data["records"])
        )
        await page.get_by_label("Value", exact=True).nth(1).select_option("custom")
        await page.get_by_label("Field 2 custom attribute", exact=True).fill("data-id")
        await page.get_by_role("button", name="Remove field 1", exact=True).click()
        await expect(
            page.get_by_label("Field 1 custom attribute", exact=True)
        ).to_have_value("data-id")
        passed(
            "Custom attribute editing, required validation, self selector, and removing/reindexing fields"
        )
        await configure(page)
        await page.get_by_label("Field 1 name", exact=True).fill(" Title ")
        status, data = await preview(page)
        assert status == 200 and data["fields"][0] == "Title"
        await expect(page.locator("tbody tr").first.locator("td").nth(1)).to_have_text(
            "The Creative Act"
        )
        passed(
            "Canonical field names prevent whitespace from producing false missing cells"
        )
        await configure(page, DEMO + "?js=slow")
        await page.get_by_label("Render JavaScript").check()
        await page.get_by_role("button", name="Advanced settings").click()
        await page.get_by_label("Page timeout (seconds)").fill("2")
        status, data = await preview(page)
        assert (
            status == 200
            and data["status"] == "failed"
            and "timed out" in data["issues"][0]["message"]
        ), data
        await page.get_by_role("button", name="Activity").click()
        await expect(
            page.get_by_text(
                "Page timed out. Try a longer timeout or HTML mode.", exact=True
            )
        ).to_be_visible()
        passed("Real JavaScript wait timeout is reported as failure")
        await configure(page)
        await page.get_by_label("Record selector", exact=True).fill("[")
        status, data = await preview(page)
        assert status == 422
        await expect(page.get_by_role("alert")).to_contain_text("Invalid CSS selector")
        await page.get_by_label("Record selector", exact=True).fill(".does-not-exist")
        status, data = await preview(page)
        assert (
            status == 200
            and not data["records"]
            and data["issues"][0]["level"] == "warning"
        )
        await page.get_by_role("button", name="Activity").click()
        await expect(
            page.get_by_text("No records matched the row selector.", exact=True)
        ).to_be_visible()
        passed("Broken selectors and valid selectors matching no records")
        for url, expected in [
            ("file:///etc/passwd", 422),
            ("http://127.0.0.1/", 200),
            ("http://169.254.169.254/", 200),
            ("https://demo.website-extractor.test/restricted", 200),
        ]:
            await configure(page, url)
            status, data = await preview(page)
            assert status == expected, (url, status, data)
            if expected == 200:
                assert data["status"] == "failed" and not data["records"], data
        passed("Unsafe schemes, private/metadata addresses, robots.txt denial")
        await configure(page)
        await page.get_by_label("Website URL").fill("not a URL")
        before = len(api_requests)
        await page.get_by_role("button", name="Start extraction", exact=True).click()
        await page.wait_for_timeout(150)
        assert len(api_requests) == before
        passed("Malformed URL blocked by form before any API request")
        await configure(page)
        await page.get_by_label("Request delay").fill("2")
        key = await start(page)
        await page.locator("tbody tr").first.wait_for(timeout=10000)
        await page.get_by_role("button", name="Stop run").click()
        await expect(page.get_by_role("button", name="Stopping…")).to_be_disabled()
        data = await finish(page, key, "cancelled")
        assert 4 <= len(data["records"]) < 11
        await exports(page, data, "review-cancelled")
        passed(
            "Cancellation retains exportable records and unlocks controls",
            records=len(data["records"]),
        )
        # Same workspace immediately supports another complete run.
        await page.get_by_label("Request delay").fill("0.5")
        await page.get_by_label("Page limit").fill("1")
        data = await finish(page, await start(page))
        assert len(data["records"]) == 4
        passed("Repeat run after cancellation")
        assert not errors, errors
        assert not bad_server, bad_server
        passed(
            "Browser console, page runtime, and actual API transport",
            api_requests=len(api_requests),
        )
        await browser.close()
    (ARTIFACTS / f"workflow-review-{browser_name}.json").write_text(
        json.dumps(
            {
                "scenarios": report,
                "errors": errors,
                "server_errors": bad_server,
                "requests": api_requests,
            },
            indent=2,
        )
    )
    print(
        f"PASS: {len(report)} workflow scenarios; exact CSV/XLSX comparisons; no browser errors or API 5xx responses."
    )


if __name__ == "__main__":
    asyncio.run(main())
