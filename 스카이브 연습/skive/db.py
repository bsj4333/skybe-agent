"""Postgres(Supabase) 연결과 마이그레이션 실행.

DATABASE_URL은 .env에서 읽는다 (git에는 안 올라감). 스키마 변경은 파일로 관리한다:
migrations/0001_init.sql, 0002_..., ... 순서대로, 한 번 적용된 파일은 다시 실행하지 않는다
(skive.schema_migrations 테이블에 기록).
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def get_connection() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(".env에 DATABASE_URL이 없음 (Supabase 프로젝트의 connection string)")
    return psycopg.connect(url)


def run_migrations() -> list[str]:
    """migrations/*.sql을 파일명 순서대로, 아직 적용 안 된 것만 실행한다."""
    applied = []
    with get_connection() as conn:
        conn.execute("create schema if not exists skive")
        conn.execute(
            "create table if not exists skive.schema_migrations "
            "(filename text primary key, applied_at timestamptz not null default now())"
        )
        conn.commit()
        done = {row[0] for row in conn.execute("select filename from skive.schema_migrations").fetchall()}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("insert into skive.schema_migrations (filename) values (%s)", (path.name,))
            conn.commit()
            applied.append(path.name)
    return applied
