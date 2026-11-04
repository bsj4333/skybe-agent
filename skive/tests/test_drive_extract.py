from docx import Document
from openpyxl import Workbook
from openpyxl.comments import Comment
from pptx import Presentation
from pypdf import PdfWriter
from pypdf.annotations import Text
from zipfile import ZipFile

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


def test_pdf_comment_keeps_page_and_reports_unreadable_annotation(tmp_path):
    path = tmp_path / "review.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.add_annotation(page_number=0, annotation=Text(rect=(10, 10, 30, 30), text="압력 수치 재확인"))
    writer.add_annotation(page_number=0, annotation=Text(rect=(40, 40, 60, 60), text=""))
    with path.open("wb") as output:
        writer.write(output)

    coverage = {}
    chunks = load_drive_file(path, path.name, coverage)
    assert any(chunk.location.startswith("p.1 annotation") and chunk.text == "압력 수치 재확인"
               for chunk in chunks)
    assert coverage["supplemental"] == [{"kind": "pdf_annotations", "label": "PDF 주석",
        "detected": 2, "extracted": 1, "status": "partial"}]


def test_pptx_speaker_notes_are_separate_source_chunks(tmp_path):
    path = tmp_path / "lecture.pptx"
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.notes_slide.notes_text_frame.text = "BOM과 CAPA 차이를 설명"
    deck.slides.add_slide(deck.slide_layouts[6])
    deck.save(path)

    coverage = {}
    chunks = load_drive_file(path, path.name, coverage)
    assert [(chunk.location, chunk.text) for chunk in chunks] == [
        ("slide 1 speaker notes", "BOM과 CAPA 차이를 설명")]
    assert coverage["supplemental"] == [{"kind": "speaker_notes", "label": "PPT 발표자 노트",
        "detected": 1, "extracted": 1, "status": "complete"}]


def test_xlsx_cell_note_keeps_sheet_address_and_reports_coverage(tmp_path):
    path = tmp_path / "scm.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "SCM"
    sheet["B2"] = "CAPA"
    sheet["B2"].comment = Comment("이 수치는 다음 주에 확인", "팀원")
    book.save(path)

    coverage = {}
    chunks = load_drive_file(path, path.name, coverage)
    assert any(chunk.location == "sheet SCM cell note B2" and chunk.text == "이 수치는 다음 주에 확인"
               for chunk in chunks)
    assert coverage["supplemental"][0] == {"kind": "cell_notes", "label": "엑셀 셀 메모",
        "detected": 1, "extracted": 1, "status": "complete"}
    assert coverage["supplemental"][1]["status"] == "absent"


def test_xlsx_threaded_comment_is_read_from_its_sheet_relationship(tmp_path):
    path = tmp_path / "threaded.xlsx"
    book = Workbook()
    book.active["C3"] = "검토 대상"
    book.save(path)
    original = tmp_path / "base.xlsx"
    path.rename(original)
    with ZipFile(original) as source, ZipFile(path, "w") as target:
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))
        target.writestr("xl/worksheets/_rels/sheet1.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="comment1" Type="http://schemas.microsoft.com/office/2017/10/relationships/threadedComment" '
            'Target="/xl/threadedComments/threadedComment1.xml"/></Relationships>')
        target.writestr("xl/threadedComments/threadedComment1.xml",
            '<ThreadedComments xmlns="http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments">'
            '<threadedComment ref="C3"><text>측정 조건을 적어 주세요</text></threadedComment></ThreadedComments>')

    coverage = {}
    chunks = load_drive_file(path, path.name, coverage)
    assert any(chunk.location == "sheet Sheet threaded comment C3" and
               chunk.text == "측정 조건을 적어 주세요" for chunk in chunks)
    assert coverage["supplemental"][1] == {"kind": "threaded_comments", "label": "엑셀 대화형 댓글",
        "detected": 1, "extracted": 1, "status": "complete"}
