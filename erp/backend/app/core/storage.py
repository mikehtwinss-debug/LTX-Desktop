"""File storage under `ERP_STORAGE_DIR`.

Files get generated names; callers keep the returned relative path (e.g. in `org_attachment`) and
never build paths from user input.
"""

import os
import re
import uuid
from datetime import date
from pathlib import Path, PurePosixPath

from app.core.config import get_settings
from app.core.errors import AppError, NotFound

_SAFE_EXTENSION = re.compile(r"\.[a-z0-9]{1,10}")
_SAFE_SEGMENT = re.compile(r"[a-z0-9_-]{1,64}")


def _root() -> Path:
    return get_settings().storage_dir.resolve()


def _extension(original_name: str) -> str:
    suffix = PurePosixPath(original_name.replace("\\", "/")).suffix.lower()
    return suffix if _SAFE_EXTENSION.fullmatch(suffix) else ""


def resolve_path(storage_path: str) -> Path:
    """Absolute path of a stored file; rejects anything that would leave the storage directory."""
    root = _root()
    candidate = (root / storage_path).resolve()
    if PurePosixPath(storage_path).is_absolute() or not candidate.is_relative_to(root) or candidate == root:
        raise AppError("INVALID_STORAGE_PATH", "Geçersiz dosya yolu")
    return candidate


def save_file(data: bytes, *, original_name: str, category: str) -> str:
    """Store `data` under a generated name and return its path relative to the storage directory.

    `category` is a short code-defined folder name such as `attachments`; the original name only
    contributes its extension.
    """
    if not _SAFE_SEGMENT.fullmatch(category):
        raise ValueError(f"Invalid storage category: {category!r}")
    today = date.today()
    relative = PurePosixPath(
        category, f"{today:%Y}", f"{today:%m}", f"{uuid.uuid4().hex}{_extension(original_name)}"
    )
    target = resolve_path(relative.as_posix())
    target.parent.mkdir(parents=True, exist_ok=True)
    # Written under a temporary name first so a crash never leaves a truncated file behind.
    temporary = target.with_name(f"{target.name}.part")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)
    return relative.as_posix()


def read_file(storage_path: str) -> bytes:
    path = resolve_path(storage_path)
    if not path.is_file():
        raise NotFound("FILE_NOT_FOUND", "Dosya bulunamadı")
    return path.read_bytes()


def delete_file(storage_path: str) -> None:
    """Remove a stored file; a file that is already gone is not an error."""
    resolve_path(storage_path).unlink(missing_ok=True)
