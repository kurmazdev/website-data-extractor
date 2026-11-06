import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .engine import extract
from .exports import export
from .middleware import BodyLimitMiddleware
from .models import Config, Result


@dataclass
class Job:
    config: Config
    result: Result = field(default_factory=Result)
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    created: float = field(default_factory=time.monotonic)
    task: object = None


jobs = {}
active_previews = 0


@asynccontextmanager
async def lifespan(app):
    yield
    tasks = [job.task for job in jobs.values() if job.task and not job.task.done()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    jobs.clear()


app = FastAPI(title="Website Data Extractor", lifespan=lifespan)
app.add_middleware(BodyLimitMiddleware)


@app.middleware("http")
async def local_access(request: Request, call_next):
    # Local utility: no CORS, remote Host headers or cross-origin mutations.
    host = request.headers.get("host", "").split(":")[0]
    if host not in ("localhost", "127.0.0.1", "testserver"):
        return Response("Local access only.", status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin not in (
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ):
            return Response("Cross-origin access blocked.", status_code=403)
    if (
        request.headers.get("content-length", "").isdigit()
        and int(request.headers["content-length"]) > 32768
    ):
        return Response("Request body too large.", status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/preview")
async def preview(config: Config):
    global active_previews
    if active_previews + sum(not j.task.done() for j in jobs.values()) >= 2:
        raise HTTPException(
            429, "Two operations are already running. Wait for one to finish."
        )
    active_previews += 1
    try:
        result = await asyncio.wait_for(extract(config, preview=True), 90)
        return {"fields": [f.name for f in config.fields], **result.model_dump()}
    except asyncio.TimeoutError:
        raise HTTPException(504, "Preview timed out. Try HTML mode or a smaller page.")
    finally:
        active_previews -= 1


async def run(job):
    try:
        await asyncio.wait_for(extract(job.config, job.result, job.cancel), 600)
    except asyncio.TimeoutError:
        job.result.status = "partial" if job.result.records else "failed"
        job.result.stop_reason = (
            "The 10-minute run limit was reached. Collected records are available."
        )
    except asyncio.CancelledError:
        job.result.status = "cancelled"
        raise


@app.post("/api/jobs", status_code=201)
async def start(config: Config):
    for key, job in list(jobs.items()):
        if job.task.done() and time.monotonic() - job.created > 3600:
            del jobs[key]
    if active_previews + sum(not j.task.done() for j in jobs.values()) >= 2:
        raise HTTPException(
            429, "Two operations are already running. Wait for one to finish."
        )
    if len(jobs) >= 10:
        finished = [key for key, j in jobs.items() if j.task.done()]
        if finished:
            del jobs[finished[0]]
    key = uuid4().hex
    job = Job(config)
    jobs[key] = job
    job.task = asyncio.create_task(run(job))
    return {"id": key}


def get_job(key):
    if key not in jobs:
        raise HTTPException(
            404, "Run not found. Runs are held in memory; a restart clears them."
        )
    return jobs[key]


@app.get("/api/jobs/{key}")
async def status(key: str):
    job = get_job(key)
    return {
        "id": key,
        "fields": [f.name for f in job.config.fields],
        **job.result.model_dump(),
    }


@app.post("/api/jobs/{key}/cancel")
async def cancel(key: str):
    job = get_job(key)
    job.cancel.set()
    return {"status": "stopping"}


@app.get("/api/jobs/{key}/export/{kind}")
async def download(key: str, kind: str):
    if kind not in ("csv", "xlsx"):
        raise HTTPException(400, "Choose csv or xlsx.")
    job = get_job(key)
    if not job.result.records:
        raise HTTPException(409, "No records to export yet.")
    # Snapshot allows a consistent export while a run is still collecting records.
    data = await asyncio.to_thread(
        export, list(job.result.records), [f.name for f in job.config.fields], kind
    )
    media = (
        "text/csv; charset=utf-8"
        if kind == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return Response(
        data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="website-data.{kind}"'},
    )


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/")
    async def index():
        return FileResponse(DIST / "index.html")
