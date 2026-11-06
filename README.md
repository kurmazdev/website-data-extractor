# Website Data Extractor

A Python and React application that extracts structured records from permitted public web pages using CSS selectors. Preview field mappings, follow link-based pagination, inspect results, and export CSV or Excel files.

## Features

- Configure record selectors, field selectors, text/attribute extraction, and next-page links.
- Preview the first page before running an extraction.
- Deduplicate records, report missing values, and retain results after partial failures.
- Inspect activity and page errors; stop a run between pages.
- Render supported JavaScript pages using guarded Chromium requests.
- Download UTF-8 CSV or XLSX exports, including source URLs.

## Technologies

Python 3.11+, FastAPI, aiohttp, Beautiful Soup, openpyxl, Playwright, React 19, TypeScript, and Vite. Tests use pytest, Ruff, and Playwright.

## Installation

Requires Python 3.11 or newer and Node.js 20.19 or newer (Node 22 recommended). Use a compatible interpreter for `python3` below. Run from the project root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -c requirements-lock.txt -e '.[test]'
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python -m playwright install chromium
.venv/bin/python -m uvicorn extractor.api:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Chromium is needed for JavaScript rendering and browser tests; HTML extraction and the default demo do not require it. On Linux, browser installation may require `python -m playwright install --with-deps chromium`.

For frontend development, keep the backend running and use `npm --prefix frontend run dev`. Open http://127.0.0.1:5173; API requests are proxied to the backend.

## Usage

1. Select **Load bookshop demo** or enter the URL of a page you are permitted to access.
2. Set a repeating record selector, field names/selectors, and an optional next-page link selector.
3. Select **Preview** and inspect the resulting columns.
4. Select **Start extraction**, review records and activity, and download CSV or Excel.

The fictional bookshop fixture produces 11 unique records across three pages, removes one duplicate, and reports one missing price. Its URL, `https://demo.website-extractor.test/catalog`, is resolved inside the application and is not an external website. Add `?failure=1` to demonstrate partial results, or `?js=1` with JavaScript rendering enabled to exercise the renderer.

## Security and limits

- Public HTTP(S) destinations only, on ports 80/443, without credentials in URLs. Private, loopback, link-local, reserved, and unsafe IP representations are blocked.
- DNS validation occurs in the connection resolver. Redirects and pagination stay on the original origin; every destination is checked.
- Robots.txt and pacing restrictions are enforced. Access restrictions, authentication errors, and rate limits are not bypassed.
- JavaScript rendering uses an offline browser whose permitted requests pass through the guarded fetcher. Only same-origin GET requests are supported; frames, WebSockets, workers, service workers, downloads, and form submissions are blocked. Existing site CSP is preserved.
- Exports neutralize spreadsheet formula prefixes; React renders scraped values as text.
- Requests, response bodies, page counts, fields, records, runtime, concurrency, and retained jobs are bounded.
- No credentials, cookies, login sessions, or environment proxies are used. Host/Origin checks protect the local API; no CORS access is enabled.

Runs are held in process memory and expire; they do not survive a restart. This is a single-user local utility, not an authenticated internet service or a general-purpose sandbox for hostile scripts. Keep it bound to loopback. Login-required pages, CAPTCHA bypass, interactive pagination, and third-party JavaScript resources are unsupported.

## Verification

```sh
RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest -q
.venv/bin/ruff check backend scripts
.venv/bin/ruff format --check backend scripts
npm --prefix frontend run build
npm --prefix frontend run format:check
# With the backend running on port 8000:
.venv/bin/python scripts/verify_ui.py
.venv/bin/python scripts/verify_layout.py
```

Verification scripts use the bundled fixture and save screenshots, reports, and downloads under ignored `artifacts/`. `REVIEW_BROWSER` selects the workflow browser; `REVIEW_BROWSERS` selects layout browsers. Install the corresponding Playwright browsers first. CI runs the Chromium security tests, production build, and UI/download/layout checks.

## Structure

- `backend/extractor/`: API, validation, guarded network access, rendering, pacing, extraction, and exports.
- `backend/tests/`: API, export, HTTP, rendering, and network security regressions.
- `frontend/src/`: extraction configuration, preview/results, activity, and downloads.
- `examples/`: fictional demo configuration and exports.
- `scripts/`: browser workflow and responsive-layout checks.

Dependencies are installed from their registries and retain their respective licenses. No third-party dependency source is vendored in this repository.
