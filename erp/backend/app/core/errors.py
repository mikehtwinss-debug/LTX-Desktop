"""Application errors and the handlers that turn every failure into the documented JSON shape.

Every error response is `{"code": "...", "message": "<Turkish>", "details": {...}}`.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    default_status = 400

    def __init__(
        self,
        code: str,
        message: str,
        status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status if status is not None else self.default_status
        self.details = details or {}


class NotFound(AppError):
    default_status = 404


class Forbidden(AppError):
    default_status = 403


class Conflict(AppError):
    default_status = 409


class ValidationFailed(AppError):
    default_status = 422


def error_response(
    status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, "details": details or {}},
        headers=headers,
    )


def app_error_response(error: AppError) -> JSONResponse:
    return error_response(error.status, error.code, error.message, error.details)


_FIELD_MESSAGES = {
    "missing": "Bu alan zorunludur",
    "string_too_short": "En az {min_length} karakter olmalıdır",
    "string_too_long": "En fazla {max_length} karakter olabilir",
    "string_pattern_mismatch": "Geçersiz biçim",
    "too_short": "En az {min_length} öğe içermelidir",
    "too_long": "En fazla {max_length} öğe içerebilir",
    "greater_than": "{gt} değerinden büyük olmalıdır",
    "greater_than_equal": "{ge} değerinden küçük olamaz",
    "less_than": "{lt} değerinden küçük olmalıdır",
    "less_than_equal": "{le} değerinden büyük olamaz",
    "decimal_max_digits": "En fazla {max_digits} basamak içerebilir",
    "decimal_max_places": "En fazla {decimal_places} ondalık basamak içerebilir",
    "extra_forbidden": "Bilinmeyen alan",
}
_FIELD_MESSAGE_PREFIXES = (
    ("int_", "Geçerli bir tam sayı giriniz"),
    ("decimal_", "Geçerli bir sayı giriniz"),
    ("float_", "Geçerli bir sayı giriniz"),
    ("bool_", "Evet veya hayır değeri bekleniyor"),
    ("datetime_", "Geçerli bir tarih ve saat giriniz"),
    ("date_", "Geçerli bir tarih giriniz"),
    ("string_", "Metin değeri bekleniyor"),
    ("json_", "Geçersiz JSON verisi"),
)
_LOCATION_ROOTS = {"body", "query", "path", "header", "cookie"}


def _field_message(error: dict[str, Any]) -> str:
    kind = str(error.get("type", ""))
    context = error.get("ctx") or {}
    if kind == "value_error" and "error" in context:
        return str(context["error"])
    template = _FIELD_MESSAGES.get(kind)
    if template is not None:
        try:
            return template.format(**context)
        except KeyError:
            return "Geçersiz değer"
    for prefix, message in _FIELD_MESSAGE_PREFIXES:
        if kind.startswith(prefix):
            return message
    return "Geçersiz değer"


def _field_path(location: tuple[Any, ...]) -> str:
    parts = [str(part) for part in location]
    if len(parts) > 1 and parts[0] in _LOCATION_ROOTS:
        parts = parts[1:]
    return ".".join(parts)


def validation_details(errors: list[dict[str, Any]]) -> dict[str, Any]:
    """Map pydantic errors to `{"fields": {"lines.0.quantity": "<message>"}}`."""
    fields: dict[str, str] = {}
    for error in errors:
        fields.setdefault(_field_path(tuple(error.get("loc", ()))), _field_message(error))
    return {"fields": fields}


# SQLSTATE values of the integrity-constraint class that are reported individually.
_SQLSTATE_RESTRICT = "23001"
_SQLSTATE_NOT_NULL = "23502"
_SQLSTATE_FOREIGN_KEY = "23503"
_SQLSTATE_UNIQUE = "23505"
_SQLSTATE_CHECK = "23514"
_RETRYABLE_SQLSTATES = {"40001", "40P01", "55P03"}


def _constraint_details(error: DBAPIError) -> dict[str, Any]:
    diag = getattr(error.orig, "diag", None)
    details = {
        "constraint": getattr(diag, "constraint_name", None),
        "table": getattr(diag, "table_name", None),
    }
    return {key: value for key, value in details.items() if value}


def integrity_error_response(error: IntegrityError) -> JSONResponse:
    sqlstate = getattr(error.orig, "sqlstate", None)
    details = _constraint_details(error)
    if sqlstate == _SQLSTATE_FOREIGN_KEY:
        primary = getattr(getattr(error.orig, "diag", None), "message_primary", "") or ""
        # PostgreSQL words the two directions differently; only the referenced side means "in use".
        if primary.startswith("update or delete"):
            return error_response(409, "IN_USE", "Kayıt kullanımda olduğu için silinemez", details)
        return error_response(422, "INVALID_REFERENCE", "İlişkili kayıt bulunamadı", details)
    if sqlstate == _SQLSTATE_UNIQUE:
        return error_response(409, "DUPLICATE", "Aynı anahtara sahip bir kayıt zaten mevcut", details)
    if sqlstate == _SQLSTATE_RESTRICT:
        return error_response(409, "IMMUTABLE_RECORD", "Kayıt değiştirilemez veya silinemez", details)
    if sqlstate in (_SQLSTATE_CHECK, _SQLSTATE_NOT_NULL):
        return error_response(422, "CONSTRAINT_VIOLATION", "Veri bütünlük kuralına uymuyor", details)
    return error_response(409, "INTEGRITY_ERROR", "Veri bütünlüğü hatası", details)


_HTTP_ERRORS = {
    401: ("UNAUTHORIZED", "Oturum açmanız gerekiyor"),
    403: ("FORBIDDEN", "Bu işlem için yetkiniz yok"),
    404: ("NOT_FOUND", "Kaynak bulunamadı"),
    405: ("METHOD_NOT_ALLOWED", "Bu işlem desteklenmiyor"),
    413: ("PAYLOAD_TOO_LARGE", "Gönderilen veri çok büyük"),
    415: ("UNSUPPORTED_MEDIA_TYPE", "Desteklenmeyen içerik türü"),
}
_INTERNAL_ERROR = ("INTERNAL_ERROR", "Beklenmeyen bir hata oluştu")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return app_error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            422, "VALIDATION_ERROR", "Gönderilen veriler geçersiz", validation_details(list(exc.errors()))
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        return integrity_error_response(exc)

    @app.exception_handler(StaleDataError)
    async def _stale_data(request: Request, exc: StaleDataError) -> JSONResponse:
        return error_response(
            409,
            "STALE_DATA",
            "Kayıt başka bir kullanıcı tarafından değiştirilmiş. Lütfen yenileyip tekrar deneyin.",
        )

    @app.exception_handler(DBAPIError)
    async def _database_error(request: Request, exc: DBAPIError) -> JSONResponse:
        if getattr(exc.orig, "sqlstate", None) in _RETRYABLE_SQLSTATES:
            return error_response(
                409, "CONCURRENT_UPDATE", "İşlem eşzamanlı bir güncelleme ile çakıştı. Lütfen tekrar deneyin."
            )
        logger.error("Database error on %s %s", request.method, request.url.path, exc_info=exc)
        return error_response(500, *_INTERNAL_ERROR)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_ERRORS.get(exc.status_code, (f"HTTP_{exc.status_code}", "İstek işlenemedi"))
        response = error_response(exc.status_code, code, message)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(Exception)
    async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return error_response(500, *_INTERNAL_ERROR)
