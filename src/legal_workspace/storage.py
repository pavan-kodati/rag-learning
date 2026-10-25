"""File storage for originals and normalised PDFs. Local disk by default; the interface fits S3/MinIO."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Protocol

from .errors import BadRequest, NotFound


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> str: ...

    def read(self, uri: str) -> bytes: ...

    def exists(self, uri: str) -> bool: ...

    def delete_prefix(self, prefix: str) -> int: ...


class FileStorage:
    """Stores under `root`; URIs are `file:<relative key>`. Rejects any key or URI that escapes the root."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if p != self.root and self.root not in p.parents:
            raise BadRequest("invalid storage path")
        return p

    def put(self, key: str, data: bytes) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_./\-]+", key) or ".." in key.split("/"):
            raise BadRequest("invalid storage key")
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)  # atomic
        return f"file:{key}"

    def read(self, uri: str) -> bytes:
        if not uri.startswith("file:"):
            raise BadRequest("unsupported storage uri")
        path = self._resolve(uri[5:])
        try:
            return path.read_bytes()
        except FileNotFoundError as e:
            raise NotFound("the stored file is missing") from e

    def exists(self, uri: str) -> bool:
        try:
            return uri.startswith("file:") and self._resolve(uri[5:]).is_file()
        except BadRequest:
            return False

    def delete_prefix(self, prefix: str) -> int:
        """Remove every stored file under `prefix` (e.g. when a matter is deleted). Returns files removed."""
        import shutil

        path = self._resolve(prefix)
        if path == self.root or not path.exists():
            return 0
        n = sum(1 for p in path.rglob("*") if p.is_file())
        shutil.rmtree(path, ignore_errors=True)
        return n


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
