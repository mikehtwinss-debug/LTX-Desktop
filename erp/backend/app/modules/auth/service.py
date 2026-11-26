"""Authentication, users, roles and permissions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core import audit, security
from app.core.context import (
    UserContext,
    accessible_companies,
    has_permission,
    permission_keys,
    resolve_company_id,
)
from app.core.db import assert_version, utcnow
from app.core.errors import AppError, Conflict, Forbidden, NotFound, ValidationFailed
from app.core.pagination import ListParams, PageData, paginate
from app.modules.auth.models import Permission, Role, RolePermission, User, UserRole
from app.modules.auth.schemas import (
    ChangePasswordIn,
    CompanyRef,
    LoginIn,
    LoginOut,
    Me,
    PasswordResetIn,
    RoleAssignmentIn,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    UserCreate,
    UserUpdate,
)
from app.modules.org.models import Company

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
USER_MANAGE = "auth.user.manage"

_USER_ENTITY = User.__tablename__
_ROLE_ENTITY = Role.__tablename__


# --- permissions -------------------------------------------------------------------------------


def sync_permissions(db: Session, permissions: Mapping[str, str]) -> None:
    """Insert missing permission keys and refresh changed descriptions. Never deletes: a restricted
    `ERP_FEATURES` run must not drop the permissions of the features it left out."""
    if not permissions:
        return
    now = utcnow()
    statement = insert(Permission).values(
        [
            {"key": key, "description": description, "created_at": now, "updated_at": now}
            for key, description in sorted(permissions.items())
        ]
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[Permission.key],
            set_={"description": statement.excluded.description, "updated_at": now},
            where=Permission.description.is_distinct_from(statement.excluded.description),
        )
    )


def list_permissions(ctx: UserContext) -> list[Permission]:
    return list(ctx.db.scalars(select(Permission).order_by(Permission.key)))


# --- login and own account ---------------------------------------------------------------------


def build_me(db: Session, user: User, company_id: int | None) -> Me:
    return Me(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        is_superuser=user.is_superuser,
        must_change_password=user.must_change_password,
        default_company_id=user.default_company_id,
        company_id=company_id,
        companies=[CompanyRef.model_validate(company) for company in accessible_companies(db, user)],
        permissions=sorted(permission_keys(db, user, company_id)),
    )


def _set_login_state(db: Session, user: User, **values: Any) -> None:
    """Update login bookkeeping without touching `version`, so that a login never makes an
    administrator's open edit form stale."""
    db.execute(
        update(User)
        .where(User.id == user.id)
        .values(updated_at=User.updated_at, **values)
        .execution_options(synchronize_session=False)
    )
    db.refresh(user, attribute_names=list(values))


def login(db: Session, data: LoginIn) -> LoginOut | AppError:
    """Check the credentials and issue a token.

    Failures are *returned*, not raised: the failed-attempt counter and the lock must be committed,
    and the request transaction only commits when the endpoint returns normally.
    """
    invalid = AppError("INVALID_CREDENTIALS", "Kullanıcı adı veya parola hatalı", 401)
    user = db.scalar(select(User).where(User.username == data.username.lower()).with_for_update())
    if user is None:
        security.verify_dummy_password(data.password)
        return invalid

    now = utcnow()
    if user.locked_until is not None:
        if user.locked_until > now:
            return _locked_error(user)
        _set_login_state(db, user, locked_until=None, failed_login_count=0)

    if not security.verify_password(data.password, user.password_hash):
        failures = user.failed_login_count + 1
        if failures < MAX_FAILED_LOGINS:
            _set_login_state(db, user, failed_login_count=failures)
            return invalid
        _set_login_state(db, user, failed_login_count=failures, locked_until=now + LOCKOUT)
        audit.log(
            UserContext(db=db, user=user),
            "ACCOUNT_LOCKED",
            _USER_ENTITY,
            user.id,
            f"{MAX_FAILED_LOGINS} hatalı giriş denemesi sonrası hesap kilitlendi",
        )
        return _locked_error(user)

    if not user.is_active:
        return Forbidden("ACCOUNT_DISABLED", "Kullanıcı hesabı pasif durumda")

    state: dict[str, Any] = {"failed_login_count": 0, "locked_until": None, "last_login_at": now}
    if security.needs_rehash(user.password_hash):
        state["password_hash"] = security.hash_password(data.password)
    _set_login_state(db, user, **state)
    audit.log(UserContext(db=db, user=user), "LOGIN", _USER_ENTITY, user.id, "Oturum açıldı")
    return LoginOut(
        access_token=security.create_access_token(user.id),
        user=build_me(db, user, resolve_company_id(db, user, None)),
    )


def _locked_error(user: User) -> AppError:
    return AppError(
        "ACCOUNT_LOCKED",
        "Çok sayıda hatalı giriş denemesi nedeniyle hesap geçici olarak kilitlendi",
        423,
        details={"locked_until": user.locked_until.isoformat() if user.locked_until else None},
    )


def change_password(ctx: UserContext, data: ChangePasswordIn) -> None:
    user = ctx.user
    if not security.verify_password(data.current_password, user.password_hash):
        raise ValidationFailed(
            "INVALID_CURRENT_PASSWORD",
            "Mevcut parola hatalı",
            details={"fields": {"current_password": "Mevcut parola hatalı"}},
        )
    if data.new_password == data.current_password:
        raise ValidationFailed(
            "PASSWORD_UNCHANGED",
            "Yeni parola mevcut paroladan farklı olmalıdır",
            details={"fields": {"new_password": "Yeni parola mevcut paroladan farklı olmalıdır"}},
        )
    user.password_hash = security.hash_password(data.new_password)
    user.must_change_password = False
    audit.log(ctx, "PASSWORD_CHANGE", _USER_ENTITY, user.id, "Kullanıcı parolasını değiştirdi")


# --- users ---------------------------------------------------------------------------------------

_USER_OPTIONS = (
    selectinload(User.roles).joinedload(UserRole.role),
    selectinload(User.roles).joinedload(UserRole.company),
)


def list_users(ctx: UserContext, params: ListParams) -> PageData:
    return paginate(
        ctx,
        select(User).options(*_USER_OPTIONS),
        params,
        search=[User.username, User.full_name, User.email],
        sort={
            "id": User.id,
            "username": User.username,
            "full_name": User.full_name,
            "email": User.email,
            "is_active": User.is_active,
            "last_login_at": User.last_login_at,
            "created_at": User.created_at,
        },
        filters={"is_active": User.is_active, "is_superuser": User.is_superuser},
        default_sort="username",
    )


def get_user(ctx: UserContext, user_id: int, *, lock: bool = False) -> User:
    stmt = select(User).where(User.id == user_id).options(*_USER_OPTIONS)
    if lock:
        stmt = stmt.with_for_update(of=User)
    user = ctx.db.scalar(stmt)
    if user is None:
        raise NotFound("USER_NOT_FOUND", "Kullanıcı bulunamadı")
    return user


def _require_superuser(ctx: UserContext) -> None:
    if not ctx.user.is_superuser:
        raise Forbidden("SUPERUSER_REQUIRED", "Bu işlemi yalnızca sistem yöneticisi yapabilir")


def _guard_superuser_account(ctx: UserContext, target: User) -> None:
    """Only a superuser may touch a superuser account; otherwise user admins could take it over."""
    if target.is_superuser:
        _require_superuser(ctx)


def _guard_managed_account(ctx: UserContext, target: User) -> None:
    """Changing an account (profile, password, lock, deletion) needs authority over every role the
    account holds: an administrator of one company must not take over a user of another."""
    _guard_superuser_account(ctx, target)
    _check_assignment_scope(ctx, {(link.role_id, link.company_id) for link in target.roles})


def _check_default_company(ctx: UserContext, company_id: int | None) -> None:
    if company_id is not None and ctx.db.get(Company, company_id) is None:
        raise ValidationFailed(
            "COMPANY_NOT_FOUND",
            "Varsayılan şirket bulunamadı",
            details={"fields": {"default_company_id": "Şirket bulunamadı"}},
        )


def _other_active_superuser_exists(ctx: UserContext, user: User) -> bool:
    stmt = select(func.count()).where(User.is_superuser, User.is_active, User.id != user.id)
    return bool(ctx.db.scalar(stmt))


def _guard_last_superuser(ctx: UserContext, user: User) -> None:
    if user.is_superuser and user.is_active and not _other_active_superuser_exists(ctx, user):
        raise Conflict("LAST_SUPERUSER", "Son aktif sistem yöneticisi kaldırılamaz veya pasife alınamaz")


def _assignment_keys(assignments: Iterable[RoleAssignmentIn]) -> set[tuple[int, int | None]]:
    return {(assignment.role_id, assignment.company_id) for assignment in assignments}


def _check_assignment_scope(ctx: UserContext, changed: Iterable[tuple[int, int | None]]) -> None:
    """A user administrator may only grant or revoke roles in companies where they hold
    `auth.user.manage` themselves; a global assignment needs a global grant."""
    if ctx.user.is_superuser:
        return
    for company_id in {company_id for _, company_id in changed}:
        if not has_permission(ctx.db, ctx.user, USER_MANAGE, company_id):
            raise Forbidden(
                "ROLE_SCOPE_DENIED",
                "Bu şirket için rol atama yetkiniz yok",
                details={"company_id": company_id},
            )


def _apply_roles(ctx: UserContext, user: User, assignments: Iterable[RoleAssignmentIn]) -> None:
    desired = _assignment_keys(assignments)
    current = {(link.role_id, link.company_id): link for link in user.roles}
    added = desired - current.keys()
    removed = current.keys() - desired
    _check_assignment_scope(ctx, added | removed)

    role_ids = {role_id for role_id, _ in added}
    known_roles = set(ctx.db.scalars(select(Role.id).where(Role.id.in_(role_ids)))) if role_ids else set()
    company_ids = {company_id for _, company_id in added if company_id is not None}
    known_companies = (
        set(ctx.db.scalars(select(Company.id).where(Company.id.in_(company_ids)))) if company_ids else set()
    )
    if role_ids - known_roles:
        raise ValidationFailed(
            "ROLE_NOT_FOUND", "Rol bulunamadı", details={"role_ids": sorted(role_ids - known_roles)}
        )
    if company_ids - known_companies:
        raise ValidationFailed(
            "COMPANY_NOT_FOUND",
            "Şirket bulunamadı",
            details={"company_ids": sorted(company_ids - known_companies)},
        )

    for key in removed:
        user.roles.remove(current[key])
    for role_id, company_id in sorted(added, key=lambda key: (key[0], key[1] or 0)):
        user.roles.append(UserRole(role_id=role_id, company_id=company_id))


def create_user(ctx: UserContext, data: UserCreate) -> User:
    if data.is_superuser:
        _require_superuser(ctx)
    if ctx.db.scalar(select(User.id).where(User.username == data.username)) is not None:
        raise Conflict(
            "USERNAME_TAKEN",
            "Bu kullanıcı adı zaten kullanılıyor",
            details={"fields": {"username": "Bu kullanıcı adı zaten kullanılıyor"}},
        )
    _check_default_company(ctx, data.default_company_id)
    user = User(
        username=data.username,
        full_name=data.full_name,
        email=data.email,
        password_hash=security.hash_password(data.password),
        is_active=data.is_active,
        is_superuser=data.is_superuser,
        default_company_id=data.default_company_id,
        must_change_password=data.must_change_password,
    )
    ctx.db.add(user)
    _apply_roles(ctx, user, data.roles)
    ctx.db.flush()
    return get_user(ctx, user.id)


def update_user(ctx: UserContext, user_id: int, data: UserUpdate) -> User:
    user = get_user(ctx, user_id, lock=True)
    assert_version(user, data.version)
    _guard_managed_account(ctx, user)
    if data.is_superuser != user.is_superuser:
        _require_superuser(ctx)
    if user.id == ctx.user.id and not data.is_active:
        raise Conflict("CANNOT_DEACTIVATE_SELF", "Kendi hesabınızı pasife alamazsınız")
    if not (data.is_superuser and data.is_active):
        _guard_last_superuser(ctx, user)
    _check_default_company(ctx, data.default_company_id)

    user.full_name = data.full_name
    user.email = data.email
    user.is_active = data.is_active
    user.is_superuser = data.is_superuser
    user.default_company_id = data.default_company_id
    ctx.db.flush()
    return user


def reset_password(ctx: UserContext, user_id: int, data: PasswordResetIn) -> User:
    user = get_user(ctx, user_id, lock=True)
    _guard_managed_account(ctx, user)
    user.password_hash = security.hash_password(data.new_password)
    user.must_change_password = data.must_change_password
    _set_login_state(ctx.db, user, failed_login_count=0, locked_until=None)
    audit.log(ctx, "PASSWORD_RESET", _USER_ENTITY, user.id, "Parola yönetici tarafından sıfırlandı")
    ctx.db.flush()
    return user


def unlock_user(ctx: UserContext, user_id: int) -> User:
    user = get_user(ctx, user_id, lock=True)
    _guard_managed_account(ctx, user)
    _set_login_state(ctx.db, user, failed_login_count=0, locked_until=None)
    audit.log(ctx, "UNLOCK", _USER_ENTITY, user.id, "Hesap kilidi yönetici tarafından kaldırıldı")
    return user


def set_user_roles(ctx: UserContext, user_id: int, assignments: list[RoleAssignmentIn]) -> User:
    user = get_user(ctx, user_id, lock=True)
    _guard_superuser_account(ctx, user)
    _apply_roles(ctx, user, assignments)
    ctx.db.flush()
    ctx.db.expire(user, ["roles"])
    return get_user(ctx, user.id)


def delete_user(ctx: UserContext, user_id: int) -> str:
    """Delete the user, or deactivate it when other records (documents, audit log) refer to it."""
    user = get_user(ctx, user_id, lock=True)
    if user.id == ctx.user.id:
        raise Conflict("CANNOT_DELETE_SELF", "Kendi hesabınızı silemezsiniz")
    _guard_managed_account(ctx, user)
    _guard_last_superuser(ctx, user)
    try:
        with ctx.db.begin_nested():
            ctx.db.delete(user)
            ctx.db.flush()
    except IntegrityError:
        ctx.db.refresh(user)
        user.is_active = False
        ctx.db.flush()
        return "DEACTIVATED"
    return "DELETED"


# --- roles ---------------------------------------------------------------------------------------

_ROLE_OPTIONS = (selectinload(Role.permission_links).joinedload(RolePermission.permission),)


def role_out(role: Role) -> RoleOut:
    return RoleOut(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=sorted(link.permission.key for link in role.permission_links),
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


def list_roles(ctx: UserContext, params: ListParams) -> PageData:
    page = paginate(
        ctx,
        select(Role).options(*_ROLE_OPTIONS),
        params,
        search=[Role.code, Role.name],
        sort={"id": Role.id, "code": Role.code, "name": Role.name, "created_at": Role.created_at},
        filters={"is_system": Role.is_system},
        default_sort="code",
    )
    page["items"] = [role_out(role) for role in page["items"]]
    return page


def get_role(ctx: UserContext, role_id: int, *, lock: bool = False) -> Role:
    stmt = select(Role).where(Role.id == role_id).options(*_ROLE_OPTIONS)
    if lock:
        stmt = stmt.with_for_update(of=Role)
    role = ctx.db.scalar(stmt)
    if role is None:
        raise NotFound("ROLE_NOT_FOUND", "Rol bulunamadı")
    return role


def set_role_permissions(db: Session, role: Role, keys: Iterable[str]) -> bool:
    """Replace the permission set of a role; returns whether anything changed."""
    wanted = set(keys)
    known = {
        permission.key: permission
        for permission in db.scalars(select(Permission).where(Permission.key.in_(wanted)))
    }
    unknown = wanted - known.keys()
    if unknown:
        raise ValidationFailed(
            "UNKNOWN_PERMISSION", "Tanımsız yetki anahtarı", details={"keys": sorted(unknown)}
        )
    current = {link.permission.key: link for link in role.permission_links}
    for key in current.keys() - wanted:
        role.permission_links.remove(current[key])
    for key in sorted(wanted - current.keys()):
        role.permission_links.append(RolePermission(permission=known[key]))
    return wanted != current.keys()


def create_role(ctx: UserContext, data: RoleCreate) -> Role:
    if ctx.db.scalar(select(Role.id).where(Role.code == data.code)) is not None:
        raise Conflict(
            "ROLE_CODE_TAKEN",
            "Bu rol kodu zaten kullanılıyor",
            details={"fields": {"code": "Bu rol kodu zaten kullanılıyor"}},
        )
    role = Role(code=data.code, name=data.name, description=data.description, is_system=False)
    ctx.db.add(role)
    set_role_permissions(ctx.db, role, data.permissions)
    ctx.db.flush()
    return role


def update_role(ctx: UserContext, role_id: int, data: RoleUpdate) -> Role:
    role = get_role(ctx, role_id, lock=True)
    role.name = data.name
    role.description = data.description
    if set_role_permissions(ctx.db, role, data.permissions):
        audit.log(
            ctx, "PERMISSIONS_CHANGED", _ROLE_ENTITY, role.id, f"{role.code} rolünün yetkileri güncellendi"
        )
    ctx.db.flush()
    return role


def delete_role(ctx: UserContext, role_id: int) -> None:
    role = get_role(ctx, role_id, lock=True)
    if role.is_system:
        raise Conflict("SYSTEM_ROLE", "Sistem rolleri silinemez")
    if ctx.db.scalar(select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)):
        raise Conflict("IN_USE", "Kayıt kullanımda olduğu için silinemez")
    ctx.db.delete(role)
    ctx.db.flush()
