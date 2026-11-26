"""Seed data. CLI: `python -m app.seed base` and `python -m app.seed company --code 1000 --name "..."`."""

from app.seed.base import seed_base
from app.seed.company import seed_company

__all__ = ["seed_base", "seed_company"]
