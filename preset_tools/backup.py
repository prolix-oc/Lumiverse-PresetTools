"""
Backup module — snapshot preset files before edits and restore them later.

Backups are timestamped copies stored in a ``.preset-backups`` directory next
to the file by default. Override the location with ``PRESET_TOOLS_BACKUP_DIR``.

Automatic backups before writes are controlled by ``PRESET_TOOLS_AUTO_BACKUP``
(default ``1``/on; set ``0``/``off``/``false`` to disable).
"""

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional


def auto_backup_enabled() -> bool:
    """Return whether automatic pre-write backups are enabled."""
    return os.environ.get("PRESET_TOOLS_AUTO_BACKUP", "1").strip().lower() not in (
        "0", "off", "false", "no", "",
    )


def backup_dir_for(path: str) -> Path:
    """Return the backup directory for a file path."""
    env = os.environ.get("PRESET_TOOLS_BACKUP_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path(path).resolve().parent / ".preset-backups"


def backup_file(path: str) -> Optional[str]:
    """Create a timestamped backup copy of a file. Returns the backup path, or
    None if the source does not exist."""
    src = Path(path)
    if not src.exists():
        return None

    bdir = backup_dir_for(path)
    bdir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = src.stem
    dest = bdir / f"{stem}.{timestamp}{src.suffix}"
    n = 1
    while dest.exists():
        dest = bdir / f"{stem}.{timestamp}.{n}{src.suffix}"
        n += 1

    shutil.copy2(str(src), str(dest))
    return str(dest)


def list_backups(path: str) -> list[dict]:
    """Return backups for a file, oldest first.

    Each entry is ``{name, path, size, mtime}``.
    """
    src = Path(path)
    bdir = backup_dir_for(path)
    if not bdir.exists():
        return []
    stem = src.stem
    out = []
    for f in sorted(bdir.glob(f"{stem}.*{src.suffix}")):
        try:
            st = f.stat()
            out.append({
                "name": f.name,
                "path": str(f),
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
        except OSError:
            continue
    return out


def resolve_backup(path: str, backup: str) -> Path:
    """Resolve a backup reference: an absolute path, or a filename relative to
    the file's backup directory."""
    bp = Path(backup)
    if bp.is_absolute():
        return bp
    return backup_dir_for(path) / backup


def restore_backup(path: str, backup: str) -> str:
    """Restore a backup over the target file, after snapshotting the current
    file. Returns the restored target path."""
    src = resolve_backup(path, backup)
    if not src.exists():
        raise FileNotFoundError(f"backup '{backup}' not found")

    backup_file(path)  # protect the current file before overwriting
    target = Path(path)
    fd, temporary_path = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".restore.tmp", dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as temporary, src.open("rb") as source:
            shutil.copyfileobj(source, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
        shutil.copystat(src, temporary_path)
        os.replace(temporary_path, target)
        try:
            directory_fd = os.open(str(target.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise
    return str(path)
