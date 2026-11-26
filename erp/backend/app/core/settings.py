"""Company settings: JSON values per company with code-declared defaults."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.modules.org.models import CompanySetting

if TYPE_CHECKING:
    from app.core.context import RequestContext


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    default: Any
    description: str


_registry: dict[str, SettingSpec] = {}


def register_setting(key: str, default: Any, description: str) -> None:
    """Declare a setting at import time. `default` must be JSON-serialisable; `description` is Turkish."""
    spec = SettingSpec(key=key, default=default, description=description)
    existing = _registry.get(key)
    if existing is not None and existing != spec:
        raise ValueError(f"Setting {key!r} is already registered with a different definition")
    _registry[key] = spec


def registered_settings() -> dict[str, SettingSpec]:
    return dict(_registry)


def _spec(key: str) -> SettingSpec:
    spec = _registry.get(key)
    if spec is None:
        raise LookupError(f"Setting {key!r} is not registered")
    return spec


def _stored(ctx: RequestContext, key: str) -> CompanySetting | None:
    return ctx.db.scalar(
        select(CompanySetting).where(CompanySetting.company_id == ctx.company_id, CompanySetting.key == key)
    )


def get_setting(ctx: RequestContext, key: str) -> Any:
    """Value of a registered setting in the active company, or its declared default."""
    spec = _spec(key)
    stored = _stored(ctx, key)
    return spec.default if stored is None else stored.value


def set_setting(ctx: RequestContext, key: str, value: Any) -> None:
    _spec(key)
    stored = _stored(ctx, key)
    if stored is None:
        ctx.db.add(CompanySetting(company_id=ctx.company_id, key=key, value=value))
    else:
        stored.value = value
    ctx.db.flush()
