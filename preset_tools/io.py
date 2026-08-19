"""
IO module — load and save preset JSON with Unicode preservation.

CRITICAL: always use ensure_ascii=False when saving. Python's default
json.dump escapes non-ASCII characters (em-dashes, smart quotes, etc.)
to \\uXXXX sequences, which corrupts the preset's formatting and breaks
visual diffing.
"""

import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .locking import preset_lock


def load(path: str) -> dict:
    """
    Load a preset JSON file.

    Handles both schema styles:
    - ThreadBare-style: top-level blocks array under preset['blocks']
    - Lucid Loom-style: blocks nested under preset['preset']['blocks']

    Returns the full preset dict. Use preset_blocks(preset) to get the
    blocks array regardless of schema.
    """
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save(preset: dict, path: str) -> None:
    """
    Save a preset JSON file with Unicode preservation.

    Uses ensure_ascii=False so em-dashes (—), smart quotes ('), accented
    characters, and CJK characters remain as literal Unicode rather than
    \\uXXXX escape sequences.

    Always uses indent=2 to match the Lumiverse export format.
    """
    # Never write directly over the live document.  A reader should observe
    # either the previous complete JSON document or the next complete one,
    # never a partially-truncated file.  The caller is responsible for the
    # corresponding read-modify-write lock.
    target = Path(path)
    previous_mode = None
    try:
        previous_mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        pass

    fd, temporary_path = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent or Path(".")), text=True,
    )
    try:
        if previous_mode is not None:
            os.chmod(temporary_path, previous_mode)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(preset, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, target)

        # Persist the directory entry as well as file contents on platforms
        # where directory fsync is supported.
        try:
            directory_fd = os.open(str(target.parent or Path(".")), os.O_RDONLY)
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


@contextmanager
def edit(path: str) -> Iterator[dict]:
    """Load, modify, and atomically save a preset under its sidecar lock.

    Use this for library-level read-modify-write work. Calling ``load`` and
    ``save`` independently still provides an atomic final save, but cannot
    protect the interval between them from another writer.
    """
    with preset_lock(path):
        preset = load(path)
        yield preset
        save(preset, path)


def preset_blocks(preset: dict) -> list[dict]:
    """
    Return the blocks array from a preset, regardless of schema.

    ThreadBare puts blocks at preset['blocks'].
    Lucid Loom puts them at preset['preset']['blocks'].
    """
    if 'preset' in preset and 'blocks' in preset['preset']:
        return preset['preset']['blocks']
    return preset['blocks']


def preset_root(preset: dict) -> dict:
    """
    Return the dict that holds the preset's live fields (blocks, prompt
    variables, prompt behavior, …), regardless of schema.

    ThreadBare keeps everything at the top level; Lucid Loom nests it under
    preset['preset'].
    """
    inner = preset.get('preset')
    if isinstance(inner, dict) and 'blocks' in inner:
        return inner
    return preset


def stored_prompt_vars(preset: dict) -> dict:
    """
    Return the stored prompt-variable values, keyed by block id.

    Mirrors the backend's ``preset.metadata.promptVariables`` — the end-user's
    saved values for a preset, merged over the creator's defaults at assembly
    time. Handles the backend's nested shape (``metadata.promptVariables``),
    the ThreadBare flat shape (top-level ``promptVariables``), and the Lucid
    Loom shape (``preset.promptVariables``).
    """
    root = preset_root(preset)
    meta = root.get('metadata')
    if isinstance(meta, dict) and isinstance(meta.get('promptVariables'), dict):
        return meta['promptVariables']
    pv = root.get('promptVariables')
    if isinstance(pv, dict):
        return pv
    return {}
