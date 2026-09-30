"""워커의 DB 없이 확인할 수 있는 부분 테스트"""
import threading

import psycopg

import worker


class FakeCursor:
    """fetchmany만 흉내 내는 가짜 DB 커서"""

    def __init__(self, total: int):
        self.rows = [(i,) for i in range(1, total + 1)]

    def fetchmany(self, size: int):
        batch, self.rows = self.rows[:size], self.rows[size:]
        return batch


def test_커서에서_CHUNK_SIZE씩_나눠서_가져온다():
    chunks = list(worker._iter_chunks(FakeCursor(total=12_345)))

    assert [len(c) for c in chunks] == [5000, 5000, 2345]
    assert chunks[0][0] == (1,) and chunks[-1][-1] == (12_345,)


def test_서버_재시작시_찌꺼기_파일만_지우고_완성된_파일은_남긴다(tmp_path, monkeypatch):
    export_dir = tmp_path / "exports"
    tmp_dir = export_dir / "tmp"
    tmp_dir.mkdir(parents=True)
    monkeypatch.setattr(worker, "EXPORT_DIR", str(export_dir))
    monkeypatch.setattr(worker, "TMP_DIR", str(tmp_dir))

    (export_dir / "orders_job_1.xlsx").write_text("완성된 파일")      # 남아야 함
    (export_dir / "orders_job_2.xlsx.part").write_text("압축하다 멈춤")  # 지워져야 함
    (tmp_dir / "tmpabc123").write_text("압축 전 임시 데이터")            # 지워져야 함

    removed = worker.cleanup_leftover_files()

    assert removed == 2
    assert sorted(p.name for p in export_dir.iterdir()) == ["orders_job_1.xlsx", "tmp"]
    assert list(tmp_dir.iterdir()) == []


def test_DB가_계속_죽어_있어도_process_job은_예외를_밖으로_던지지_않는다(tmp_path, monkeypatch):
    def broken_connect(**kwargs):
        raise psycopg.OperationalError("DB 연결 실패 (모의)")

    monkeypatch.setattr(worker, "EXPORT_DIR", str(tmp_path))
    monkeypatch.setattr(worker, "connect", broken_connect)

    # 엑셀 생성도 실패하고, 실패 기록(_mark_failed)도 실패하는 상황
    worker.process_job(1)  # 예외가 나면 이 테스트가 실패한다


def test_작업_처리_중_예상못한_예외가_나도_워커는_다음_작업을_계속_처리한다(monkeypatch):
    stop = threading.Event()
    queue = [1, 2]
    processed = []

    def fake_claim():
        if not queue:
            stop.set()  # 할 일을 다 하면 워커를 멈춘다
            return None
        return queue.pop(0)

    def exploding_process(job_id):
        processed.append(job_id)
        raise RuntimeError("예상 못한 오류 (모의)")

    monkeypatch.setattr(worker, "claim_next_job", fake_claim)
    monkeypatch.setattr(worker, "process_job", exploding_process)
    monkeypatch.setattr(worker, "POLL_INTERVAL_SEC", 0.01)

    worker._run_forever(stop)  # 1번 작업에서 예외가 나도 루프가 끝나지 않고 2번까지 처리해야 한다

    assert processed == [1, 2]
