# SKIVE

개인 자료를 폴더 구조 그대로 보관하고, 자료의 근거를 찾아 공부·경험 회상·자소서 작성에 활용하는 FastAPI 앱입니다.

## 시작하기

이 README가 있는 `skive/` 폴더가 독립 프로젝트 루트입니다. 상위 폴더의 연습 코드나 `.env`가 필요하지 않습니다. Python 3.12와 [uv](https://docs.astral.sh/uv/)를 사용합니다.

```powershell
cd skive
uv sync --locked
Copy-Item .env.example .env
```

`.env`에 **동일한 Supabase 프로젝트**의 URL, publishable key, 서버 전용 secret key, Transaction pooler DB 연결 문자열과 OpenAI 키를 입력합니다. DB 비밀번호에 특수문자가 있으면 URL 인코딩합니다. 이미 `.env`가 있다면 예시 파일을 덮어쓰지 말고 필요한 항목만 수정합니다.

새 Supabase 프로젝트에는 DB 스키마·RLS 정책·Storage 버킷 초기화가 필요합니다. 기존 프로젝트의 사용자·파일은 키를 바꾸는 것만으로 이전되지 않습니다. 프로젝트 소유자가 대상과 실행 내용을 확인한 후에만 다음 마이그레이션을 실행합니다.

```powershell
uv run python -c "from skive.db import run_migrations; print(run_migrations())"
```

웹 서버와 파일 추출 워커는 각각 별도 터미널에서 실행합니다.

```powershell
uv run uvicorn skive.server:app --host 127.0.0.1 --port 8010
uv run python -m skive.drive_worker
```

브라우저에서 <http://localhost:8010/>에 접속합니다. 작업 중인 에이전트의 포트는 [AGENTS.md](AGENTS.md)를 따릅니다. Windows에서는 `--reload` 없이 실행합니다.

## 검증

```powershell
uv run python -m scripts.test_offline
uv run python -m compileall -q skive scripts tests
```

무료 회귀 명령은 `DATABASE_URL`을 해당 프로세스에서 비워 실제 DB 검사를 비활성화합니다. 기존 pytest에는 DB 접속 설정이 있으면 켜지는 보안 검사 3개가 있으므로, 새 프로젝트나 실제 개인 자료를 대상으로 기본 pytest를 실행하지 않습니다. 해당 검사의 단언은 그대로 유지하며 준비된 시험 프로젝트에서 따로 실행합니다. `tests/live_*.py`도 별도 실행 도구입니다. UI 검증에는 자기 서버를 가리키는 `SKIVE_TEST_BASE_URL`을 지정합니다.

## 폴더 안내

| 경로 | 용도 |
|---|---|
| `skive/` | 서버, 인증, 업로드, 추출, 검색, 챗봇·자소서 코드 |
| `ui_mockup/` | 현재 서버가 제공하는 HTML·JavaScript와 업로드 라이브러리 |
| `migrations/` | DB 구조와 사용자별 접근 정책 |
| `tests/` | 무료 회귀 검사와 별도 live 검증 도구 |
| `scripts/` | 앱을 통한 로컬 자료 가져오기, 비교 실험 도구 |
| `samples/` | 합성 수업·프로젝트 예시 |
| `src/` | Python 패키징용 기존 진입점 |
| `harness/` | 현재 진행 상태, 작업 목록, 설계·검토 |
| `docs/` | 설계 배경, 과거 기록, 비용 산출 근거 |
| `data/` | 로컬 실행 자료·대화·생성 결과. Git 제외 |
| `.env` | 이 앱의 실제 접속 설정. Git 제외 |

## 현재 범위

계정별 드라이브, 파일 추출, 출처 색인과 활동·대화·자소서 작업 공간이 있습니다. 추출 완료는 개인 역할이나 성과가 검증됐다는 뜻이 아닙니다. 실제 대용량 자료의 검색 품질, 프로젝트 요약 비용, 문장별 근거 검증은 [현재 작업 목록](harness/feature_list.json)에서 상태를 확인합니다.

기존 단일 사용자 엔진은 개발 PC에서 `skive.legacy_server:app`으로 별도 실행할 수 있습니다. 멀티유저 드라이브와 데이터 저장 경로가 같다는 뜻은 아닙니다.

## 문서

- [설정 안내](DRIVE_SETUP.md)
- [문서 목차](docs/README.md)
- [현재 진행 상태](harness/progress.md)
- [구현·검토 규칙](AGENTS.md)

실제 `.env`, 개인 원본·자소서·대화, 백업과 가상환경은 공개 저장소에 포함하지 않습니다. `samples/`만 공개 예시로 사용합니다.
