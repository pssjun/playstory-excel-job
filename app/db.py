import os
import time

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/playstory")


def connect(**kwargs) -> psycopg.Connection:
    """DB 연결을 하나 연다. `with connect() as conn:` 블록이 끝나면 commit 후 자동으로 닫힌다."""
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, **kwargs)


def wait_for_db(timeout_sec: int = 60) -> None:
    """앱이 DB보다 먼저 떠도 죽지 않도록, 연결될 때까지 잠깐씩 재시도한다."""
    deadline = time.time() + timeout_sec
    while True:
        try:
            with connect():
                return
        except psycopg.OperationalError:
            if time.time() > deadline:
                raise
            time.sleep(1)
