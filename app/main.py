import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from db import connect, wait_for_db
from worker import EXPORT_DIR, cleanup_leftover_files, recover_interrupted_jobs, start_worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

MAX_PENDING_JOBS = 20  # pending 작업이 이만큼 쌓이면 새 요청은 429로 거절 (대기열이 끝없이 쌓이는 것 방지)

# "개수 확인 → 등록"을 한 번에 한 요청씩만 실행하게 하는 잠금.
# 없으면 두 요청이 동시에 19개를 보고 둘 다 등록해서 상한을 넘을 수 있다.
# 단일 프로세스 전제이므로 파이썬 Lock으로 충분하다.
_create_lock = threading.Lock()

JOB_COLUMNS = """
    id AS job_id, status, requested_at, started_at, finished_at,
    file_path, total_rows, processed_rows, error_message
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 시작 시: DB 연결 확인 → 중단된 작업·남은 임시 파일 정리 → 워커 시작
    wait_for_db()
    os.makedirs(EXPORT_DIR, exist_ok=True)
    recover_interrupted_jobs()
    cleanup_leftover_files()
    stop_event = threading.Event()
    worker_thread = start_worker(stop_event)
    yield
    # 서버 종료 시: 워커 정지
    stop_event.set()
    worker_thread.join(timeout=10)


app = FastAPI(title="Playstory Excel Export", lifespan=lifespan)


@app.post("/api/jobs", status_code=202)
def create_job():
    """엑셀 생성 요청. 파일은 만들지 않고 작업(job)만 등록한 뒤 바로 응답한다."""
    with _create_lock, connect() as conn:
        pending = conn.execute("SELECT count(*) AS n FROM jobs WHERE status = 'pending'").fetchone()["n"]
        if pending >= MAX_PENDING_JOBS:
            raise HTTPException(429, "대기 중인 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.")
        job = conn.execute(f"INSERT INTO jobs DEFAULT VALUES RETURNING {JOB_COLUMNS}").fetchone()
    return job


@app.get("/api/jobs")
def list_jobs(limit: int = 50):
    limit = max(1, min(limit, 200))
    with connect() as conn:
        return conn.execute(f"SELECT {JOB_COLUMNS} FROM jobs ORDER BY id DESC LIMIT %s", (limit,)).fetchall()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    with connect() as conn:
        job = conn.execute(f"SELECT {JOB_COLUMNS} FROM jobs WHERE id = %s", (job_id,)).fetchone()
    if job is None:
        raise HTTPException(404, "job을 찾을 수 없습니다.")
    return job


@app.get("/api/jobs/{job_id}/download")
def download(job_id: int):
    job = get_job(job_id)
    if job["status"] != "done":
        raise HTTPException(409, f"아직 다운로드할 수 없습니다. (현재 상태: {job['status']})")
    if not job["file_path"] or not os.path.exists(job["file_path"]):
        raise HTTPException(404, "파일이 존재하지 않습니다.")
    return FileResponse(
        job["file_path"],
        filename=os.path.basename(job["file_path"]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# 프론트엔드(index.html)도 같은 서버가 제공한다. API 라우트보다 뒤에 등록해야 /api/* 가 가려지지 않는다.
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")
