from typing import Literal

from pydantic import BaseModel, Field

UNKNOWN = "확인 필요"


class Evidence(BaseModel):
    chunk_id: str = Field(description="근거가 나온 원문 조각의 ID. 입력의 [C숫자] 표기에서 C숫자만 사용 (예: C3)")
    quote: str = Field(description="원문에서 글자 그대로 복사한 60자 이내 구절. 요약·의역 금지")


class Fact(BaseModel):
    text: str = Field(description="한 문장으로 쓴 사실")
    owner: Literal["본인", "팀"] = Field(
        description="지정된 본인이 직접 한 일로 원문에서 확인되면 '본인'. 팀 전체가 한 일이거나 누가 했는지 불명확하면 '팀'"
    )
    evidence: list[Evidence] = Field(description="이 사실을 뒷받침하는 원문 근거 1개 이상")


class Experience(BaseModel):
    title: str
    summary: str = Field(description="한 줄 요약")
    kind: Literal["project", "course", "activity", "award", "other"] = Field(
        description="project=결과물을 만든 프로젝트, course=수업 노트·과제·학습 기록, activity=동아리·캠프·대외활동, award=수상, other=그 외"
    )
    period: str = Field(description="기간. 원문에 없으면 '확인 필요'")
    organization: str = Field(description="소속·유형. 원문에 없으면 '확인 필요'")
    problem: str = Field(description="해결하려던 문제 또는 학습 목표")
    my_role: str = Field(description="지정된 본인이 실제 담당한 일. 이름이 명시된 근거가 없으면 '확인 필요'")
    my_role_evidence: list[Evidence] = Field(description="my_role의 근거. my_role이 '확인 필요'면 빈 리스트")
    actions: list[Fact] = Field(description="수행한 행동")
    decisions_and_trials: list[Fact] = Field(description="기술적 의사결정과 시행착오")
    results: list[Fact] = Field(description="정량 성과. 수치는 원문 그대로")
    skills: list[str]
    lessons: str = Field(description="원문에 명시된 배운 점. 없으면 '확인 필요'")
    open_questions: list[str] = Field(description="원문만으로 확정할 수 없어 사용자에게 물어봐야 할 구체적 질문")


class ImportanceLLM(BaseModel):
    impact: int = Field(description="성과의 크기 0~3")
    uniqueness: int = Field(description="문제 정의·접근·시행착오의 독자성 0~3")
    goal_relevance: int = Field(description="진로 목표와의 관련성 0~3")
    reason: str = Field(description="점수 근거를 한두 문장으로")


class Competency(BaseModel):
    name: str
    description: str = Field(description="이 역량을 뒷받침하는 사실을 한두 문장으로. 과장 금지")
    experience_ids: list[str] = Field(description="근거가 되는 경험 id 1개 이상")


class Trait(BaseModel):
    trait: str
    rationale: str
    experience_ids: list[str] = Field(description="서로 다른 경험 id 2개 이상")


class Profile(BaseModel):
    headline: str = Field(description="지원자를 한 문장으로 요약. 입력 경험에서 확인된 내용만")
    competencies: list[Competency]
    traits: list[Trait]
    gaps: list[str] = Field(description="진로 목표에 비해 근거가 부족한 부분")


class JobRequirements(BaseModel):
    company: str
    role: str
    responsibilities: list[str]
    required_skills: list[str]
    preferred_skills: list[str]
    values: list[str] = Field(description="공고에 명시된 인재상. 명시가 없으면 빈 리스트")
    key_competencies: list[str] = Field(description="이 직무에서 핵심이라고 공고 내용으로 판단되는 역량 3~5개")
    essay_questions: list[str] = Field(description="공고에 명시된 자기소개서 문항. 없으면 빈 리스트")


class CompetencyLink(BaseModel):
    competency: str
    experience_ids: list[str]
    strength: Literal["강함", "보통", "약함", "없음"]
    note: str = Field(description="연결 이유 한 문장. 없으면 '해당 경험 없음'")


class QuestionPlan(BaseModel):
    question: str = Field(description="공고의 자기소개서 문항 원문")
    experience_ids: list[str] = Field(description="이 문항에 쓸 경험 id 1~2개. 맞는 경험이 없으면 빈 리스트")
    angle: str = Field(description="이 경험을 어떤 관점으로 풀어쓸지 한 문장")
    gap: str = Field(description="부족하거나 확인이 필요한 점. 없으면 빈 문자열")


class Plan(BaseModel):
    """탐색을 모두 마친 뒤 최종 매칭 계획을 제출한다. 마지막에 한 번만 호출한다."""

    competency_links: list[CompetencyLink]
    question_plans: list[QuestionPlan]
    questions_for_user: list[str] = Field(description="사용자에게 확인받아야 할 질문 (예: 역할이 미확인인 경험)")


class StudyItem(BaseModel):
    text: str = Field(description="한 문장으로 쓴 내용")
    quote: str = Field(description="대화에서 글자 그대로 복사한 60자 이내 구절. 요약·의역 금지")


class StudySummary(BaseModel):
    topic: str = Field(description="이번 공부의 주제")
    keywords: list[str]
    learned: list[StudyItem] = Field(description="대화에서 다뤄졌고 사용자가 이해했다고 표현했거나 정리된 핵심 개념")
    confusions: list[StudyItem] = Field(description="사용자가 이해하지 못했다·헷갈린다고 표현했거나 반복해서 질문한 것")
    review_questions: list[str] = Field(description="복습이나 면접 대비용 질문 3개 이내")
    related_experience_ids: list[str] = Field(description="주어진 경험 목록 중 이 공부와 직접 관련된 경험 id. 없으면 빈 리스트")


class Answerability(BaseModel):
    level: Literal["가능", "부분", "불가"]
    missing: str = Field(description="문항이 요구하지만 근거 자료에 없는 내용. 없으면 빈 문자열")


class SentenceCheck(BaseModel):
    sentence: str
    verdict: Literal["supported", "unsupported", "misattributed"]
    reason: str


class JudgeResult(BaseModel):
    checks: list[SentenceCheck]
