"""Tek Düzen Hesap Planı: the official main accounts with their class and group structure.

The data lives in `data/tdhp.json`. Besides seeding the chart of a new company, the class and
group names drive the balance sheet and income statement layouts.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.modules.fi.models.gl import AccountType, Side

DATA_DIR = Path(__file__).resolve().parent / "data"
_CONTRA_MARK = "(-)"


@dataclass(frozen=True, slots=True)
class ChartAccount:
    code: str
    name: str
    account_type: AccountType
    normal_side: Side

    @property
    def is_contra(self) -> bool:
        return self.name.endswith(_CONTRA_MARK)


@dataclass(frozen=True, slots=True)
class ChartGroup:
    code: str
    name: str
    accounts: tuple[ChartAccount, ...]


@dataclass(frozen=True, slots=True)
class ChartClass:
    code: str
    name: str
    groups: tuple[ChartGroup, ...]

    @property
    def accounts(self) -> tuple[ChartAccount, ...]:
        return tuple(account for group in self.groups for account in group.accounts)


def load_json(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _opposite(side: Side) -> Side:
    return Side.CREDIT if side is Side.DEBIT else Side.DEBIT


def _account(raw: dict[str, str], default_type: AccountType, class_side: Side) -> ChartAccount:
    name = raw["name"]
    if "side" in raw:
        side = Side(raw["side"])
    else:
        # Contra accounts are named with "(-)" and carry the opposite of the class's normal side.
        side = _opposite(class_side) if name.endswith(_CONTRA_MARK) else class_side
    return ChartAccount(
        code=raw["code"],
        name=name,
        account_type=AccountType(raw["type"]) if "type" in raw else default_type,
        normal_side=side,
    )


@lru_cache
def load_tdhp() -> tuple[ChartClass, ...]:
    classes = []
    for raw_class in load_json("tdhp.json")["classes"]:
        class_type = AccountType(raw_class["type"])
        class_side = Side(raw_class["side"])
        groups = []
        for raw_group in raw_class["groups"]:
            group_type = AccountType(raw_group["type"]) if "type" in raw_group else class_type
            accounts = tuple(_account(raw, group_type, class_side) for raw in raw_group["accounts"])
            groups.append(ChartGroup(code=raw_group["code"], name=raw_group["name"], accounts=accounts))
        classes.append(ChartClass(code=raw_class["code"], name=raw_class["name"], groups=tuple(groups)))
    return tuple(classes)


def main_accounts() -> list[ChartAccount]:
    return [account for chart_class in load_tdhp() for account in chart_class.accounts]
