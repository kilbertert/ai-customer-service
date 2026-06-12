"""Local-disk attachment storage backend (PR13).

Layout: ``{root}/{sha256[:2]}/{sha256}`` (two-char sharding to bound
per-directory fan-out). Atomic writes via ``.tmp`` + ``os.replace``.
File mode ``0o600``.

An ``S3Storage`` stub class ships for symmetry; PR13 only ships the
local driver. Swap in a real S3 client in a follow-up.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class MediaStorage:
    """Local-disk attachment backend. Bytes are sharded by sha256 prefix."""

    def __init__(self, root: str | None = None):
        from config import settings

        self.root = Path(
            root
            or os.environ.get("MEDIA_STORAGE_DIR")
            or settings.media_storage_dir
        )
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- internals ----------------------------------------------------------

    def _path(self, sha256: str) -> Path:
        return self.root / sha256[:2] / sha256

    # ---- public API --------------------------------------------------------

    def put(self, sha256: str, blob: bytes) -> str:
        """Persist *blob* under its sha256; returns the relative storage key.

        Idempotent: if the file already exists (sha256 hit), returns the same
        key without re-writing.
        """
        path = self._path(sha256)
        if path.exists():
            return str(path.relative_to(self.root))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(blob)
            os.fchmod(fh.fileno(), 0o600)
        os.replace(tmp, path)
        return str(path.relative_to(self.root))

    def get(self, storage_key: str) -> bytes:
        return (self.root / storage_key).read_bytes()

    def open_stream(self, storage_key: str) -> BinaryIO:
        return open(self.root / storage_key, "rb")

    def delete(self, storage_key: str) -> None:
        path = self.root / storage_key
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        # Best-effort: remove the (now empty) sharding parent dir.
        try:
            path.parent.rmdir()
        except OSError:
            pass


class S3Storage:
    """S3 stub — PR13 does not implement this; raise loudly if instantiated."""

    def __init__(self, *_, **__):
        raise NotImplementedError(
            "S3 storage is a stub in PR13. Use MediaStorage (local disk)."
        )
