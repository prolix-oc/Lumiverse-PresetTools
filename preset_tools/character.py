"""
Character card editing utilities for chara_card_v3 spec.

Provides safe getters / setters for the core fields an LLM is most likely
to enhance (description, personality, scenario, first_mes, etc.) as well as
nested extension fields via dot-notation paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Core fields under card["data"] that are most commonly edited.
CORE_STRING_FIELDS = [
    "name",
    "description",
    "personality",
    "scenario",
    "first_mes",
    "mes_example",
    "creator",
    "creator_notes",
    "system_prompt",
    "post_history_instructions",
    "character_version",
]

CORE_LIST_FIELDS = [
    "tags",
    "alternate_greetings",
]

CORE_FIELDS = CORE_STRING_FIELDS + CORE_LIST_FIELDS


def _get_data(card: dict) -> dict:
    if not isinstance(card, dict):
        raise ValueError("Character card must be a JSON object")
    if "data" not in card:
        raise ValueError("Character card missing top-level 'data' key")
    return card["data"]


def get_field(card: dict, field: str) -> Any:
    """Get a field from the character card data section.

    Supports dot notation for nested values, e.g.
        ``extensions.talkativeness``
        ``extensions.depth_prompt.prompt``
    """
    data = _get_data(card)
    parts = field.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Field '{field}' not found in character card")
            current = current[part]
        else:
            raise KeyError(f"Cannot traverse into non-dict at '{part}' of '{field}'")
    return current


def set_field(card: dict, field: str, value: Any) -> None:
    """Set a field in the character card data section.

    Supports dot notation for nested values.  Missing intermediate dicts are
    created automatically.
    """
    data = _get_data(card)
    parts = field.split(".")
    current: Any = data
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]
        if not isinstance(current, dict):
            raise ValueError(
                f"Cannot set nested field '{field}': intermediate value is not a dict"
            )
    current[parts[-1]] = value


def get_summary(card: dict) -> dict[str, Any]:
    """Return a summary of all core character card fields with char counts."""
    data = _get_data(card)
    summary: dict[str, Any] = {}
    for field in CORE_FIELDS:
        val = data.get(field)
        if isinstance(val, str):
            summary[field] = {"value": val, "chars": len(val)}
        elif isinstance(val, list):
            summary[field] = {"value": val, "items": len(val)}
        else:
            summary[field] = {"value": val}
    summary["extensions"] = data.get("extensions", {})
    return summary


def validate_card(card: dict) -> dict[str, Any]:
    """Validate a character card against basic v3 spec expectations."""
    errors: list[str] = []
    warnings: list[str] = []

    if card.get("spec") != "chara_card_v3":
        errors.append(f"Expected spec 'chara_card_v3', got '{card.get('spec')}'")
    if "data" not in card:
        errors.append("Missing top-level 'data' key")
        return {"ok": False, "errors": errors, "warnings": warnings}

    data = card["data"]
    for field in ("name", "description"):
        if not data.get(field):
            warnings.append(f"Core field '{field}' is empty or missing")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


def load_card(path: str) -> dict:
    """Load a character card JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_card(card: dict, path: str) -> None:
    """Save a character card JSON file with Unicode preservation."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(card, f, indent=2, ensure_ascii=False)


def token_estimate(text: Any) -> int:
    """Rough token estimate for a value (chars // 4)."""
    if isinstance(text, str):
        return len(text) // 4
    if isinstance(text, list):
        return sum(token_estimate(item) for item in text)
    return 0


def field_stats(card: dict, field: str) -> dict[str, Any]:
    """Return char count and rough token estimate for a single field."""
    value = get_field(card, field)
    chars = len(value) if isinstance(value, str) else None
    approx_tokens = token_estimate(value)
    return {
        "field": field,
        "chars": chars,
        "approx_tokens": approx_tokens,
        "type": type(value).__name__,
    }
