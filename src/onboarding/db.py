from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row


@contextmanager
def connect(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as c:
        c.execute("SET statement_timeout='10s'")
        yield c


def lock(c, company):
    c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (company,))
