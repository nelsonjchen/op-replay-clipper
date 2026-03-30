"""FastAPI backend for the local Docker-based op-replay-clipper web UI."""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="OP Replay Clipper")

CLIPPER_IMAGE = os.environ.get("CLIPPER_IMAGE", "op-replay-clipper-render")
# Host path used for `docker run -v` mounts (must be a real host filesystem path).
SHARED_HOST_DIR = os.environ.get("SHARED_HOST_DIR", os.environ.get("SHARED_DIR", "/app/shared"))
# Local path inside the web container where the same volume is mounted.
SHARED_LOCAL_DIR = Path(os.environ.get("SHARED_LOCAL_DIR", "/app/shared"))


# ---------------------------------------------------------------------------
# Job tracking
# ---------------------------------------------------------------------------

class JobState(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


@dataclass
class Job:
    job_id: str
    state: JobState = JobState.queued
    logs: list[str] = field(default_factory=list)
    output_path: str = ""
    error: str = ""


JOBS: dict[str, Job] = {}


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

SMEAR_RENDER_TYPES = {"ui", "ui-alt", "driver-debug"}


class ClipRequestBody(BaseModel):
    route: str
    render_type: str = "ui"
    file_size_mb: int = 9
    file_format: str = "auto"
    smear_seconds: int = 3
    jwt_token: str = ""


class JobResponse(BaseModel):
    job_id: str
    state: str


class JobStatusResponse(BaseModel):
    job_id: str
    state: str
    error: str = ""
    has_output: bool = False


# ---------------------------------------------------------------------------
# Docker container management
# ---------------------------------------------------------------------------

def _build_docker_cmd(job: Job, req: ClipRequestBody) -> list[str]:
    """Build the ``docker run`` command to execute clip.py inside the render container."""
    job_dir = SHARED_LOCAL_DIR / job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    output_inside = f"/src/shared/{job.job_id}/output.mp4"

    cmd: list[str] = [
        "docker", "run", "--rm",
        "--shm-size=1g",
        "--gpus", "all",
        "-v", f"{SHARED_HOST_DIR}:/src/shared",
        "-e", "NVIDIA_DRIVER_CAPABILITIES=all",
        CLIPPER_IMAGE,
        # clip.py args (entrypoint already includes --skip-openpilot-update --skip-openpilot-bootstrap)
        req.render_type,
        req.route,
        "-o", output_inside,
        "-m", str(req.file_size_mb),
        "--file-format", req.file_format,
    ]

    if req.render_type in SMEAR_RENDER_TYPES:
        cmd.extend(["--smear-seconds", str(req.smear_seconds)])

    if req.jwt_token:
        cmd.extend(["-j", req.jwt_token])

    return cmd


async def _run_container(job: Job, req: ClipRequestBody) -> None:
    """Run the render container and stream its output into the job log."""
    cmd = _build_docker_cmd(job, req)
    job.state = JobState.running
    job.logs.append(f"$ {' '.join(cmd[:6])} ... {cmd[-1]}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    assert proc.stdout is not None
    async for raw_line in proc.stdout:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
        job.logs.append(line)

    exit_code = await proc.wait()

    output_path = SHARED_LOCAL_DIR / job.job_id / "output.mp4"
    if exit_code == 0 and output_path.exists():
        job.state = JobState.done
        job.output_path = str(output_path)
        job.logs.append("Render complete.")
    else:
        job.state = JobState.failed
        job.error = f"Container exited with code {exit_code}"
        job.logs.append(f"ERROR: {job.error}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text())


@app.post("/api/clip", response_model=JobResponse)
async def create_clip(body: ClipRequestBody) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]
    job = Job(job_id=job_id)
    JOBS[job_id] = job

    asyncio.create_task(_run_container(job, body))

    return {"job_id": job_id, "state": job.state.value}


@app.get("/api/clip/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.job_id,
        "state": job.state.value,
        "error": job.error,
        "has_output": bool(job.output_path),
    }


@app.get("/api/clip/{job_id}/status")
async def stream_status(job_id: str) -> StreamingResponse:
    """SSE endpoint that streams job logs in real-time."""
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_stream():
        sent = 0
        while True:
            # Send any new log lines
            while sent < len(job.logs):
                line = job.logs[sent]
                yield f"data: {line}\n\n"
                sent += 1

            # If job is terminal, send final state event and stop
            if job.state in (JobState.done, JobState.failed):
                yield f"event: state\ndata: {job.state.value}\n\n"
                break

            await asyncio.sleep(0.3)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/clip/{job_id}/download")
async def download_clip(job_id: str) -> FileResponse:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.state != JobState.done or not job.output_path:
        raise HTTPException(status_code=400, detail="Clip not ready")
    return FileResponse(
        job.output_path,
        media_type="video/mp4",
        filename=f"clip-{job_id}.mp4",
    )
