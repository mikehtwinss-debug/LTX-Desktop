"""Purchasing: info records, requisitions, RFQs, quotations, comparisons, purchase orders."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, CompanyMixin, IdMixin, TimestampMixin, VersionMixin, currency_ref, ref
from app.core.types import Money, Pct, Price, Qty, Rate, enum_type

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.co.models import CostCenter
    from app.modules.fi.models.gl import GLAccount, TaxCode
    from app.modules.fi.models.partners import PaymentTerm, Vendor
    from app.modules.mm.models.master import Material
    from app.modules.org.models import Plant, PurchasingGroup, Uom, Warehouse


class RequisitionStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RequisitionLineStatus(enum.StrEnum):
    OPEN = "OPEN"
    IN_RFQ = "IN_RFQ"
    PARTIALLY_ORDERED = "PARTIALLY_ORDERED"
    ORDERED = "ORDERED"
    CLOSED = "CLOSED"


class RfqStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    QUOTED = "QUOTED"
    DECIDED = "DECIDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RfqVendorStatus(enum.StrEnum):
    INVITED = "INVITED"
    QUOTED = "QUOTED"
    DECLINED = "DECLINED"


class TechnicalStatus(enum.StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    COMPLIANT = "COMPLIANT"
    RESERVED = "RESERVED"
    NON_COMPLIANT = "NON_COMPLIANT"


class QuotationStatus(enum.StrEnum):
    ENTERED = "ENTERED"
    SELECTED = "SELECTED"
    PARTIALLY_SELECTED = "PARTIALLY_SELECTED"
    NOT_SELECTED = "NOT_SELECTED"


class OfferStatus(enum.StrEnum):
    OFFERED = "OFFERED"
    NOT_OFFERED = "NOT_OFFERED"
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    UNSPECIFIED = "UNSPECIFIED"


class ComparisonStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ComparisonMarkColor(enum.StrEnum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"


class PurchaseOrderStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AccountAssignment(enum.StrEnum):
    STOCK = "STOCK"
    COST_CENTER = "COST_CENTER"


_PCT_RANGE = "BETWEEN 0 AND 100"


class InfoRecord(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    """Vendor-specific purchasing conditions of a material."""

    __tablename__ = "mm_info_record"
    __audit__ = True
    __table_args__ = (
        Index("ix_mm_info_record_vendor_id_material_id", "vendor_id", "material_id"),
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint(f"discount_pct {_PCT_RANGE}", name="discount_pct_range"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="lead_time_non_negative"),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from", name="validity_range"
        ),
    )

    vendor_id: Mapped[int] = ref("fi_vendor.id")
    material_id: Mapped[int] = ref("mm_material.id", index=True)
    vendor_material_code: Mapped[str | None] = mapped_column(String(64))
    price: Mapped[Decimal] = mapped_column(Price)
    currency_code: Mapped[str] = currency_ref()
    uom_id: Mapped[int] = ref("org_uom.id")
    discount_pct: Mapped[Decimal] = mapped_column(Pct, default=Decimal(0))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    last_po_line_id: Mapped[int | None] = ref("mm_purchase_order_line.id")

    vendor: Mapped[Vendor] = relationship(foreign_keys=[vendor_id])
    material: Mapped[Material] = relationship(foreign_keys=[material_id])
    uom: Mapped[Uom] = relationship(foreign_keys=[uom_id])


class Requisition(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    __tablename__ = "mm_requisition"
    __table_args__ = (
        UniqueConstraint("company_id", "number"),
        Index("ix_mm_requisition_company_id_status", "company_id", "status"),
    )

    number: Mapped[str] = mapped_column(String(24))
    request_date: Mapped[date] = mapped_column(Date)
    requester_id: Mapped[int] = ref("auth_user.id", index=True)
    plant_id: Mapped[int | None] = ref("org_plant.id")
    cost_center_id: Mapped[int | None] = ref("co_cost_center.id")
    project_name: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RequisitionStatus] = mapped_column(
        enum_type(RequisitionStatus), default=RequisitionStatus.DRAFT
    )

    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    plant: Mapped[Plant | None] = relationship(foreign_keys=[plant_id])
    cost_center: Mapped[CostCenter | None] = relationship(foreign_keys=[cost_center_id])
    lines: Mapped[list[RequisitionLine]] = relationship(
        back_populates="requisition",
        foreign_keys="RequisitionLine.requisition_id",
        cascade="all, delete-orphan",
        order_by="RequisitionLine.line_no",
    )


class RequisitionLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "mm_requisition_line"
    __table_args__ = (
        UniqueConstraint("requisition_id", "line_no"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("ordered_qty >= 0", name="ordered_qty_non_negative"),
        CheckConstraint(
            "(estimated_price IS NULL OR estimated_price >= 0) "
            "AND (budget_unit_price IS NULL OR budget_unit_price >= 0)",
            name="prices_non_negative",
        ),
    )

    requisition_id: Mapped[int] = ref("mm_requisition.id", ondelete="CASCADE")
    line_no: Mapped[int] = mapped_column(Integer)
    material_id: Mapped[int | None] = ref("mm_material.id", index=True)
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Qty)
    uom_id: Mapped[int] = ref("org_uom.id")
    required_date: Mapped[date | None] = mapped_column(Date)
    warehouse_id: Mapped[int | None] = ref("org_warehouse.id")
    cost_center_id: Mapped[int | None] = ref("co_cost_center.id")
    estimated_price: Mapped[Decimal | None] = mapped_column(Price)
    currency_code: Mapped[str | None] = currency_ref()
    budget_unit_price: Mapped[Decimal | None] = mapped_column(Price)
    preferred_vendor_id: Mapped[int | None] = ref("fi_vendor.id")
    ordered_qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal(0))
    status: Mapped[RequisitionLineStatus] = mapped_column(
        enum_type(RequisitionLineStatus), default=RequisitionLineStatus.OPEN
    )

    requisition: Mapped[Requisition] = relationship(back_populates="lines", foreign_keys=[requisition_id])
    material: Mapped[Material | None] = relationship(foreign_keys=[material_id])
    uom: Mapped[Uom] = relationship(foreign_keys=[uom_id])
    warehouse: Mapped[Warehouse | None] = relationship(foreign_keys=[warehouse_id])
    cost_center: Mapped[CostCenter | None] = relationship(foreign_keys=[cost_center_id])
    preferred_vendor: Mapped[Vendor | None] = relationship(foreign_keys=[preferred_vendor_id])


class Rfq(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    __tablename__ = "mm_rfq"
    __table_args__ = (
        UniqueConstraint("company_id", "number"),
        Index("ix_mm_rfq_company_id_status", "company_id", "status"),
    )

    number: Mapped[str] = mapped_column(String(24))
    rfq_date: Mapped[date] = mapped_column(Date)
    deadline: Mapped[date | None] = mapped_column(Date)
    project_name: Mapped[str | None] = mapped_column(String(128))
    subject: Mapped[str | None] = mapped_column(String(255))
    requester_name: Mapped[str | None] = mapped_column(String(128))
    requisition_id: Mapped[int | None] = ref("mm_requisition.id", index=True)
    budget_name: Mapped[str | None] = mapped_column(String(128))
    budget_currency: Mapped[str | None] = currency_ref()
    buyer_id: Mapped[int] = ref("auth_user.id")
    status: Mapped[RfqStatus] = mapped_column(enum_type(RfqStatus), default=RfqStatus.DRAFT)

    requisition: Mapped[Requisition | None] = relationship(foreign_keys=[requisition_id])
    buyer: Mapped[User] = relationship(foreign_keys=[buyer_id])
    lines: Mapped[list[RfqLine]] = relationship(
        back_populates="rfq",
        foreign_keys="RfqLine.rfq_id",
        cascade="all, delete-orphan",
        order_by="RfqLine.line_no",
    )
    vendors: Mapped[list[RfqVendor]] = relationship(
        back_populates="rfq",
        foreign_keys="RfqVendor.rfq_id",
        cascade="all, delete-orphan",
        order_by="RfqVendor.id",
    )


class RfqLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "mm_rfq_line"
    __table_args__ = (
        UniqueConstraint("rfq_id", "line_no"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("budget_unit_price IS NULL OR budget_unit_price >= 0", name="budget_non_negative"),
    )

    rfq_id: Mapped[int] = ref("mm_rfq.id", ondelete="CASCADE")
    line_no: Mapped[int] = mapped_column(Integer)
    requisition_line_id: Mapped[int | None] = ref("mm_requisition_line.id", index=True)
    material_id: Mapped[int | None] = ref("mm_material.id")
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Qty)
    uom_id: Mapped[int] = ref("org_uom.id")
    required_date: Mapped[date | None] = mapped_column(Date)
    budget_unit_price: Mapped[Decimal | None] = mapped_column(Price)

    rfq: Mapped[Rfq] = relationship(back_populates="lines", foreign_keys=[rfq_id])
    requisition_line: Mapped[RequisitionLine | None] = relationship(foreign_keys=[requisition_line_id])
    material: Mapped[Material | None] = relationship(foreign_keys=[material_id])
    uom: Mapped[Uom] = relationship(foreign_keys=[uom_id])


class RfqVendor(IdMixin, TimestampMixin, Base):
    __tablename__ = "mm_rfq_vendor"
    __table_args__ = (UniqueConstraint("rfq_id", "vendor_id"),)

    rfq_id: Mapped[int] = ref("mm_rfq.id", ondelete="CASCADE")
    vendor_id: Mapped[int] = ref("fi_vendor.id", index=True)
    status: Mapped[RfqVendorStatus] = mapped_column(
        enum_type(RfqVendorStatus), default=RfqVendorStatus.INVITED
    )

    rfq: Mapped[Rfq] = relationship(back_populates="vendors", foreign_keys=[rfq_id])
    vendor: Mapped[Vendor] = relationship(foreign_keys=[vendor_id])


class Quotation(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    __tablename__ = "mm_quotation"
    __table_args__ = (
        UniqueConstraint("company_id", "number"),
        CheckConstraint(f"discount_pct {_PCT_RANGE}", name="discount_pct_range"),
        CheckConstraint(f"vat_rate {_PCT_RANGE}", name="vat_rate_range"),
        CheckConstraint("freight_amount IS NULL OR freight_amount >= 0", name="freight_non_negative"),
        CheckConstraint(
            "(payment_days IS NULL OR payment_days >= 0) AND (delivery_days IS NULL OR delivery_days >= 0)",
            name="days_non_negative",
        ),
    )

    rfq_id: Mapped[int] = ref("mm_rfq.id", index=True)
    vendor_id: Mapped[int] = ref("fi_vendor.id", index=True)
    number: Mapped[str] = mapped_column(String(24))
    vendor_ref: Mapped[str | None] = mapped_column(String(64))
    quote_date: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    currency_code: Mapped[str] = currency_ref()
    discount_pct: Mapped[Decimal] = mapped_column(Pct, default=Decimal(0))
    vat_rate: Mapped[Decimal] = mapped_column(Pct, default=Decimal(20))
    contact_name: Mapped[str | None] = mapped_column(String(128))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    freight_text: Mapped[str | None] = mapped_column(String(128))
    freight_amount: Mapped[Decimal | None] = mapped_column(Money)
    delivery_place: Mapped[str | None] = mapped_column(String(255))
    payment_text: Mapped[str | None] = mapped_column(String(255))
    payment_days: Mapped[int | None] = mapped_column(Integer)
    delivery_text: Mapped[str | None] = mapped_column(String(255))
    delivery_days: Mapped[int | None] = mapped_column(Integer)
    warranty_text: Mapped[str | None] = mapped_column(String(255))
    technical_status: Mapped[TechnicalStatus] = mapped_column(
        enum_type(TechnicalStatus), default=TechnicalStatus.NOT_EVALUATED
    )
    technical_note: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[QuotationStatus] = mapped_column(
        enum_type(QuotationStatus), default=QuotationStatus.ENTERED
    )

    rfq: Mapped[Rfq] = relationship(foreign_keys=[rfq_id])
    vendor: Mapped[Vendor] = relationship(foreign_keys=[vendor_id])
    lines: Mapped[list[QuotationLine]] = relationship(
        back_populates="quotation",
        foreign_keys="QuotationLine.quotation_id",
        cascade="all, delete-orphan",
        order_by="QuotationLine.id",
    )


class QuotationLine(IdMixin, TimestampMixin, Base):
    """One vendor answer per RFQ line; lines carry no number of their own and follow the RFQ line."""

    __tablename__ = "mm_quotation_line"
    __table_args__ = (
        UniqueConstraint("quotation_id", "rfq_line_id"),
        CheckConstraint("unit_price IS NULL OR unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint(f"discount_pct {_PCT_RANGE}", name="discount_pct_range"),
        CheckConstraint("delivery_days IS NULL OR delivery_days >= 0", name="delivery_days_non_negative"),
    )

    quotation_id: Mapped[int] = ref("mm_quotation.id", ondelete="CASCADE")
    rfq_line_id: Mapped[int] = ref("mm_rfq_line.id", index=True)
    offer_status: Mapped[OfferStatus] = mapped_column(enum_type(OfferStatus), default=OfferStatus.OFFERED)
    unit_price: Mapped[Decimal | None] = mapped_column(Price)
    discount_pct: Mapped[Decimal] = mapped_column(Pct, default=Decimal(0))
    delivery_days: Mapped[int | None] = mapped_column(Integer)
    brand: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(String(255))

    quotation: Mapped[Quotation] = relationship(back_populates="lines", foreign_keys=[quotation_id])
    rfq_line: Mapped[RfqLine] = relationship(foreign_keys=[rfq_line_id])


class QuotationComparison(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    __tablename__ = "mm_quotation_comparison"
    __table_args__ = (UniqueConstraint("company_id", "number"),)

    rfq_id: Mapped[int] = ref("mm_rfq.id", index=True)
    number: Mapped[str] = mapped_column(String(24))
    comparison_date: Mapped[date] = mapped_column(Date)
    comparison_currency: Mapped[str] = currency_ref()
    rates: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ranking: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ComparisonStatus] = mapped_column(
        enum_type(ComparisonStatus), default=ComparisonStatus.DRAFT
    )
    prepared_by_id: Mapped[int] = ref("auth_user.id")

    rfq: Mapped[Rfq] = relationship(foreign_keys=[rfq_id])
    prepared_by: Mapped[User] = relationship(foreign_keys=[prepared_by_id])
    selections: Mapped[list[ComparisonSelection]] = relationship(
        back_populates="comparison",
        foreign_keys="ComparisonSelection.comparison_id",
        cascade="all, delete-orphan",
        order_by="ComparisonSelection.id",
    )
    marks: Mapped[list[ComparisonMark]] = relationship(
        back_populates="comparison",
        foreign_keys="ComparisonMark.comparison_id",
        cascade="all, delete-orphan",
        order_by="ComparisonMark.id",
    )


class ComparisonSelection(IdMixin, TimestampMixin, Base):
    """Award of (part of) an RFQ line to one quotation line."""

    __tablename__ = "mm_comparison_selection"
    __table_args__ = (CheckConstraint("awarded_qty > 0", name="awarded_qty_positive"),)

    comparison_id: Mapped[int] = ref("mm_quotation_comparison.id", ondelete="CASCADE", index=True)
    rfq_line_id: Mapped[int] = ref("mm_rfq_line.id", index=True)
    quotation_line_id: Mapped[int] = ref("mm_quotation_line.id", index=True)
    awarded_qty: Mapped[Decimal] = mapped_column(Qty)
    is_cheapest: Mapped[bool] = mapped_column(Boolean, default=False)
    justification: Mapped[str | None] = mapped_column(Text)

    comparison: Mapped[QuotationComparison] = relationship(
        back_populates="selections", foreign_keys=[comparison_id]
    )
    rfq_line: Mapped[RfqLine] = relationship(foreign_keys=[rfq_line_id])
    quotation_line: Mapped[QuotationLine] = relationship(foreign_keys=[quotation_line_id])


class ComparisonMark(IdMixin, TimestampMixin, Base):
    """Colour mark on a quotation, or on one of its lines when `rfq_line_id` is set."""

    __tablename__ = "mm_comparison_mark"

    comparison_id: Mapped[int] = ref("mm_quotation_comparison.id", ondelete="CASCADE", index=True)
    quotation_id: Mapped[int] = ref("mm_quotation.id", index=True)
    rfq_line_id: Mapped[int | None] = ref("mm_rfq_line.id")
    mark: Mapped[ComparisonMarkColor] = mapped_column(enum_type(ComparisonMarkColor))

    comparison: Mapped[QuotationComparison] = relationship(
        back_populates="marks", foreign_keys=[comparison_id]
    )


class PurchaseOrder(IdMixin, TimestampMixin, CompanyMixin, VersionMixin, Base):
    __tablename__ = "mm_purchase_order"
    __table_args__ = (
        UniqueConstraint("company_id", "number"),
        Index("ix_mm_purchase_order_company_id_status", "company_id", "status"),
        Index("ix_mm_purchase_order_company_id_order_date", "company_id", "order_date"),
        CheckConstraint("exchange_rate > 0", name="exchange_rate_positive"),
        CheckConstraint("revision >= 0", name="revision_non_negative"),
        CheckConstraint(
            "net_total >= 0 AND discount_total >= 0 AND tax_total >= 0 AND gross_total >= 0 "
            "AND net_total_local >= 0",
            name="totals_non_negative",
        ),
    )

    number: Mapped[str] = mapped_column(String(24))
    order_date: Mapped[date] = mapped_column(Date)
    vendor_id: Mapped[int] = ref("fi_vendor.id", index=True)
    buyer_id: Mapped[int] = ref("auth_user.id")
    purchasing_group_id: Mapped[int | None] = ref("org_purchasing_group.id")
    plant_id: Mapped[int] = ref("org_plant.id")
    currency_code: Mapped[str] = currency_ref()
    exchange_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal(1))
    payment_term_id: Mapped[int | None] = ref("fi_payment_term.id")
    payment_text: Mapped[str | None] = mapped_column(String(255))
    delivery_terms: Mapped[str | None] = mapped_column(String(255))
    delivery_address: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        enum_type(PurchaseOrderStatus), default=PurchaseOrderStatus.DRAFT
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comparison_id: Mapped[int | None] = ref("mm_quotation_comparison.id", index=True)
    rfq_id: Mapped[int | None] = ref("mm_rfq.id", index=True)
    net_total: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    discount_total: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    tax_total: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    gross_total: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    net_total_local: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))

    vendor: Mapped[Vendor] = relationship(foreign_keys=[vendor_id])
    buyer: Mapped[User] = relationship(foreign_keys=[buyer_id])
    purchasing_group: Mapped[PurchasingGroup | None] = relationship(foreign_keys=[purchasing_group_id])
    plant: Mapped[Plant] = relationship(foreign_keys=[plant_id])
    payment_term: Mapped[PaymentTerm | None] = relationship(foreign_keys=[payment_term_id])
    lines: Mapped[list[PurchaseOrderLine]] = relationship(
        back_populates="order",
        foreign_keys="PurchaseOrderLine.order_id",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLine.line_no",
    )
    revisions: Mapped[list[PurchaseOrderRevision]] = relationship(
        back_populates="order",
        foreign_keys="PurchaseOrderRevision.order_id",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderRevision.revision",
    )


class PurchaseOrderLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "mm_purchase_order_line"
    __table_args__ = (
        UniqueConstraint("order_id", "line_no"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("base_qty_factor > 0", name="base_qty_factor_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint(f"discount_pct {_PCT_RANGE}", name="discount_pct_range"),
        CheckConstraint("over_delivery_pct >= 0", name="over_delivery_pct_non_negative"),
        CheckConstraint("net_amount >= 0 AND tax_amount >= 0", name="amounts_non_negative"),
        CheckConstraint(
            "received_qty >= 0 AND invoiced_qty >= 0 AND invoiced_amount >= 0 AND received_value_local >= 0",
            name="progress_non_negative",
        ),
    )

    order_id: Mapped[int] = ref("mm_purchase_order.id", ondelete="CASCADE")
    line_no: Mapped[int] = mapped_column(Integer)
    requisition_line_id: Mapped[int | None] = ref("mm_requisition_line.id", index=True)
    quotation_line_id: Mapped[int | None] = ref("mm_quotation_line.id", index=True)
    material_id: Mapped[int | None] = ref("mm_material.id", index=True)
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Qty)
    uom_id: Mapped[int] = ref("org_uom.id")
    base_qty_factor: Mapped[Decimal] = mapped_column(Rate, default=Decimal(1))
    unit_price: Mapped[Decimal] = mapped_column(Price)
    discount_pct: Mapped[Decimal] = mapped_column(Pct, default=Decimal(0))
    net_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    tax_code_id: Mapped[int | None] = ref("fi_tax_code.id")
    tax_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    delivery_date: Mapped[date | None] = mapped_column(Date)
    warehouse_id: Mapped[int | None] = ref("org_warehouse.id")
    account_assignment: Mapped[AccountAssignment] = mapped_column(
        enum_type(AccountAssignment), default=AccountAssignment.STOCK
    )
    cost_center_id: Mapped[int | None] = ref("co_cost_center.id")
    gl_account_id: Mapped[int | None] = ref("fi_gl_account.id")
    received_qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal(0))
    invoiced_qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal(0))
    invoiced_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    received_value_local: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    over_delivery_pct: Mapped[Decimal] = mapped_column(Pct, default=Decimal(0))

    order: Mapped[PurchaseOrder] = relationship(back_populates="lines", foreign_keys=[order_id])
    material: Mapped[Material | None] = relationship(foreign_keys=[material_id])
    uom: Mapped[Uom] = relationship(foreign_keys=[uom_id])
    tax_code: Mapped[TaxCode | None] = relationship(foreign_keys=[tax_code_id])
    warehouse: Mapped[Warehouse | None] = relationship(foreign_keys=[warehouse_id])
    cost_center: Mapped[CostCenter | None] = relationship(foreign_keys=[cost_center_id])
    gl_account: Mapped[GLAccount | None] = relationship(foreign_keys=[gl_account_id])


class PurchaseOrderRevision(IdMixin, TimestampMixin, Base):
    """Snapshot and stored PDF of an approved purchase order revision."""

    __tablename__ = "mm_purchase_order_revision"
    __table_args__ = (UniqueConstraint("order_id", "revision"),)

    order_id: Mapped[int] = ref("mm_purchase_order.id", ondelete="CASCADE")
    revision: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    pdf: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    reason: Mapped[str | None] = mapped_column(String(255))

    order: Mapped[PurchaseOrder] = relationship(back_populates="revisions", foreign_keys=[order_id])
