# SKIVE 프로젝트 현황 (2026-09-22 기준)

새 컴퓨터에서 Claude Code를 열었다면, 이 파일을 먼저 읽고 이어서 진행하면 됩니다.
(대화 세션과 Claude 쪽 메모리는 컴퓨터마다 로컬이라 안 따라오지만, 이 파일은 git으로 어디서든 똑같이 보입니다.)

## 한 줄 요약
대학생 개인용 커리어 에이전트 "SKIVE". 폴더(경험 자료)를 넣으면 → 근거 인용 기반으로 경험을 구조화하고 → 프로필로 종합하고 → 공고와 매칭해 자소서 초안까지 만들어주는 로컬 우선 웹앱. 2026년 12월 데모 목표.

## 지금 상태
- **동작하는 CLI 프로토타입**: `skive/` 패키지, `uv run python -m skive.cli {ingest-all|list|profile|apply|chat|ask|report}`
- **샘플 데이터 6건 이미 ingest 완료** (`data/store/`), 프로필도 생성됨 (`data/profile/`)
- **UI 목업**: https://claude.ai/artifact/GHkYW4om7KiLF64KyR56cE (v3) — 드라이브형 홈, 프로필(개인정보 통합), 공고 폴더 리스트, 스코프 지정 챗봇, 정정 확인 카드, 복습 플래시카드. 클릭 가능한 HTML 시안, 실제 코드와는 아직 연결 안 됨.
- **아직 진짜 웹앱 아님** — FastAPI 서버 등 백엔드 뼈대가 없어서 위 목업은 정적 시안일 뿐.

## 아키텍처 (파일 위치)
| 역할 | 파일 |
|---|---|
| 스키마 (Pydantic) | `skive/models.py` |
| 폴더→청크 로딩 | `skive/loaders.py` |
| 근거 인용 검증 | `skive/verify.py` |
| 경험 추출 (폴더→experience.md) | `skive/analyzer.py` |
| 중요도 채점 | `skive/importance.py` |
| 프로필 종합 (전체 재계산 방식) | `skive/profile.py` |
| 공고 파싱 | `skive/job.py` |
| 공고↔경험 매칭 에이전트 | `skive/agent.py` |
| 자소서 작성 (gate→write→judge→repair) | `skive/writer.py`, `skive/apply.py` |
| 저장소 (플랫파일) | `skive/store.py` |
| 챗봇 그래프 | `skive/chat.py` |
| 공부 세션 요약 | `skive/study.py` |
| **기억 회상 (키워드 TF-IDF, 약함)** | `skive/recall.py` |
| HTML 리포트 | `skive/report_html.py` |

## 실측으로 확인한 버그 (2026-09-22 테스트, 추측 아님)
사용자가 만든 8개 유형 테스트셋 중 10여개를 실제 코드로 돌려서 확인:
1. ✅ 단순 회상, 경험 통합, 드릴다운, 오염/거짓전제 방어, 공부기록 회상 — 다 잘 됨 (예상보다 좋음)
2. ❌ **패러프레이즈 실패** — "오류 잡는 성능 좋아진 사례?"처럼 정확한 단어(F1-score, 퍼센타일)를 안 쓰면 `recall.py`의 키워드 매칭이 실제로 있는 기록도 못 찾고 "기록에 없다"고 답함
3. ❌❌ **정정이 씹힘 (제일 심각)** — 같은 대화 세션 안에서 사용자가 "FastAPI는 내가 안 만들었어"라고 정정해도, 바로 다음 턴에 `recall()`이 원본 저장값을 다시 끌어와 정정 이전 사실을 그대로 재출력함. 세션 간이 아니라 **한 대화 안에서도** 깨짐.
4. ⚠️ 자소서 문항 1·2가 같은 3D프린터 에피소드를 겹쳐 인용 (소재 다양화 로직 없음)

## 다음에 할 일 (우선순위순, 최신 논의 기준)
1. **FastAPI 백엔드 뼈대** — 지금 CLI 함수들을 HTTP로 노출, 목업 JS를 실제 fetch로 교체
2. **정정(correction) 파이프라인 신설** (`skive/corrections.py` 없음, 새로 만들어야 함) — 버그 #3 해결
3. **챗봇 스코프 필터를 `recall()`에 연결** — 버그 #2 완화 (임베딩 검색 전에 할 수 있는 빠른 개선)
4. **공고를 1회성 파일 처리 → 저장되는 레코드로 리팩터링** (`data/jobs/<id>/...`) — 목업의 "공고 폴더 리스트" 화면을 실제로 만들려면 필요
5. **`data/user.json`에 학교/학과/학년 필드 추가** — 목업 프로필 탭의 "기본 정보" 연결용
6. (이후) 임베딩 기반 recall, 세션 working-context, profile.py 증분 업데이트 — Generative Agents / MemGPT 논문 기반 설계는 이미 논의됨, 필요하면 이전 대화 요약 참고

## 참고
- 경쟁 서비스 조사함: 다글로/Lilys AI/UnivAI/ThetaWave — 전부 단일 문서 요약 도구, 크로스 경험 프로필·공고매칭 기능 없음 (SKIVE 차별점)
- `.env`에 OpenAI 키 있음 (프로젝트 루트, git에는 안 올라감 — `.gitignore` 확인됨)
