"""Settings, storage, posting periods, security helpers, configuration and decimal types."""

from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security, storage
from app.core.config import DEFAULT_SECRET_KEY, Settings, get_settings
from app.core.context import RequestContext
from app.core.errors import AppError, NotFound
from app.core.periods import assert_period_open, get_period
from app.core.settings import get_setting, register_setting, registered_settings, set_setting
from app.core.types import q_money, q_price, q_qty
from app.modules.fi.models.gl import Period, PeriodStatus
from app.modules.org.models import CompanySetting
from tests import factories

# --- company settings ----------------------------------------------------------------------------


def _setting_key() -> str:
    return f"test.{uuid.uuid4().hex[:10]}"


def test_setting_default_then_stored_value(ctx: RequestContext, db: Session) -> None:
    key = _setting_key()
    register_setting(key, {"currency": "TRY", "tolerance": "2.5"}, "Deneme ayarı")

    assert get_setting(ctx, key) == {"currency": "TRY", "tolerance": "2.5"}
    assert registered_settings()[key].description == "Deneme ayarı"

    set_setting(ctx, key, {"currency": "EUR", "tolerance": "1"})
    set_setting(ctx, key, {"currency": "USD", "tolerance": "1"})

    assert get_setting(ctx, key) == {"currency": "USD", "tolerance": "1"}
    rows = db.scalars(select(CompanySetting).where(CompanySetting.key == key)).all()
    assert [(row.company_id, row.value["currency"]) for row in rows] == [(ctx.company_id, "USD")]


@pytest.mark.parametrize("value", [False, 0, "", [], None])
def test_falsy_stored_values_are_not_mistaken_for_missing(ctx: RequestContext, value: object) -> None:
    key = _setting_key()
    register_setting(key, "varsayılan", "Deneme ayarı")

    set_setting(ctx, key, value)

    assert get_setting(ctx, key) == value


def test_settings_are_per_company(ctx: RequestContext, db: Session) -> None:
    key = _setting_key()
    register_setting(key, False, "Deneme ayarı")
    other_ctx = RequestContext(db=db, user=ctx.user, company_id=factories.make_company(db).id)

    set_setting(ctx, key, True)

    assert get_setting(ctx, key) is True
    assert get_setting(other_ctx, key) is False


def test_setting_registration_rules(ctx: RequestContext) -> None:
    key = _setting_key()
    register_setting(key, 1, "Deneme ayarı")
    register_setting(key, 1, "Deneme ayarı")

    with pytest.raises(ValueError, match="already registered"):
        register_setting(key, 2, "Deneme ayarı")
    with pytest.raises(LookupError):
        get_setting(ctx, "test.not.registered")
    with pytest.raises(LookupError):
        set_setting(ctx, "test.not.registered", 1)


# --- file storage ----------------------------------------------------------------------------------


def test_stored_file_round_trip() -> None:
    root = get_settings().storage_dir.resolve()

    path = storage.save_file(
        b"%PDF-1.4 deneme", original_name="Sipariş Formu (son).PDF", category="attachments"
    )

    today = date.today()
    directory, name = path.rsplit("/", 1)
    assert directory == f"attachments/{today:%Y}/{today:%m}"
    assert len(name) == 32 + len(".pdf") and name.endswith(".pdf")
    assert "Sipariş" not in path
    assert storage.read_file(path) == b"%PDF-1.4 deneme"
    assert storage.resolve_path(path) == root / path
    assert not list((root / directory).glob("*.part"))

    storage.delete_file(path)
    storage.delete_file(path)  # deleting twice is harmless
    with pytest.raises(NotFound) as error:
        storage.read_file(path)
    assert error.value.code == "FILE_NOT_FOUND"


def test_generated_names_are_unique_and_extensions_are_sanitised() -> None:
    first = storage.save_file(b"a", original_name="rapor.xlsx", category="attachments")
    second = storage.save_file(b"b", original_name="rapor.xlsx", category="attachments")
    no_extension = storage.save_file(b"c", original_name="README", category="attachments")
    hostile = storage.save_file(b"d", original_name="../../etc/passwd.sh;rm -rf", category="attachments")
    windows = storage.save_file(b"e", original_name="C:\\Belgeler\\fatura.JPG", category="attachments")

    assert first != second
    assert Path(no_extension).suffix == ""
    assert Path(hostile).suffix == ""
    assert Path(windows).suffix == ".jpg"
    assert all(path.startswith("attachments/") and ".." not in path for path in (hostile, windows))


@pytest.mark.parametrize(
    "path",
    ["../outside.txt", "attachments/../../outside.txt", "/etc/passwd", "", ".", "attachments/../.."],
)
def test_paths_outside_the_storage_directory_are_rejected(path: str) -> None:
    for operation in (storage.read_file, storage.delete_file, storage.resolve_path):
        with pytest.raises(AppError) as error:
            operation(path)
        assert error.value.code == "INVALID_STORAGE_PATH"


def test_symlink_escaping_the_storage_directory_is_rejected(tmp_path: Path) -> None:
    root = get_settings().storage_dir.resolve()
    outside = tmp_path / "secret.txt"
    outside.write_text("gizli")
    (root / "attachments").mkdir(parents=True, exist_ok=True)
    link = root / "attachments" / f"link-{uuid.uuid4().hex}"
    os.symlink(outside, link)
    try:
        with pytest.raises(AppError) as error:
            storage.read_file(f"attachments/{link.name}")
        assert error.value.code == "INVALID_STORAGE_PATH"
    finally:
        link.unlink()


@pytest.mark.parametrize("category", ["../x", "a/b", "", "Büyük", "x" * 65])
def test_storage_category_must_be_a_plain_folder_name(category: str) -> None:
    with pytest.raises(ValueError, match="Invalid storage category"):
        storage.save_file(b"x", original_name="a.txt", category=category)


# --- posting periods -------------------------------------------------------------------------------


def test_period_lookup_by_date(ctx: RequestContext) -> None:
    year = date.today().year

    period = get_period(ctx, date(year, 2, 14))
    last_day = assert_period_open(ctx, date(year + 1, 12, 31))

    assert (period.year, period.period) == (year, 2)
    assert (last_day.year, last_day.period) == (year + 1, 12)


def test_missing_period(ctx: RequestContext) -> None:
    with pytest.raises(AppError) as error:
        assert_period_open(ctx, date(1999, 5, 20))

    assert (error.value.code, error.value.status) == ("PERIOD_MISSING", 400)
    assert error.value.message == "20.05.1999 tarihi için tanımlı bir muhasebe dönemi yok"
    assert error.value.details == {"date": "1999-05-20"}


def test_closed_period(ctx: RequestContext, db: Session) -> None:
    year = date.today().year
    march = db.scalars(
        select(Period).where(Period.company_id == ctx.company_id, Period.year == year, Period.period == 3)
    ).one()
    march.status = PeriodStatus.CLOSED
    db.flush()

    with pytest.raises(AppError) as error:
        assert_period_open(ctx, date(year, 3, 31))

    assert error.value.code == "PERIOD_CLOSED"
    assert error.value.message == f"{year}/03 muhasebe dönemi kapalı"
    assert error.value.details == {"year": year, "period": 3, "date": f"{year}-03-31"}
    assert get_period(ctx, date(year, 3, 31)).status is PeriodStatus.CLOSED  # plain lookup still works
    assert assert_period_open(ctx, date(year, 4, 1)).period == 4


def test_periods_belong_to_the_company(ctx: RequestContext, db: Session) -> None:
    other_ctx = RequestContext(db=db, user=ctx.user, company_id=factories.make_company(db).id)

    with pytest.raises(AppError) as error:
        get_period(other_ctx, date.today())

    assert error.value.code == "PERIOD_MISSING"


# --- security helpers ------------------------------------------------------------------------------


def test_password_hashing() -> None:
    first = security.hash_password("Parola-Test-1")
    second = security.hash_password("Parola-Test-1")

    assert first.startswith("$argon2id$")
    assert first != second  # salted
    assert security.verify_password("Parola-Test-1", first)
    assert not security.verify_password("parola-test-1", first)
    assert not security.verify_password("Parola-Test-1", "not-a-hash")
    assert not security.needs_rehash(first)


def test_access_token_round_trip() -> None:
    token = security.create_access_token(42)

    assert security.decode_access_token(token) == 42
    with pytest.raises(AppError) as error:
        security.decode_access_token(token[:-2] + "xx")
    assert (error.value.code, error.value.status) == ("INVALID_TOKEN", 401)


# --- configuration ---------------------------------------------------------------------------------


@pytest.fixture
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide every ERP_* variable of the developer's shell, so only the values under test apply."""
    for name in [name for name in os.environ if name.startswith("ERP_")]:
        monkeypatch.delenv(name)


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)


def test_test_run_configuration() -> None:
    settings = get_settings()

    assert settings.env == "test"
    assert "/erp_test_" in settings.database_url
    assert settings.access_token_minutes == 12 * 60


@pytest.mark.usefixtures("clean_environment")
def test_production_refuses_a_default_or_short_secret_key() -> None:
    with pytest.raises(ValidationError, match="ERP_SECRET_KEY"):
        _settings(env="production")
    with pytest.raises(ValidationError, match="ERP_SECRET_KEY"):
        _settings(env="production", secret_key=DEFAULT_SECRET_KEY)
    with pytest.raises(ValidationError, match="ERP_SECRET_KEY"):
        _settings(env="production", secret_key="x" * 31)

    assert _settings(env="production", secret_key="x" * 32).secret_key == "x" * 32
    assert _settings(env="development").secret_key == DEFAULT_SECRET_KEY


@pytest.mark.usefixtures("clean_environment")
def test_settings_come_from_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ERP_DATABASE_URL", "postgresql://erp:erp@db:5432/erp")
    monkeypatch.setenv("ERP_FEATURES", " auth, fi.gl ,,mm.master ")
    monkeypatch.setenv("ERP_CORS_ORIGINS", "http://localhost:5173, https://erp.ornek.example")
    monkeypatch.setenv("ERP_ADMIN_PASSWORD", "")
    monkeypatch.setenv("ERP_STORAGE_DIR", "/var/lib/erp/storage")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://erp:erp@db:5432/erp"
    assert settings.feature_list == ["auth", "fi.gl", "mm.master"]
    assert settings.cors_origin_list == ["http://localhost:5173", "https://erp.ornek.example"]
    assert settings.admin_password is None
    assert settings.storage_dir == Path("/var/lib/erp/storage")
    assert _settings(features="").feature_list is None
    assert _settings(cors_origins="").cors_origin_list == []


# --- decimal helpers -------------------------------------------------------------------------------


def test_quantize_helpers_round_half_up() -> None:
    assert q_money("2.345") == Decimal("2.35")
    assert q_money(Decimal("2.344999")) == Decimal("2.34")
    assert q_money(Decimal("-2.345")) == Decimal("-2.35")
    assert q_money(7) == Decimal("7.00")
    assert q_qty("1.0005") == Decimal("1.001")
    assert q_price(Decimal("0.1234565")) == Decimal("0.123457")
    assert str(q_money(Decimal("0.1") + Decimal("0.2"))) == "0.30"
    assert q_money(Decimal("1.005")) - q_money(Decimal("1.00")) == Decimal("0.01")
