from langchain_core.messages import HumanMessage, SystemMessage

from skive.llm import get_llm
from skive.models import JobRequirements

SYSTEM_PROMPT = """채용공고 텍스트에서 구조화된 정보를 추출한다. 공고에 적힌 내용만 쓰고 추측하지 않는다.
- values: 공고에 인재상으로 명시된 항목만. 명시가 없으면 빈 리스트.
- key_competencies: 주요 업무와 자격요건에서 도출되는 이 직무의 핵심 역량 3~5개.
- essay_questions: 공고에 적힌 자기소개서 문항을 글자 수 표기까지 원문 그대로. 없으면 빈 리스트.
- 회사명이 없으면 '미기재'로 쓴다."""


def parse_job(text: str) -> JobRequirements:
    llm = get_llm().with_structured_output(JobRequirements)
    return llm.invoke([SystemMessage(SYSTEM_PROMPT), HumanMessage(text)])
