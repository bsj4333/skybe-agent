"""Every drive query runs as the verified Supabase user under Postgres RLS."""

from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from skive.db import CONNECT_OPTIONS, database_url

# 새 접속 한 번에 약 1.75초가 걸려서 파일마다 접속하면 업로드가 파일당 수 초씩 느려진다.
POOL_MAX_SIZE = 8
POOL_WAIT_SECONDS = 15


@lru_cache(maxsize=1)
def _pool() -> ConnectionPool:
    pool = ConnectionPool(
        database_url(), kwargs={**CONNECT_OPTIONS, "row_factory": dict_row}, open=False,
        min_size=1, max_size=POOL_MAX_SIZE, timeout=POOL_WAIT_SECONDS,
        check=ConnectionPool.check_connection,
    )
    pool.open()
    return pool


def service_connection():
    """Pooled privileged connection for the background worker. RLS does not apply."""
    return _pool().connection()


@contextmanager
def user_connection(user_id: UUID):
    with _pool().connection() as conn:
        # The pool connection is privileged. Both settings are transaction-local, so RLS
        # applies to every query here and cannot leak to the next user of this connection.
        conn.execute("select set_config('request.jwt.claim.sub', %s, true), "
                     "set_config('role', 'authenticated', true)", (str(user_id),))
        yield conn
