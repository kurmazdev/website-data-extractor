"""Real wheel/keyboard regression checks against the built, running application.

Set REVIEW_BROWSERS=chromium,firefox,webkit to expand browser coverage.
Playwright synthesizes wheel input; physical trackpad momentum is not emulated.
"""

import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright, expect

SIZES = [
    (1440, 900),
    (1280, 720),
    (1024, 768),
    (801, 650),
    (820, 600),
    (1280, 480),
    (768, 900),
    (600, 800),
    (390, 844),
    (320, 568),
]


async def wheel_to_edge(page, region, direction):
    # Firefox caps a wheel event to roughly one viewport, regardless of delta.
    # Repeat real wheel events instead of assuming one event reaches an edge.
    for _ in range(30):
        edge = await region.evaluate(
            "(e)=>({top:e.scrollTop,max:e.scrollHeight-e.clientHeight})"
        )
        if (direction < 0 and edge["top"] <= 1) or (
            direction > 0 and edge["top"] >= edge["max"] - 1
        ):
            return
        await page.mouse.wheel(0, direction * 5000)
        await page.wait_for_timeout(250)
    raise AssertionError("Wheel input did not reach the settings boundary")


async def check(page, width, height, stress=False):
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(os.environ.get("EXTRACTOR_TEST_URL", "http://127.0.0.1:8000"))
    await page.get_by_role("button", name="Load bookshop demo").click()
    if stress:
        for _ in range(16):
            await page.get_by_role("button", name="Add field", exact=True).click()
    region = page.get_by_role("region", name="Configuration settings", exact=True)
    desktop = width > 800 and height >= 650
    await page.evaluate("window.scrollTo(0, 0)")
    if desktop:
        initial = await region.evaluate(
            "(e) => ({top:e.scrollTop,height:e.clientHeight,full:e.scrollHeight})"
        )
        assert initial["height"] < initial["full"], initial
        box = await region.bounding_box()
        await page.mouse.move(box["x"] + 80, box["y"] + min(80, box["height"] / 2))
        await page.mouse.wheel(0, 5000)
        await page.wait_for_function(
            "document.querySelector('.config-scroll').scrollTop > 0"
        )
        await page.wait_for_timeout(200)
        assert await page.evaluate("scrollY") == 0, (
            "Wheel escaped the configuration scroller"
        )
        bottom = await page.locator(".configuration").evaluate(
            "(e)=>e.getBoundingClientRect().bottom"
        )
        assert bottom <= height, (bottom, height)
        before = await page.evaluate("scrollY")
        await wheel_to_edge(page, region, 1)
        await page.mouse.wheel(0, 5000)
        await page.wait_for_timeout(150)
        assert await page.evaluate("scrollY") == before, (
            "Wheel chained to page at boundary"
        )
        await wheel_to_edge(page, region, -1)
        # Small deltas exercise the same path used by high-resolution trackpads.
        for _ in range(8):
            await page.mouse.wheel(0, 24)
        await page.wait_for_function(
            "document.querySelector('.config-scroll').scrollTop > 0"
        )
        assert await page.evaluate("scrollY") == before
        # Allow the synthetic wheel gesture to finish before switching input modes.
        await page.wait_for_timeout(250)
        await region.focus()
        await page.keyboard.press("Control+Home" if os.name == "nt" else "Home")
        await page.wait_for_function(
            "document.querySelector('.config-scroll').scrollTop === 0"
        )
        await expect(region).to_be_focused()
        await page.wait_for_timeout(150)
        await page.keyboard.press("PageDown")
        await page.wait_for_function(
            "document.querySelector('.config-scroll').scrollTop > 0"
        )
        await page.keyboard.press("End")
        await page.wait_for_function(
            "document.querySelector('.config-scroll').scrollTop > 0"
        )
    else:
        assert await region.evaluate("(e)=>e.clientHeight === e.scrollHeight"), (
            "Unexpected nested mobile/short-screen scroll"
        )
        await page.mouse.move(min(width - 40, 200), min(height - 80, 350))
        await page.mouse.wheel(0, 800)
        await page.wait_for_function("scrollY > 0")
    await page.get_by_role("button", name="Advanced settings").click()
    timeout = page.get_by_label("Page timeout (seconds)")
    await timeout.fill("12")
    # Traverse the complete real form using Tab: browser focus must scroll each
    # control into view, including off-screen custom fields and advanced options.
    await page.get_by_label("Website URL").focus()
    expected = await region.evaluate("""root => Array.from(root.querySelectorAll('input, select, button'))
      .map((e,i) => ({e,i})).filter(({e})=>!e.disabled && e.getBoundingClientRect().width>0).map(({i})=>i)""")
    reached = set()
    visited = 0
    for _ in range(180):
        reached.add(
            await region.evaluate(
                "root=>Array.from(root.querySelectorAll('input,select,button')).indexOf(document.activeElement)"
            )
        )
        element = page.locator(":focus")
        bounds = await element.bounding_box()
        if bounds:
            assert bounds["y"] >= -1 and bounds["y"] + bounds["height"] <= height + 1, (
                width,
                height,
                await element.get_attribute("id"),
                bounds,
            )
        if await timeout.evaluate("(e)=>e===document.activeElement"):
            break
        await page.keyboard.press("Tab")
        visited += 1
    else:
        raise AssertionError("Keyboard navigation never reached page timeout")
    assert set(expected) <= reached, (
        f"Keyboard skipped configuration controls: {set(expected) - reached}"
    )
    assert visited > 15
    await page.keyboard.press("Tab")
    await expect(
        page.get_by_role("button", name="Preview", exact=True),
        f"After timeout, focus landed on {await page.evaluate('document.activeElement.outerHTML.slice(0,200)')}",
    ).to_be_focused()
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
        "Horizontal page overflow"
    )
    assert await region.evaluate("(e)=>e.scrollWidth <= e.clientWidth"), (
        "Clipped configuration columns"
    )
    # The help dialog traps focus and restores the triggering control.
    guide = page.get_by_role("button", name="Quick guide")
    await guide.click()
    await page.keyboard.press("Shift+Tab")
    await expect(page.get_by_role("button", name="Got it")).to_be_focused()
    await page.keyboard.press("Tab")
    await expect(page.get_by_role("button", name="Close guide")).to_be_focused()
    await page.keyboard.press("Escape")
    await expect(guide).to_be_focused()
    return {
        "viewport": f"{width}x{height}",
        "stress_fields": 20 if stress else 4,
        "tab_steps": visited,
        "scroll": "panel" if desktop else "document",
    }


async def main():
    Path("artifacts").mkdir(exist_ok=True)
    report = []
    async with async_playwright() as p:
        for name in os.environ.get("REVIEW_BROWSERS", "chromium").split(","):
            print(f"Checking {name}", flush=True)
            browser = await getattr(p, name).launch()
            page = await browser.new_page()
            for width, height in SIZES:
                result = await check(page, width, height)
                report.append({"browser": name, **result})
                print(name, result, flush=True)
            for width, height in [(1440, 900), (390, 844)]:
                result = await check(page, width, height, stress=True)
                report.append({"browser": name, **result})
            await page.screenshot(
                path=f"artifacts/{name}-layout-mobile.png", full_page=True
            )
            await browser.close()
    Path("artifacts/layout-review.json").write_text(json.dumps(report, indent=2))
    print(
        f"PASS: {len(report)} viewport/field-count combinations; wheel, keyboard, boundaries, responsive layout, focus trapping."
    )


if __name__ == "__main__":
    asyncio.run(main())
