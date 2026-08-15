"""Helpers for editing Lumiverse regex scripts.

Regex scripts can live in either of the JSON shapes used by Lumiverse:

* Preset: ``document["extensions"]["regex_scripts"]``
* Standalone export: ``{"type": "lumiverse_regex_scripts", "scripts": [...]}``

The helpers in this module deliberately do not compile ``find_regex`` with
Python's regex engine.  Lumiverse patterns use JavaScript syntax (including
named captures such as ``(?<name>...)``), which Python does not accept.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal, Optional


RegexContainer = Literal["auto", "preset", "standalone"]
STANDALONE_TYPE = "lumiverse_regex_scripts"
REQUIRED_FIELDS = ("name", "script_id", "find_regex", "replace_string")
_STRING_FIELDS = (
    "name",
    "script_id",
    "find_regex",
    "replace_string",
    "flags",
    "scope",
    "substitute_macros",
    "description",
    "folder",
)
_LIST_FIELDS = ("placement", "target", "trim_strings", "actions")
_BOOL_FIELDS = ("run_on_edit", "disabled")
_INT_OR_NONE_FIELDS = ("min_depth", "max_depth")
_JS_FLAGS = frozenset("dgimsuvy")


def new_regex_export(*, exported_at: int = 0) -> dict[str, Any]:
    """Return an empty standalone Lumiverse regex export document."""
    return {
        "version": 1,
        "type": STANDALONE_TYPE,
        "scripts": [],
        "exported_at": exported_at,
    }


def _looks_like_preset(document: dict[str, Any]) -> bool:
    return any(
        key in document
        for key in ("blocks", "preset", "extensions", "presetVersion", "schemaVersion")
    )


def regex_scripts(
    document: dict[str, Any],
    *,
    container: RegexContainer = "auto",
    create: bool = False,
) -> tuple[list[dict[str, Any]], Literal["preset", "standalone"]]:
    """Return a document's script list and detected container kind.

    With ``create=True``, a missing ``extensions.regex_scripts`` list is
    created for a recognizable preset.  Standalone documents must already
    have their ``scripts`` list; use :func:`new_regex_export` for a new one.
    """
    if not isinstance(document, dict):
        raise ValueError("regex document must be a JSON object")

    standalone = document.get("type") == STANDALONE_TYPE or "scripts" in document
    preset = _looks_like_preset(document)

    if container == "standalone":
        if not standalone:
            raise ValueError("document is not a standalone Lumiverse regex export")
        kind: Literal["preset", "standalone"] = "standalone"
    elif container == "preset":
        if standalone and not preset:
            raise ValueError("document is a standalone regex export, not a preset")
        kind = "preset"
    elif standalone:
        kind = "standalone"
    elif preset:
        kind = "preset"
    else:
        raise ValueError(
            "could not detect JSON shape; expected a preset or standalone Lumiverse regex export"
        )

    if kind == "standalone":
        if create:
            existing_type = document.get("type")
            if existing_type is not None and existing_type != STANDALONE_TYPE:
                raise ValueError(
                    f"standalone 'type' must be '{STANDALONE_TYPE}', got {existing_type!r}"
                )
            document.setdefault("type", STANDALONE_TYPE)
            document.setdefault("version", 1)
        scripts = document.get("scripts")
        if not isinstance(scripts, list):
            raise ValueError("standalone regex export 'scripts' must be an array")
    else:
        extensions = document.get("extensions")
        if extensions is None and create:
            extensions = {}
            document["extensions"] = extensions
        if not isinstance(extensions, dict):
            if extensions is None:
                return [], kind
            raise ValueError("preset 'extensions' must be an object")

        scripts = extensions.get("regex_scripts")
        if scripts is None and create:
            scripts = []
            extensions["regex_scripts"] = scripts
        if scripts is None:
            return [], kind
        if not isinstance(scripts, list):
            raise ValueError("preset 'extensions.regex_scripts' must be an array")

    for index, script in enumerate(scripts):
        if not isinstance(script, dict):
            raise ValueError(f"regex script at index {index} must be an object")
    return scripts, kind


def new_regex_script(
    *,
    name: str,
    script_id: str,
    find_regex: str,
    replace_string: str,
    flags: str = "gi",
    placement: Optional[list[str]] = None,
    target: Optional[list[str]] = None,
    scope: str = "global",
    disabled: bool = False,
    description: str = "",
    sort_order: int = 100,
    options: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a reference-complete regex script like the ThreadBare entries."""
    script: dict[str, Any] = {
        "name": name,
        "script_id": script_id,
        "find_regex": find_regex,
        "replace_string": replace_string,
        "flags": flags,
        "placement": list(placement if placement is not None else ["ai_output"]),
        "scope": scope,
        "scope_id": None,
        "target": list(target if target is not None else ["display"]),
        "min_depth": None,
        "max_depth": None,
        "trim_strings": [],
        "run_on_edit": True,
        "substitute_macros": "none",
        "disabled": disabled,
        "sort_order": sort_order,
        "description": description,
        "folder": "",
        "metadata": {},
    }
    if options:
        reserved = set(REQUIRED_FIELDS) | {"flags", "placement", "target", "scope", "disabled", "description", "sort_order"}
        overlap = reserved.intersection(options)
        if overlap:
            fields = ", ".join(sorted(overlap))
            raise ValueError(f"options cannot override explicit fields: {fields}")
        script.update(deepcopy(options))

    result = validate_regex_script(script)
    if result["errors"]:
        raise ValueError("; ".join(result["errors"]))
    return script


def validate_regex_script(script: dict[str, Any]) -> dict[str, list[str]]:
    """Structurally validate one JavaScript regex script."""
    errors: list[str] = []
    warnings: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in script:
            errors.append(f"missing required field '{field}'")

    for field in _STRING_FIELDS:
        if field in script and not isinstance(script[field], str):
            errors.append(f"'{field}' must be a string")
    for field in ("name", "script_id", "find_regex"):
        if isinstance(script.get(field), str) and not script[field]:
            errors.append(f"'{field}' must not be empty")

    flags = script.get("flags")
    if isinstance(flags, str):
        invalid = sorted(set(flags) - _JS_FLAGS)
        duplicates = sorted({flag for flag in flags if flags.count(flag) > 1})
        if invalid:
            errors.append(f"'flags' contains unsupported JavaScript flags: {''.join(invalid)}")
        if duplicates:
            errors.append(f"'flags' contains duplicate flags: {''.join(duplicates)}")

    for field in _LIST_FIELDS:
        if field in script and not isinstance(script[field], list):
            errors.append(f"'{field}' must be an array")
    for field in ("placement", "target", "trim_strings"):
        if isinstance(script.get(field), list) and not all(isinstance(v, str) for v in script[field]):
            errors.append(f"'{field}' entries must be strings")
    for field in _BOOL_FIELDS:
        if field in script and not isinstance(script[field], bool):
            errors.append(f"'{field}' must be a boolean")
    for field in _INT_OR_NONE_FIELDS:
        value = script.get(field)
        if field in script and value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            errors.append(f"'{field}' must be an integer or null")
    if "sort_order" in script and (not isinstance(script["sort_order"], int) or isinstance(script["sort_order"], bool)):
        errors.append("'sort_order' must be an integer")
    if "metadata" in script and not isinstance(script["metadata"], dict):
        errors.append("'metadata' must be an object")

    actions = script.get("actions")
    if isinstance(actions, list):
        action_ids: set[str] = set()
        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                errors.append(f"'actions[{index}]' must be an object")
                continue
            action_id = action.get("id")
            if not isinstance(action_id, str) or not action_id:
                errors.append(f"'actions[{index}].id' must be a non-empty string")
            elif action_id in action_ids:
                errors.append(f"duplicate action id '{action_id}'")
            else:
                action_ids.add(action_id)

    if "placement" not in script:
        warnings.append("missing optional field 'placement'")
    if "target" not in script:
        warnings.append("missing optional field 'target'")
    return {"errors": errors, "warnings": warnings}


def validate_regex_document(
    document: dict[str, Any], *, container: RegexContainer = "auto"
) -> dict[str, Any]:
    """Validate a preset's embedded scripts or a standalone export."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        scripts, kind = regex_scripts(document, container=container)
    except ValueError as exc:
        return {"ok": False, "container": None, "script_count": 0, "errors": [str(exc)], "warnings": []}

    if kind == "standalone":
        if document.get("type") != STANDALONE_TYPE:
            errors.append(f"standalone 'type' must be '{STANDALONE_TYPE}'")
        if not isinstance(document.get("version"), int):
            errors.append("standalone 'version' must be an integer")

    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for index, script in enumerate(scripts):
        result = validate_regex_script(script)
        label = script.get("script_id") or script.get("name") or str(index)
        errors.extend(f"script[{index}] ({label}): {message}" for message in result["errors"])
        warnings.extend(f"script[{index}] ({label}): {message}" for message in result["warnings"])

        script_id = script.get("script_id")
        if isinstance(script_id, str):
            if script_id in seen_ids:
                errors.append(f"duplicate script_id '{script_id}'")
            seen_ids.add(script_id)
        name = script.get("name")
        if isinstance(name, str):
            if name in seen_names:
                warnings.append(f"duplicate script name '{name}'")
            seen_names.add(name)

    return {
        "ok": not errors,
        "container": kind,
        "script_count": len(scripts),
        "errors": errors,
        "warnings": warnings,
    }


def find_regex_script(
    document: dict[str, Any], identifier: str
) -> tuple[dict[str, Any], int, Literal["preset", "standalone"]]:
    """Find by exact script_id, falling back to an exact unique name."""
    scripts, kind = regex_scripts(document)
    id_matches = [(index, script) for index, script in enumerate(scripts) if script.get("script_id") == identifier]
    if len(id_matches) == 1:
        index, script = id_matches[0]
        return script, index, kind
    if len(id_matches) > 1:
        raise ValueError(f"multiple regex scripts have script_id '{identifier}'")

    name_matches = [(index, script) for index, script in enumerate(scripts) if script.get("name") == identifier]
    if len(name_matches) == 1:
        index, script = name_matches[0]
        return script, index, kind
    if len(name_matches) > 1:
        raise ValueError(f"multiple regex scripts have name '{identifier}'; use script_id")
    raise KeyError(f"regex script '{identifier}' not found")


def insert_regex_script(
    document: dict[str, Any],
    script: dict[str, Any],
    *,
    container: RegexContainer = "auto",
    index: Optional[int] = None,
) -> tuple[int, Literal["preset", "standalone"]]:
    """Insert a validated script, rejecting duplicate IDs."""
    result = validate_regex_script(script)
    if result["errors"]:
        raise ValueError("; ".join(result["errors"]))
    scripts, kind = regex_scripts(document, container=container, create=True)
    script_id = script["script_id"]
    if any(existing.get("script_id") == script_id for existing in scripts):
        raise ValueError(f"regex script_id '{script_id}' already exists")

    if index is None:
        index = len(scripts)
    if index < 0 or index > len(scripts):
        raise ValueError(f"index must be between 0 and {len(scripts)}")
    scripts.insert(index, deepcopy(script))
    return index, kind


def update_regex_script(
    document: dict[str, Any],
    identifier: str,
    updates: dict[str, Any],
    *,
    remove_fields: Optional[list[str]] = None,
) -> tuple[dict[str, Any], int, Literal["preset", "standalone"]]:
    """Patch a script atomically and return the updated script."""
    if not isinstance(updates, dict):
        raise ValueError("updates must be an object")
    current, index, kind = find_regex_script(document, identifier)
    candidate = deepcopy(current)
    candidate.update(deepcopy(updates))
    for field in remove_fields or []:
        if field in REQUIRED_FIELDS:
            raise ValueError(f"cannot remove required field '{field}'")
        candidate.pop(field, None)

    result = validate_regex_script(candidate)
    if result["errors"]:
        raise ValueError("; ".join(result["errors"]))

    scripts, _ = regex_scripts(document, container=kind)
    new_id = candidate["script_id"]
    if any(i != index and script.get("script_id") == new_id for i, script in enumerate(scripts)):
        raise ValueError(f"regex script_id '{new_id}' already exists")
    scripts[index] = candidate
    return candidate, index, kind


def delete_regex_script(
    document: dict[str, Any], identifier: str
) -> tuple[dict[str, Any], int, Literal["preset", "standalone"]]:
    """Delete a script by ID or unique exact name."""
    _, index, kind = find_regex_script(document, identifier)
    scripts, _ = regex_scripts(document, container=kind)
    return scripts.pop(index), index, kind


def script_summary(script: dict[str, Any], index: int) -> dict[str, Any]:
    """Return a compact script summary suitable for MCP listings."""
    return {
        "index": index,
        "name": script.get("name"),
        "script_id": script.get("script_id"),
        "disabled": script.get("disabled", False),
        "flags": script.get("flags", ""),
        "placement": script.get("placement", []),
        "target": script.get("target", []),
        "sort_order": script.get("sort_order"),
        "find_regex_chars": len(script.get("find_regex", "")) if isinstance(script.get("find_regex", ""), str) else None,
        "replace_string_chars": len(script.get("replace_string", "")) if isinstance(script.get("replace_string", ""), str) else None,
        "actions": len(script.get("actions", [])) if isinstance(script.get("actions", []), list) else None,
    }
