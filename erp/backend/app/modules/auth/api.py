"""Auth endpoints: login, own account, user and role administration."""

from fastapi import Request, Response

from app.core.context import (
    COMPANY_HEADER,
    AuthenticatedUser,
    Db,
    UserContext,
    UserCtx,
    require,
    resolve_company_id,
)
from app.core.errors import app_error_response
from app.core.pagination import ListQuery, Page
from app.core.routing import make_router
from app.modules.auth import service
from app.modules.auth.schemas import (
    ChangePasswordIn,
    LoginIn,
    LoginOut,
    Me,
    PasswordResetIn,
    PermissionOut,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    UserCreate,
    UserDeleteOut,
    UserOut,
    UserRolesIn,
    UserUpdate,
)

router = make_router("/api", ["auth"])

USER_VIEW = require("auth.user.view")
USER_MANAGE = require("auth.user.manage")
ROLE_VIEW = require("auth.role.view")
ROLE_MANAGE = require("auth.role.manage")


@router.post("/auth/login", response_model=LoginOut)
def login(data: LoginIn, db: Db) -> LoginOut | Response:
    outcome = service.login(db, data)
    if isinstance(outcome, LoginOut):
        return outcome
    # Returned instead of raised so that the failed-attempt counter is committed with the response.
    return app_error_response(outcome)


@router.get("/auth/me", response_model=Me)
def me(request: Request, db: Db, user: AuthenticatedUser) -> Me:
    company_id = resolve_company_id(db, user, request.headers.get(COMPANY_HEADER))
    return service.build_me(db, user, company_id)


@router.post("/auth/change-password", status_code=204)
def change_password(data: ChangePasswordIn, db: Db, user: AuthenticatedUser) -> None:
    service.change_password(UserContext(db=db, user=user), data)


@router.get("/permissions", response_model=list[PermissionOut], dependencies=[ROLE_VIEW])
def list_permissions(ctx: UserCtx) -> list[PermissionOut]:
    return service.list_permissions(ctx)


@router.get("/users", response_model=Page[UserOut], dependencies=[USER_VIEW])
def list_users(ctx: UserCtx, params: ListQuery) -> Page[UserOut]:
    return service.list_users(ctx, params)


@router.post("/users", response_model=UserOut, status_code=201, dependencies=[USER_MANAGE])
def create_user(data: UserCreate, ctx: UserCtx) -> UserOut:
    return service.create_user(ctx, data)


@router.get("/users/{user_id}", response_model=UserOut, dependencies=[USER_VIEW])
def get_user(user_id: int, ctx: UserCtx) -> UserOut:
    return service.get_user(ctx, user_id)


@router.put("/users/{user_id}", response_model=UserOut, dependencies=[USER_MANAGE])
def update_user(user_id: int, data: UserUpdate, ctx: UserCtx) -> UserOut:
    return service.update_user(ctx, user_id, data)


@router.delete("/users/{user_id}", response_model=UserDeleteOut, dependencies=[USER_MANAGE])
def delete_user(user_id: int, ctx: UserCtx) -> UserDeleteOut:
    return UserDeleteOut(result=service.delete_user(ctx, user_id))


@router.post("/users/{user_id}/reset-password", response_model=UserOut, dependencies=[USER_MANAGE])
def reset_password(user_id: int, data: PasswordResetIn, ctx: UserCtx) -> UserOut:
    return service.reset_password(ctx, user_id, data)


@router.post("/users/{user_id}/unlock", response_model=UserOut, dependencies=[USER_MANAGE])
def unlock_user(user_id: int, ctx: UserCtx) -> UserOut:
    return service.unlock_user(ctx, user_id)


@router.put("/users/{user_id}/roles", response_model=UserOut, dependencies=[USER_MANAGE])
def set_user_roles(user_id: int, data: UserRolesIn, ctx: UserCtx) -> UserOut:
    return service.set_user_roles(ctx, user_id, data.roles)


@router.get("/roles", response_model=Page[RoleOut], dependencies=[ROLE_VIEW])
def list_roles(ctx: UserCtx, params: ListQuery) -> Page[RoleOut]:
    return service.list_roles(ctx, params)


@router.post("/roles", response_model=RoleOut, status_code=201, dependencies=[ROLE_MANAGE])
def create_role(data: RoleCreate, ctx: UserCtx) -> RoleOut:
    return service.role_out(service.create_role(ctx, data))


@router.get("/roles/{role_id}", response_model=RoleOut, dependencies=[ROLE_VIEW])
def get_role(role_id: int, ctx: UserCtx) -> RoleOut:
    return service.role_out(service.get_role(ctx, role_id))


@router.put("/roles/{role_id}", response_model=RoleOut, dependencies=[ROLE_MANAGE])
def update_role(role_id: int, data: RoleUpdate, ctx: UserCtx) -> RoleOut:
    return service.role_out(service.update_role(ctx, role_id, data))


@router.delete("/roles/{role_id}", status_code=204, dependencies=[ROLE_MANAGE])
def delete_role(role_id: int, ctx: UserCtx) -> None:
    service.delete_role(ctx, role_id)
