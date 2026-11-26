"""The Phase 1 data model as a whole: documented tables, mixin columns and constraint conventions."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, Engine, inspect, text
from sqlalchemy.orm import RelationshipProperty, configure_mappers
from sqlalchemy.sql.ddl import sort_tables_and_constraints

from app.core.db import Base

BACKEND_DIR = Path(__file__).resolve().parents[2]
DOCUMENTED_TABLES = {
    "auth_user", "auth_role", "auth_permission", "auth_role_permission", "auth_user_role",
    "org_company", "org_plant", "org_warehouse", "org_purchasing_group", "org_currency",
    "org_exchange_rate", "org_uom", "org_number_range", "org_company_setting", "org_audit_log",
    "org_attachment", "org_approval_rule", "org_approval_request", "org_approval_step",
    "co_cost_center", "co_internal_order", "co_profit_center",
    "fi_gl_account", "fi_period", "fi_tax_code", "fi_journal_entry", "fi_journal_line", "fi_clearing",
    "fi_clearing_item", "fi_reflection_rule", "fi_payment_term", "fi_vendor", "fi_customer",
    "fi_treasury_account", "fi_invoice", "fi_invoice_line", "fi_payment",
    "mm_material_group", "mm_valuation_class", "mm_account_determination", "mm_material",
    "mm_material_plant", "mm_batch", "mm_stock_balance", "mm_material_document",
    "mm_material_document_line", "mm_physical_inventory", "mm_physical_inventory_line",
    "mm_info_record", "mm_requisition", "mm_requisition_line", "mm_rfq", "mm_rfq_line", "mm_rfq_vendor",
    "mm_quotation", "mm_quotation_line", "mm_quotation_comparison", "mm_comparison_selection",
    "mm_comparison_mark", "mm_purchase_order", "mm_purchase_order_line", "mm_purchase_order_revision",
    "mm_supplier_invoice", "mm_supplier_invoice_line",
}  # fmt: skip
COMPANY_TABLES = {
    "org_plant", "org_warehouse", "org_purchasing_group", "org_number_range", "org_company_setting",
    "org_attachment", "org_approval_rule", "org_approval_request",
    "co_cost_center", "co_internal_order", "co_profit_center",
    "fi_gl_account", "fi_period", "fi_tax_code", "fi_journal_entry", "fi_journal_line", "fi_clearing",
    "fi_reflection_rule", "fi_payment_term", "fi_vendor", "fi_customer", "fi_treasury_account",
    "fi_invoice", "fi_payment",
    "mm_material_group", "mm_valuation_class", "mm_account_determination", "mm_material",
    "mm_material_document", "mm_physical_inventory", "mm_info_record", "mm_requisition", "mm_rfq",
    "mm_quotation", "mm_quotation_comparison", "mm_purchase_order", "mm_supplier_invoice",
}  # fmt: skip
VERSIONED_TABLES = {
    "auth_user", "org_company", "org_plant", "org_warehouse", "co_cost_center", "fi_gl_account",
    "fi_tax_code", "fi_vendor", "fi_customer", "fi_treasury_account", "mm_material", "mm_material_plant",
    "mm_physical_inventory", "mm_info_record", "mm_requisition", "mm_rfq", "mm_quotation",
    "mm_quotation_comparison", "mm_purchase_order",
}  # fmt: skip
AUDITED_TABLES = {
    "auth_user", "auth_role", "auth_user_role", "org_company", "org_plant", "org_warehouse",
    "org_purchasing_group", "org_exchange_rate", "org_uom", "org_approval_rule", "co_cost_center",
    "fi_gl_account", "fi_period", "fi_tax_code", "fi_payment_term", "fi_vendor", "fi_customer",
    "fi_treasury_account", "mm_material_group", "mm_valuation_class", "mm_account_determination",
    "mm_material", "mm_batch", "mm_info_record",
}  # fmt: skip
# Immutable document lines and the append-only log carry no timestamp columns (see their models).
TABLES_WITHOUT_TIMESTAMPS = {"fi_journal_line", "mm_material_document_line", "org_audit_log"}
TIMESTAMP_COLUMNS = {"created_at", "updated_at", "created_by_id", "updated_by_id"}
UNIQUE_KEYS = {
    "auth_user": [("username",)],
    "auth_role": [("code",)],
    "auth_permission": [("key",)],
    "auth_role_permission": [("role_id", "permission_id")],
    "org_company": [("code",)],
    "org_currency": [("code",)],
    "org_uom": [("code",)],
    "org_exchange_rate": [("currency_code", "rate_date", "rate_type")],
    "org_number_range": [("company_id", "key", "year")],
    "org_company_setting": [("company_id", "key")],
    "fi_gl_account": [("company_id", "code")],
    "fi_period": [("company_id", "year", "period")],
    "fi_journal_entry": [("company_id", "fiscal_year", "number")],
    "fi_vendor": [("company_id", "code")],
    "fi_customer": [("company_id", "code")],
    "mm_material": [("company_id", "code"), ("company_id", "barcode")],
    "mm_material_plant": [("material_id", "plant_id")],
    "mm_batch": [("material_id", "batch_no")],
    "mm_purchase_order": [("company_id", "number")],
    "mm_purchase_order_line": [("order_id", "line_no")],
}


def _mapper_tables() -> dict[str, type]:
    return {mapper.local_table.name: mapper.class_ for mapper in Base.registry.mappers}


def test_every_documented_table_exists_and_nothing_else() -> None:
    assert set(Base.metadata.tables) == DOCUMENTED_TABLES


def test_mappers_configure() -> None:
    configure_mappers()


def test_every_table_has_an_identity_primary_key() -> None:
    for table in Base.metadata.tables.values():
        assert [column.name for column in table.primary_key.columns] == ["id"], table.name
        assert table.c.id.identity is not None, table.name


def test_timestamp_columns() -> None:
    for name, table in Base.metadata.tables.items():
        present = TIMESTAMP_COLUMNS & set(table.c.keys())
        assert present == (set() if name in TABLES_WITHOUT_TIMESTAMPS else TIMESTAMP_COLUMNS), name


def test_company_version_and_audit_flags_follow_the_contract() -> None:
    classes = _mapper_tables()
    for name, table in Base.metadata.tables.items():
        has_company = "company_id" in table.c and not table.c.company_id.nullable
        assert has_company == (name in COMPANY_TABLES), name
        assert ("version" in table.c) == (name in VERSIONED_TABLES), name
        assert (getattr(classes[name], "__audit__", False) is True) == (name in AUDITED_TABLES), name
    for name in VERSIONED_TABLES:
        assert classes[name].__mapper__.version_id_col is Base.metadata.tables[name].c.version, name


def test_documented_unique_keys() -> None:
    for name, keys in UNIQUE_KEYS.items():
        table = Base.metadata.tables[name]
        unique_sets = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        for key in keys:
            assert key in unique_sets, (name, key)


def test_every_foreign_key_declares_its_delete_rule() -> None:
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.ondelete in {"RESTRICT", "CASCADE", "SET NULL"}, foreign_key
            if foreign_key.ondelete == "CASCADE":
                # Only rows owned by their parent (lines of a header, links of a user) cascade.
                assert not foreign_key.parent.nullable, foreign_key


def test_tables_can_be_created_in_dependency_order() -> None:
    """Alembic's autogenerate cannot order mutually dependent tables, so the model must not have any
    foreign-key cycle (self-references are fine)."""
    ordered = sort_tables_and_constraints(Base.metadata.tables.values())

    deferred = [constraint for table, constraints in ordered if table is None for constraint in constraints]
    assert deferred == []
    position = {table.name: index for index, (table, _) in enumerate(ordered) if table is not None}
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            if foreign_key.column.table is not table:
                assert position[foreign_key.column.table.name] < position[table.name], foreign_key


def test_line_collections_are_ordered_by_line_no() -> None:
    checked = 0
    for mapper in Base.registry.mappers:
        for relationship in mapper.relationships:
            target = relationship.mapper.local_table
            if (
                isinstance(relationship, RelationshipProperty)
                and relationship.uselist
                and "line_no" in target.c
            ):
                assert [str(column) for column in relationship.order_by] == [f"{target.name}.line_no"], (
                    relationship
                )
                checked += 1
    # journal entry, FI invoice, material document, physical inventory, requisition, RFQ, PO, supplier invoice
    assert checked == 8


def test_amount_and_side_checks_are_declared() -> None:
    def checks(table_name: str) -> set[str]:
        table = Base.metadata.tables[table_name]
        prefix = f"ck_{table_name}_"
        return {str(c.name).removeprefix(prefix) for c in table.constraints if isinstance(c, CheckConstraint)}

    assert {"side_valid", "amount_non_negative", "amount_local_non_negative", "single_partner"} <= checks(
        "fi_journal_line"
    )
    assert "normal_side_valid" in checks("fi_gl_account")
    assert "quantity_non_negative" in checks("mm_stock_balance")
    assert "quantity_positive" in checks("mm_material_document_line")


def test_database_schema_matches_the_metadata(engine: Engine) -> None:
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == DOCUMENTED_TABLES
    with engine.connect() as connection:
        partial_indexes = set(
            connection.scalars(
                text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexdef LIKE '%WHERE%'"
                )
            )
        )
        not_valid = connection.scalar(text("SELECT count(*) FROM pg_constraint WHERE NOT convalidated"))
    assert {
        "uq_mm_stock_balance_no_batch",
        "uq_mm_stock_balance_batch",
        "uq_auth_user_role_global",
        "uq_auth_user_role_company",
        "uq_mm_supplier_invoice_vendor_reference",
        "ix_fi_journal_line_vendor_open",
        "ix_fi_journal_line_customer_open",
    } <= partial_indexes
    assert not_valid == 0


def test_alembic_environment_sees_no_drift(engine: Engine) -> None:
    """Runs the real alembic.ini / env.py against the test database: autogenerate must find nothing
    to do for a schema built by `create_all`, i.e. every construct reflects the way it is declared."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))

    try:
        command.check(config)  # raises CommandError when it detects pending operations
    finally:
        # The check leaves Alembic's bookkeeping table behind; other tests expect a pristine schema.
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
