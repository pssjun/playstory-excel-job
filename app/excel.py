from typing import Callable, Iterable, Sequence

import xlsxwriter

HEADERS = ["주문번호", "주문자", "상품명", "카테고리", "결제금액(원)", "주문상태", "주문일시"]
COLUMN_WIDTHS = [10, 12, 28, 12, 14, 12, 20]


def write_orders_xlsx(
    path: str,
    chunks: Iterable[Sequence[tuple]],
    on_progress: Callable[[int], None] = lambda n: None,
    tmpdir: str | None = None,
) -> int:
    """
    주문 데이터를 엑셀 파일로 쓴다.

    - chunks: 행 묶음(예: 5,000행씩)을 차례로 내주는 iterable. 10만 건을 한 번에 받지 않는다.
    - constant_memory 모드: 한 행을 다 쓰면 바로 디스크로 내보내서 메모리에 쌓이지 않는다.
      (대신 이미 쓴 행으로 되돌아가 수정할 수 없다 → 위에서 아래로 한 번만 쓰는 우리 용도에 딱 맞음)
    - tmpdir: constant_memory 모드는 행 데이터를 임시 파일에 먼저 쓰고, close() 때 압축해서 .xlsx로 만든다.
      그 임시 파일을 둘 폴더. (서버가 중간에 죽으면 남으므로, 시작 시 청소할 수 있게 위치를 고정)
    - 반환값: 쓴 데이터 행 수
    """
    options = {
        "constant_memory": True,
        "default_date_format": "yyyy-mm-dd hh:mm:ss",
    }
    if tmpdir:
        options["tmpdir"] = tmpdir
    workbook = xlsxwriter.Workbook(path, options)
    try:
        sheet = workbook.add_worksheet("주문내역")
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#DDEBF7", "border": 1})
        amount_fmt = workbook.add_format({"num_format": "#,##0"})

        for col, width in enumerate(COLUMN_WIDTHS):
            sheet.set_column(col, col, width, amount_fmt if col == 4 else None)
        sheet.write_row(0, 0, HEADERS, header_fmt)
        sheet.freeze_panes(1, 0)  # 스크롤해도 헤더가 보이게

        row_idx = 1
        for chunk in chunks:
            for row in chunk:
                sheet.write_row(row_idx, 0, row)
                row_idx += 1
            on_progress(row_idx - 1)

        return row_idx - 1
    finally:
        workbook.close()
