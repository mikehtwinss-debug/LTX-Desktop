"""Batches, stock balances, material documents and physical inventory."""

from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, CompanyMixin, IdMixin, TimestampMixin, VersionMixin, ref
from app.core.types import Money, Qty, enum_type

if TYPE_CHECKING:
    from app.modules.mm.models.master import Material
    from app.modules.org.models import Plant, Uom, Warehouse


class StockType(enum.StrEnum):
    UNRESTRICTED = "UNRESTRICTED"
    QUALITY = "QUALITY"
    BLOCKED = "BLOCKED"


class MaterialDocumentStatus(enum.StrEnum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PhysicalInventoryStatus(enum.StrEnum):
    OPEN = "OPEN"
    COUNTED = "COUNTED"
    POSTED = "POSTED"
    CANCELLED = "CANCELLED"


class Batch(IdMixin, TimestampMixin, Base):
    __tablename__ = "mm_batch"
    __audit__ = True
    __table_args__ = (
        UniqueConstraint("material_id", "batch_no"),
        Index("ix_mm_batch_expiry_date", "expiry_date", postgresql_where="expiry_date IS NOT NULL"),
    )

    material_id: Mapped[int] = ref("mm_material.id")
    batch_no: Mapped[str] = mapped_column(String(40))
    production_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    vendor_batch_no: Mapped[str | None] = mapped_column(String(40))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)

    material: Mapped[Material] = relationship(foreign_keys=[material_id])


class StockBalance(IdMixin, TimestampMixin, Base):
    """Quantity per material, warehouse, batch and stock type. `batch_id` is NULL for materials
    without batch management, so uniqueness is enforced by two partial indexes."""

    __tablename__ = "mm_stock_balance"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        Index(
            "uq_mm_stock_balance_no_batch",
            "material_id",
            "warehouse_id",
            "stock_type",
            unique=True,
            postgresql_where="batch_id IS NULL",
        ),
        Index(
            "uq_mm_stock_balance_batch",
            "material_id",
            "warehouse_id",
            "batch_id",
            "stock_type",
            unique=True,
            postgresql_where="batch_id IS NOT NULL",
        ),
        Index("ix_mm_stock_balance_material_id_plant_id", "material_id", "plant_id"),
    )

    material_id: Mapped[int] = ref("mm_material.id")
    plant_id: Mapped[int] = ref("org_plant.id", index=True)
    warehouse_id: Mapped[int] = ref("org_warehouse.id", index=True)
    batch_id: Mapped[int | None] = ref("mm_batch.id", index=True)
    stock_type: Mapped[StockType] = mapped_column(enum_type(StockType), default=StockType.UNRESTRICTED)
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal(0))

    material: Mapped[Material] = relationship(foreign_keys=[material_id])
    plant: Mapped[Plant] = relationship(foreign_keys=[plant_id])
    warehouse: Mapped[Warehouse] = relationship(foreign_keys=[warehouse_id])
    batch: Mapped[Batch | None] = relationship(foreign_keys=[batch_id])


class MaterialDocument(IdMixin, TimestampMixin, CompanyMixin, Base):
    """Posted stock movement. A trigger rejects DELETE and any UPDATE outside the bookkeeping columns."""

    __tablename__ = "mm_material_document"
    __table_args__ = (
        UniqueConstraint("company_id", "number"),
        Index("ix_mm_material_document_company_id_posting_date", "company_id", "posting_date"),
        Index("ix_mm_material_document_source", "company_id", "source_type", "source_id"),
    )

    number: Mapped[str] = mapped_column(String(24))
    year: Mapped[int] = mapped_column(Integer)
    posting_date: Mapped[date] = mapped_column(Date)
    document_date: Mapped[date] = mapped_column(Date)
    reference: Mapped[str | None] = mapped_column(String(64))
    header_text: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[MaterialDocumentStatus] = mapped_column(
        enum_type(MaterialDocumentStatus), default=MaterialDocumentStatus.POSTED
    )
    reversal_of_id: Mapped[int | None] = ref("mm_material_document.id", index=True)
    reversed_by_id: Mapped[int | None] = ref("mm_material_document.id")
    journal_entry_id: Mapped[int | None] = ref("fi_journal_entry.id", index=True)
    source_type: Mapped[str | None] = mapped_column(String(32))
    source_id: Mapped[int | None] = mapped_column(BigInteger)

    lines: Mapped[list[MaterialDocumentLine]] = relationship(
        back_populates="document",
        foreign_keys="MaterialDocumentLine.document_id",
        cascade="all, delete-orphan",
        order_by="MaterialDocumentLine.line_no",
    )


class MaterialDocumentLine(IdMixin, Base):
    """Movement line. Carries no timestamps: the document does, and the line is immutable after
    posting except for `reversed_line_id`."""

    __tablename__ = "mm_material_document_line"
    __table_args__ = (
        UniqueConstraint("document_id", "line_no"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("entry_quantity > 0", name="entry_quantity_positive"),
        CheckConstraint("direction IN (1, -1)", name="direction_valid"),
        CheckConstraint("amount_local >= 0", name="amount_local_non_negative"),
        Index("ix_mm_material_document_line_material_id_plant_id", "material_id", "plant_id"),
        Index(
            "ix_mm_material_document_line_po_line_id", "po_line_id", postgresql_where="po_line_id IS NOT NULL"
        ),
        Index("ix_mm_material_document_line_batch_id", "batch_id", postgresql_where="batch_id IS NOT NULL"),
    )

    document_id: Mapped[int] = ref("mm_material_document.id", ondelete="CASCADE")
    line_no: Mapped[int] = mapped_column(Integer)
    movement_type: Mapped[str] = mapped_column(String(4))
    material_id: Mapped[int] = ref("mm_material.id")
    plant_id: Mapped[int] = ref("org_plant.id")
    warehouse_id: Mapped[int] = ref("org_warehouse.id", index=True)
    batch_id: Mapped[int | None] = ref("mm_batch.id")
    stock_type: Mapped[StockType] = mapped_column(enum_type(StockType), default=StockType.UNRESTRICTED)
    quantity: Mapped[Decimal] = mapped_column(Qty)
    direction: Mapped[int] = mapped_column(SmallInteger)
    entry_quantity: Mapped[Decimal] = mapped_column(Qty)
    entry_uom_id: Mapped[int] = ref("org_uom.id")
    amount_local: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    po_line_id: Mapped[int | None] = ref("mm_purchase_order_line.id")
    cost_center_id: Mapped[int | None] = ref("co_cost_center.id")
    internal_order_id: Mapped[int | None] = ref("co_internal_order.id")
    gl_account_id: Mapped[int | None] = ref("fi_gl_account.id")
    dest_plant_id: Mapped[int | None] = ref("org_plant.id")
    dest_warehouse_id: Mapped[int | None] = ref("org_warehouse.id")
    dest_batch_id: Mapped[int | None] = ref("mm_batch.id")
    dest_stock_type: Mapped[StockType | None] = mapped_column(enum_type(StockType))
    text: Mapped[str | None] = mapped_column(String(255))
    reversed_line_id: Mapped[int | None] = ref("mm_material_document_line.id")

    document: Mapped[MaterialDocument] = relationship(back_populates="lines", foreign_keys=[document_id])
    material: Mapped[Material] = relationship(foreign_keys=[material_id])
    plant: Mapped[Plant] = relationship(foreign_keys=[plant_id])
    warehouse: Mapped[Warehouse] = relationship(foreign_keys=[warehouse_id])
    batch: Mapped[Batch | None] = relationship(foreign_keys=[batch_id])
    entry_uom: Mapped[Uom] = relationship(foreign_keys=[entry_uom_id])


class PhysicalInventory(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    __tablename__ = "mm_physical_inventory"
    __table_args__ = (UniqueConstraint("company_id", "number"),)

    number: Mapped[str] = mapped_column(String(24))
    plant_id: Mapped[int] = ref("org_plant.id")
    warehouse_id: Mapped[int] = ref("org_warehouse.id", index=True)
    count_date: Mapped[date] = mapped_column(Date)
    status: Mapped[PhysicalInventoryStatus] = mapped_column(
        enum_type(PhysicalInventoryStatus), default=PhysicalInventoryStatus.OPEN
    )
    note: Mapped[str | None] = mapped_column(Text)
    material_document_id: Mapped[int | None] = ref("mm_material_document.id")

    plant: Mapped[Plant] = relationship(foreign_keys=[plant_id])
    warehouse: Mapped[Warehouse] = relationship(foreign_keys=[warehouse_id])
    lines: Mapped[list[PhysicalInventoryLine]] = relationship(
        back_populates="inventory",
        foreign_keys="PhysicalInventoryLine.inventory_id",
        cascade="all, delete-orphan",
        order_by="PhysicalInventoryLine.line_no",
    )


class PhysicalInventoryLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "mm_physical_inventory_line"
    __table_args__ = (
        UniqueConstraint("inventory_id", "line_no"),
        CheckConstraint("book_qty IS NULL OR book_qty >= 0", name="book_qty_non_negative"),
        CheckConstraint("counted_qty IS NULL OR counted_qty >= 0", name="counted_qty_non_negative"),
    )

    inventory_id: Mapped[int] = ref("mm_physical_inventory.id", ondelete="CASCADE")
    line_no: Mapped[int] = mapped_column(Integer)
    material_id: Mapped[int] = ref("mm_material.id", index=True)
    batch_id: Mapped[int | None] = ref("mm_batch.id")
    stock_type: Mapped[StockType] = mapped_column(enum_type(StockType), default=StockType.UNRESTRICTED)
    book_qty: Mapped[Decimal | None] = mapped_column(Qty)
    counted_qty: Mapped[Decimal | None] = mapped_column(Qty)
    is_counted: Mapped[bool] = mapped_column(Boolean, default=False)

    inventory: Mapped[PhysicalInventory] = relationship(back_populates="lines", foreign_keys=[inventory_id])
    material: Mapped[Material] = relationship(foreign_keys=[material_id])
    batch: Mapped[Batch | None] = relationship(foreign_keys=[batch_id])
