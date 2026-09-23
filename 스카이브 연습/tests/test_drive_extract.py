from docx import Document
from openpyxl import Workbook

from skive.loaders import load_drive_file


def test_drive_extracts_jsonl_and_javascript_with_locations(tmp_path):
    for name, content in (("trace.jsonl", '{"event":"test"}\n'),
                          ("testcase.js", "const result = 42;\n")):
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        chunks = load_drive_file(path, name)
        assert [(chunk.location, chunk.text) for chunk in chunks] == [
            ("L1-1", content.strip())
        ]


def test_csv_profiles_all_rows_and_keeps_metric_source_row(tmp_path):
    path = tmp_path / "scores.csv"
    path.write_text("run,f1_score\na,0.2\nb,0.9\nc,0.4\n", encoding="utf-8")
    chunks = load_drive_file(path, path.name)
    text = "\n".join(chunk.text for chunk in chunks)
    assert "데이터 행 3개" in text
    assert "최대 0.9 (L3)" in text
    assert "f1_score L3" in text


def test_xlsx_extracts_cells_with_sheet_and_formula_locations(tmp_path):
    path = tmp_path / "sample.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "SCM"
    sheet["A1"] = "BOM"
    sheet["B1"] = 42
    sheet["C2"] = "=B1*2"
    book.save(path)

    chunks = load_drive_file(path, path.name)
    assert chunks
    assert "sheet SCM rows 1-2" in chunks[0].location
    assert "A1: BOM" in chunks[0].text
    assert "B1: 42" in chunks[0].text
    assert "C2: formula =B1*2 (cached value unavailable)" in chunks[0].text


def test_docx_extracts_paragraph_and_table_row_locations(tmp_path):
    path = tmp_path / "sample.docx"
    doc = Document()
    doc.add_paragraph("CAPA 수업 내용")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "계획"
    table.cell(0, 1).text = "실적"
    doc.save(path)

    chunks = load_drive_file(path, path.name)
    assert [(chunk.location, chunk.text) for chunk in chunks] == [
        ("paragraph 1", "CAPA 수업 내용"),
        ("table 1 row 1", "계획 | 실적"),
    ]
