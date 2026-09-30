"""
비교 실험용 "단순한 방식" (실제 서비스 코드 아님)

흔히 가장 먼저 떠올리는 구현:
- 요청마다 FastAPI BackgroundTasks로 바로 작업 시작 (동시 실행 개수 제한 없음)
- fetchall()로 10만 건을 한 번에 메모리로 가져옴
- pandas DataFrame → to_excel() (openpyxl이 모든 셀을 메모리에 들고 있다가 한 번에 저장)
"""
import os
import threading

import pandas as pd
import psycopg
from fastapi import BackgroundTasks, FastAPI

DATABASE_URL = os.environ["DATABASE_URL"]
app = FastAPI()
jobs: dict[int, str] = {}   # 상태를 메모리에만 저장 (서버가 죽으면 사라짐)
_lock = threading.Lock()


def make_excel(job_id: int) -> None:
    jobs[job_id] = "processing"
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            cur = conn.execute("SELECT id, user_name, product_name, category, amount, status, order_date FROM orders")
            rows = cur.fetchall()                    # 10만 건을 한 번에
            columns = [d.name for d in cur.description]
        df = pd.DataFrame(rows, columns=columns)
        df.to_excel(f"/tmp/naive_job_{job_id}.xlsx", index=False)
        jobs[job_id] = "done"
    except Exception as e:
        jobs[job_id] = f"failed: {e}"


@app.post("/jobs", status_code=202)
def create_job(background_tasks: BackgroundTasks):
    with _lock:
        job_id = len(jobs) + 1
        jobs[job_id] = "pending"
    background_tasks.add_task(make_excel, job_id)
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def get_job(job_id: int):
    return {"job_id": job_id, "status": jobs.get(job_id, "unknown")}
