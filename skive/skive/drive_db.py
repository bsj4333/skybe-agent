"""Every drive query runs as the verified Supabase user under Postgres RLS."""

from contextlib import contextmanager
from uuid import UUID

from psycopg.rows import dict_row

from skive.db import get_connection


@contextmanager
def user_connection(user_id: UUID):
    with get_connection() as conn:
        conn.row_factory = dict_row
        # The pool connection is privileged. SET LOCAL ROLE makes RLS apply to
        # every query in this transaction and cannot leak to another request.
        conn.execute("select set_config('request.jwt.claim.sub', %s, true)", (str(user_id),))
        conn.execute("set local role authenticated")
        yield conn
