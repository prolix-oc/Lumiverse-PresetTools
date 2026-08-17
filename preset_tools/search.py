"""
Search module — unified block search across prompt blocks, prompt
variables, and categories.

Use these to locate content anywhere in a preset without knowing ahead of
time whether the match lives in a block name, block content, a prompt
variable definition, or a category header.
"""

import re
from typing import Any, Optional

from .io import preset_blocks


def _matcher(query: str, case_sensitive: bool, regex: bool) -> re.Pattern:
    """Build a compiled matcher for the query.

    Literal mode escapes the query; case-insensitivity uses IGNORECASE so
    multi-char folds (e.g. ``ß`` -> ``ss``) are handled correctly.
    """
    pattern = query if regex else re.escape(query)
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(pattern, flags)


def block_categories(preset: dict) -> list[dict]:
    """Return per-block category membership.

    A block with ``marker == 'category'`` starts a section and is its own
    category; every following block belongs to that section until the next
    category marker. Blocks before the first category marker have ``category``
    of ``None``.
    """
    out: list[dict] = []
    current: Optional[str] = None
    for i, b in enumerate(preset_blocks(preset)):
        is_category = b.get("marker") == "category"
        if is_category:
            current = b.get("name")
        out.append({
            "name": b.get("name"),
            "index": i,
            "category": current,
            "is_category": is_category,
            "marker": b.get("marker"),
        })
    return out


def list_categories(preset: dict) -> list[str]:
    """Return the names of all category blocks, in preset order."""
    return [b.get("name") for b in preset_blocks(preset) if b.get("marker") == "category"]


def _snippet(text: str, start: int, end: int, radius: int) -> str:
    """Return a whitespace-collapsed window of text around a match span."""
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    body = re.sub(r"\s+", " ", text[lo:hi]).strip()
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(text) else ""
    return prefix + body + suffix


def _variable_searchable_fields(var: dict) -> dict[str, str]:
    """Map a prompt variable definition to its searchable text fields."""
    fields: dict[str, str] = {}
    if var.get("name"):
        fields["name"] = str(var["name"])
    if var.get("label"):
        fields["label"] = str(var["label"])
    if var.get("description"):
        fields["description"] = str(var["description"])
    options = var.get("options") or []
    if options:
        parts = []
        for opt in options:
            if isinstance(opt, dict):
                parts.append(
                    f'{opt.get("id", "")} {opt.get("label", "")} {opt.get("value", "")}'
                )
            else:
                parts.append(str(opt))
        fields["options"] = " ".join(parts)
    return fields


def _variable_summary(var: dict) -> dict:
    return {
        "name": var.get("name"),
        "label": var.get("label"),
        "type": var.get("type"),
        "default": var.get("defaultValue"),
    }


def search_preset(
    preset: dict,
    query: str,
    *,
    case_sensitive: bool = False,
    regex: bool = False,
    surfaces: Optional[list[str]] = None,
    category: Optional[str] = None,
    enabled_only: bool = False,
    snippet_radius: int = 60,
    limit: Optional[int] = None,
) -> dict:
    """Search a preset across blocks, prompt variables, and categories.

    ``surfaces`` is a subset of ``{"blocks", "variables", "categories"}``
    (default: all three). ``blocks`` matches block names and content,
    ``variables`` matches prompt-variable name/label/description/options, and
    ``categories`` matches category header names.

    ``category`` restricts results to a single section. ``enabled_only``
    skips disabled blocks. ``regex`` treats ``query`` as a regular
    expression; otherwise it is a case-insensitive literal (unless
    ``case_sensitive`` is set).

    Returns a dict with ``query``, ``counts``, and an ordered ``matches``
    list. Each match records its surface type, owning block, section,
    matched field, and a context snippet.
    """
    if not query:
        raise ValueError("query is required")

    if surfaces is None:
        surfaces = ["blocks", "variables", "categories"]
    surfaces = list(dict.fromkeys(surfaces))  # dedupe, preserve order
    valid = {"blocks", "variables", "categories"}
    unknown = [s for s in surfaces if s not in valid]
    if unknown:
        raise ValueError(f"unknown surfaces: {unknown}; expected subset of {sorted(valid)}")

    if category is not None:
        available = list_categories(preset)
        if category not in available:
            raise ValueError(
                f"category '{category}' not found; available categories: {available}"
            )

    matcher = _matcher(query, case_sensitive, regex)
    blocks = preset_blocks(preset)
    cats = block_categories(preset)

    matches: list[dict[str, Any]] = []
    counts = {"blocks": 0, "variables": 0, "categories": 0}

    for i, b in enumerate(blocks):
        meta = cats[i]
        section = meta["category"]
        name = b.get("name") or ""
        enabled = bool(b.get("enabled", True))
        is_category = meta["is_category"]

        if enabled_only and not enabled:
            continue
        if category is not None and section != category:
            continue

        name_match = bool(matcher.search(name))
        emit_category = is_category and "categories" in surfaces and name_match

        if emit_category:
            counts["categories"] += 1
            matches.append({
                "type": "category",
                "block": name,
                "index": i,
                "category": section,
                "enabled": enabled,
                "field": "name",
                "match": name,
                "match_count": None,
                "snippet": None,
                "variable": None,
            })
        elif "blocks" in surfaces and name_match:
            counts["blocks"] += 1
            matches.append({
                "type": "block_name",
                "block": name,
                "index": i,
                "category": section,
                "enabled": enabled,
                "field": "name",
                "match": name,
                "match_count": None,
                "snippet": None,
                "variable": None,
            })

        if "blocks" in surfaces:
            content = b.get("content") or ""
            spans = list(matcher.finditer(content)) if content else []
            if spans:
                counts["blocks"] += 1
                first = spans[0]
                matches.append({
                    "type": "block_content",
                    "block": name,
                    "index": i,
                    "category": section,
                    "enabled": enabled,
                    "field": "content",
                    "match": content[first.start():first.end()],
                    "match_count": len(spans),
                    "snippet": _snippet(content, first.start(), first.end(), snippet_radius),
                    "variable": None,
                })

        if "variables" in surfaces:
            for var in (b.get("variables") or []):
                fields: list[str] = []
                short_match: Optional[str] = None
                matched_snippet: Optional[str] = None
                for field, text in _variable_searchable_fields(var).items():
                    spans = list(matcher.finditer(text))
                    if not spans:
                        continue
                    fields.append(field)
                    if field in ("name", "label"):
                        short_match = text
                    elif matched_snippet is None:
                        matched_snippet = _snippet(text, spans[0].start(), spans[0].end(), snippet_radius)
                if fields:
                    counts["variables"] += 1
                    matches.append({
                        "type": "prompt_variable",
                        "block": name,
                        "index": i,
                        "category": section,
                        "enabled": enabled,
                        "field": ", ".join(fields),
                        "match": short_match,
                        "match_count": None,
                        "snippet": matched_snippet,
                        "variable": _variable_summary(var),
                    })

    if limit is not None:
        matches = matches[:limit]

    return {
        "query": query,
        "case_sensitive": case_sensitive,
        "regex": regex,
        "surfaces": surfaces,
        "category": category,
        "total_matches": len(matches),
        "counts": counts,
        "matches": matches,
    }
