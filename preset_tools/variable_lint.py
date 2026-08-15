"""Repair and validate Lumiverse prompt-variable payloads.

Prompt variables have two LLM-hostile input shapes: ``options_json`` and
multiselect ``default_value`` are JSON strings *inside* the tool call (JSON
in JSON), and several parameters are silently dropped when they do not match
``var_type``.  This module provides the same safety net the regex tools use:

* :func:`repair_json_payload` tolerantly parses JSON-in-string fields,
  repairing over-escaped quotes, smart quotes, Python-literal syntax
  (single quotes, ``True``/``False``/``None``, trailing commas), and bare
  object keys — reporting every repair it applied.
* :func:`lint_variable_def` checks a built variable definition for the
  mistakes that otherwise save silently: a ``defaultValue`` that does not
  match any option id, duplicate option ids, ``min`` above ``max``,
  non-positive ``step``, duplicate variable names in a block, and parameters
  that were ignored because they do not apply to the variable's type.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any, Optional

_SENTINEL = object()

_SMART_QUOTES = {
    "\u201c": '"', "\u201d": '"',   # “ ”
    "\u2018": "'", "\u2019": "'",   # ‘ ’
    "\u2026": "...",
}
_BARE_KEY_RE = re.compile(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:)")
_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")


def _finding(severity: str, code: str, message: str, field: str = "variables") -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "field": field}


def _collapse_overescaped(s: str) -> str:
    """Turn over-escaped quote sequences (``\\"`` as two characters) into quotes."""
    return s.replace('\\"', '"')


def _normalize_smart_quotes(s: str) -> str:
    return "".join(_SMART_QUOTES.get(c, c) for c in s)


def _quote_bare_keys(s: str) -> str:
    return _BARE_KEY_RE.sub(r'\1"\2"\3', s)


# (diagnostic label, transform) pairs tried in order; the empty label means
# "try the input as-is first".
_JSON_TRANSFORMS = [
    ("", lambda s: s),
    ("collapsed over-escaped quote sequences", _collapse_overescaped),
    ("normalized smart quotes", _normalize_smart_quotes),
    ("quoted bare object keys", _quote_bare_keys),
    ("smart quotes and collapsed escapes", lambda s: _normalize_smart_quotes(_collapse_overescaped(s))),
    ("bare keys and collapsed escapes", lambda s: _quote_bare_keys(_collapse_overescaped(s))),
]


def repair_json_payload(raw: str) -> tuple[Optional[Any], list[dict[str, Any]], str]:
    """Tolerantly parse a JSON-in-string field such as ``options_json``.

    Returns ``(value, diagnostics, error_message)``.  On success the value is
    the parsed object and the error message is empty; every applied repair is
    reported as an info diagnostic.  On failure the value is None and the
    error message describes the original JSON syntax problem.
    """
    diagnostics: list[dict[str, Any]] = []
    s = (raw or "").strip()
    if not s:
        return None, diagnostics, "empty input"

    first_error = "unparseable"
    for label, transform in _JSON_TRANSFORMS:
        candidate = transform(s)
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as exc:
            if label == "":
                first_error = str(exc)
            continue
        if label:
            diagnostics.append(_finding(
                "info", "json_repair",
                f"repaired JSON payload: {label}",
            ))
        return value, diagnostics, ""

    # Python-literal syntax: single quotes, True/False/None, trailing commas.
    for transform in (lambda s: s, _normalize_smart_quotes):
        try:
            value = ast.literal_eval(transform(s))
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            continue
        if isinstance(value, (list, dict, str, int, float, bool)):
            diagnostics.append(_finding(
                "info", "python_literal",
                "parsed Python-literal syntax (single quotes, True/False/None, or trailing commas) as JSON",
            ))
            return value, diagnostics, ""

    return None, diagnostics, first_error


def normalize_default_value(var_type: str, default_value: Any, *, repair: bool = True) -> tuple[Any, list[dict[str, Any]]]:
    """Normalize an LLM-provided ``default_value`` before coercion.

    Repairs the JSON-in-string shapes: an over-escaped multiselect array
    (``[\\"a\\",\\"b\\"]``) and a select id wrapped in stray quotes.
    """
    if not repair or not isinstance(default_value, str):
        return default_value, []
    stripped = default_value.strip()

    if var_type == "multiselect" and stripped.startswith("["):
        value, diagnostics, error = repair_json_payload(stripped)
        if value is not None and isinstance(value, list):
            return value, diagnostics
        return default_value, diagnostics

    if var_type == "select" and len(stripped) >= 2 and stripped.startswith('"') and stripped.endswith('"'):
        inner = stripped[1:-1]
        if '"' not in inner:
            return inner, [_finding(
                "info", "stripped_surrounding_quotes",
                "stripped stray surrounding quotes from default_value",
            )]
    return default_value, []


def default_value_warnings(var_type: str, default_value: Any) -> list[dict[str, Any]]:
    """Warn when a string default cannot be honored and will be coerced."""
    if not isinstance(default_value, str) or not default_value.strip():
        return []
    s = default_value.strip()
    if var_type in ("number", "slider"):
        try:
            float(s)
        except ValueError:
            return [_finding(
                "warning", "unparseable_default",
                f"default_value '{s}' does not parse as a number; it will be coerced to 0",
            )]
    elif var_type == "switch" and s.lower() not in ("1", "true", "on", "yes", "0", "false", "off", "no"):
        return [_finding(
            "warning", "unparseable_default",
            f"default_value '{s}' is not a recognized switch value (1/true/on/yes/0/false/off/no); it will be coerced to 0",
        )]
    return []


def lint_variable_def(
    var_def: dict[str, Any],
    *,
    existing_names: Optional[list[str]] = None,
    ignored_fields: Optional[list[dict[str, str]]] = None,
) -> list[dict[str, Any]]:
    """Lint one built prompt-variable definition.

    ``existing_names`` are the other variable names in the same block (the
    definition under test is assumed to already be excluded).  Fields the
    caller dropped because they do not apply to ``var_type`` are reported as
    warnings instead of vanishing silently.
    """
    findings: list[dict[str, Any]] = []
    var_type = var_def.get("type")
    options = var_def.get("options") or []
    ids = [opt.get("id") for opt in options if isinstance(opt, dict)]

    name = var_def.get("name") or ""
    if name and not _NAME_RE.fullmatch(name):
        findings.append(_finding(
            "warning", "unusual_variable_name",
            f"variable name '{name}' contains characters that may break {{{{var::{name}}}}} macro resolution",
            field="name",
        ))
    if name and name in (existing_names or []):
        findings.append(_finding(
            "error", "duplicate_variable_name",
            f"a variable named '{name}' already exists in this block",
            field="name",
        ))

    if var_type in ("select", "multiselect"):
        seen: set[str] = set()
        for option_id in ids:
            if option_id in seen:
                findings.append(_finding(
                    "error", "duplicate_option_id",
                    f"option id '{option_id}' appears more than once",
                    field="options",
                ))
            seen.add(option_id)

        default = var_def.get("defaultValue")
        available = f"; available ids: {', '.join(str(i) for i in ids)}" if ids else " and the option list is empty"
        if var_type == "select" and isinstance(default, str) and default and ids and default not in ids:
            findings.append(_finding(
                "error", "unknown_option_default",
                f"defaultValue '{default}' does not match any option id{available}",
                field="defaultValue",
            ))
        if var_type == "multiselect" and isinstance(default, list):
            unknown = [str(d) for d in default if str(d) not in ids]
            if unknown:
                findings.append(_finding(
                    "error", "unknown_option_default",
                    f"defaultValue ids {unknown} do not match any option id{available}",
                    field="defaultValue",
                ))

    if var_type in ("number", "slider"):
        minimum = var_def.get("min")
        maximum = var_def.get("max")
        step = var_def.get("step")
        if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)):
            if minimum > maximum:
                findings.append(_finding(
                    "error", "reversed_range",
                    f"min ({minimum}) is greater than max ({maximum})",
                    field="min",
                ))
            elif minimum == maximum:
                findings.append(_finding(
                    "warning", "degenerate_range",
                    f"min and max are both {minimum}; the control cannot change",
                    field="min",
                ))
        if isinstance(step, (int, float)) and step <= 0:
            findings.append(_finding(
                "error", "invalid_step",
                f"step must be positive, got {step}",
                field="step",
            ))

    for entry in ignored_fields or []:
        findings.append(_finding(
            "warning", "ignored_field",
            f"'{entry['field']}' was ignored: {entry['reason']}",
            field=entry["field"],
        ))
    return findings
