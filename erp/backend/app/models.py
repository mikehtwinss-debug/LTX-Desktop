"""Imports every model module so `Base.metadata` is complete, and wires the model-level hooks.

Import this module (directly or through `app.main` / `app.seed`) before using the ORM.
"""

from app.core import audit  # noqa: F401  (registers the audit listeners)
from app.core.db import Base
from app.core.triggers import install_triggers
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.co import models as co_models  # noqa: F401
from app.modules.fi.models import documents, gl, partners, treasury  # noqa: F401
from app.modules.mm.models import inventory, invoice, master, purchasing  # noqa: F401
from app.modules.org import models as org_models  # noqa: F401

install_triggers(Base.metadata)

__all__ = ["Base"]
