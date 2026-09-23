import csv
import json
import math
from collections import deque
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pypdf import PdfReader

TEXT_EXT = {".md", ".txt", ".py", ".json", ".yaml", ".yml"}
DRIVE_TEXT_EXT = TEXT_EXT | {".jsonl", ".js", ".html", ".ps1"}
CSV_PROFILE_COLUMNS = 500
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}
MAX_FILE_BYTES = 2_000_000
LINES_PER_CHUNK = 80
CSV_PREVIEW_ROWS = 20  # 헤더 + 데이터 20행만. 표 전체가 아니라 "이런 표가 있었다"만 알면 된다
CSV_PREVIEW_CHARS = 2000  # 행 수를 제한해도 열이 아주 많은 표(센서 수백 개 등)는 여전히
# 거대할 수 있다 — 실측: 한 파일이 20행만으로도 216,039자였다. 글자 수로 한 번 더 자른다.


@dataclass(frozen=True)
class Chunk:
    source: str
    location: str
    text: str


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp949", errors="replace")


def _text_chunks(source: str, text: str) -> list[Chunk]:
    lines = text.splitlines()
    chunks = []
    for start in range(0, len(lines), LINES_PER_CHUNK):
        part = lines[start : start + LINES_PER_CHUNK]
        chunks.append(Chunk(source, f"L{start + 1}-{start + len(part)}", "\n".join(part)))
    return chunks


def _csv_chunks(source: str, text: str) -> list[Chunk]:
    """CSV는 표 전체를 넣지 않고 헤더+미리보기만 넣는다.

    실측(2026-09-23): 실사용자 폴더에 ML 파이프라인 중간 산출물 CSV가 68개, 합쳐서
    7.4MB(=analyze_folder의 200,000자 상한을 40배 넘김) 있었다. 이런 CSV는 수만 행짜리
    숫자 나열이라 LLM이 "무엇을 했는지" 읽어내는 데 거의 도움이 안 되면서 자리만
    크게 차지한다 — 다른 파일(md, 코드, 보고서)에 있는 진짜 서술형 근거를 밀어낸다.
    작은 결과표(성과 근거가 될 수 있는 것)는 미리보기로 대부분 통째로 남는다.

    행 수만 제한하면 안 된다 — 실측: 센서 컬럼이 수백 개인 표는 **20행만으로도
    216,039자**였다. 글자 수로도 한 번 더 자른다."""
    lines = text.splitlines()
    if not lines:
        return []
    total_rows = len(lines) - 1  # 헤더 제외
    row_preview = lines[: CSV_PREVIEW_ROWS + 1]
    row_truncated = len(lines) > len(row_preview)
    body = "\n".join(row_preview)
    char_truncated = len(body) > CSV_PREVIEW_CHARS
    if char_truncated:
        body = body[:CSV_PREVIEW_CHARS]
    if row_truncated or char_truncated:
        reason = "행이 많아서" if row_truncated and not char_truncated else \
                  "각 행이 길어서" if char_truncated and not row_truncated else "행이 많고 길어서"
        body += f"\n[표 미리보기 — 전체 {total_rows}행 중 일부만 표시, {reason} 나머지 생략]"
    return [Chunk(source, f"미리보기(전체 {total_rows}행)", body)]


def _csv_profile(source: str, path: Path) -> list[Chunk]:
    """Scan every CSV row while keeping only bounded provenance-aware statistics.

    Raw time-series rows remain in Storage. A few sample and metric-winning rows
    make the index useful without copying a whole dataset into Postgres.
    """
    with path.open("rb") as stream:
        probe = stream.read(65536)
    encoding = "utf-8-sig"
    try:
        probe.decode(encoding)
    except UnicodeDecodeError:
        encoding = "cp949"
    with path.open("r", encoding=encoding, errors="replace", newline="") as stream:
        reader = csv.reader(stream)
        try:
            header = next(reader)
        except StopIteration:
            return []
        width = len(header)
        tracked = min(width, CSV_PROFILE_COLUMNS)
        counts = [0] * tracked
        missing = [0] * tracked
        means = [0.0] * tracked
        minimum = [math.inf] * tracked
        maximum = [-math.inf] * tracked
        min_row = [0] * tracked
        max_row = [0] * tracked
        numeric = [True] * tracked
        first_rows = []
        last_rows = deque(maxlen=3)
        best_rows = {}
        row_count = ragged = 0
        metric_columns = [i for i, name in enumerate(header[:tracked])
                          if any(word in name.lower() for word in
                                 ("f1", "auc", "accuracy", "precision", "recall", "score", "false_alarm"))][:12]
        for line_number, row in enumerate(reader, 2):
            row_count += 1
            if len(row) != width:
                ragged += 1
            sample = (line_number, [value[:200] for value in row[:40]])
            if len(first_rows) < 3:
                first_rows.append(sample)
            last_rows.append(sample)
            for i in range(tracked):
                value = row[i].strip() if i < len(row) else ""
                if not value:
                    missing[i] += 1
                    continue
                try:
                    number = float(value.replace(",", ""))
                    if not math.isfinite(number):
                        raise ValueError("non-finite")
                except ValueError:
                    numeric[i] = False
                    continue
                counts[i] += 1
                means[i] += (number - means[i]) / counts[i]
                if number < minimum[i]:
                    minimum[i], min_row[i] = number, line_number
                if number > maximum[i]:
                    maximum[i], max_row[i] = number, line_number
                    if i in metric_columns:
                        best_rows[i] = sample
    lines = [f"# CSV 전체 스캔: {source}", f"데이터 행 {row_count}개, 열 {width}개, 열 개수 불일치 행 {ragged}개.",
             "아래 수치는 원본 전체 행을 계산한 값입니다. 원본 행 전체는 Storage 파일에 있습니다.",
             "열 이름: " + json.dumps(header, ensure_ascii=False)]
    if tracked < width:
        lines.append(f"통계는 앞의 {tracked}개 열만 계산했습니다. 나머지 {width-tracked}개 열은 원본에서 확인해야 합니다.")
    for i, name in enumerate(header[:tracked]):
        label = f"{i+1}. {name or '(이름 없음)'}"
        if numeric[i] and counts[i]:
            lines.append(f"{label}: 숫자 {counts[i]}개, 결측 {missing[i]}개, "
                         f"최소 {minimum[i]:.8g} (L{min_row[i]}), 최대 {maximum[i]:.8g} "
                         f"(L{max_row[i]}), 평균 {means[i]:.8g}")
        else:
            lines.append(f"{label}: 숫자 통계 부적합, 결측 {missing[i]}개")
    for label, samples in (("첫 3행", first_rows), ("마지막 3행", list(last_rows))):
        lines.append(label + ":")
        lines.extend(f"L{number}: {json.dumps(row, ensure_ascii=False)}" for number, row in samples)
    if best_rows:
        lines.append("지표 열별 최대값을 기록한 행 (앞의 40개 열):")
        for i, (number, row) in best_rows.items():
            lines.append(f"{header[i]} L{number}: {json.dumps(row, ensure_ascii=False)}")
    return [Chunk(source, f"CSV L1-L{row_count+1} 전체 스캔", "\n".join(lines))]


def _pdf_chunks(source: str, path: Path) -> list[Chunk]:
    reader = PdfReader(path)
    return [
        Chunk(source, f"p.{i}", (page.extract_text() or "").strip())
        for i, page in enumerate(reader.pages, start=1)
    ]


def _pptx_chunks(source: str, path: Path) -> list[Chunk]:
    chunks = []
    for i, slide in enumerate(Presentation(path).slides, start=1):
        texts = [
            shape.text_frame.text
            for shape in slide.shapes
            if shape.has_text_frame and shape.text_frame.text.strip()
        ]
        chunks.append(Chunk(source, f"slide {i}", "\n".join(texts)))
    return chunks


def _xlsx_chunks(source: str, path: Path):
    """Read cached values and formulas with sheet/row/column provenance."""
    values_book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    formulas_book = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    try:
        for sheet_name in values_book.sheetnames:
            values_sheet = values_book[sheet_name]
            formulas_sheet = formulas_book[sheet_name]
            lines: list[str] = []
            first_row = last_row = 0
            char_count = 0
            for row_number, (value_row, formula_row) in enumerate(zip_longest(
                values_sheet.iter_rows(values_only=True),
                formulas_sheet.iter_rows(values_only=True), fillvalue=(),
            ), 1):
                cells = []
                for col_number, (value, formula) in enumerate(zip_longest(value_row, formula_row), 1):
                    if value is None and formula is None:
                        continue
                    address = f"{get_column_letter(col_number)}{row_number}"
                    if isinstance(formula, str) and formula.startswith("="):
                        rendered = f"{value} (formula {formula})" if value is not None else f"formula {formula} (cached value unavailable)"
                    else:
                        rendered = str(value if value is not None else formula)
                    cells.append(f"{address}: {rendered}")
                if not cells:
                    continue
                line = " | ".join(cells)
                if lines and (len(lines) >= 50 or char_count + len(line) > 7500):
                    yield Chunk(source, f"sheet {sheet_name} rows {first_row}-{last_row}", "\n".join(lines))
                    lines = []
                    char_count = 0
                if not lines:
                    first_row = row_number
                lines.append(line)
                last_row = row_number
                char_count += len(line)
            if lines:
                yield Chunk(source, f"sheet {sheet_name} rows {first_row}-{last_row}", "\n".join(lines))
    finally:
        values_book.close()
        formulas_book.close()


def _docx_chunks(source: str, path: Path):
    """Keep paragraphs and table rows separately addressable."""
    document = Document(path)
    paragraph_number = table_number = 0
    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            paragraph_number += 1
            if block.text.strip():
                yield Chunk(source, f"paragraph {paragraph_number}", block.text.strip())
        elif isinstance(block, Table):
            table_number += 1
            for row_number, row in enumerate(block.rows, 1):
                text = " | ".join(cell.text.strip() for cell in row.cells)
                if text.strip(" |"):
                    yield Chunk(source, f"table {table_number} row {row_number}", text)


def load_folder(root: Path) -> list[Chunk]:
    """업로드 루트를 있는 그대로 읽는다 — 껍데기 폴더를 자동으로 접지 않는다.

    한때 "감싸는 폴더 한 겹(예: 본인 이름 폴더)을 접어서 보여준다"는 걸 시도했는데,
    사용자 피드백(2026-09-23): "홈은 그냥 드라이브다. 폴더 올리는 대로 그냥 올려야지,
    왜 임의로 구조를 바꾸냐." 드라이브는 사용자가 정리한 구조를 있는 그대로 보여주는
    곳이지 AI가 "정리해주는" 곳이 아니다 — 되돌린다."""
    chunks: list[Chunk] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        source = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        if suffix == ".csv":
            chunks += _csv_chunks(source, _read_text(path))
        elif suffix in TEXT_EXT:
            chunks += _text_chunks(source, _read_text(path))
        elif suffix == ".pdf":
            chunks += _pdf_chunks(source, path)
        elif suffix == ".pptx":
            chunks += _pptx_chunks(source, path)
    return [c for c in chunks if c.text.strip()]


def load_drive_file(path: Path, source: str) -> list[Chunk]:
    """Extract one stored original without the legacy folder loader's 2 MB skip.

    The worker applies its own explicit byte/chunk limits and reports unsupported
    files. This does not change the old single-user ingestion path.
    """
    suffix = Path(source).suffix.lower()
    if suffix == ".csv":
        chunks = _csv_profile(source, path)
    elif suffix in DRIVE_TEXT_EXT:
        chunks = _text_chunks(source, _read_text(path))
    elif suffix == ".pdf":
        chunks = _pdf_chunks(source, path)
    elif suffix == ".pptx":
        chunks = _pptx_chunks(source, path)
    elif suffix == ".xlsx":
        chunks = _xlsx_chunks(source, path)
    elif suffix == ".docx":
        chunks = _docx_chunks(source, path)
    else:
        return []
    bounded: list[Chunk] = []
    for chunk in chunks:
        if not chunk.text.strip():
            continue
        for start in range(0, len(chunk.text), 8000):
            part = chunk.text[start:start + 8000]
            location = chunk.location if len(chunk.text) <= 8000 else f"{chunk.location} chars {start + 1}-{start + len(part)}"
            bounded.append(Chunk(source, location, part))
            if len(bounded) > 10_000:
                raise ValueError("File produces more than 10,000 text chunks")
    return bounded
