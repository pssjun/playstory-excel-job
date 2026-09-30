"""엑셀 쓰기 테스트 (DB 없이 가짜 데이터로 확인)"""
from datetime import datetime

import openpyxl

from excel import HEADERS, write_orders_xlsx


def make_chunks(total: int, size: int):
    """DB 대신 가짜 주문 데이터를 size건씩 묶어서 내준다."""
    for start in range(0, total, size):
        yield [
            (i, f"고객{i}", "오션월드 종일권", "워터파크", 55000, "confirmed", datetime(2026, 1, 1, 12, 0, 0))
            for i in range(start + 1, min(start + size, total) + 1)
        ]


def read_rows(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    wb.close()
    return rows


def test_모든_행과_헤더가_엑셀에_들어간다(tmp_path):
    path = tmp_path / "orders.xlsx"

    written = write_orders_xlsx(str(path), make_chunks(total=12_345, size=5000))

    rows = read_rows(path)
    assert written == 12_345
    assert list(rows[0]) == HEADERS                 # 첫 줄은 헤더
    assert len(rows) - 1 == 12_345                  # 헤더 제외 데이터 행 수
    assert rows[1][:6] == (1, "고객1", "오션월드 종일권", "워터파크", 55000, "confirmed")
    assert rows[1][6] == datetime(2026, 1, 1, 12, 0, 0)  # 날짜가 문자열이 아니라 날짜로 저장됨
    assert rows[-1][0] == 12_345                    # 마지막 행까지 순서대로


def test_묶음마다_진행률을_알려준다(tmp_path):
    progress = []

    write_orders_xlsx(str(tmp_path / "orders.xlsx"), make_chunks(total=12_345, size=5000), progress.append)

    # 5,000건씩 3묶음 → 누적 행 수가 3번 보고된다 (화면의 진행률 %가 이 값으로 계산됨)
    assert progress == [5000, 10000, 12_345]


def test_데이터가_없어도_헤더만_있는_파일이_만들어진다(tmp_path):
    path = tmp_path / "empty.xlsx"

    written = write_orders_xlsx(str(path), make_chunks(total=0, size=5000))

    assert written == 0
    assert read_rows(path) == [tuple(HEADERS)]
