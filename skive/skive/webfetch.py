"""공고 URL / 인재상 URL에서 텍스트만 뽑아온다. 검색이 아니라 사용자가 준 그 페이지 하나만 읽는다."""

import re

import httpx
from bs4 import BeautifulSoup

MAX_CHARS = 20_000
TIMEOUT = 15


def fetch_url_text(url: str) -> str:
    resp = httpx.get(
        url,
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; SkiveBot/1.0)"},
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
    if not text:
        raise ValueError("페이지에서 텍스트를 추출하지 못했습니다 (자바스크립트 렌더링 페이지일 수 있음)")
    return text[:MAX_CHARS]
