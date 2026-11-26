"""Material master, valuation classes and account determination."""

from __future__ import annotations

import enum
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, CompanyMixin, IdMixin, TimestampMixin, VersionMixin, ref
from app.core.types import Money, Price, Qty, Rate, enum_type

if TYPE_CHECKING:
    from app.modules.fi.models.gl import GLAccount, TaxCode
    from app.modules.org.models import Plant, Uom, Warehouse


class AccountKey(enum.StrEnum):
    STOCK = "STOCK"
    GR_IR = "GR_IR"
    PRICE_DIFF = "PRICE_DIFF"
    CONSUMPTION = "CONSUMPTION"
    SCRAP = "SCRAP"
    INVENTORY_GAIN = "INVENTORY_GAIN"
    INVENTORY_LOSS = "INVENTORY_LOSS"
    INITIAL_STOCK = "INITIAL_STOCK"
    RECEIPT_OTHER = "RECEIPT_OTHER"


class MaterialType(enum.StrEnum):
    HAMMADDE = "HAMMADDE"
    YARI_MAMUL = "YARI_MAMUL"
    MAMUL = "MAMUL"
    TICARI_MAL = "TICARI_MAL"
    SARF = "SARF"
    HIZMET = "HIZMET"


class ValuationMethod(enum.StrEnum):
    MAP = "MAP"  # moving average price
    STD = "STD"  # standard price


class MaterialGroup(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "mm_material_group"
    __audit__ = True
    __table_args__ = (UniqueConstraint("company_id", "code"),)

    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))


class ValuationClass(IdMixin, TimestampMixin, CompanyMixin, Base):
    __tablename__ = "mm_valuation_class"
    __audit__ = True
    __table_args__ = (UniqueConstraint("company_id", "code"),)

    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))


class AccountDetermination(IdMixin, TimestampMixin, CompanyMixin, Base):
    """GL account per posting key; the most specific (valuation class, modifier) match wins."""

    __tablename__ = "mm_account_determination"
    __audit__ = True
    __table_args__ = (
        Index(
            "uq_mm_account_determination_key",
            "company_id",
            "key",
            "valuation_class_id",
            "modifier",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    key: Mapped[AccountKey] = mapped_column(enum_type(AccountKey))
    valuation_class_id: Mapped[int | None] = ref("mm_valuation_class.id")
    modifier: Mapped[str | None] = mapped_column(String(32))
    gl_account_id: Mapped[int] = ref("fi_gl_account.id")

    valuation_class: Mapped[ValuationClass | None] = relationship(foreign_keys=[valuation_class_id])
    gl_account: Mapped[GLAccount] = relationship(foreign_keys=[gl_account_id])


class Material(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    __tablename__ = "mm_material"
    __audit__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        UniqueConstraint("company_id", "barcode"),
        CheckConstraint("order_uom_factor > 0", name="order_uom_factor_positive"),
        CheckConstraint("shelf_life_days IS NULL OR shelf_life_days >= 0", name="shelf_life_non_negative"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="lead_time_non_negative"),
    )

    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    material_type: Mapped[MaterialType] = mapped_column(enum_type(MaterialType))
    material_group_id: Mapped[int | None] = ref("mm_material_group.id", index=True)
    base_uom_id: Mapped[int] = ref("org_uom.id")
    order_uom_id: Mapped[int | None] = ref("org_uom.id")
    order_uom_factor: Mapped[Decimal] = mapped_column(Rate, default=Decimal(1))
    valuation_class_id: Mapped[int | None] = ref("mm_valuation_class.id")
    valuation_method: Mapped[ValuationMethod] = mapped_column(
        enum_type(ValuationMethod), default=ValuationMethod.MAP
    )
    purchase_tax_code_id: Mapped[int | None] = ref("fi_tax_code.id")
    is_stock_managed: Mapped[bool] = mapped_column(Boolean, default=True)
    is_batch_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_serial_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer)
    barcode: Mapped[str | None] = mapped_column(String(64))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    material_group: Mapped[MaterialGroup | None] = relationship(foreign_keys=[material_group_id])
    base_uom: Mapped[Uom] = relationship(foreign_keys=[base_uom_id])
    order_uom: Mapped[Uom | None] = relationship(foreign_keys=[order_uom_id])
    valuation_class: Mapped[ValuationClass | None] = relationship(foreign_keys=[valuation_class_id])
    purchase_tax_code: Mapped[TaxCode | None] = relationship(foreign_keys=[purchase_tax_code_id])
    plants: Mapped[list[MaterialPlant]] = relationship(
        back_populates="material",
        foreign_keys="MaterialPlant.material_id",
        cascade="all, delete-orphan",
        order_by="MaterialPlant.id",
    )


class MaterialPlant(IdMixin, TimestampMixin, VersionMixin, Base):
    """Plant data and the valuation row of a material; locked for every valued movement."""

    __tablename__ = "mm_material_plant"
    __table_args__ = (
        UniqueConstraint("material_id", "plant_id"),
        CheckConstraint("stock_qty >= 0", name="stock_qty_non_negative"),
        CheckConstraint("stock_value >= 0", name="stock_value_non_negative"),
        CheckConstraint("moving_avg_price >= 0 AND standard_price >= 0", name="prices_non_negative"),
        CheckConstraint(
            "min_stock >= 0 AND reorder_point >= 0 AND reorder_qty >= 0 "
            "AND (max_stock IS NULL OR max_stock >= 0)",
            name="planning_non_negative",
        ),
    )

    material_id: Mapped[int] = ref("mm_material.id", ondelete="CASCADE")
    plant_id: Mapped[int] = ref("org_plant.id", index=True)
    stock_qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal(0))
    stock_value: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    moving_avg_price: Mapped[Decimal] = mapped_column(Price, default=Decimal(0))
    standard_price: Mapped[Decimal] = mapped_column(Price, default=Decimal(0))
    min_stock: Mapped[Decimal] = mapped_column(Qty, default=Decimal(0))
    reorder_point: Mapped[Decimal] = mapped_column(Qty, default=Decimal(0))
    reorder_qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal(0))
    max_stock: Mapped[Decimal | None] = mapped_column(Qty)
    default_warehouse_id: Mapped[int | None] = ref("org_warehouse.id")

    material: Mapped[Material] = relationship(back_populates="plants", foreign_keys=[material_id])
    plant: Mapped[Plant] = relationship(foreign_keys=[plant_id])
    default_warehouse: Mapped[Warehouse | None] = relationship(foreign_keys=[default_warehouse_id])
