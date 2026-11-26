"""Feature discovery: every package under `app.modules` may contribute a router and permissions.

There is no shared registration file. A feature is a package with an `api.py` exposing `router`
and, usually, a `permissions.py` exposing `PERMISSIONS` (key -> Turkish description). Importing the
package runs its registrations (number ranges, settings, approval handlers).
"""

import importlib
import importlib.util
import pkgutil
from collections.abc import Sequence
from dataclasses import dataclass, field

from fastapi import APIRouter

import app.modules

ALWAYS_LOADED = ("auth", "org", "co")
_ROOT = "app.modules"


@dataclass(slots=True)
class Discovery:
    features: list[str] = field(default_factory=list)
    routers: list[APIRouter] = field(default_factory=list)
    permissions: dict[str, str] = field(default_factory=dict)


def _package_names() -> list[str]:
    """Dotted names, relative to `app.modules`, of every package below it."""
    prefix = f"{_ROOT}."
    names = [
        info.name.removeprefix(prefix)
        for info in pkgutil.walk_packages(app.modules.__path__, prefix)
        if info.ispkg
    ]
    return sorted(names)


def _covers(selection: str, name: str) -> bool:
    return name == selection or name.startswith(f"{selection}.")


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def discover_features(enabled: Sequence[str] | None = None) -> Discovery:
    """Import the feature packages and collect their routers and permissions.

    `enabled` (from `ERP_FEATURES`) restricts discovery to the named packages and everything below
    them; `auth`, `org` and `co` are always included. Parent packages of an enabled feature are
    imported for their side effects but contribute nothing themselves.
    """
    names = _package_names()
    if enabled is None:
        selected = names
    else:
        selections = [*ALWAYS_LOADED, *enabled]
        unknown = [selection for selection in selections if selection not in names]
        if unknown:
            raise ValueError(f"Unknown feature(s) in ERP_FEATURES: {', '.join(unknown)}")
        selected = [name for name in names if any(_covers(selection, name) for selection in selections)]

    discovery = Discovery()
    for name in selected:
        package = f"{_ROOT}.{name}"
        importlib.import_module(package)
        discovery.features.append(name)
        if _has_module(f"{package}.permissions"):
            declared: dict[str, str] = importlib.import_module(f"{package}.permissions").PERMISSIONS
            duplicates = declared.keys() & discovery.permissions.keys()
            if duplicates:
                raise ValueError(f"Permission keys declared twice: {', '.join(sorted(duplicates))}")
            discovery.permissions.update(declared)
        if _has_module(f"{package}.api"):
            discovery.routers.append(importlib.import_module(f"{package}.api").router)
    return discovery
