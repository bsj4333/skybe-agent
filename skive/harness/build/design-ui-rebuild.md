# 설계: 새 화면과 경험 지도 API

> 작성: Claude (2026-11-05) · 상태: 사람 지시로 진행 중 · 관련 문서: `design-experience-map.md`

## 1. 구조

- `skive/web/`: Next.js(App Router, TypeScript), Tailwind, shadcn/ui 방식 컴포넌트, lucide 아이콘, Pretendard. `output: "export"`, `trailingSlash: true`로 정적 빌드해 `web/out`을 만든다.
- 서버: `web/out`이 있으면 FastAPI가 API 뒤에서 정적 파일로 제공한다. 서비스는 Render 하나다.
- 인증: 브라우저에서 Supabase Auth, API 호출은 `Authorization: Bearer <access_token>`. 공개 설정은 `GET /api/drive/config`.
- 업로드: 브라우저에서 `tus-js-client`로 Storage에 직접 올린다. 흐름은 기존 `ui_mockup/skive_drive.html`과 같다.

## 2. 화면

| 주소 | 화면 |
|---|---|
| `/login` | 로그인, 가입 |
| `/drive?folder=<id>` | 내 드라이브. 목록, 드래그 업로드, 구글 가져오기, 오른쪽 상세 패널, 원문 보기 |
| `/experiences` | 경험 지도. 만들기, 후보 카드, 합치기, 나누기, 타인 자료, 제외 |
| `/experiences/detail?id=<id>` | 경험 상세. 연결 파일, 사실 확인, 활동 요약 MD |
| `/chat?session=<id>` | 왼쪽 대화 목록, 가운데 답변, 출처 칩을 누르면 원문 패널 |
| `/career?job=<id>` | 왼쪽 공고·문항, 가운데 초안과 문장별 근거 표시, 오른쪽 AI 대화 |
| `/profile` | 연대기, 이력 카드, 프로젝트, 역량, 성장 서사 |
| `/settings` | 기본 프로필, 구글 드라이브 연동, 계정 |

정적 빌드라 동적 경로 대신 쿼리 문자열을 쓴다.

## 3. 새 API

모두 로그인 필요. 기존 API 목록은 코드가 기준이다.

### 경험 지도 `/api/drive/experiences`

| 요청 | 내용 |
|---|---|
| `POST /build` | 파일 카드와 경험 후보 만들기 시작. `{status}` |
| `GET /build` | `{status: idle/queued/processing/ready/failed, stage, cards_total, cards_done, experiences, error}` |
| `GET ""` | `[{id,title,category,subcategory,period_text,status,why,file_count,fact_count,confirmed_fact_count}]` |
| `GET /{id}` | 위 필드 + `files:[{id,name,path,owner,doc_type,summary,analysis_status}]` |
| `PATCH /{id}` | `{status?,title?,category?,subcategory?,period_text?}` |
| `POST /merge` | `{ids:[...],title?}` → 합쳐진 경험 |
| `POST /{id}/split` | `{file_ids:[...],title}` → 새 경험 |
| `PATCH /files/{file_id}/owner` | `{owner}` |

- `status`: `candidate`, `confirmed`, `excluded`
- `category`: `학교 수업`, `프로젝트`, `대외활동·공모전`, `인턴·직장`, `연구`, `취업 준비`, `참고자료`
- `owner`: `self`, `team`, `other_person`, `reference`, `unknown`

사실 확인과 활동 MD는 기존 `/api/drive/activities/{id}/...`를 쓴다. 경험의 `id`는 활동 `id`와 같다.

### 프로필 `/api/drive/profile-entries`

| 요청 | 내용 |
|---|---|
| `GET ""` | `[{id,kind,title,organization,start_date,end_date,detail,status,source_file_id}]` |
| `POST ""` | 직접 추가 |
| `PATCH /{id}`, `DELETE /{id}` | 수정, 삭제 |
| `POST /extract` | 이력서류에서 후보 추출. `{created}` |

- `kind`: `education`, `work`, `military`, `license`, `language`, `award`, `overseas`
- `status`: `candidate`, `confirmed`. 프로필에는 `confirmed`만 표시한다
- 날짜는 `YYYY-MM` 또는 `YYYY-MM-DD` 문자열이고 비어 있을 수 있다

### 성장 서사 `/api/drive/narrative`

`GET`은 `{paragraphs:[{text,experience_ids:[...]}], skills:[{name,experience_ids:[...]}], stale, updated_at}` 또는 없으면 `{paragraphs:[],skills:[]}`. `POST`는 확인된 경험으로 다시 만든다.

### 자소서 문장 검증

`GET /api/career/jobs/{id}`의 `essays[]`와 `POST /messages` 응답의 `essay`에 `sentence_checks`를 더한다.

`[{sentence, status: supported/unsupported/opinion, reason}]`. `unsupported`는 화면에서 강조하고 사용자가 고칠 때까지 `검토 필요`로 둔다.
