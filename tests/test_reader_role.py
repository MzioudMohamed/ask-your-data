import psycopg
import pytest

from askdata import config

WRITE_STATEMENTS = [
    "insert into marts.fct_orders (order_id) values ('x')",
    "update marts.fct_orders set order_status = 'x'",
    "delete from marts.fct_orders",
    "truncate marts.fct_orders",
    "drop table marts.fct_orders",
    "create table marts.hack (id int)",
    "create table public.hack (id int)",
    "create temp table hack (id int)",
    "create schema hack",
]


def reader():
    return psycopg.connect(**config.DB_READER, autocommit=True)


def test_reader_can_read_marts():
    with reader() as conn:
        for table in ("fct_orders", "fct_order_items", "dim_customers"):
            assert conn.execute(f"select count(*) from marts.{table}").fetchone()[0] > 0


@pytest.mark.parametrize("sql", [
    "select * from raw.orders limit 1",
    "select * from staging.stg_orders limit 1",
    "select * from rag.glossary_chunks limit 1",
])
def test_reader_cannot_read_other_schemas(sql):
    with reader() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql)


def test_reader_sees_only_marts():
    with reader() as conn:
        schemas = {row[0] for row in conn.execute(
            "select table_schema from information_schema.tables "
            "where table_schema not in ('pg_catalog', 'information_schema')"
        ).fetchall()}
    assert schemas == {"marts"}


def test_session_settings():
    with reader() as conn:
        assert conn.execute("show default_transaction_read_only").fetchone()[0] == "on"
        assert conn.execute("show statement_timeout").fetchone()[0] == "10s"


@pytest.mark.parametrize("sql", WRITE_STATEMENTS)
def test_writes_are_blocked_by_default(sql):
    with reader() as conn:
        with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.ReadOnlySqlTransaction)):
            conn.execute(sql)


@pytest.mark.parametrize("sql", WRITE_STATEMENTS)
def test_writes_are_blocked_by_privileges_even_if_readonly_mode_is_switched_off(sql):
    """Defense in depth: a session can turn read-only mode off, so privileges must block writes on their own."""
    with reader() as conn:
        conn.execute("set default_transaction_read_only = off")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql)