"""Journal posting engine: the only place where journal entries are created or reversed.

`post_entry` validates an entry against the posting rules and stores it; every rule has its own
error code. `reverse_entry` books the exact mirror of a posted entry. Both lock what they depend on
(period, number range, the reversed entry and its lines) until the surrounding transaction ends.

Decisions beyond the wording of the contract:
- Amounts must already be rounded to two decimals; the engine never rounds a document amount.
- Every id on a line must belong to the active company (cost objects, tax code, payment term,
  material, plant) and referenced cost objects must be active on the posting date.
- A reversal copies the original lines with swapped sides and identical local amounts and does not
  re-check master data, so an entry can always be undone while a posting period is open. The open
  items of the original and of the mirror are closed against each other.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import joinedload

from app.core import audit
from app.core.context import RequestContext
from app.core.db import utcnow
from app.core.errors import AppError, Conflict, NotFound, ValidationFailed
from app.core.numbering import next_number
from app.core.periods import assert_period_open
from app.core.rates import get_rate, local_currency
from app.core.types import q_money, q_rate
from app.modules.co.models import CostCenter, InternalOrder, ProfitCenter
from app.modules.fi import JOURNAL_NUMBER_RANGE
from app.modules.fi.models.gl import (
    FiDocType,
    GLAccount,
    JournalEntry,
    JournalLine,
    JournalStatus,
    Period,
    PeriodStatus,
    ReconType,
    Side,
    TaxCode,
)
from app.modules.fi.models.partners import Customer, PaymentTerm, Vendor
from app.modules.mm.models.master import Material
from app.modules.org.models import Currency, Plant, Uom

_ZERO = Decimal(0)
_ROUNDING_UNIT = Decimal("0.01")
_REASON_MAX_LENGTH = 255
_ENTITY = JournalEntry.__tablename__


@dataclass(frozen=True, slots=True, kw_only=True)
class LineIn:
    account: str | int | None = None  # GL code or id; None → derived from vendor/customer recon account
    debit: Decimal = Decimal(0)  # document currency; exactly one of debit/credit may be non-zero
    credit: Decimal = Decimal(0)
    local_debit: Decimal | None = None  # explicit local amounts (FX-exact postings, local-only FX lines)
    local_credit: Decimal | None = None
    vendor_id: int | None = None
    customer_id: int | None = None
    cost_center_id: int | None = None
    internal_order_id: int | None = None
    profit_center_id: int | None = None
    tax_code_id: int | None = None
    tax_base: Decimal | None = None
    is_tax_line: bool = False
    due_date: date | None = None
    payment_term_id: int | None = None
    payment_block: bool = False
    material_id: int | None = None
    plant_id: int | None = None
    quantity: Decimal | None = None
    uom_id: int | None = None
    assignment: str | None = None
    text: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryIn:
    doc_type: FiDocType
    posting_date: date
    document_date: date | None = None
    currency_code: str | None = None  # default: company currency
    exchange_rate: Decimal | None = None  # default: looked up for posting_date
    reference: str | None = None
    header_text: str | None = None
    source_type: str | None = None  # e.g. "MM_MATDOC", "MM_SINV", "FI_INVOICE", "FI_PAYMENT", "FI_CLEARING"
    source_id: int | None = None
    lines: Sequence[LineIn]


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """Local-currency turnover of an account; `balance` is positive for a debit balance."""

    debit: Decimal
    credit: Decimal

    @property
    def balance(self) -> Decimal:
        return self.debit - self.credit


@dataclass(slots=True)
class _Draft:
    """A line while it is being validated."""

    index: int
    line: LineIn
    side: Side
    amount: Decimal
    amount_local: Decimal
    explicit_local: bool
    account: GLAccount | None = None
    partner: Vendor | Customer | None = None


@dataclass(slots=True)
class _Lookup:
    """Master data referenced by the lines, restricted to the active company."""

    accounts_by_id: dict[int, GLAccount]
    accounts_by_code: dict[str, GLAccount]
    vendors: dict[int, Vendor]
    customers: dict[int, Customer]
    cost_centers: dict[int, CostCenter]
    internal_orders: dict[int, InternalOrder]
    profit_centers: dict[int, ProfitCenter]
    payment_terms: dict[int, PaymentTerm]
    tax_codes: set[int]
    materials: set[int]
    plants: set[int]
    uoms: set[int]


def _line_error(code: str, index: int, message: str, **details: Any) -> AppError:
    return AppError(code, f"{index}. satır: {message}", details={"line": index, **details})


# --- accounts and balances -------------------------------------------------------------------------


def get_account(ctx: RequestContext, code_or_id: str | int) -> GLAccount:
    """GL account of the active company by code (`"320.01"`) or id; raises `ACCOUNT_NOT_FOUND`."""
    stmt = select(GLAccount).where(GLAccount.company_id == ctx.company_id)
    if isinstance(code_or_id, str):
        stmt = stmt.where(GLAccount.code == code_or_id)
    else:
        stmt = stmt.where(GLAccount.id == code_or_id)
    account = ctx.db.scalar(stmt)
    if account is None:
        raise AppError(
            "ACCOUNT_NOT_FOUND", f"Hesap bulunamadı: {code_or_id}", details={"account": code_or_id}
        )
    return account


def account_balance(
    ctx: RequestContext,
    account: GLAccount | str | int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> AccountBalance:
    """Debit and credit turnover (local currency) of an account and all of its sub-accounts for
    postings dated within `date_from`..`date_to` (both inclusive, both optional)."""
    if not isinstance(account, GLAccount):
        account = get_account(ctx, account)
    elif account.company_id != ctx.company_id:
        raise AppError(
            "ACCOUNT_NOT_FOUND", f"Hesap bulunamadı: {account.code}", details={"account": account.code}
        )

    def turnover(side: Side) -> Any:
        return func.coalesce(func.sum(case((JournalLine.side == side, JournalLine.amount_local), else_=0)), 0)

    stmt = (
        select(turnover(Side.DEBIT), turnover(Side.CREDIT))
        .join(GLAccount, GLAccount.id == JournalLine.gl_account_id)
        .where(
            JournalLine.company_id == ctx.company_id,
            or_(GLAccount.id == account.id, GLAccount.code.startswith(f"{account.code}.", autoescape=True)),
        )
    )
    if date_from is not None:
        stmt = stmt.where(JournalLine.posting_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(JournalLine.posting_date <= date_to)
    debit, credit = ctx.db.execute(stmt).one()
    return AccountBalance(debit=q_money(debit), credit=q_money(credit))


# --- posting ---------------------------------------------------------------------------------------


def _exchange_rate(ctx: RequestContext, entry: EntryIn, currency: str, local: str) -> Decimal:
    if currency == local:
        if entry.exchange_rate is not None and Decimal(entry.exchange_rate) != 1:
            raise AppError(
                "EXCHANGE_RATE_INVALID",
                f"{local} cinsinden kayıtlarda kur 1 olmalıdır",
                details={"currency_code": currency},
            )
        return Decimal(1)
    if ctx.db.scalar(select(Currency.id).where(Currency.code == currency)) is None:
        raise AppError(
            "CURRENCY_NOT_FOUND", f"Para birimi tanımlı değil: {currency}", details={"currency_code": currency}
        )
    if entry.exchange_rate is None:
        return get_rate(ctx, currency, entry.posting_date)
    rate = Decimal(entry.exchange_rate)
    if not rate.is_finite() or q_rate(rate) <= 0:
        raise AppError("EXCHANGE_RATE_INVALID", "Kur sıfırdan büyük olmalıdır", details={"currency_code": currency})
    return q_rate(rate)


def _money(index: int, value: Decimal | None) -> Decimal | None:
    """A line amount as a non-negative two-decimal `Decimal`; anything else is refused, never rounded."""
    if value is None:
        return None
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0:
        raise _line_error("LINE_AMOUNT_INVALID", index, "Tutar negatif olamaz")
    if amount != q_money(amount):
        raise _line_error("LINE_AMOUNT_INVALID", index, "Tutar en fazla iki ondalık basamak içerebilir")
    return q_money(amount)


def _draft(index: int, line: LineIn, rate: Decimal, in_local_currency: bool) -> _Draft:
    debit = _money(index, line.debit) or _ZERO
    credit = _money(index, line.credit) or _ZERO
    local_debit = _money(index, line.local_debit)
    local_credit = _money(index, line.local_credit)

    if debit > 0 and credit > 0:
        raise _line_error("LINE_AMOUNT_INVALID", index, "Borç ve alacak aynı satırda birlikte girilemez")
    if debit == 0 and credit == 0:
        # Local-only line: no document amount, explicit local amount on exactly one side.
        if bool(local_debit) == bool(local_credit):
            raise _line_error("LINE_AMOUNT_INVALID", index, "Borç veya alacak tutarı girilmelidir")
        side = Side.DEBIT if local_debit else Side.CREDIT
        draft = _Draft(index, line, side, _ZERO, local_debit or local_credit or _ZERO, explicit_local=True)
    else:
        side = Side.DEBIT if debit > 0 else Side.CREDIT
        amount = debit or credit
        explicit, opposite = (local_debit, local_credit) if side is Side.DEBIT else (local_credit, local_debit)
        if opposite:
            raise _line_error(
                "LINE_AMOUNT_INVALID", index, "Yerel tutar, belge tutarıyla aynı tarafta girilmelidir"
            )
        amount_local = explicit if explicit is not None else q_money(amount * rate)
        draft = _Draft(index, line, side, amount, amount_local, explicit_local=explicit is not None)

    if in_local_currency and draft.amount_local != draft.amount:
        raise _line_error(
            "LINE_AMOUNT_INVALID", index, "Yerel para birimindeki kayıtlarda yerel tutar belge tutarına eşit olmalıdır"
        )
    return draft


def _ids(lines: Iterable[LineIn], attribute: str) -> set[int]:
    return {value for line in lines if (value := getattr(line, attribute)) is not None}


def _owned[T](ctx: RequestContext, model: type[T], ids: set[int], *options: Any) -> dict[int, T]:
    if not ids:
        return {}
    stmt = select(model).where(model.company_id == ctx.company_id, model.id.in_(ids)).options(*options)
    return {row.id: row for row in ctx.db.scalars(stmt)}


def _owned_ids(ctx: RequestContext, model: Any, ids: set[int]) -> set[int]:
    if not ids:
        return set()
    return set(ctx.db.scalars(select(model.id).where(model.company_id == ctx.company_id, model.id.in_(ids))))


def _load_references(ctx: RequestContext, lines: Sequence[LineIn]) -> _Lookup:
    account_ids = {line.account for line in lines if isinstance(line.account, int)}
    account_codes = {line.account for line in lines if isinstance(line.account, str)}
    accounts: list[GLAccount] = []
    if account_ids or account_codes:
        accounts = list(
            ctx.db.scalars(
                select(GLAccount).where(
                    GLAccount.company_id == ctx.company_id,
                    or_(GLAccount.id.in_(account_ids), GLAccount.code.in_(account_codes)),
                )
            )
        )
    uom_ids = _ids(lines, "uom_id")
    return _Lookup(
        accounts_by_id={account.id: account for account in accounts},
        accounts_by_code={account.code: account for account in accounts},
        vendors=_owned(
            ctx,
            Vendor,
            _ids(lines, "vendor_id"),
            joinedload(Vendor.recon_account),
            joinedload(Vendor.payment_term),
        ),
        customers=_owned(
            ctx,
            Customer,
            _ids(lines, "customer_id"),
            joinedload(Customer.recon_account),
            joinedload(Customer.payment_term),
        ),
        cost_centers=_owned(ctx, CostCenter, _ids(lines, "cost_center_id")),
        internal_orders=_owned(ctx, InternalOrder, _ids(lines, "internal_order_id")),
        profit_centers=_owned(ctx, ProfitCenter, _ids(lines, "profit_center_id")),
        payment_terms=_owned(ctx, PaymentTerm, _ids(lines, "payment_term_id")),
        tax_codes=_owned_ids(ctx, TaxCode, _ids(lines, "tax_code_id")),
        materials=_owned_ids(ctx, Material, _ids(lines, "material_id")),
        plants=_owned_ids(ctx, Plant, _ids(lines, "plant_id")),
        uoms=set(ctx.db.scalars(select(Uom.id).where(Uom.id.in_(uom_ids)))) if uom_ids else set(),
    )


def _resolve_partner(lookup: _Lookup, draft: _Draft) -> None:
    line = draft.line
    if line.vendor_id is not None and line.customer_id is not None:
        raise _line_error(
            "RECON_ACCOUNT_MISMATCH", draft.index, "Bir satırda hem satıcı hem müşteri bulunamaz"
        )
    if line.vendor_id is not None:
        draft.partner = lookup.vendors.get(line.vendor_id)
        if draft.partner is None:
            raise _line_error("PARTNER_NOT_FOUND", draft.index, "Satıcı bulunamadı", vendor_id=line.vendor_id)
    elif line.customer_id is not None:
        draft.partner = lookup.customers.get(line.customer_id)
        if draft.partner is None:
            raise _line_error(
                "PARTNER_NOT_FOUND", draft.index, "Müşteri bulunamadı", customer_id=line.customer_id
            )


def _resolve_account(lookup: _Lookup, draft: _Draft) -> GLAccount:
    line = draft.line
    if line.account is None:
        if draft.partner is None:
            raise _line_error("ACCOUNT_REQUIRED", draft.index, "Hesap belirtilmelidir")
        account = draft.partner.recon_account
    else:
        found = (
            lookup.accounts_by_code.get(line.account)
            if isinstance(line.account, str)
            else lookup.accounts_by_id.get(line.account)
        )
        if found is None:
            raise _line_error(
                "ACCOUNT_NOT_FOUND", draft.index, f"Hesap bulunamadı: {line.account}", account=line.account
            )
        account = found
    if not account.is_postable:
        raise _line_error(
            "ACCOUNT_NOT_POSTABLE",
            draft.index,
            f"{account.code} hesabına doğrudan kayıt yapılamaz; alt hesap kullanılmalıdır",
            account=account.code,
        )
    if account.is_blocked:
        raise _line_error(
            "ACCOUNT_BLOCKED", draft.index, f"{account.code} hesabı kayıtlara kapalıdır", account=account.code
        )

    if isinstance(draft.partner, Vendor):
        expected = ReconType.VENDOR
    elif isinstance(draft.partner, Customer):
        expected = ReconType.CUSTOMER
    else:
        expected = ReconType.NONE
    if account.recon_type is not expected:
        if account.recon_type is ReconType.VENDOR:
            message = f"{account.code} satıcı mutabakat hesabıdır; satırda satıcı belirtilmelidir"
        elif account.recon_type is ReconType.CUSTOMER:
            message = f"{account.code} müşteri mutabakat hesabıdır; satırda müşteri belirtilmelidir"
        elif expected is ReconType.VENDOR:
            message = f"Satıcı yalnızca satıcı mutabakat hesabına kaydedilebilir ({account.code} değil)"
        else:
            message = f"Müşteri yalnızca müşteri mutabakat hesabına kaydedilebilir ({account.code} değil)"
        raise _line_error("RECON_ACCOUNT_MISMATCH", draft.index, message, account=account.code)
    return account


def _check_cost_objects(lookup: _Lookup, draft: _Draft, posting_date: date) -> None:
    line, index = draft.line, draft.index
    cost_center = internal_order = None
    if line.cost_center_id is not None:
        cost_center = lookup.cost_centers.get(line.cost_center_id)
        if cost_center is None:
            raise _line_error("COST_OBJECT_NOT_FOUND", index, "Masraf yeri bulunamadı")
        valid = (cost_center.valid_from is None or cost_center.valid_from <= posting_date) and (
            cost_center.valid_to is None or cost_center.valid_to >= posting_date
        )
        if not (cost_center.is_active and valid):
            raise _line_error(
                "COST_OBJECT_INACTIVE",
                index,
                f"{cost_center.code} masraf yeri kayıt tarihinde aktif değil",
                cost_center=cost_center.code,
            )
    if line.internal_order_id is not None:
        internal_order = lookup.internal_orders.get(line.internal_order_id)
        if internal_order is None:
            raise _line_error("COST_OBJECT_NOT_FOUND", index, "İç sipariş bulunamadı")
        if not internal_order.is_active:
            raise _line_error(
                "COST_OBJECT_INACTIVE",
                index,
                f"{internal_order.code} iç siparişi aktif değil",
                internal_order=internal_order.code,
            )
    if line.profit_center_id is not None:
        profit_center = lookup.profit_centers.get(line.profit_center_id)
        if profit_center is None:
            raise _line_error("COST_OBJECT_NOT_FOUND", index, "Kâr merkezi bulunamadı")
        if not profit_center.is_active:
            raise _line_error(
                "COST_OBJECT_INACTIVE",
                index,
                f"{profit_center.code} kâr merkezi aktif değil",
                profit_center=profit_center.code,
            )
    account = draft.account
    if account is not None and account.requires_cost_center and cost_center is None and internal_order is None:
        raise _line_error(
            "COST_OBJECT_REQUIRED",
            index,
            f"{account.code} hesabı için masraf yeri veya iç sipariş zorunludur",
            account=account.code,
        )


def _check_other_references(lookup: _Lookup, draft: _Draft) -> None:
    line = draft.line
    checks = (
        ("tax_code_id", line.tax_code_id, lookup.tax_codes, "Vergi kodu bulunamadı"),
        ("payment_term_id", line.payment_term_id, lookup.payment_terms, "Ödeme koşulu bulunamadı"),
        ("material_id", line.material_id, lookup.materials, "Malzeme bulunamadı"),
        ("plant_id", line.plant_id, lookup.plants, "İşyeri bulunamadı"),
        ("uom_id", line.uom_id, lookup.uoms, "Ölçü birimi bulunamadı"),
    )
    for field, value, known, message in checks:
        if value is not None and value not in known:
            raise _line_error("LINE_REFERENCE_INVALID", draft.index, message, field=field)


def _signed_total(drafts: Sequence[_Draft], attribute: str) -> Decimal:
    return sum(
        (
            getattr(draft, attribute) if draft.side is Side.DEBIT else -getattr(draft, attribute)
            for draft in drafts
        ),
        _ZERO,
    )


def _not_balanced(currency: str, difference: Decimal) -> AppError:
    return AppError(
        "ENTRY_NOT_BALANCED",
        f"Borç ve alacak toplamları eşit değil ({currency} farkı: {abs(difference)})",
        details={"currency_code": currency, "difference": str(difference)},
    )


def _balance(drafts: Sequence[_Draft], currency: str, local: str) -> None:
    """Check that debits equal credits in both currencies.

    A local difference that can only come from converting line by line (no explicit local amount,
    at most 0.01 per line) is absorbed by the largest line.
    """
    difference = _signed_total(drafts, "amount")
    if difference != 0:
        raise _not_balanced(currency, difference)
    local_difference = _signed_total(drafts, "amount_local")
    if local_difference == 0:
        return
    if any(draft.explicit_local for draft in drafts) or abs(local_difference) > _ROUNDING_UNIT * len(drafts):
        raise _not_balanced(local, local_difference)
    largest = max(drafts, key=lambda draft: draft.amount_local)
    adjusted = largest.amount_local + (-local_difference if largest.side is Side.DEBIT else local_difference)
    if adjusted < 0:
        raise _not_balanced(local, local_difference)
    largest.amount_local = adjusted


def _journal_line(ctx: RequestContext, entry: EntryIn, lookup: _Lookup, draft: _Draft, rate: Decimal) -> JournalLine:
    line, partner = draft.line, draft.partner
    payment_term_id = line.payment_term_id
    due_date = line.due_date
    if partner is not None and due_date is None:
        # Rule 7: the due date follows the payment term (the line's, else the partner's own).
        term = lookup.payment_terms[payment_term_id] if payment_term_id is not None else partner.payment_term
        payment_term_id = term.id if term is not None else None
        due_date = entry.posting_date + timedelta(days=term.days if term is not None else 0)
    return JournalLine(
        line_no=draft.index,
        company_id=ctx.company_id,
        posting_date=entry.posting_date,
        gl_account_id=draft.account.id,
        side=draft.side,
        amount=draft.amount,
        amount_local=draft.amount_local,
        vendor_id=line.vendor_id,
        customer_id=line.customer_id,
        cost_center_id=line.cost_center_id,
        internal_order_id=line.internal_order_id,
        profit_center_id=line.profit_center_id,
        tax_code_id=line.tax_code_id,
        tax_base_local=q_money(Decimal(line.tax_base) * rate) if line.tax_base is not None else None,
        is_tax_line=line.is_tax_line,
        due_date=due_date,
        payment_term_id=payment_term_id,
        payment_block=line.payment_block,
        material_id=line.material_id,
        plant_id=line.plant_id,
        quantity=line.quantity,
        uom_id=line.uom_id,
        assignment=line.assignment,
        text=line.text,
        is_open_item=partner is not None,
        open_amount=draft.amount if partner is not None else _ZERO,
        open_amount_local=draft.amount_local if partner is not None else _ZERO,
    )


def post_entry(ctx: RequestContext, entry: EntryIn) -> JournalEntry:
    """Validate and store a journal entry; returns it flushed, with number and lines.

    Error codes: `PERIOD_MISSING`, `PERIOD_CLOSED`, `CURRENCY_NOT_FOUND`, `RATE_MISSING`,
    `EXCHANGE_RATE_INVALID`, `ENTRY_TOO_FEW_LINES`, `LINE_AMOUNT_INVALID`, `ACCOUNT_REQUIRED`,
    `ACCOUNT_NOT_FOUND`, `ACCOUNT_NOT_POSTABLE`, `ACCOUNT_BLOCKED`, `PARTNER_NOT_FOUND`,
    `RECON_ACCOUNT_MISMATCH`, `COST_OBJECT_NOT_FOUND`, `COST_OBJECT_INACTIVE`, `COST_OBJECT_REQUIRED`,
    `LINE_REFERENCE_INVALID`, `ENTRY_NOT_BALANCED`.
    """
    period = assert_period_open(ctx, entry.posting_date)
    local = local_currency(ctx)
    currency = entry.currency_code or local
    rate = _exchange_rate(ctx, entry, currency, local)
    if len(entry.lines) < 2:
        raise AppError("ENTRY_TOO_FEW_LINES", "Yevmiye kaydı en az iki satırdan oluşmalıdır")

    drafts = [
        _draft(index, line, rate, currency == local) for index, line in enumerate(entry.lines, start=1)
    ]
    lookup = _load_references(ctx, entry.lines)
    for draft in drafts:
        _resolve_partner(lookup, draft)
        draft.account = _resolve_account(lookup, draft)
        _check_cost_objects(lookup, draft, entry.posting_date)
        _check_other_references(lookup, draft)
    _balance(drafts, currency, local)

    journal = JournalEntry(
        company_id=ctx.company_id,
        fiscal_year=period.year,
        period=period.period,
        # Taken last: the number range stays locked until the transaction ends.
        number=next_number(ctx, JOURNAL_NUMBER_RANGE, year=period.year),
        doc_type=entry.doc_type,
        posting_date=entry.posting_date,
        document_date=entry.document_date or entry.posting_date,
        reference=entry.reference,
        header_text=entry.header_text,
        currency_code=currency,
        exchange_rate=rate,
        status=JournalStatus.POSTED,
        is_reversal=False,
        source_type=entry.source_type,
        source_id=entry.source_id,
        total_local=sum((draft.amount_local for draft in drafts if draft.side is Side.DEBIT), _ZERO),
        lines=[_journal_line(ctx, entry, lookup, draft, rate) for draft in drafts],
    )
    ctx.db.add(journal)
    ctx.db.flush()
    return journal


# --- reversal --------------------------------------------------------------------------------------


def _is_untouched(line: JournalLine) -> bool:
    return (
        line.cleared_at is None
        and line.open_amount == line.amount
        and line.open_amount_local == line.amount_local
    )


def _reversal_date(ctx: RequestContext, original: JournalEntry, requested: date | None) -> date:
    """The requested date, else the original posting date while its period is open, else today."""
    if requested is None:
        status = ctx.db.scalar(
            select(Period.status).where(
                Period.company_id == ctx.company_id,
                Period.start_date <= original.posting_date,
                Period.end_date >= original.posting_date,
            )
        )
        requested = original.posting_date if status is PeriodStatus.OPEN else date.today()
    if requested < original.posting_date:
        raise AppError(
            "REVERSAL_DATE_INVALID",
            "Ters kayıt tarihi, iptal edilen kaydın tarihinden önce olamaz",
            details={"posting_date": original.posting_date.isoformat()},
        )
    return requested


def reverse_entry(
    ctx: RequestContext,
    entry_id: int,
    *,
    reason: str,
    posting_date: date | None = None,
    from_source: bool = False,
) -> JournalEntry:
    """Post the mirror of an entry, link both and mark the original `REVERSED`; returns the mirror.

    Without `posting_date` the mirror is dated like the original while that period is open, and
    today otherwise. Entries created for a source document (`source_type`) are only reversed by
    their owning module, which passes `from_source=True`.

    Error codes: `JOURNAL_ENTRY_NOT_FOUND`, `REVERSAL_REASON_REQUIRED`, `ALREADY_REVERSED`,
    `REVERSAL_NOT_REVERSIBLE`, `REVERSE_VIA_SOURCE`, `HAS_CLEARED_ITEMS`, `REVERSAL_DATE_INVALID`,
    `PERIOD_MISSING`, `PERIOD_CLOSED`.
    """
    reason = reason.strip()
    if not reason or len(reason) > _REASON_MAX_LENGTH:
        message = f"İptal nedeni yazılmalıdır (en fazla {_REASON_MAX_LENGTH} karakter)"
        raise ValidationFailed("REVERSAL_REASON_REQUIRED", message, details={"fields": {"reason": message}})
    original = ctx.db.scalar(
        select(JournalEntry)
        .where(JournalEntry.id == entry_id, JournalEntry.company_id == ctx.company_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if original is None:
        raise NotFound("JOURNAL_ENTRY_NOT_FOUND", "Yevmiye kaydı bulunamadı")
    if original.status is JournalStatus.REVERSED:
        raise Conflict("ALREADY_REVERSED", f"{original.number} numaralı kayıt daha önce iptal edilmiş")
    if original.is_reversal:
        raise Conflict("REVERSAL_NOT_REVERSIBLE", "Ters kayıtlar iptal edilemez")
    if original.source_type is not None and not from_source:
        raise Conflict(
            "REVERSE_VIA_SOURCE",
            "Bu kayıt bir kaynak belgeden oluşmuştur; iptal işlemi kaynak belge üzerinden yapılmalıdır",
            details={"source_type": original.source_type, "source_id": original.source_id},
        )
    # Open items are changed by clearing; lock them so the check below cannot race with a payment.
    lines = ctx.db.scalars(
        select(JournalLine)
        .where(JournalLine.entry_id == original.id)
        .order_by(JournalLine.line_no)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    if any(line.is_open_item and not _is_untouched(line) for line in lines):
        raise Conflict(
            "HAS_CLEARED_ITEMS",
            "Kayıtta kapatılmış (ödenmiş veya mahsup edilmiş) kalemler var; önce kapatma işlemi geri alınmalıdır",
        )
    reversal_date = _reversal_date(ctx, original, posting_date)
    period = assert_period_open(ctx, reversal_date)

    now = utcnow()
    mirror_lines = []
    for line in lines:
        mirror_lines.append(
            JournalLine(
                line_no=line.line_no,
                company_id=line.company_id,
                posting_date=reversal_date,
                gl_account_id=line.gl_account_id,
                side=Side.CREDIT if line.side is Side.DEBIT else Side.DEBIT,
                amount=line.amount,
                amount_local=line.amount_local,
                vendor_id=line.vendor_id,
                customer_id=line.customer_id,
                cost_center_id=line.cost_center_id,
                internal_order_id=line.internal_order_id,
                profit_center_id=line.profit_center_id,
                tax_code_id=line.tax_code_id,
                tax_base_local=line.tax_base_local,
                is_tax_line=line.is_tax_line,
                due_date=line.due_date,
                payment_term_id=line.payment_term_id,
                payment_block=False,
                material_id=line.material_id,
                plant_id=line.plant_id,
                quantity=line.quantity,
                uom_id=line.uom_id,
                assignment=line.assignment,
                text=line.text,
                is_open_item=line.is_open_item,
                open_amount=_ZERO,
                open_amount_local=_ZERO,
                cleared_at=now if line.is_open_item else None,
            )
        )
        if line.is_open_item:
            # The original item and its mirror settle each other; neither may be paid or cleared again.
            line.open_amount = _ZERO
            line.open_amount_local = _ZERO
            line.cleared_at = now

    reversal = JournalEntry(
        company_id=ctx.company_id,
        fiscal_year=period.year,
        period=period.period,
        number=next_number(ctx, JOURNAL_NUMBER_RANGE, year=period.year),
        doc_type=original.doc_type,
        posting_date=reversal_date,
        document_date=original.document_date,
        reference=original.reference,
        header_text=original.header_text,
        currency_code=original.currency_code,
        exchange_rate=original.exchange_rate,
        status=JournalStatus.POSTED,
        is_reversal=True,
        reversal_of_id=original.id,
        reversal_reason=reason,
        source_type=original.source_type,
        source_id=original.source_id,
        total_local=original.total_local,
        lines=mirror_lines,
    )
    ctx.db.add(reversal)
    ctx.db.flush()
    original.status = JournalStatus.REVERSED
    original.reversed_by_id = reversal.id
    original.reversal_reason = reason
    ctx.db.flush()
    audit.log(
        ctx,
        "REVERSE",
        _ENTITY,
        original.id,
        f"{original.number} numaralı kayıt {reversal.number} numaralı ters kayıtla iptal edildi: {reason}",
    )
    return reversal
