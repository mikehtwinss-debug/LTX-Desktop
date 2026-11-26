"""Request context: authenticated user, active company, permission checks.

Company-scoped endpoints take `Ctx` (a `RequestContext`). Endpoints that work on global data (users,
roles, creating the first company) take `UserCtx`, which carries no company.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, params
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import security
from app.core.errors import AppError, Forbidden
from app.modules.auth.models import Permission, RolePermission, User, UserRole
from app.modules.org.models import Company

COMPANY_HEADER = "X-Company-Id"

_bearer = HTTPBearer(auto_error=False)


@dataclass(slots=True)
class UserContext:
    db: Session
    user: User


@dataclass(slots=True)
class RequestContext(UserContext):
    company_id: int


def accessible_companies(db: Session, user: User) -> list[Company]:
    """Active companies the user may work in: all of them for superusers and holders of a global role."""
    stmt = select(Company).where(Company.is_active).order_by(Company.code)
    if not user.is_superuser:
        scopes = db.scalars(select(UserRole.company_id).where(UserRole.user_id == user.id)).all()
        if None not in scopes:
            stmt = stmt.where(Company.id.in_(set(scopes)))
    return list(db.scalars(stmt))


def permission_keys(db: Session, user: User, company_id: int | None) -> set[str]:
    """Permissions of the user in a company; with `company_id=None` only global role assignments count."""
    if user.is_superuser:
        return set(db.scalars(select(Permission.key)))
    scope = UserRole.company_id.is_(None)
    if company_id is not None:
        scope = or_(scope, UserRole.company_id == company_id)
    stmt = (
        select(Permission.key)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user.id, scope)
    )
    return set(db.scalars(stmt))


def has_permission(db: Session, user: User, key: str, company_id: int | None) -> bool:
    return user.is_superuser or key in permission_keys(db, user, company_id)


def resolve_company_id(db: Session, user: User, requested: str | None) -> int | None:
    """Active company of a request: the `X-Company-Id` header, else the user's default company, else the
    first accessible one. None when the user has no company at all."""
    companies = accessible_companies(db, user)
    allowed = {company.id for company in companies}
    if requested is not None and requested.strip():
        try:
            company_id = int(requested)
        except ValueError as exc:
            raise AppError("INVALID_COMPANY", "Geçersiz şirket bilgisi") from exc
        if company_id not in allowed:
            raise Forbidden("COMPANY_ACCESS_DENIED", "Bu şirkette işlem yapma yetkiniz yok")
        return company_id
    if user.default_company_id in allowed:
        return user.default_company_id
    return companies[0].id if companies else None


async def get_db(request: Request) -> Session:
    """The session opened by `TransactionalRoute`; it also commits and closes it."""
    return request.state.db


Db = Annotated[Session, Depends(get_db)]


def get_authenticated_user(
    db: Db, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> User:
    """The active user of the bearer token, including one who still has to change the password."""
    if credentials is None:
        raise AppError("NOT_AUTHENTICATED", "Oturum açmanız gerekiyor", 401)
    user = db.get(User, security.decode_access_token(credentials.credentials))
    if user is None or not user.is_active:
        raise AppError("INVALID_TOKEN", "Oturum bilgisi geçersiz. Lütfen tekrar giriş yapın.", 401)
    db.info["user_id"] = user.id
    return user


AuthenticatedUser = Annotated[User, Depends(get_authenticated_user)]


def get_current_user(user: AuthenticatedUser) -> User:
    if user.must_change_password:
        raise Forbidden("PASSWORD_CHANGE_REQUIRED", "Devam etmeden önce parolanızı değiştirmelisiniz")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_active_company_id(request: Request, db: Db, user: CurrentUser) -> int | None:
    company_id = resolve_company_id(db, user, request.headers.get(COMPANY_HEADER))
    db.info["company_id"] = company_id
    return company_id


ActiveCompanyId = Annotated[int | None, Depends(get_active_company_id)]


def get_user_ctx(db: Db, user: CurrentUser) -> UserContext:
    return UserContext(db=db, user=user)


def get_ctx(db: Db, user: CurrentUser, company_id: ActiveCompanyId) -> RequestContext:
    if company_id is None:
        raise Forbidden("COMPANY_REQUIRED", "Bu işlem için yetkili olduğunuz bir şirket seçilmelidir")
    return RequestContext(db=db, user=user, company_id=company_id)


UserCtx = Annotated[UserContext, Depends(get_user_ctx)]
Ctx = Annotated[RequestContext, Depends(get_ctx)]


def require(key: str) -> params.Depends:
    """Route dependency that demands a permission in the active company (superusers always pass)."""

    def check_permission(db: Db, user: CurrentUser, company_id: ActiveCompanyId) -> None:
        if not has_permission(db, user, key, company_id):
            raise Forbidden("PERMISSION_DENIED", "Bu işlem için yetkiniz yok", details={"permission": key})

    return Depends(check_permission)
