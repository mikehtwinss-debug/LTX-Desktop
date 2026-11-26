"""PostgreSQL triggers that keep posted documents immutable and the audit log append-only.

`Base.metadata.create_all` installs them through an `after_create` hook; an Alembic migration runs
`trigger_statements()` (and `drop_trigger_statements()` on downgrade). The SQL contains no `%` or
bind-style `:name` tokens, so it is safe to pass through `text()` and `op.execute()` alike.
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import Connection, MetaData, Table, event, text

# Columns that may still change after a document row is posted; everything else is frozen.
UPDATABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "fi_journal_entry": (
        "status",
        "reversed_by_id",
        "reversal_reason",
        "journal_no",
        "updated_at",
        "updated_by_id",
    ),
    "fi_journal_line": ("open_amount", "open_amount_local", "cleared_at", "payment_block"),
    "mm_material_document": ("status", "reversed_by_id", "journal_entry_id", "updated_at", "updated_by_id"),
    "mm_material_document_line": ("reversed_line_id",),
}
APPEND_ONLY_TABLES: tuple[str, ...] = ("org_audit_log",)

_POSTED_ROW_FUNCTION = "erp_guard_posted_row"
_APPEND_ONLY_FUNCTION = "erp_guard_append_only"
_TRUNCATE_FUNCTION = "erp_guard_truncate"

# SQLSTATE 23001 (restrict_violation) surfaces as an IntegrityError and maps to HTTP 409.
_FUNCTION_STATEMENTS = (
    f"""
CREATE OR REPLACE FUNCTION {_POSTED_ROW_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    changed text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING
            ERRCODE = 'restrict_violation',
            MESSAGE = TG_TABLE_NAME || ' rows cannot be deleted',
            TABLE = TG_TABLE_NAME;
    END IF;
    SELECT string_agg(n.key, ', ' ORDER BY n.key) INTO changed
      FROM jsonb_each(to_jsonb(NEW)) AS n
     WHERE n.key <> ALL (TG_ARGV)
       AND n.value IS DISTINCT FROM to_jsonb(OLD) -> n.key;
    IF changed IS NOT NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = 'restrict_violation',
            MESSAGE = TG_TABLE_NAME || ' columns cannot be changed after posting - ' || changed,
            TABLE = TG_TABLE_NAME;
    END IF;
    RETURN NEW;
END
$$
""",
    f"""
CREATE OR REPLACE FUNCTION {_APPEND_ONLY_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING
        ERRCODE = 'restrict_violation',
        MESSAGE = TG_TABLE_NAME || ' is append-only',
        TABLE = TG_TABLE_NAME;
END
$$
""",
    f"""
CREATE OR REPLACE FUNCTION {_TRUNCATE_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING
        ERRCODE = 'restrict_violation',
        MESSAGE = TG_TABLE_NAME || ' cannot be truncated',
        TABLE = TG_TABLE_NAME;
END
$$
""",
)


def _table_trigger_statements(table: str) -> list[str]:
    if table in UPDATABLE_COLUMNS:
        arguments = ", ".join(f"'{column}'" for column in UPDATABLE_COLUMNS[table])
        row_guard = f"{_POSTED_ROW_FUNCTION}({arguments})"
    else:
        row_guard = f"{_APPEND_ONLY_FUNCTION}()"
    return [
        f"CREATE OR REPLACE TRIGGER trg_{table}_guard BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {row_guard}",
        f"CREATE OR REPLACE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
        f"FOR EACH STATEMENT EXECUTE FUNCTION {_TRUNCATE_FUNCTION}()",
    ]


def guarded_tables() -> tuple[str, ...]:
    return (*UPDATABLE_COLUMNS, *APPEND_ONLY_TABLES)


def trigger_statements(tables: Iterable[str] | None = None) -> list[str]:
    """SQL statements that (re)create the guard functions and the triggers of `tables` (default: all)."""
    selected = guarded_tables() if tables is None else tuple(tables)
    statements = [statement.strip() for statement in _FUNCTION_STATEMENTS]
    for table in selected:
        statements.extend(_table_trigger_statements(table))
    return statements


def drop_trigger_statements() -> list[str]:
    """SQL statements that remove every guard trigger and function (migration downgrade)."""
    statements = []
    for table in guarded_tables():
        statements.append(f"DROP TRIGGER IF EXISTS trg_{table}_guard ON {table}")
        statements.append(f"DROP TRIGGER IF EXISTS trg_{table}_no_truncate ON {table}")
    for function in (_POSTED_ROW_FUNCTION, _APPEND_ONLY_FUNCTION, _TRUNCATE_FUNCTION):
        statements.append(f"DROP FUNCTION IF EXISTS {function}()")
    return statements


def install_triggers(metadata: MetaData) -> None:
    """Make `metadata.create_all` install the triggers of every guarded table it creates."""

    @event.listens_for(metadata, "after_create")
    def _create_triggers(
        target: MetaData, connection: Connection, tables: Iterable[Table] | None = None, **kwargs: Any
    ) -> None:
        created = {table.name for table in tables or ()}
        selected = [name for name in guarded_tables() if name in created]
        if selected:
            for statement in trigger_statements(selected):
                connection.execute(text(statement))
