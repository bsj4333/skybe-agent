"""Decides how much attention a file deserves before any model tokens are spent.

Extraction costs CPU only; sending text to a model costs tokens. Students' folders hold far
more generated output than writing, so documents are read fully and everything else only
when it looks like a result or when a project has no documents at all.
"""

import re
from pathlib import Path

DOCUMENT = 1  # Written by a person to explain the work. Read to the end.
RESULT = 2  # Structured results worth a look.
BULK = 3  # Code, logs and raw data. Looked at only when nothing better exists.

DOCUMENT_EXT = {".pdf", ".docx", ".pptx", ".md", ".txt", ".rtf", ".hwp", ".hwpx"}
RESULT_EXT = {".xlsx", ".ipynb"}
RESULT_NAME = re.compile(r"readme|report|summary|result|결과|보고|요약|발표|최종", re.IGNORECASE)
NOISE_NAME = re.compile(r"^(package-lock\.json|yarn\.lock|poetry\.lock|uv\.lock|pnpm-lock\.yaml)$", re.IGNORECASE)
DOCUMENT_PRIORITY_SQL = r"lower(f.name) ~ '\.(pdf|docx|pptx|md|txt|rtf|hwp|hwpx)$'"


def file_tier(name: str) -> int:
    suffix = Path(name).suffix.lower()
    if suffix in DOCUMENT_EXT:
        return DOCUMENT
    if suffix in RESULT_EXT or RESULT_NAME.search(name):
        return RESULT
    return BULK


def worth_reading(name: str) -> bool:
    return not NOISE_NAME.match(name)
