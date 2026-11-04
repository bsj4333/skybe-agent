"""Deterministic, versioned inventory of text extracted from one Drive file.

This records raw excerpts and number mentions with locations. It does not infer
who performed an action, whether a number is an outcome, or whether the source
supports a career claim.
"""

import re
from collections import deque

PARSER_VERSION = "read-card-v1"
SAMPLE_HEAD = 20
SAMPLE_TAIL = 20
MAX_CONTEXT = 280
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?(?:\s?(?:%|점|건|개|명|초|분|시간|GB|MB|kW|MW|℃|°C))?")
LINE_RANGE = re.compile(r"^L(\d+)(?:-\d+)?$")
EXPLICIT_LINE = re.compile(r"\bL(\d+)\b")
CELL = re.compile(r"\b([A-Z]{1,3}\d{1,7}):")


class _Samples:
    def __init__(self):
        self.count = 0
        self.head: list[dict] = []
        self.tail: deque[dict] = deque(maxlen=SAMPLE_TAIL)

    def add(self, item: dict):
        self.count += 1
        if len(self.head) < SAMPLE_HEAD:
            self.head.append(item)
        else:
            self.tail.append(item)

    def result(self) -> list[dict]:
        return self.head + list(self.tail)


def _location(base: str, line: str, offset: int) -> str:
    explicit = EXPLICIT_LINE.search(line)
    if explicit:
        return f"{base} · L{explicit.group(1)}"
    cell = CELL.search(line)
    if cell and base.startswith("sheet "):
        return f"{base} · {cell.group(1)}"
    line_range = LINE_RANGE.fullmatch(base)
    if line_range:
        return f"L{int(line_range.group(1)) + offset}"
    return base


def build_read_card(chunks, coverage: dict | None = None) -> dict:
    quotes, numbers = _Samples(), _Samples()
    chunk_count = 0
    for chunk_count, chunk in enumerate(chunks, start=1):
        text = chunk.text if hasattr(chunk, "text") else chunk["text"]
        base = chunk.location if hasattr(chunk, "location") else chunk["location"]
        index = chunk_count
        if not text.strip():
            continue
        for offset, line in enumerate(text.splitlines()):
            if not line.strip():
                continue
            location = _location(base, line, offset)
            quotes.add({"chunk_index": index, "location": location,
                        "quote": line.strip()[:MAX_CONTEXT]})
            for match in NUMBER.finditer(line):
                start = max(0, match.start() - 100)
                end = min(len(line), match.end() + 140)
                numbers.add({"chunk_index": index, "location": location,
                             "value": match.group().strip(), "quote": line[start:end][:MAX_CONTEXT]})
    return {"parser_version": PARSER_VERSION, "status": "ready", "chunk_count": chunk_count,
            "quote_count": quotes.count, "number_count": numbers.count,
            "quote_samples": quotes.result(), "number_samples": numbers.result(),
            "coverage": coverage or {}, "error": None}
