import asyncio

import pytest
from extractor.engine import extract, parse
from extractor.models import DEMO_URL, Config, ExtractionField, Result


def config(**kwargs):
    data = dict(
        url=DEMO_URL,
        row_selector=".book",
        fields=[
            ExtractionField(name="Title", selector="h2"),
            ExtractionField(name="Price", selector=".price"),
        ],
        next_selector="a.next",
        delay=0.5,
    )
    data.update(kwargs)
    return Config(**data)


async def test_demo_pagination_duplicates_missing():
    result = await extract(config())
    assert result.status == "completed"
    assert result.pages == 3
    assert len(result.records) == 11
    assert result.duplicates == 1
    assert result.missing == 1
    assert all(r["_source"].startswith(DEMO_URL) for r in result.records)


async def test_partial_failure_keeps_rows():
    result = await extract(config(url=DEMO_URL + "?failure=1"))
    assert result.status == "partial"
    assert result.pages == 2 and result.attempted == 3
    assert len(result.records) == 8
    assert "503" in result.issues[0].message


async def test_preview_only_first_page():
    result = await extract(config(), preview=True)
    assert result.pages == 1 and len(result.records) == 4


async def test_page_limit_and_no_dedupe():
    result = await extract(config(max_pages=2, deduplicate=False))
    assert result.pages == 2 and len(result.records) == 9 and result.duplicates == 0
    assert result.stop_reason == "Page limit reached."


def test_malformed_html_attribute_and_missing():
    c = config(
        fields=[
            ExtractionField(name="Link", selector="a", attribute="href"),
            ExtractionField(name="Absent", selector=".missing"),
        ]
    )
    rows, next_url = parse('<div class=book><a href="/detail"> Unclosed', c, DEMO_URL)
    assert rows[0]["Link"] == "https://demo.website-extractor.test/detail"
    assert rows[0]["Absent"] == ""
    assert next_url is None


class FakeFetcher:
    def __init__(self, config):
        self.config = config

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def document(self, url):
        return (
            '<div class=book><h2>Test</h2></div><a class=next href="/catalog">Next</a>',
            url,
        )


async def test_pagination_loop():
    result = await extract(config(), fetcher_factory=FakeFetcher)
    assert result.pages == 1
    assert "loop" in result.issues[0].message


async def test_timeout_is_clear():
    class TimedOut(FakeFetcher):
        async def document(self, url):
            raise asyncio.TimeoutError()

    result = await extract(config(), fetcher_factory=TimedOut)
    assert result.status == "failed"
    assert "timed out" in result.issues[0].message


async def test_external_pagination_blocked_keeps_results():
    class External(FakeFetcher):
        async def document(self, url):
            return (
                '<div class=book><h2>Test</h2></div><a class=next href="https://example.org/">Next</a>',
                url,
            )

    result = await extract(config(), fetcher_factory=External)
    assert result.status == "partial" and len(result.records) == 1
    assert "original origin" in result.issues[0].message


async def test_cancel_preserves_partial_rows():
    event = asyncio.Event()
    result = Result(records=[{"Title": "Kept"}])
    event.set()
    await extract(config(), result=result, cancel=event)
    assert result.status == "cancelled" and result.records == [{"Title": "Kept"}]


async def test_empty_selector_warning():
    result = await extract(config(row_selector=".nothing"), preview=True)
    assert not result.records and result.status == "completed"
    assert "No records" in result.issues[0].message


@pytest.mark.parametrize(
    "changes",
    [
        dict(row_selector="["),
        dict(url="file:///etc/passwd"),
        dict(url="https://user:secret@example.org"),
        dict(max_pages=51),
        dict(delay=0),
        dict(
            fields=[
                ExtractionField(name="Same", selector="a"),
                ExtractionField(name="same", selector="p"),
            ]
        ),
    ],
)
def test_configuration_validation(changes):
    with pytest.raises(ValueError):
        config(**changes)


async def test_record_cap_stops_without_extra_pages():
    class Many(FakeFetcher):
        async def document(self, url):
            html = "".join(
                f"<div class=book><h2>Row {i}</h2></div>" for i in range(5010)
            )
            return html + '<a class=next href="?page=2">Next</a>', url

    result = await extract(config(), fetcher_factory=Many)
    assert len(result.records) == 5000 and result.attempted == 1
    assert result.stop_reason == "Record limit reached (5,000)."


async def test_output_limit_keeps_records_and_missing_count_consistent(monkeypatch):
    import extractor.engine as engine

    class Rows(FakeFetcher):
        async def document(self, url):
            return (
                "<div class=book><h2>Kept</h2><span class=price>$10</span></div><div class=book><h2>Rejected</h2></div>",
                url,
            )

    first_size = sum(
        len(v.encode())
        for v in {"Title": "Kept", "Price": "$10", "_source": config().url}.values()
    )
    monkeypatch.setattr(engine, "MAX_OUTPUT_BYTES", first_size)
    result = await extract(config(), fetcher_factory=Rows)
    assert result.status == "partial" and len(result.records) == 1
    assert result.records[0]["Title"] == "Kept" and result.missing == 0
    assert "Output limit" in result.issues[0].message


def test_field_value_cap():
    rows, _ = parse(
        "<div class=book><h2>" + ("x" * 3000) + "</h2></div>", config(), config().url
    )
    assert len(rows[0]["Title"]) == 2000
