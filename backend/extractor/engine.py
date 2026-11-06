import asyncio
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup

from .models import Issue, Result
from .network import Fetcher
from .renderer import render
from .security import AccessError, check_url, origin

MAX_RECORDS = 5000
MAX_OUTPUT_BYTES = 10_000_000


def parse(html, config, url):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for element in soup.select(config.row_selector, limit=MAX_RECORDS + 1):
        record = {}
        for field in config.fields:
            node = element.select_one(field.selector) if field.selector else element
            value = ""
            if node is not None:
                if field.attribute:
                    value = node.get(field.attribute, "")
                    if isinstance(value, list):
                        value = " ".join(value)
                    if value and field.attribute in ("href", "src"):
                        value = urljoin(url, value)
                else:
                    value = node.get_text(" ", strip=True)
            record[field.name] = str(value).strip()[:2000]
        record["_source"] = url
        rows.append(record)
    link = soup.select_one(config.next_selector) if config.next_selector else None
    next_url = urljoin(url, link.get("href")) if link and link.get("href") else None
    return rows, next_url


async def extract(
    config, result=None, cancel=None, preview=False, fetcher_factory=Fetcher
):
    result = result or Result()
    visited, seen = set(), set()
    url = config.url
    output_bytes = 0
    try:
        async with fetcher_factory(config) as fetcher:
            for _ in range(1 if preview else config.max_pages):
                if cancel and cancel.is_set():
                    result.status = "cancelled"
                    result.stop_reason = (
                        "Stopped by you. Collected records are available."
                    )
                    return result
                url = urldefrag(url)[0]
                if url in visited:
                    result.issues.append(
                        Issue(
                            page=url,
                            message="Pagination loop detected.",
                            level="warning",
                        )
                    )
                    result.stop_reason = "Pagination loop detected."
                    break
                visited.add(url)
                result.current_url = url
                result.attempted += 1
                try:
                    check_url(url)
                    if origin(url) != origin(config.url):
                        raise AccessError(
                            "Pagination must stay on the original origin."
                        )
                    if config.render_js:
                        html, final = await asyncio.wait_for(
                            render(fetcher, url, config.row_selector),
                            config.timeout + 10,
                        )
                    else:
                        html, final = await fetcher.document(url)
                    records, next_url = parse(html, config, final)
                    result.pages += 1
                    if not records:
                        result.issues.append(
                            Issue(
                                page=final,
                                message="No records matched the row selector.",
                                level="warning",
                            )
                        )
                    for record in records:
                        fingerprint = tuple(record[f.name] for f in config.fields)
                        if config.deduplicate and fingerprint in seen:
                            result.duplicates += 1
                            continue
                        output_bytes += sum(
                            len(v.encode("utf-8")) for v in record.values()
                        )
                        if output_bytes > MAX_OUTPUT_BYTES:
                            raise AccessError(
                                "Output limit reached (10 MB). Collected records are available."
                            )
                        seen.add(fingerprint)
                        result.missing += sum(not record[f.name] for f in config.fields)
                        result.records.append(record)
                        if len(result.records) >= (10 if preview else MAX_RECORDS):
                            result.stop_reason = (
                                "Preview limited to 10 records."
                                if preview
                                else "Record limit reached (5,000)."
                            )
                            break
                    if len(result.records) >= (10 if preview else MAX_RECORDS):
                        break
                    if not next_url:
                        result.stop_reason = (
                            "No next page found."
                            if config.next_selector
                            else "Single page extracted."
                        )
                        break
                    url = next_url
                except Exception as e:
                    message = str(e) or type(e).__name__
                    if isinstance(e, asyncio.TimeoutError):
                        message = "Page timed out. Try a longer timeout or HTML mode."
                    result.issues.append(Issue(page=url, message=message[:500]))
                    result.stop_reason = (
                        "A page failed. Collected records have been kept."
                    )
                    break
            else:
                result.stop_reason = (
                    "Preview finished." if preview else "Page limit reached."
                )
        result.status = (
            "partial"
            if any(i.level == "error" for i in result.issues) and result.records
            else (
                "failed"
                if any(i.level == "error" for i in result.issues)
                else "completed"
            )
        )
    except Exception as e:
        result.issues.append(
            Issue(page=url, message=(str(e) or type(e).__name__)[:500])
        )
        result.status = "partial" if result.records else "failed"
    return result
