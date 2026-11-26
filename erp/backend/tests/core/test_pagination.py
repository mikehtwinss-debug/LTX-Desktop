"""List contract: paging, sorting, filtering and search."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.context import RequestContext
from app.core.errors import ValidationFailed
from app.core.pagination import ListParams, paginate
from app.modules.auth.models import User
from app.modules.fi.models.gl import AccountType, GLAccount, Period
from tests import factories

SORT = {"code": GLAccount.code, "name": GLAccount.name, "level": GLAccount.level, "id": GLAccount.id}
FILTERS = {
    "account_type": GLAccount.account_type,
    "is_postable": GLAccount.is_postable,
    "level": GLAccount.level,
    "code": GLAccount.code,
}


def _params(
    query: str = "", *, page: int = 1, page_size: int = 50, sort: str | None = None, q: str | None = None
):
    request = Request({"type": "http", "query_string": query.encode(), "headers": []})
    return ListParams(request, page=page, page_size=page_size, sort=sort, q=q)


def _accounts(ctx: RequestContext):
    return select(GLAccount).where(GLAccount.company_id == ctx.company_id)


def _count(ctx: RequestContext, *conditions) -> int:
    return ctx.db.scalar(
        select(func.count()).select_from(GLAccount).where(GLAccount.company_id == ctx.company_id, *conditions)
    )


def test_pages_and_total(ctx: RequestContext) -> None:
    total = _count(ctx)

    first = paginate(ctx, _accounts(ctx), _params(page=1, page_size=10), sort=SORT, default_sort="code")
    second = paginate(ctx, _accounts(ctx), _params(page=2, page_size=10), sort=SORT, default_sort="code")
    beyond = paginate(ctx, _accounts(ctx), _params(page=999, page_size=10), sort=SORT, default_sort="code")

    assert (first["total"], first["page"], first["page_size"]) == (total, 1, 10)
    assert total > 300
    first_codes = [account.code for account in first["items"]]
    second_codes = [account.code for account in second["items"]]
    assert len(first_codes) == len(second_codes) == 10
    assert first_codes + second_codes == sorted(first_codes + second_codes)
    assert not set(first_codes) & set(second_codes)
    assert (beyond["items"], beyond["total"]) == ([], total)


def test_sorting_ascending_descending_and_by_several_fields(ctx: RequestContext) -> None:
    descending = paginate(ctx, _accounts(ctx), _params(sort="-code", page_size=5), sort=SORT)
    combined = paginate(ctx, _accounts(ctx), _params(sort="-level,code", page_size=5), sort=SORT)

    codes = [account.code for account in descending["items"]]
    assert codes == sorted(codes, reverse=True)
    assert codes[0] == "951"
    assert [(account.level, account.code) for account in combined["items"]][:2] == [
        (2, "000.01"),
        (2, "100.01"),
    ]


def test_default_sort_breaks_ties_of_the_requested_sort(ctx: RequestContext) -> None:
    page = paginate(ctx, _accounts(ctx), _params(sort="level", page_size=4), sort=SORT, default_sort="-code")

    assert [account.code for account in page["items"]] == ["951", "950", "921", "920"]


def test_unknown_sort_field_is_rejected(ctx: RequestContext) -> None:
    with pytest.raises(ValidationFailed) as error:
        paginate(ctx, _accounts(ctx), _params(sort="password"), sort=SORT)

    assert error.value.code == "INVALID_SORT"
    assert error.value.details == {"allowed": ["code", "id", "level", "name"]}


def test_filters_by_type(ctx: RequestContext) -> None:
    not_postable = paginate(ctx, _accounts(ctx), _params("is_postable=false", page_size=500), filters=FILTERS)
    equity = paginate(ctx, _accounts(ctx), _params("account_type=EQUITY", page_size=500), filters=FILTERS)
    level_two = paginate(
        ctx, _accounts(ctx), _params("level=2&is_postable=true", page_size=500), filters=FILTERS
    )
    exact = paginate(ctx, _accounts(ctx), _params("code=320.01"), filters=FILTERS)

    assert not_postable["total"] == _count(ctx, GLAccount.is_postable.is_(False)) > 0
    assert all(not account.is_postable for account in not_postable["items"])
    assert {account.account_type for account in equity["items"]} == {AccountType.EQUITY}
    assert level_two["total"] == _count(ctx, GLAccount.level == 2)
    assert [account.name for account in exact["items"]] == ["Yurtiçi Satıcılar"]


def test_filter_with_several_values_matches_any(ctx: RequestContext) -> None:
    expected = _count(ctx, GLAccount.account_type.in_([AccountType.EQUITY, AccountType.OFFBALANCE]))

    comma = paginate(
        ctx, _accounts(ctx), _params("account_type=EQUITY,OFFBALANCE", page_size=500), filters=FILTERS
    )
    repeated = paginate(
        ctx,
        _accounts(ctx),
        _params("account_type=EQUITY&account_type=OFFBALANCE", page_size=500),
        filters=FILTERS,
    )

    assert comma["total"] == repeated["total"] == expected
    assert {account.account_type for account in comma["items"]} == {
        AccountType.EQUITY,
        AccountType.OFFBALANCE,
    }


def test_blank_and_unknown_filters_are_ignored(ctx: RequestContext) -> None:
    page = paginate(ctx, _accounts(ctx), _params("account_type=&unknown=1&_=cache"), filters=FILTERS)

    assert page["total"] == _count(ctx)


@pytest.mark.parametrize("query", ["is_postable=maybe", "account_type=NOPE", "level=two"])
def test_invalid_filter_value_is_rejected(ctx: RequestContext, query: str) -> None:
    with pytest.raises(ValidationFailed) as error:
        paginate(ctx, _accounts(ctx), _params(query), filters=FILTERS)

    assert error.value.code == "INVALID_FILTER"
    assert error.value.status == 422


def test_range_filters_on_dates_and_numbers(ctx: RequestContext) -> None:
    year = date.today().year
    periods = select(Period).where(Period.company_id == ctx.company_id)
    filters = {"start_date": Period.start_date, "period": Period.period, "year": Period.year}
    sort = {"start_date": Period.start_date}

    quarter = paginate(
        ctx,
        periods,
        _params(f"start_date_from={year}-02-01&start_date_to={year}-04-30"),
        filters=filters,
        sort=sort,
        default_sort="start_date",
    )
    late = paginate(ctx, periods, _params(f"year={year}&period_from=11"), filters=filters)

    assert [(period.year, period.period) for period in quarter["items"]] == [(year, 2), (year, 3), (year, 4)]
    assert late["total"] == 2


def test_date_only_upper_bound_on_a_timestamp_includes_the_whole_day(
    ctx: RequestContext, db: Session
) -> None:
    user = factories.make_user(db)
    today = user.created_at.date().isoformat()
    users = select(User).where(User.id == user.id)

    included = paginate(
        ctx, users, _params(f"created_at_to={today}"), filters={"created_at": User.created_at}
    )
    excluded = paginate(
        ctx, users, _params("created_at_to=2000-01-01"), filters={"created_at": User.created_at}
    )

    assert (included["total"], excluded["total"]) == (1, 0)


def test_search_is_case_insensitive_and_spans_columns(ctx: RequestContext) -> None:
    search = [GLAccount.code, GLAccount.name]

    by_name = paginate(
        ctx, _accounts(ctx), _params(q="satıcılar"), search=search, sort=SORT, default_sort="code"
    )
    by_code = paginate(ctx, _accounts(ctx), _params(q="191."), search=search, sort=SORT, default_sort="code")
    nothing = paginate(ctx, _accounts(ctx), _params(q="böyle bir hesap yok"), search=search)

    assert [account.code for account in by_name["items"]] == ["320", "320.01", "320.02", "420"]
    assert [account.code for account in by_code["items"]] == ["191.01", "191.10", "191.20"]
    assert (nothing["items"], nothing["total"]) == ([], 0)


@pytest.mark.parametrize("term", ["SATICILAR", "satıcılar", "saticilar", "Satıcılar"])
def test_search_ignores_turkish_dotted_and_dotless_i(ctx: RequestContext, term: str) -> None:
    page = paginate(
        ctx, _accounts(ctx), _params(q=term), search=[GLAccount.name], sort=SORT, default_sort="code"
    )

    assert [account.code for account in page["items"]] == ["320", "320.01", "320.02", "420"]


def test_search_folds_the_other_turkish_capitals(ctx: RequestContext) -> None:
    page = paginate(
        ctx,
        _accounts(ctx),
        _params(q="İŞÇİLİK ÜCRET"),
        search=[GLAccount.name],
        sort=SORT,
        default_sort="code",
    )

    assert [account.name for account in page["items"]] == ["Direkt İşçilik Ücret Farkları"]


def test_search_treats_wildcard_characters_literally(ctx: RequestContext) -> None:
    search = [GLAccount.name]

    percent = paginate(ctx, _accounts(ctx), _params(q="%"), search=search, sort=SORT, default_sort="code")
    underscore = paginate(ctx, _accounts(ctx), _params(q="_"), search=search)

    assert [account.code for account in percent["items"]] == [
        "191.01",
        "191.10",
        "191.20",
        "391.01",
        "391.10",
        "391.20",
    ]
    assert underscore["total"] == 0


def test_multi_column_statements_return_rows(ctx: RequestContext) -> None:
    stmt = select(GLAccount.code, GLAccount.name).where(GLAccount.company_id == ctx.company_id)

    page = paginate(ctx, stmt, _params("code=100"), filters=FILTERS)

    [row] = page["items"]
    assert (row.code, row.name) == ("100", "Kasa")


def test_list_endpoint_follows_the_contract(client: TestClient, db: Session) -> None:
    for index in range(3):
        factories.make_user(db, username=f"liste.kullanici{index}", full_name=f"Liste Kullanıcı {index}")

    response = client.get("/api/users", params={"q": "liste.kullanici", "sort": "-username", "page_size": 2})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "page", "page_size"}
    assert (body["total"], body["page"], body["page_size"]) == (3, 1, 2)
    assert [item["username"] for item in body["items"]] == ["liste.kullanici2", "liste.kullanici1"]


def test_list_endpoint_validates_paging_parameters(client: TestClient) -> None:
    too_large = client.get("/api/users", params={"page_size": 501})
    zero_page = client.get("/api/users", params={"page": 0})
    bad_sort = client.get("/api/users", params={"sort": "password_hash"})
    bad_filter = client.get("/api/users", params={"is_active": "belki"})

    assert too_large.status_code == 422
    assert too_large.json()["details"]["fields"] == {"page_size": "500 değerinden büyük olamaz"}
    assert zero_page.json()["details"]["fields"] == {"page": "1 değerinden küçük olamaz"}
    assert (bad_sort.status_code, bad_sort.json()["code"]) == (422, "INVALID_SORT")
    assert (bad_filter.status_code, bad_filter.json()["code"]) == (422, "INVALID_FILTER")
    assert client.get("/api/users", params={"page_size": 500}).status_code == 200
