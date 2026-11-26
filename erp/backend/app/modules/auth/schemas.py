"""Request and response models of the auth feature."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

PASSWORD_MIN_LENGTH = 8

Password = Annotated[str, StringConstraints(min_length=PASSWORD_MIN_LENGTH, max_length=128)]
Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"
    ),
]
Email = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
]
RoleCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=32, pattern=r"^[a-z0-9_]+$")
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CompanyRef(OrmModel):
    id: int
    code: str
    name: str


class RoleRef(OrmModel):
    id: int
    code: str
    name: str


class Me(BaseModel):
    id: int
    username: str
    full_name: str
    email: str | None
    is_superuser: bool
    must_change_password: bool
    default_company_id: int | None
    company_id: int | None
    companies: list[CompanyRef]
    permissions: list[str]


class LoginIn(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class LoginOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: Me


class ChangePasswordIn(BaseModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    new_password: Password


class RoleAssignmentIn(BaseModel):
    role_id: int
    company_id: int | None = None  # None = every company


class RoleAssignmentOut(OrmModel):
    id: int
    role: RoleRef
    company: CompanyRef | None


class UserOut(OrmModel):
    id: int
    username: str
    full_name: str
    email: str | None
    is_active: bool
    is_superuser: bool
    default_company_id: int | None
    must_change_password: bool
    last_login_at: datetime | None
    locked_until: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime
    roles: list[RoleAssignmentOut]


class UserCreate(BaseModel):
    username: Username
    full_name: Name
    email: Email | None = None
    password: Password
    is_active: bool = True
    is_superuser: bool = False
    default_company_id: int | None = None
    must_change_password: bool = True
    roles: list[RoleAssignmentIn] = Field(default_factory=list)

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class UserUpdate(BaseModel):
    full_name: Name
    email: Email | None = None
    is_active: bool
    is_superuser: bool
    default_company_id: int | None = None
    version: int

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class PasswordResetIn(BaseModel):
    new_password: Password
    must_change_password: bool = True


class UserRolesIn(BaseModel):
    roles: list[RoleAssignmentIn]


class UserDeleteOut(BaseModel):
    """`DEACTIVATED` when the user is referenced by other records and was switched off instead."""

    result: Literal["DELETED", "DEACTIVATED"]


class PermissionOut(OrmModel):
    key: str
    description: str


class RoleOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None
    is_system: bool
    permissions: list[str]
    created_at: datetime
    updated_at: datetime


class RoleCreate(BaseModel):
    code: RoleCode
    name: Name
    description: str | None = Field(default=None, max_length=1000)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: Name
    description: str | None = Field(default=None, max_length=1000)
    permissions: list[str]
