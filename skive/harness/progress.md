# SKIVE 진행 상태

**현재 상태의 유일한 기준.** 세션을 시작할 때 읽고, 끝낼 때 갱신한다. 규칙은 `AGENTS.md` §2.

## Current snapshot (2026-11-04)

- Active app: standalone `skive/` project. Practice examples are archived locally outside the published tree.
- Configuration: app-local `.env`; explicit deployment environment wins. Parent-folder credentials are never loaded.
- Supabase: 새 프로젝트에 마이그레이션 `0001`~`0016` 적용 완료(2026-11-04, 사람 승인). 테이블 33개, 비공개 버킷 `skive-originals`, Storage 정책 2개. 사용자·파일 0건(이전 프로젝트 자료는 이전되지 않음). 이전 프로젝트는 DNS 기록이 없어 접속 불가.
- OpenAI: `.env`의 키는 인증되지만(모델 목록 200) 1토큰 호출이 `429 credit_balance_exhausted`(2026-11-04). 이 키는 이전 키와 같고, 최신 키 파일에는 OpenAI 키가 없고 Claude 키만 있다. 앱은 아직 OpenAI 어댑터만 쓴다 → 모델 기능은 F-105 전까지 멈춤.
- Publication: user explicitly authorized app-only GitHub publication. Credentials, backups, runtime data, and exercises are excluded.
- Checks: the local app and a source-only publication snapshot both pass 88 tests (4 skipped: 3 optional live-DB checks and 1 existing skip). Standalone dependency lock, source compilation, Markdown links, and HTTP startup/assets are verified under F-108.

## Historical snapshot (2026-09-30; applies to the previous Supabase project)

- 브랜치 `skive-agent`. 2026-09-30에 개인 자료를 뺀 이력으로 GitHub에 push함 (아래 로그). 9/28 커밋은 새 해시 `e0ea084`
- 현재 단계: **phase-00 기준선 고정** → 다음은 phase-01 실자료 시뮬레이션
- 결정론적 테스트 기준선: **85 passed, 1 skipped**
- Supabase: 마이그레이션 `0001`~`0016` 적용됨. **`0016` 파일은 아직 커밋 안 됨** (F-100)
- OpenAI: **선불 크레딧 잔액 0** (`credit_balance_exhausted`, 2026-09-29 확인). 모델을 부르는 기능은 전부 멈춤 → F-105
- GitHub: 공개 저장소. 실사용자 자료(`data/user.json` 실제 값, `data/store/2. 화력발전소 이상탐지/`, `data/outputs/apply_job_1790126169799.json`)는 이 PC에만 있고 `.gitignore`·skip-worktree로 추적 제외 (F-101 완료)
- 모델 배치 설계: [build/design-model-routing.md](build/design-model-routing.md) (사람 승인 대기). luna 기본 + sol 중요 작업, astra 금지, 사용자 비용 상한 없음
- Supabase 사람 계정 (2026-09-30 읽기 전용 조회): 파일 4,325개. 9/29 업로드 "Local Experience Archive 2026-09-29" 3,246개(하위 폴더 3개)는 **추출 대기열에 안 들어감**(B-001), 50MiB 초과 53개는 조각 저장이라 앱에서 빈 파일(B-002). Storage 실제 사용 약 47GB
- 구현 현황 판단: [reviews/2026-09-29-implementation-assessment.md](reviews/2026-09-29-implementation-assessment.md)
- 커밋 안 된 Codex 작업 (9/28~): `skive/drive_project_summary.py`, `migrations/0016_*.sql`, `tests/test_drive_project_summary.py`, `scripts/compare_agents_api.py`, `AGENTS_API_COMPARISON_2026-09-28.md`, 그리고 `drive_worker.py`·`drive_workspace.py`·`server.py`·`skive_drive.html`·문서 4개 수정

## 작업 점유표

| 에이전트 | 항목 | 수정 중인 파일 | 포트 | 시작 |
|---|---|---|---|---|
| (비어 있음) | | | | |

## 다음 작업 (우선순위 순)

0. **F-107** (사람, 긴급) Supabase 요금제 결정. 무료 플랜 Storage 1GB의 약 47배 사용 중. 결정 전 추가 업로드·대량 추출 금지
1. **F-100** (Codex) 진행 중 변경 정리·커밋, 테스트 기준선 기록
2. **F-106** (Codex) astra 기본값·사용 경로 제거
3. **B-005** (Codex) 검색어에서 조사·어미 제거, 무관한 프로젝트 요약 끼어들기 차단 (모델 없이 가능)
4. **B-004** (Codex) 청크 텍스트 인덱스 마이그레이션 작성 → 사람 승인 후 적용
5. **B-007** (Codex) 활동 후보를 실제 프로젝트 단위로
6. **F-207** ipynb 추출, **F-208** zip 목차 색인·선택 해제 (둘 다 ready)
7. **B-006** 한국어→영어 키워드 확장 (F-105 크레딧 이후)
8. **B-001, B-002** (F-107 요금제 이후) 9/29 업로드 대기열 등록, 조각 파일 다운로드
3. **F-105** (사람) OpenAI 크레딧 충전, 월 지출 상한 설정
4. **F-103** (Codex) Live 테스트 기본 포트 문제
5. **F-102** (Claude) 동결 문서 안내 추가, F-100 이후
6. phase-01: S1·S2는 지금 가능. S3~S8은 F-105 이후

## 열린 질문 (사람에게)

1. 모델 배치 설계(`build/design-model-routing.md`) 승인 여부, OpenAI 조직 월 예산 금액
2. 원시 데이터(대회 데이터셋 등)를 SKIVE에 계속 보관할지. Pro 기준 보관비는 100GB까지 포함, 초과분 GB당 월 $0.0213
3. Supabase Pro 전환 시점 (사람: "나중에 올림"). 그 전까지 추가 업로드·9/29 자료 추출 보류
4. 평가셋에 실사용자 원문을 넣어도 되나, 파일 ID·위치만 넣어야 하나? 공개 저장소라면 원문은 넣지 않는 쪽이 기본값 (phase-02)
5. 12월 데모 날짜가 정해지면 알려주기. 그때 phase 기간을 역산한다

## 결정 기록

| 날짜 | 결정 | 누가 |
|---|---|---|
| 2026-09-29 | 역할: Codex는 구현, Claude는 설계·평가, 사람은 실자료 시뮬·승인 | 사람 |
| 2026-09-29 | 하네스 위치 `스카이브 연습/`, 에이전트 커밋 허용 (push·병합은 사람) | 사람 |
| 2026-09-29 | `PROJECT_STATUS.md` 동결, 현재 상태는 이 파일만 사용 | 사람 |
| 2026-09-29 | Codex는 이 PC에서 로컬 실행 (클라우드 아님) | 사람 |
| 2026-09-29 | 원격 저장소는 공개. 12월 데모 날짜 미정 | 사람 |
| 2026-09-30 | 공개 유지, 실사용자 자료만 빼고 push (F-101 선택지 B) | 사람 |
| 2026-09-30 | `gpt-6-astra` 사용 금지. luna·sol(·4o-mini 예비)로 충분. 사용자 비용 상한은 제약이 커서 두지 않음 | 사람 |
| 2026-09-30 | zip은 목차 색인 + 문서·코드·노트북·작은 표만 선택 해제 (F-208 ready). Supabase Pro는 나중에 전환 | 사람 |
| 2026-11-05 | 구글 파일은 원본을 구글에 두고 파싱 결과만 보관. 직접 올린 파일만 Storage에 원본 보관 | 사람 |
| 2026-11-05 | 자소서 외부 자료는 `build/design-essay-references.md`로 관리하고 근거 검증 뒤에 작성 품질 층으로 반영 | 사람 |
| 2026-11-05 | 요약 단위는 경험. 드라이브 구조는 두고 `내 경험`에서 재구성. 타인 자료는 자소서 근거 금지. 서사는 확인된 경험으로만. 프로필은 확인된 항목만 표시 (`build/design-experience-map.md`) | 사람 |

## 세션 로그 (새 기록을 아래에 추가)

### 2026-09-29 · claude
- 저장소를 읽기 전용으로 분석하고 구현 현황을 판단했다 (reviews/2026-09-29-implementation-assessment.md).
- 하네스 파일 작성: `AGENTS.md`, `CLAUDE.md`, `harness/goal.md`, `feature_list.json`, `progress.md`, `build/_TEMPLATE.md`, `build/phase-00~02`.
- 검증: `uv run pytest -q` → 85 passed, 1 skipped. 앱 코드·테스트·설정은 수정하지 않았다.
- 발견: `0016` 적용됐지만 미커밋, 실사용자 자료 git 추적, live 테스트 기본 포트가 8010, `uvx`는 앱 제어 정책에 막힘.
- 다음: Codex가 F-100부터. 하네스 파일은 Codex 커밋과 섞이지 않게 따로 커밋한다.

### 2026-09-29 · claude (2)
- 사람 답변 반영: Codex 로컬 실행, 공개 저장소, OpenAI 한도 미해제, 데모 날짜 미정.
- git 이력 전체 비밀값 검사: 실제 키·토큰·DB 비밀번호 없음 (postgres URL 1건은 자리표시자).
- GitHub(origin `21caf04`)에는 합성 샘플만 있음. 실명·학교가 든 `data/user.json`, `data/store/2. 화력발전소 이상탐지/`, `data/outputs/apply_job_1790126169799.json`은 push 안 된 커밋 4개에만 있음 → F-101을 "다음 push 전 필수"로 올림.
- OpenAI 1토큰 호출 → `credit_balance_exhausted`. 사용량 한도가 아니라 선불 잔액 0 → F-105 추가.
- 코드 확인: 업로드·추출·읽기 카드·활동 후보 제안은 모델 호출 없음 → phase-01 S1·S2는 지금 가능.
- `AGENTS.md`에 공개 저장소 커밋 규칙, 크레딧 소진 시 재시도 금지 규칙 추가.

### 2026-09-30 · claude
- 사람 지시("개인 자료만 빼고 push")로 push 안 된 커밋 5개를 개인 자료 없이 다시 만들었다: `687a177→08f77cd`, `38ce281→502d7ec`, `ff0bc85→e0ea084`, `be34693→3edd025`, `1c00365→74656e4`. 작업 트리는 건드리지 않았다(임시 인덱스 사용).
- 뺀 것: `data/store/2. 화력발전소 이상탐지/` 4개, `data/outputs/apply_job_1790126169799.json`. `data/user.json`은 GitHub에 이미 있던 합성 인물(김민수) 버전으로 유지하고, 이 PC의 실제 값은 `git update-index --skip-worktree`로 숨김. 원래 커밋은 로컬 브랜치 `backup/local-before-privacy-filter`에 보존(push 금지).
- `.gitignore`에 실사용자 자료 경로 추가. `samples/` 기반 `*_raw` 예제는 계속 추적.
- 모델 배치 설계 `build/design-model-routing.md` 작성. 발견: `drive_project_summary.py`의 기본 모델이 `gpt-6-astra`로 하드코딩 → F-106. F-205(작업별 모델 표), F-206(자체 루프 vs Agents API 실험) 추가.
- 이미 GitHub에 있던 것(되돌리지 않음): 샘플 `metadata.json`의 로컬 경로에 들어간 폴더명, UI 목업의 학교명.
- push 완료: `21caf04..f5ca72d`. push 전 6개 커밋 모두 개인 자료 경로·실명·이메일·키 0건 확인.

### 2026-09-30 · claude (2)
- 모델 가격 웹 확인: `gpt-6-sol` $2/$10, `gpt-6-luna` $0.10/$0.50 (2026-09-22 출시). sol이 `gpt-4o`보다 싸고 강하며, luna가 `gpt-4o-mini`보다 싸다. 둘 다 추론 모델이라 추론 토큰이 출력 요금으로 청구되고, Chat Completions에서는 추론 강도 none일 때만 도구 호출이 된다 → 에이전트 루프는 Responses API 필요.
- `design-model-routing.md` 개정: astra 제외, 작업별 모델·강도·도구 회전 수 표, 사용자 비용 상한 대신 안전장치, 자소서는 luna 대화 + sol 초안.
- Supabase 사람 계정 읽기 전용 조회: 9/29 폴더 3,246개 중 3,193개가 `waiting`이고 작업이 없음(B-001). 50MiB 초과 53개는 `{uid}/{file_id}/parts/N` 조각(823개, 33.4GB)으로 저장됐고 대표 객체는 0바이트(B-002). 9/23 시험 계정 고아 객체 12개(B-003). 쓰기는 하지 않았다.
- 9/29 폴더 구성: zip 21.4GB, csv 16.5GB, safetensors 3.8GB, mp4 2.2GB 등 원시 데이터가 대부분. 문서류(pdf 81, docx 27, pptx 7, ipynb 15)는 2GB 미만.

### 2026-09-30 · claude (3)
- 사람 답변: Supabase는 무료 플랜. 9/29 업로드는 다른 컴퓨터에서 Codex에게 "Supabase에 직접 올려줘"라고 해서 올림 → 앱의 완료 처리(대기열 등록)를 거치지 않았고, 파일당 50MB 제한을 조각 저장으로 피함. B-001·B-002 원인 설명됨.
- Supabase 문서 확인: 무료 플랜은 Storage 1GB·파일당 50MB·이그레스 5GB+5GB. 초과 시 경고 후 유예, 이후 프로젝트 제한 가능 → F-107(P0) 추가. 결정 전 대기열 등록 금지(이그레스 초과).
- 추출기 지원 형식 확인: md/txt/py/json/yaml/jsonl/js/html/ps1/csv/pdf/pptx/xlsx(5MB 이하)/docx, 파일당 50MiB. ipynb·zip·이미지·가중치·영상 미지원.
- `design-file-type-policy.md` 작성: 원본은 전부 보관, 분석은 종류별로 다르게. zip은 목차 색인 + 문서·코드·노트북·작은 표만 선택 해제. 모든 파일 메타데이터 색인. F-207~F-210 추가.
- 교훈: 에이전트가 앱을 거치지 않고 Supabase에 직접 쓰면 대기열·조각·요금제 문제가 한꺼번에 생긴다 → AGENTS.md에 규칙 추가.

### 2026-09-30 · claude (4) — 첫 시뮬레이션 (읽기 전용, 모델 호출 0회)
- S4 검색 6문항: 정답 있는 5문항 중 현재 방식 top5 3/5. 검색 1회 약 25~30초. 결과: [reviews/2026-09-30-sim-retrieval-dryrun.md](reviews/2026-09-30-sim-retrieval-dryrun.md)
- 새 결함: B-004 텍스트 인덱스 없음(느림), B-005 조사가 검색어로 들어가 무관한 요약이 5/6문항에서 1순위, B-006 한국어 질문↔영어 보고서, B-007 활동 후보 13개 중 3개만 프로젝트 단위.
- S3, S5~S8은 크레딧(F-105), 9/29 자료는 요금제(F-107) 이후에 가능.

### 2026-11-04 · codex — F-108 독립 프로젝트 정리와 게시 준비
- 사용자 요청으로 앱을 `skive/`로 분리하고 과거 학습 파일을 로컬 `에이전트 연습/`에 보존했다. 변경 전 파일 191개와 Git 이력을 `.workspace-backups/`에 백업했고 앱 파일 175개를 이동 직후 해시 대조했다.
- `.env`를 앱 내부로 분리하고 공통 로더가 상위 프로젝트 설정을 읽지 않게 했다. 기존 루트 `.env`와 백업은 유지했다. 계획·과거 상태·평가 문서를 `docs/`로 정리하고 README·문서 링크·실행 경로를 갱신했다.
- 게시 대상은 `skive/`와 루트 `.gitignore`뿐이다. 원본·개인 프로필·대화·자소서·키·가상환경은 Git 대상에서 제외했고 로컬 원본은 보존했다. 공개 문서·합성 테스트의 실제 이름과 과거 DB 연결 예시를 익명화했다.
- 새로 받은 소스만으로 실행할 때 빠진 런타임 디렉터리 때문에 실패하던 문제를 재현한 후 수정했다. 빈 개인 프로필과 SQLite 디렉터리를 안전하게 초기화하며 기존 자료는 유지한다. 새 회귀 검사 6개를 추가했다.
- 검증: 자체 `uv sync --offline`, `uv lock --check`, 컴파일, 문서 링크 검사 통과. 로컬과 `.env`·개인 자료가 없는 게시용 복사본에서 각각 `88 passed, 4 skipped`. 복사본의 임시 서버 홈·업로드 JS·자소서 JS·OpenAPI·공개 설정 모두 HTTP 200, 임시 서버 종료. 공개 후보와 기존 미푸시 커밋 3개의 비밀값 검사에서 검출 0건. 사용자 승인한 원격 브랜치에 게시한다.
- 새 Supabase 키는 읽기 전용 HTTP 검사에 성공했지만 DB URI의 호스트 조회가 실패해 IPv4 공유 pooler 주소를 기다린다. DB 스키마·Storage 초기화·기존 데이터 이전은 실행하지 않았다. Supabase MCP 연결도 계정 OAuth 승인 전이다. 앱의 실제 사용자 자료 분석·모델 품질 검증은 이 결과에 포함하지 않는다.
- 게시 완료: `git push origin HEAD:refs/heads/skive-agent` 성공. 구현 커밋 `2c2fd6d`와 GitHub 원격 HEAD 일치 확인. 처음 403이 발생했지만 인증 재확인 후 재시도는 성공했다. 최신 트리는 `skive/`와 루트 `.gitignore`만 포함하며 기존 Git 이력은 유지했다.

### 2026-11-04 - Codex: shared-pooler connection verification

- User authorized testing the supplied shared-pooler URI and DB password; saved the percent-encoded URI only in the ignored app-local .env and backed up its prior contents.
- DNS resolution, TLS connection and read-only SELECT 1 succeeded. Metadata queries confirmed no skive schema/tables and zero Storage buckets.
- No migrations, Storage changes, user-data writes, model calls or server launches. Next: initialize the new project schema and private Storage configuration; older-project data is not migrated.

### 2026-11-04 · claude — 새 Supabase 초기화와 연결 검증
- 사람 지시로 새 프로젝트에 마이그레이션 16개를 적용했다. 드라이브 테이블 전부 RLS 켜짐, `anon` 조회 불가 확인. 기존 `public.skive` 빈 테이블은 건드리지 않았다.
- `tests/live_drive_smoke.py` 통과: 로그인, TUS 끊김 재개, 추출 워커, 메타데이터 RLS, Storage 격리. 임시 계정·파일은 삭제했고 사용자·객체·파일 모두 0건.
- 임시 사용자 1명을 둔 `pytest -q`: 90 passed, 2 skipped. `test_reanalyze_cannot_queue_another_users_file`은 파일이 없어 건너뛰었다. 서버는 8020에서 기동 확인 후 종료, `/api/drive/config`는 새 주소를 주고 비밀 키는 노출하지 않는다.
- 남은 일: F-105(OpenAI 크레딧 또는 Claude 어댑터 결정), 사람 자료 재업로드, 브라우저 UI 로그인 확인. 이전 프로젝트 자료(파일 4,325개)는 복구 경로가 확인되지 않았다.

### 2026-11-04 · claude — Claude 전환, 드래그 업로드, 업로드 속도
- 사람 지시로 앱 코드를 고쳤다. 모든 모델 호출을 공식 `anthropic` SDK로 전환(`skive/llm.py`). 기본 `claude-haiku-5-5`/low, 자소서 작성만 `get_essay_llm()`으로 `claude-sonnet-5-5`/medium. 임베딩은 Claude API에 없어 레거시 경로에서 OpenAI 유지.
- 프로젝트 통합 요약을 OpenAI Agents 세션에서 Claude 도구 루프로 이식. `gpt-6-astra` 앱 기본값 제거(`scripts/compare_agents_api.py`에는 남아 있음).
- 드래그 앤 드롭 업로드 추가. 실제 Edge에서 폴더 드롭으로 확인.
- 트랜잭션 풀러 충돌 수정(`prepare_threshold=None`): 이전에는 추출이 `_pg3_0 already exists`로 실패. 사용자 요청·워커에 연결 풀, 동시 업로드 4개.
- 실측: 합성 자료 아닌 실제 폴더 255개 기준 업로드 10분에 123개 → 약 6분에 255개, 업로드 실패 0. 추출은 단일 워커로 파일당 약 8.5초(연결 풀 적용 전 측정). 원인은 DB 위치 `eu-central-1`, 쿼리 왕복 약 0.29초.
- 검증: `pytest` 99 passed, 1 skipped. 실제 모델 E2E(챗봇·사실 후보·자소서·프로젝트 요약) 통과. 사고 블록 재전송은 단위 테스트만 있고 실제 호출에서는 사고 블록이 나오지 않아 미검증.
- 커밋·push 안 함. 남은 일: 실제 계정 생성, 자료 범위 결정, DB 지역 결정.

### 2026-11-04 · claude — 서울 프로젝트로 이전
- 사람이 서울 리전(`ap-northeast-2`) Supabase를 새로 만들었다. `.env` 교체(이전 값은 로컬 백업), 마이그레이션 `0001`~`0016` 적용, 드라이브 테이블 20개 전부 RLS 확인. 사용자·파일 0건.
- 측정: 쿼리 왕복 0.288초 → 0.011초, 접속 1.75초 → 0.15초. 실제 폴더 255개 드래그 업로드 6분 40초 → 63초, 업로드 후 남은 추출 34초. 결과 212개 추출, 43개 미지원, 실패 0.
- 60MB 파일은 여전히 413. Supabase Storage 전역 파일 크기 한도를 대시보드에서 올려야 한다(사람).
- 프랑크푸르트 프로젝트는 앱이 쓰지 않는다. 삭제는 사람이 한다.

### 2026-11-04 · claude — 배포 준비와 Google Drive 확인
- Storage 파일 크기 한도 10GB 확인: 60MB·9GB 생성 허용, 11GB는 413.
- Google Drive MCP는 계정에 연결됐지만 이 세션 도구에는 없어서 새 headless 세션으로 읽기 전용 확인했다. 대상 폴더 5개 존재, 쓰기 없음.
- `Dockerfile`, `deploy/start.sh`, `render.yaml` 추가. 이 PC에 Docker가 없어 이미지 빌드와 실제 배포는 미검증. 호스팅 계정 연결은 사람이 한다.

### 2026-11-04 · claude — Render 배포 확인
- 사람이 Render 무료 플랜으로 배포했다. 임시 계정으로 배포 서버에서 로그인·업로드·워커 추출까지 통과, 임시 자료 삭제. 남은 일: Supabase URL Configuration에 배포 주소 등록, 두 사람 가입, 실제 자료 넣기.

### 2026-11-04 · claude — 구글 드라이브 가져오기 (F-302)
- 사람 요청으로 구현. 브라우저 토큰 방식이라 서버 저장·마이그레이션·비밀 키가 없다. 범위는 `drive.readonly`, 앱 게시 전까지 Testing 상태로 쓴다.
- 실제 Edge와 실제 Supabase로 검증하되 구글 응답은 모의로 했다. 탐색, 공유 문서함, 폴더 구조 유지, Google 문서 변환, 바로가기 제외, 추출까지 통과. 실제 구글 로그인과 드라이브 응답은 미검증.
- 남은 일: Google Cloud 프로젝트와 Client ID(사람), 재가져오기 중복 방지, 1시간 넘는 가져오기의 토큰 재발급.

### 2026-11-04 · claude — 구글 드라이브 지속 연동으로 변경 (F-302)
- 사람이 계속 유지 방식을 골랐다. 브라우저 토큰 방식을 서버 OAuth로 교체. 갱신 토큰 암호화 저장, 토큰 칸은 사용자 권한으로 조회 불가, 시작한 브라우저 쿠키로 승인 위조 차단, 워커가 6MB 조각으로 전송, 재가져오기 중복 없음. 마이그레이션 `0017` 서울 프로젝트에 적용.
- 실제 API·Storage·DB·워커로 검증하고 구글 서버만 모의했다. 실제 구글 로그인은 미검증. 화면은 Edge로 안내·프로필·복귀·선택·진행·해제 확인.
- Testing 상태의 구글 승인은 7일 뒤 만료되어 다시 연동이 필요하다. 해소하려면 구글 앱 심사가 필요하다.

### 2026-11-05 · claude — 구글 원본 미보관 구조로 변경
- 사람 결정으로 구글 가져오기를 복사에서 연결로 바꿨다. 가져오기는 메타데이터만 등록하고, 워커가 구글에서 임시로 읽어 글자만 저장한다. 마이그레이션 `0018`.
- 자소서 참고 자료를 `build/design-essay-references.md`에 정리하고 F-211~F-214를 spec으로 추가했다. phase-02 순서는 F-203 다음.
- 실제 연동 1건 확인. 실제 구글 파일 읽기는 사람의 첫 가져오기로 확인한다.

### 2026-11-05 · claude — 브라우저 시뮬레이션과 수정
- 실제 구글 가져오기 성공: 파일 1,293개 등록, 원본 저장 0개. 읽기 완료 512개 이상, 실패 0.
- 임시 계정으로 배포 사이트에서 드래그 → 읽기 → 활동 후보 → 사실 확인 → 프로젝트 MD → 챗봇 → 자소서를 돌렸다.
- 수정: 분석 작업 우선 처리, PDF NUL 문자, 시스템 임시 파일 제외, 업로드 패널이 버튼 가림, 영어 자료를 못 찾던 검색, 확인된 사실이 자소서에 빠지던 문제.
- 실수: `8af0eb9`에 NUL 문자가 들어간 워커가 컴파일 실패 상태로 push됐고 `26086e7`로 고쳤다. 명령을 `;`로 이어 테스트 실패를 놓친 것이 원인이다. push 전 단계는 `&&`로 묶는다.
- 남은 일: F-203, 활동 MD 화면 버튼 재확인, 타인 문서 구분, 프로젝트 요약 품질, UI 재구성.
