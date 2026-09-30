"""
엑셀 생성 워커 (백그라운드 스레드 1개)

- 1초마다 jobs 테이블을 보고, 가장 오래된 pending 작업을 하나 가져와 처리한다.
- 워커가 1개라 엑셀 생성은 항상 한 번에 하나만 실행된다.
  → 요청이 몰려도 "엑셀 생성 작업"이 동시에 쓰는 메모리·CPU는 1건 분량으로 제한된다. (대신 대기 시간이 늘어난다)
- 단일 프로세스·단일 워커를 전제로 설계했다. (서버 시작 시 정리 코드가 이 전제에 의존함)
"""
import logging
import os
import threading
import time

from psycopg import IsolationLevel
from psycopg.rows import tuple_row

from db import connect
from excel import write_orders_xlsx

try:
    import resource  # 리눅스 전용 (메모리 사용량 측정용)
except ImportError:
    resource = None

EXPORT_DIR = os.environ.get("EXPORT_DIR", "./exports")
TMP_DIR = os.path.join(EXPORT_DIR, "tmp")  # 엑셀 라이브러리가 쓰는 작업용 임시 파일 위치
CHUNK_SIZE = 5000          # DB에서 한 번에 가져오는 행 수
POLL_INTERVAL_SEC = 1.0    # 할 일이 없을 때(또는 오류 후) jobs 테이블을 다시 보는 간격

log = logging.getLogger("worker")


def start_worker(stop_event: threading.Event) -> threading.Thread:
    thread = threading.Thread(target=_run_forever, args=(stop_event,), name="excel-worker", daemon=True)
    thread.start()
    return thread


def _run_forever(stop_event: threading.Event) -> None:
    log.info("excel worker started")
    while not stop_event.is_set():
        try:
            job_id = claim_next_job()
        except Exception:
            log.exception("failed to claim job")
            stop_event.wait(POLL_INTERVAL_SEC)
            continue

        if job_id is None:
            stop_event.wait(POLL_INTERVAL_SEC)  # 할 일 없음 → 잠깐 쉬기
            continue

        try:
            process_job(job_id)
        except Exception:
            # process_job 안에서 처리하지 못한 예외가 있어도 워커 스레드는 죽지 않고 다음 작업을 기다린다.
            log.exception("job %s: unexpected error", job_id)
            stop_event.wait(POLL_INTERVAL_SEC)
    log.info("excel worker stopped")


def claim_next_job() -> int | None:
    """
    가장 오래된 pending 작업 하나를 processing으로 바꾸고 그 id를 돌려준다.

    FOR UPDATE SKIP LOCKED: 다른 트랜잭션이 잠근 행은 건너뛴다.
    여러 워커가 "동시에 같은 pending 작업을 가져가는" 충돌을 막는 쿼리다.
    다만 시스템 전체는 단일 워커 전제라서, 워커를 늘리려면 서버 시작 시 정리 로직도 함께 바꿔야 한다.
    """
    with connect() as conn:
        row = conn.execute(
            """
            UPDATE jobs
               SET status = 'processing', started_at = now()
             WHERE id = (
                   SELECT id FROM jobs
                    WHERE status = 'pending'
                    ORDER BY id
                    LIMIT 1
                      FOR UPDATE SKIP LOCKED
             )
            RETURNING id
            """
        ).fetchone()
    return row["id"] if row else None


def process_job(job_id: int) -> None:
    final_path = os.path.join(EXPORT_DIR, f"orders_job_{job_id}.xlsx")
    temp_path = final_path + ".part"   # 다 쓰기 전까지는 임시 이름 → 반쯤 만들어진 파일이 노출되지 않음
    started = time.monotonic()
    log.info("job %s: start", job_id)

    try:
        # status_conn: 진행률을 바로바로 반영하는 연결 (autocommit)
        # data_conn  : 주문 데이터를 읽는 연결 (하나의 트랜잭션 안에서 끝까지 읽음)
        with connect(autocommit=True) as status_conn, connect() as data_conn:
            # REPEATABLE READ: count를 센 시점과 실제로 읽는 시점의 데이터가 같도록 스냅샷 고정
            data_conn.isolation_level = IsolationLevel.REPEATABLE_READ

            total = data_conn.execute("SELECT count(*) AS n FROM orders").fetchone()["n"]
            status_conn.execute("UPDATE jobs SET total_rows = %s WHERE id = %s", (total, job_id))

            def report_progress(done_rows: int) -> None:
                status_conn.execute("UPDATE jobs SET processed_rows = %s WHERE id = %s", (done_rows, job_id))

            # 이름 있는 커서(name=...) = 서버 사이드 커서.
            # 결과 10만 건을 DB 서버에 두고, fetchmany로 5,000건씩만 가져온다.
            with data_conn.cursor(name=f"export_job_{job_id}", row_factory=tuple_row) as cur:
                cur.execute(
                    """
                    SELECT id, user_name, product_name, category, amount, status, order_date
                      FROM orders
                     ORDER BY id
                    """
                )
                written = write_orders_xlsx(temp_path, _iter_chunks(cur), report_progress, tmpdir=TMP_DIR)

        os.replace(temp_path, final_path)  # 다 쓴 뒤에 한 번에 이름 변경
        _mark_done(job_id, final_path, written)
        log.info(
            "job %s: done rows=%s elapsed=%.1fs peak_mem=%s",
            job_id, written, time.monotonic() - started, _peak_memory_mb(),
        )

    except Exception as e:
        log.exception("job %s: failed", job_id)
        # 정리 단계에서 또 실패해도(예: DB가 계속 죽어 있음) 예외를 밖으로 던지지 않는다.
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            log.exception("job %s: could not remove temp file", job_id)
        try:
            _mark_failed(job_id, f"{type(e).__name__}: {e}")
        except Exception:
            # 실패 기록도 못 했으면 이 작업은 processing으로 남는다.
            # 복구 범위: 다음 서버 시작 시 recover_interrupted_jobs()가 failed로 정리한다. (실행 중 자동 복구는 하지 않음)
            log.exception("job %s: could not record failure; stays 'processing' until next restart", job_id)


def recover_interrupted_jobs() -> int:
    """
    서버가 켜질 때(워커 시작 전) 호출한다.
    processing 상태로 남은 작업 = 만드는 도중 서버가 꺼졌거나, 실패를 DB에 기록하지 못한 작업 → failed로 정리.
    단일 프로세스 전제: 다른 인스턴스가 함께 떠 있다면 그쪽이 처리 중인 작업까지 failed로 바꿔버린다.

    pending으로 되돌려 자동 재시도하지 않는 이유:
    그 작업 때문에 서버가 죽은 거라면(예: 메모리 부족) 재시작 → 재시도 → 또 죽음을 무한 반복할 수 있다.
    """
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE jobs
               SET status = 'failed', finished_at = now(),
                   error_message = '서버 재시작으로 작업이 중단되었습니다. 다시 요청해 주세요.'
             WHERE status = 'processing'
            """
        )
        count = cur.rowcount
    if count:
        log.warning("recovered %s interrupted job(s) as failed", count)
    return count


def cleanup_leftover_files() -> int:
    """
    서버가 켜질 때 호출한다. 작업 도중 서버가 죽으면 남는 찌꺼기 파일을 지운다.
    - TMP_DIR 안의 임시 파일 (행 데이터가 압축 전 상태로 20MB 넘게 쌓여 있음)
    - EXPORT_DIR 안의 *.part 파일 (압축하다 멈춘 결과 파일)
    워커가 아직 시작되기 전에만 호출하므로, 이 프로세스가 쓰고 있는 파일을 지울 일은 없다.
    (단일 프로세스 전제. 인스턴스가 여러 개라면 다른 인스턴스의 작업 파일을 지울 수 있다.)
    """
    os.makedirs(TMP_DIR, exist_ok=True)
    targets = [os.path.join(TMP_DIR, f) for f in os.listdir(TMP_DIR)]
    targets += [os.path.join(EXPORT_DIR, f) for f in os.listdir(EXPORT_DIR) if f.endswith(".part")]
    for path in targets:
        if os.path.isfile(path):
            os.remove(path)
    if targets:
        log.warning("removed %s leftover file(s)", len(targets))
    return len(targets)


def _iter_chunks(cur):
    while True:
        rows = cur.fetchmany(CHUNK_SIZE)
        if not rows:
            return
        yield rows


def _mark_done(job_id: int, file_path: str, rows: int) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE jobs
               SET status = 'done', finished_at = now(), file_path = %s, processed_rows = %s
             WHERE id = %s
            """,
            (file_path, rows, job_id),
        )


def _mark_failed(job_id: int, message: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'failed', finished_at = now(), error_message = %s WHERE id = %s",
            (message[:1000], job_id),
        )


def _peak_memory_mb() -> str:
    if resource is None:
        return "n/a"
    # 리눅스에서 ru_maxrss 단위는 KB
    return f"{resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f}MB"
