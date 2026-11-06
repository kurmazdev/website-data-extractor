import asyncio
import csv
from io import BytesIO, StringIO

import pytest
from extractor.api import app, jobs
from extractor.exports import export
from httpx import ASGITransport, AsyncClient
from openpyxl import load_workbook
from test_engine import config


def test_csv_unicode_commas_and_formulas():
    records = [
        {
            "Title": 'Café, "A"\nTwo',
            "Price": ' =HYPERLINK("evil")',
            "_source": "https://example.org",
        }
    ]
    data = export(records, ["Title", "Price"], "csv")
    rows = list(csv.reader(StringIO(data.decode("utf-8-sig"))))
    assert rows[1][0] == records[0]["Title"]
    assert rows[1][1].startswith("' =")
    assert rows[0] == ["Title", "Price", "_source"]


def test_xlsx_values_and_formula_safety():
    data = export(
        [{"Title": "=1+1", "Price": "$25", "_source": "https://example.org"}],
        ["Title", "Price"],
        "xlsx",
    )
    sheet = load_workbook(BytesIO(data)).active
    assert sheet["A2"].value == "'=1+1" and sheet["A2"].data_type == "s"
    assert sheet["B2"].value == "$25" and sheet.freeze_panes == "A2"
    assert sheet.max_column == 3


async def test_full_api_preview_run_partial_and_exports():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        c = config(url=config().url + "?failure=1").model_dump()
        preview = await client.post("/api/preview", json=c)
        assert preview.status_code == 200 and len(preview.json()["records"]) == 4
        started = await client.post("/api/jobs", json=c)
        assert started.status_code == 201
        key = started.json()["id"]
        await jobs[key].task
        result = (await client.get("/api/jobs/" + key)).json()
        assert result["status"] == "partial" and len(result["records"]) == 8
        for kind in ("csv", "xlsx"):
            response = await client.get(f"/api/jobs/{key}/export/{kind}")
            assert response.status_code == 200
            if kind == "csv":
                assert (
                    len(
                        list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
                    )
                    == 9
                )
            else:
                assert load_workbook(BytesIO(response.content)).active.max_row == 9
        assert (await client.get(f"/api/jobs/{key}/export/pdf")).status_code == 400
        assert (await client.get("/api/jobs/missing")).status_code == 404
    jobs.clear()


async def test_origin_host_and_validation():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (
            await client.post(
                "/api/preview",
                json=config().model_dump(),
                headers={"Origin": "https://evil.example"},
            )
        ).status_code == 403
        assert (
            await client.get("/api/health", headers={"Host": "evil.example"})
        ).status_code == 403
        c = config().model_dump()
        c["row_selector"] = "["
        assert (await client.post("/api/preview", json=c)).status_code == 422


async def test_job_concurrency_limit():
    event = asyncio.Event()
    from unittest.mock import patch

    async def held(job):
        await event.wait()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        with patch("extractor.api.run", new=held):
            for _ in range(2):
                assert (
                    await client.post("/api/jobs", json=config().model_dump())
                ).status_code == 201
            assert (
                await client.post("/api/jobs", json=config().model_dump())
            ).status_code == 429
            event.set()
            await asyncio.gather(*(j.task for j in jobs.values()))
    jobs.clear()


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_export_strips_illegal_controls(kind):
    data = export([{"Title": "A\x00B\x0bC"}], ["Title"], kind)
    if kind == "csv":
        assert "ABC" in data.decode("utf-8-sig")
    else:
        assert load_workbook(BytesIO(data)).active["A2"].value == "ABC"


async def test_chunked_body_limit():
    async def chunks():
        yield b"{" + b" " * 20000
        yield b" " * 20000 + b"}"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/preview",
            content=chunks(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413


async def test_finished_job_retention_and_empty_export():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for _ in range(11):
            started = await client.post(
                "/api/jobs", json=config(url="http://127.0.0.1/").model_dump()
            )
            assert started.status_code == 201
            key = started.json()["id"]
            await jobs[key].task
        assert len(jobs) == 10
        assert (await client.get(f"/api/jobs/{key}/export/csv")).status_code == 409
    jobs.clear()


async def test_preview_returns_canonical_field_names():
    body = config().model_dump()
    body["fields"][0]["name"] = " Title "
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/api/preview", json=body)
        assert response.status_code == 200
        result = response.json()
        assert result["fields"] == ["Title", "Price"]
        assert result["records"][0]["Title"] == "The Creative Act"
