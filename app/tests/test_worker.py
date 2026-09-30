"""워커의 DB 없이 확인할 수 있는 부분 테스트"""
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
