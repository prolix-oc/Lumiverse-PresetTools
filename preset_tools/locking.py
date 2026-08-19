"""Process-safe locking for preset documents.

The lock is deliberately a *sidecar* (``<preset>.lock``), rather than a lock
on the JSON file itself.  Atomic saves replace the JSON inode, while the
sidecar remains a stable synchronization point for the lifetime of a preset.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def preset_lock(path: str | Path) -> Iterator[None]:
    """Take an exclusive, advisory lock for one preset path.

    All preset-tools writers use this lock.  It coordinates separate MCP
    server processes as well as concurrent requests in a single process.  As
    with any advisory filesystem lock, external applications must cooperate
    by taking the same lock to be included in that guarantee.
    """
    target = Path(path).resolve()
    lock_path = target.with_name(target.name + ".lock")
    # The preset parent must already exist for a normal save; making only the
    # lock parent here also supports creation of a standalone regex export.
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        if os.name == "nt":  # pragma: no cover - exercised on Windows
            import msvcrt

            # Lock one byte.  Ensure the file has one before locking it.
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":  # pragma: no cover - exercised on Windows
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
