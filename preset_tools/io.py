"""
IO module — load and save preset JSON with Unicode preservation.

CRITICAL: always use ensure_ascii=False when saving. Python's default
json.dump escapes non-ASCII characters (em-dashes, smart quotes, etc.)
to \\uXXXX sequences, which corrupts the preset's formatting and breaks
visual diffing.
"""

import json
from typing import Any


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
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(preset, f, indent=2, ensure_ascii=False)


def preset_blocks(preset: dict) -> list[dict]:
    """
    Return the blocks array from a preset, regardless of schema.

    ThreadBare puts blocks at preset['blocks'].
    Lucid Loom puts them at preset['preset']['blocks'].
    """
    if 'preset' in preset and 'blocks' in preset['preset']:
        return preset['preset']['blocks']
    return preset['blocks']
