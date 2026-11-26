"""Router factory: every API router uses the transactional route class."""

from collections.abc import Sequence
from enum import Enum

from fastapi import APIRouter, params

from app.core.transaction import TransactionalRoute


def make_router(
    prefix: str, tags: Sequence[str | Enum], *, dependencies: Sequence[params.Depends] | None = None
) -> APIRouter:
    return APIRouter(
        prefix=prefix, tags=list(tags), dependencies=dependencies, route_class=TransactionalRoute
    )
