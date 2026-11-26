"""Database triggers: posted documents are immutable, the audit log is append-only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.core.context import RequestContext
from app.core.db import utcnow
from app.core.triggers import (
    APPEND_ONLY_TABLES,
    UPDATABLE_COLUMNS,
    drop_trigger_statements,
    guarded_tables,
    trigger_statements,
)
from app.modules.fi.models.gl import FiDocType, JournalEntry, JournalLine, JournalStatus, Side
from app.modules.mm.models.inventory import (
    MaterialDocument,
    MaterialDocumentLine,
    MaterialDocumentStatus,
    StockType,
)
from app.modules.org.models import AuditLog, Plant, Uom, Warehouse
from tests import factories

RESTRICT_VIOLATION = "23001"


def _journal_entry(ctx: RequestContext, number: str = "2600000001") -> JournalEntry:
    cash = factories.gl_account(ctx.db, "100.01")
    vendor_account = factories.gl_account(ctx.db, "320.01")
    vendor = factories.make_vendor(ctx.db)
    entry = JournalEntry(
        company_id=ctx.company_id,
        fiscal_year=2026,
        period=3,
        number=number,
        doc_type=FiDocType.VP,
        posting_date=date(2026, 3, 15),
        document_date=date(2026, 3, 15),
        currency_code="TRY",
        exchange_rate=Decimal(1),
        total_local=Decimal("1500.00"),
        lines=[
            JournalLine(
                line_no=1,
                company_id=ctx.company_id,
                posting_date=date(2026, 3, 15),
                gl_account_id=vendor_account.id,
                side=Side.DEBIT,
                amount=Decimal("1500.00"),
                amount_local=Decimal("1500.00"),
                vendor_id=vendor.id,
                is_open_item=True,
                open_amount=Decimal("1500.00"),
                open_amount_local=Decimal("1500.00"),
            ),
            JournalLine(
                line_no=2,
                company_id=ctx.company_id,
                posting_date=date(2026, 3, 15),
                gl_account_id=cash.id,
                side=Side.CREDIT,
                amount=Decimal("1500.00"),
                amount_local=Decimal("1500.00"),
            ),
        ],
    )
    ctx.db.add(entry)
    ctx.db.flush()
    return entry


def _material_document(ctx: RequestContext, number: str = "MB260000001") -> MaterialDocument:
    db = ctx.db
    material = factories.make_material(db)
    plant = db.scalars(select(Plant).where(Plant.company_id == ctx.company_id)).one()
    warehouse = db.scalars(select(Warehouse).where(Warehouse.company_id == ctx.company_id)).one()
    document = MaterialDocument(
        company_id=ctx.company_id,
        number=number,
        year=2026,
        posting_date=date(2026, 3, 15),
        document_date=date(2026, 3, 15),
        lines=[
            MaterialDocumentLine(
                line_no=1,
                movement_type="561",
                material_id=material.id,
                plant_id=plant.id,
                warehouse_id=warehouse.id,
                stock_type=StockType.UNRESTRICTED,
                quantity=Decimal("10"),
                direction=1,
                entry_quantity=Decimal("10"),
                entry_uom_id=db.scalars(select(Uom.id).where(Uom.code == "ADET")).one(),
                amount_local=Decimal("250.00"),
            )
        ],
    )
    db.add(document)
    db.flush()
    return document


def _rejected(db: Session, statement) -> str:
    """Run a statement that a trigger must reject; returns the database error message."""
    with pytest.raises(IntegrityError) as error, db.begin_nested():
        db.execute(statement)
    assert error.value.orig.sqlstate == RESTRICT_VIOLATION
    return str(error.value.orig)


def test_trigger_definitions_cover_the_documented_whitelist() -> None:
    assert UPDATABLE_COLUMNS == {
        "fi_journal_entry": (
            "status",
            "reversed_by_id",
            "reversal_reason",
            "journal_no",
            "updated_at",
            "updated_by_id",
        ),
        "fi_journal_line": ("open_amount", "open_amount_local", "cleared_at", "payment_block"),
        "mm_material_document": (
            "status",
            "reversed_by_id",
            "journal_entry_id",
            "updated_at",
            "updated_by_id",
        ),
        "mm_material_document_line": ("reversed_line_id",),
    }
    assert APPEND_ONLY_TABLES == ("org_audit_log",)
    statements = trigger_statements()
    assert sum(statement.startswith("CREATE OR REPLACE FUNCTION") for statement in statements) == 3
    assert sum(statement.startswith("CREATE OR REPLACE TRIGGER") for statement in statements) == 10
    # Safe for text() and Alembic's op.execute(): no percent signs and no bind-like tokens.
    assert not any("%" in statement or ":=" in statement for statement in statements)


def test_create_all_installed_every_trigger(engine: Engine) -> None:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE NOT t.tgisinternal"
            )
        )
        triggers = {(table, trigger) for table, trigger in rows}

    assert triggers == {
        (table, f"trg_{table}_{suffix}") for table in guarded_tables() for suffix in ("guard", "no_truncate")
    }


def test_journal_entry_cannot_be_deleted_or_rewritten(ctx: RequestContext, db: Session) -> None:
    entry = _journal_entry(ctx)

    message = _rejected(db, delete(JournalEntry).where(JournalEntry.id == entry.id))
    assert "fi_journal_entry rows cannot be deleted" in message
    for values in (
        {"posting_date": date(2026, 4, 1)},
        {"total_local": Decimal("1.00")},
        {"number": "2600009999"},
        {"doc_type": FiDocType.GL},
        {"currency_code": "USD"},
        {"header_text": "sonradan eklendi"},
        {"company_id": factories.make_company(db).id},
        {"reversal_of_id": entry.id},
        {"status": JournalStatus.REVERSED, "fiscal_year": 2027},
    ):
        message = _rejected(db, update(JournalEntry).where(JournalEntry.id == entry.id).values(**values))
        assert "fi_journal_entry columns cannot be changed after posting" in message
        assert all(column in message for column in values if column != "status")


def test_journal_entry_bookkeeping_columns_may_change(ctx: RequestContext, db: Session) -> None:
    entry = _journal_entry(ctx)
    reversal = _journal_entry(ctx, number="2600000002")

    entry.status = JournalStatus.REVERSED
    entry.reversed_by_id = reversal.id
    entry.reversal_reason = "Hatalı kayıt"
    entry.journal_no = 17
    db.flush()  # the ORM also sets updated_at and updated_by_id, both whitelisted

    db.expire_all()
    stored = db.get_one(JournalEntry, entry.id)
    assert (stored.status, stored.reversed_by_id, stored.reversal_reason, stored.journal_no) == (
        JournalStatus.REVERSED,
        reversal.id,
        "Hatalı kayıt",
        17,
    )
    assert stored.updated_by_id == ctx.user.id


def test_journal_line_allows_only_open_item_bookkeeping(ctx: RequestContext, db: Session) -> None:
    entry = _journal_entry(ctx)
    line = entry.lines[0]

    _rejected(db, delete(JournalLine).where(JournalLine.id == line.id))
    for values in (
        {"amount": Decimal("1.00")},
        {"amount_local": Decimal("1.00")},
        {"side": Side.CREDIT},
        {"gl_account_id": factories.gl_account(db, "102.01").id},
        {"vendor_id": None},
        {"posting_date": date(2026, 4, 1)},
        {"text": "değişti"},
        {"due_date": date(2026, 4, 30)},
        {"is_open_item": False},
    ):
        message = _rejected(db, update(JournalLine).where(JournalLine.id == line.id).values(**values))
        assert "fi_journal_line columns cannot be changed after posting" in message

    line.open_amount = Decimal("500.00")
    line.open_amount_local = Decimal("500.00")
    line.payment_block = True
    db.flush()
    line.open_amount = Decimal("0.00")
    line.open_amount_local = Decimal("0.00")
    line.cleared_at = utcnow()
    line.payment_block = False
    db.flush()

    db.expire_all()
    stored = db.get_one(JournalLine, line.id)
    assert (stored.open_amount, stored.payment_block) == (Decimal("0.00"), False)
    assert stored.cleared_at is not None
    assert stored.amount == Decimal("1500.00")


def test_whitelisted_update_that_changes_nothing_else_passes_even_as_a_full_row_update(
    ctx: RequestContext, db: Session
) -> None:
    entry = _journal_entry(ctx)

    # An UPDATE may name frozen columns as long as their values stay the same.
    db.execute(
        update(JournalEntry)
        .where(JournalEntry.id == entry.id)
        .values(number=entry.number, total_local=Decimal("1500.0"), status=JournalStatus.REVERSED)
    )

    db.expire_all()
    assert db.get_one(JournalEntry, entry.id).status is JournalStatus.REVERSED


def test_material_document_is_immutable(ctx: RequestContext, db: Session) -> None:
    document = _material_document(ctx)
    reversal = _material_document(ctx, number="MB260000002")
    journal_entry = _journal_entry(ctx)
    line = document.lines[0]

    _rejected(db, delete(MaterialDocument).where(MaterialDocument.id == document.id))
    _rejected(db, delete(MaterialDocumentLine).where(MaterialDocumentLine.id == line.id))
    for values in ({"posting_date": date(2026, 4, 1)}, {"number": "MB269999999"}, {"reference": "x"}):
        _rejected(db, update(MaterialDocument).where(MaterialDocument.id == document.id).values(**values))
    for values in (
        {"quantity": Decimal("11")},
        {"amount_local": Decimal("1.00")},
        {"movement_type": "501"},
        {"direction": -1},
        {"stock_type": StockType.BLOCKED},
        {"text": "değişti"},
    ):
        message = _rejected(
            db, update(MaterialDocumentLine).where(MaterialDocumentLine.id == line.id).values(**values)
        )
        assert "mm_material_document_line columns cannot be changed after posting" in message

    document.status = MaterialDocumentStatus.REVERSED
    document.reversed_by_id = reversal.id
    document.journal_entry_id = journal_entry.id
    line.reversed_line_id = reversal.lines[0].id
    db.flush()

    db.expire_all()
    stored = db.get_one(MaterialDocument, document.id)
    assert (stored.status, stored.reversed_by_id, stored.journal_entry_id) == (
        MaterialDocumentStatus.REVERSED,
        reversal.id,
        journal_entry.id,
    )
    assert db.get_one(MaterialDocumentLine, line.id).reversed_line_id == reversal.lines[0].id


def test_orm_delete_of_a_posted_document_fails(ctx: RequestContext, db: Session) -> None:
    entry = _journal_entry(ctx)

    with pytest.raises(IntegrityError) as error, db.begin_nested():
        db.delete(entry)
        db.flush()

    assert error.value.orig.sqlstate == RESTRICT_VIOLATION


def test_audit_log_is_append_only(ctx: RequestContext, db: Session) -> None:
    entry = audit.log(ctx, "TEST", "org_uom", 1, "silinemez kayıt")
    db.flush()

    assert "org_audit_log is append-only" in _rejected(
        db, update(AuditLog).where(AuditLog.id == entry.id).values(summary="değiştirildi")
    )
    assert "org_audit_log is append-only" in _rejected(db, delete(AuditLog).where(AuditLog.id == entry.id))
    assert (
        db.scalar(text("SELECT summary FROM org_audit_log WHERE id = :id"), {"id": entry.id})
        == "silinemez kayıt"
    )


@pytest.mark.parametrize(
    "table", ["fi_journal_entry", "fi_journal_line", "mm_material_document", "org_audit_log"]
)
def test_guarded_tables_cannot_be_truncated(db: Session, table: str) -> None:
    message = _rejected(db, text(f"TRUNCATE {table} CASCADE"))

    assert "cannot be truncated" in message


def test_drop_and_reinstall_statements(ctx: RequestContext, db: Session) -> None:
    """The statements handed to migrations work in both directions (DDL is transactional here)."""
    entry = _journal_entry(ctx)
    change = update(JournalEntry).where(JournalEntry.id == entry.id).values(header_text="serbest")

    for statement in drop_trigger_statements():
        db.execute(text(statement))
    db.execute(change)
    remaining = db.scalar(text("SELECT count(*) FROM pg_proc WHERE proname LIKE 'erp_guard_%'"))

    for statement in trigger_statements():
        db.execute(text(statement))
    _rejected(db, update(JournalEntry).where(JournalEntry.id == entry.id).values(header_text="yine kilitli"))

    assert remaining == 0
    assert db.scalar(text("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal")) == 10
