"""
MCP server for preset_tools — exposes Lumiverse preset editing
utilities as Model Context Protocol tools.

Run directly (stdio transport, for local MCP clients):
    python -m preset_tools.mcp_server

Or via the installed console script:
    preset-tools-mcp

Environment:
    PRESET_TOOLS_WORKSPACE  root directory for relative preset paths
                            (defaults to the server's current working directory)
    PRESET_TOOLS_MACRO_DIR  directory containing macro_reference.json and
                            macro_reference.md (defaults to this package's
                            directory)
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import inspect
import json
import logging
import os
import re
import traceback
import typing
from difflib import unified_diff
from io import StringIO
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

from pydantic import Field

from mcp.server.fastmcp import FastMCP

from .audit import audit, list_blocks, token_count
from .backup import auto_backup_enabled, backup_file, list_backups, restore_backup
from .blocks import (
    add_prompt_variable,
    clone_block,
    delete_block,
    find_block,
    find_block_index,
    get_block_lines,
    get_seal_status,
    apply_unified_diff,
    insert_block,
    is_unified_diff,
    list_prompt_variables,
    mass_set_seal,
    modify_block,
    move_block,
    new_block,
    remove_prompt_variable,
    rename_block,
    set_block_seal,
    set_stored_prompt_variable,
    stored_variable_report,
    toggle_block,
    update_prompt_variable,
    rewrite_variable_references,
)
from .compare import diff_presets
from .inspect import (
    dump_enabled_to_file,
    extract_macros,
    find_blocks_referencing,
    get_section,
    show_block,
)
from .io import load, preset_blocks, save
from .locking import preset_lock
from .search import search_preset
from .replace import (
    REPLACE_MODES,
    REPLACE_SURFACES,
    ReplaceRejected,
    check_replace,
    replace_in_preset,
)
from .render import RenderEnv, render_block, render_preset
from .lumiverse import render_preset_live
from .regex_lint import (
    engine_compile,
    engine_compile_many,
    engine_kind,
    engine_render,
    lint_js_pattern,
    lint_script,
    normalize_pattern_input,
    normalize_replacement_input,
)
from .regex_scripts import (
    delete_regex_script as _delete_regex_script,
    find_regex_script,
    insert_regex_script,
    new_regex_export,
    new_regex_script,
    regex_scripts,
    script_summary,
    update_regex_script,
    validate_regex_document,
)
from .validate import _SEV_RANK, validate_file, variable_report
from .variable_lint import (
    default_value_warnings,
    lint_variable_def,
    normalize_default_value,
    repair_json_payload,
)
from . import character as _char

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "preset_tools_mcp",
    instructions=(
        "Preset writes are serialized per file and committed atomically. "
        "Every successful write returns its revision. You may issue multiple "
        "independent writes to the same preset in one turn: they are safely "
        "serialized against the latest saved document. When an edit depends on "
        "a previously-read version, pass expected_revision from that read; a "
        "mismatch returns RevisionConflict and makes no change. Do not use a "
        "stale revision for multiple dependent edits—make them in call order or "
        "refresh after a conflict. For edits to existing block content, prefer "
        "preset_modify_block with a standard unified diff containing one or more "
        "@@ hunks. Use the read-only line tools only to inspect a small block portion."
    ),
)

WORKSPACE_ROOT = Path(os.environ.get("PRESET_TOOLS_WORKSPACE", os.getcwd())).resolve()

PathArg = Annotated[
    str,
    Field(
        ...,
        description=(
            "Path to the preset JSON file. Relative paths are resolved against "
            "the workspace root; absolute paths are accepted verbatim."
        ),
        min_length=1,
    ),
]

RevisionArg = Annotated[
    Optional[str],
    Field(
        description=(
            "Optional SHA-256 revision returned by a prior write. When supplied, "
            "the edit is rejected with RevisionConflict unless the file is still "
            "at exactly that revision. Omit for an intent-based edit that should "
            "be serialized against the latest saved preset."
        ),
    ),
]


def _resolve_path(path: str) -> Path:
    """Resolve a user-supplied path.

    Absolute paths are returned as-is. Relative paths are resolved against
    WORKSPACE_ROOT (including paths that traverse above it, e.g. ../..).
    """
    if not path:
        raise ValueError("path is required")
    p = Path(path)
    if p.is_absolute():
        return p.resolve()
    return (WORKSPACE_ROOT / path).resolve()


def _revision(path: Path) -> Optional[str]:
    """Return the byte-level revision of a document, or ``None`` if missing."""
    try:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except FileNotFoundError:
        return None


def _with_write_revision(response: str, *, before: Optional[str], after: Optional[str]) -> str:
    """Add transaction metadata without changing individual tool bodies."""
    try:
        payload = json.loads(response)
    except (TypeError, json.JSONDecodeError):
        return response
    if payload.get("ok") and isinstance(payload.get("result"), dict):
        result = payload["result"]
        result.setdefault("base_revision", before)
        result.setdefault("revision", after)
        result.setdefault("write_serialized", True)
        return json.dumps(payload, indent=2, ensure_ascii=False)
    return response


def _guard_preset_write(func):
    """Wrap a complete MCP mutation in the canonical preset sidecar lock.

    It is crucial that this decorator wraps the whole tool body, not merely
    ``_save``: each body loads its document after the lock is acquired, so a
    waiting writer always applies its intent to the most recently committed
    document instead of saving a stale full-file snapshot.
    """
    signature = inspect.signature(func)
    # Resolve postponed annotations before FastMCP builds its dynamic Pydantic
    # argument model.  A wrapper otherwise leaves aliases such as ``PathArg``
    # as unresolved forward references in that model.
    hints = typing.get_type_hints(func, include_extras=True)
    signature = signature.replace(
        parameters=[
            parameter.replace(annotation=hints.get(parameter.name, parameter.annotation))
            for parameter in signature.parameters.values()
        ],
        return_annotation=hints.get("return", signature.return_annotation),
    )
    if "expected_revision" in signature.parameters:
        raise RuntimeError(f"{func.__name__} already declares expected_revision")
    parameters = list(signature.parameters.values())
    parameters.append(inspect.Parameter(
        "expected_revision",
        kind=inspect.Parameter.KEYWORD_ONLY,
        default=None,
        annotation=RevisionArg,
    ))

    @functools.wraps(func)
    async def guarded(*args, **kwargs):
        expected_revision = kwargs.pop("expected_revision", None)
        bound = signature.bind_partial(*args, **kwargs)
        path = bound.arguments.get("path")
        if path is None:
            return _err("path is required")
        resolved = _resolve_path(path)
        with preset_lock(resolved):
            before = _revision(resolved)
            if expected_revision is not None and expected_revision != before:
                return _err("RevisionConflict", {
                    "file": path,
                    "expected_revision": expected_revision,
                    "actual_revision": before,
                    "message": "the preset changed after it was read; refresh and retry",
                })
            response = await func(*args, **kwargs)
            after = _revision(resolved)
        return _with_write_revision(response, before=before, after=after)

    # FastMCP inspects the callable's signature to build JSON Schema.  Keep
    # functools.wraps for docs, but explicitly expose this added safety field.
    guarded.__signature__ = signature.replace(parameters=parameters)
    annotations = dict(getattr(func, "__annotations__", {}))
    annotations["expected_revision"] = RevisionArg
    guarded.__annotations__ = annotations
    return guarded


def _load(path: str) -> dict:
    return load(str(_resolve_path(path)))


def _save(preset: dict, path: str) -> None:
    resolved = _resolve_path(path)
    if auto_backup_enabled():
        backup_file(str(resolved))
    save(preset, str(resolved))


def _save_card(card: dict, path: str) -> None:
    resolved = _resolve_path(path)
    if auto_backup_enabled():
        backup_file(str(resolved))
    _char.save_card(card, str(resolved))


def _ok(result: Any) -> str:
    return json.dumps({"ok": True, "result": result}, indent=2, ensure_ascii=False)


def _err(message: str, detail: Any = None) -> str:
    out: dict[str, Any] = {"ok": False, "error": message}
    if detail is not None:
        out["detail"] = detail
    return json.dumps(out, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Read / inspect tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="preset_audit",
    annotations={
        "title": "Audit a preset",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_audit(
    path: PathArg,
    show_disabled: Annotated[bool, Field(description="Include disabled blocks in the listing")] = True,
    response_format: Annotated[Literal["json", "markdown"], Field(description="Output format")] = "json",
) -> str:
    """Structural overview of a preset: blocks, enabled state, word/char counts, markers.

    Use this as the first tool when exploring a preset.
    """
    try:
        _resolve_path(path)
        preset = _load(path)
        if response_format == "markdown":
            buf = StringIO()
            with contextlib.redirect_stdout(buf):
                audit(preset, show_disabled=show_disabled)
            return buf.getvalue()

        rows = list_blocks(preset, enabled_only=False)
        chars, approx_tokens = token_count(preset, enabled_only=True)
        return _ok({
            "file": path,
            "blocks": rows,
            "totals": {
                "total_blocks": len(rows),
                "enabled_blocks": sum(1 for r in rows if r["enabled"]),
                "enabled_chars": chars,
                "enabled_approx_tokens": approx_tokens,
            },
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_list_blocks",
    annotations={
        "title": "List preset blocks",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_list_blocks(
    path: PathArg,
    enabled_only: Annotated[bool, Field(description="Only include enabled blocks")] = False,
) -> str:
    """List blocks in a preset with name, index, words, chars, enabled state, marker, and variables flag."""
    try:
        preset = _load(path)
        rows = list_blocks(preset, enabled_only=enabled_only)
        return _ok({"file": path, "blocks": rows})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_find_block",
    annotations={
        "title": "Get a block by name (full block)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_find_block(
    path: PathArg,
    name: Annotated[str, Field(description="Exact block name to retrieve", min_length=1)],
) -> str:
    """Return the full block dict for the first block matching the given name.

    Prefer preset_get_block_lines when you only need a slice of a long block.
    """
    try:
        preset = _load(path)
        block = find_block(preset, name)
        if block is None:
            return _err(f"block '{name}' not found in {path}")
        return _ok({"file": path, "block": block})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_show_block",
    annotations={
        "title": "Show whole block content",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_show_block(
    path: PathArg,
    name: Annotated[str, Field(description="Exact block name to display", min_length=1)],
    max_chars: Annotated[Optional[int], Field(description="Truncate content after this many characters")] = None,
) -> str:
    """Pretty-print a block's content. Use max_chars to preview long blocks.

    Prefer preset_get_block_lines for surgical inspection with line numbers.
    """
    try:
        preset = _load(path)
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            show_block(preset, name, max_chars=max_chars)
        return buf.getvalue()
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_get_block_lines",
    annotations={
        "title": "Get block lines (start to end)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_get_block_lines(
    path: PathArg,
    name: Annotated[str, Field(description="Exact block name to inspect", min_length=1)],
    start_line: Annotated[int, Field(description="1-based first line to return", ge=1)] = 1,
    end_line: Annotated[
        Optional[int],
        Field(description="1-based last line to return, inclusive. Defaults to the end of the block.", ge=1),
    ] = None,
) -> str:
    """Return numbered lines from a block.

    If end_line is omitted, the tool returns from start_line through the end of
    the block. For an exact range, prefer preset_get_block_line_range so both
    bounds are explicit in the request.
    """
    try:
        preset = _load(path)
        selection = get_block_lines(preset, name, start_line=start_line, end_line=end_line)
        return _ok({"file": path, "block": name, **selection})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_get_block_line_range",
    annotations={
        "title": "Get exact block line range",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_get_block_line_range(
    path: PathArg,
    name: Annotated[str, Field(description="Exact block name to inspect", min_length=1)],
    start_line: Annotated[int, Field(description="1-based first line to return", ge=1)],
    end_line: Annotated[int, Field(description="1-based last line to return, inclusive", ge=1)],
) -> str:
    """Return an exact numbered line range from a block.

    This is the preferred retrieval tool when you know both bounds because
    end_line is required rather than inferred.
    """
    try:
        preset = _load(path)
        selection = get_block_lines(preset, name, start_line=start_line, end_line=end_line)
        return _ok({"file": path, "block": name, **selection})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_find_blocks_referencing",
    annotations={
        "title": "Find blocks referencing a pattern",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_find_blocks_referencing(
    path: PathArg,
    pattern: Annotated[str, Field(description="Literal substring to search for in block contents", min_length=1)],
) -> str:
    """Return names of all blocks whose content contains the given literal substring."""
    try:
        preset = _load(path)
        names = find_blocks_referencing(preset, pattern)
        return _ok({"file": path, "pattern": pattern, "blocks": names})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_search",
    annotations={
        "title": "Search blocks, prompt variables, and categories",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_search(
    path: PathArg,
    query: Annotated[str, Field(description="Text to search for (literal substring by default, or a regex when regex=True)", min_length=1)],
    case_sensitive: Annotated[bool, Field(description="Match case exactly")] = False,
    regex: Annotated[bool, Field(description="Treat query as a regular expression")] = False,
    surfaces: Annotated[
        Optional[list[Literal["blocks", "variables", "categories"]]],
        Field(description="Which surfaces to search. Defaults to all three: blocks (names + content), variables (prompt-variable definitions), categories (category names)."),
    ] = None,
    category: Annotated[
        Optional[str],
        Field(description="Restrict results to a single category section (by exact category name)"),
    ] = None,
    enabled_only: Annotated[bool, Field(description="Skip disabled blocks")] = False,
    limit: Annotated[Optional[int], Field(description="Cap the number of returned matches", ge=1)] = None,
) -> str:
    """Search a preset for a query across blocks, prompt variables, and categories.

    Returns ordered matches with each hit's surface type, owning block,
    category section, matched field, and a context snippet. Use this instead
    of preset_find_blocks_referencing when you need case-insensitive/regex
    matching, category awareness, or to search prompt-variable definitions.
    """
    try:
        preset = _load(path)
        result = search_preset(
            preset,
            query,
            case_sensitive=case_sensitive,
            regex=regex,
            surfaces=surfaces,
            category=category,
            enabled_only=enabled_only,
            limit=limit,
        )
        return _ok({"file": path, **result})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_get_section",
    annotations={
        "title": "Get a category section",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_get_section(
    path: PathArg,
    category_name: Annotated[str, Field(description="Name of the category block that starts the section", min_length=1)],
) -> str:
    """Return all blocks between the named category marker and the next category marker."""
    try:
        preset = _load(path)
        section = get_section(preset, category_name)
        index_map = {id(b): i for i, b in enumerate(preset_blocks(preset))}
        return _ok({
            "file": path,
            "category": category_name,
            "blocks": [
                {"index": index_map[id(b)], "name": b.get("name"), "enabled": b.get("enabled"), "marker": b.get("marker")}
                for b in section
            ],
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_extract_macros",
    annotations={
        "title": "Extract macros from a block",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_extract_macros(
    path: PathArg,
    name: Annotated[str, Field(description="Exact block name to extract macros from", min_length=1)],
) -> str:
    """Return the sorted unique list of {{...}} macro patterns in a block's content."""
    try:
        preset = _load(path)
        block = find_block(preset, name)
        if block is None:
            return _err(f"block '{name}' not found in {path}")
        macros = extract_macros(block.get("content", ""))
        return _ok({"file": path, "block": name, "macros": macros})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

@mcp.tool(
    name="preset_token_count",
    annotations={
        "title": "Estimate preset token count",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_token_count(
    path: PathArg,
    enabled_only: Annotated[bool, Field(description="Only count enabled blocks")] = True,
) -> str:
    """Return character count and rough token estimate (chars // 4) for the preset."""
    try:
        preset = _load(path)
        chars, toks = token_count(preset, enabled_only=enabled_only)
        return _ok({"file": path, "chars": chars, "approx_tokens": toks, "enabled_only": enabled_only})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_count_tokens",
    annotations={
        "title": "Count real Claude tokens",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_count_tokens(
    path: PathArg,
    enabled_only: Annotated[bool, Field(description="Only count enabled blocks")] = True,
) -> str:
    """Count real Claude tokens per block using the bundled tokenizer (requires the `tokenizers` package).

    Returns per-block counts and totals. If tokenizers is not installed, the
    error explains how to install it.
    """
    try:
        from . import tokenizer as _tokenizer
        preset = _load(path)
        rows = _tokenizer.count_blocks(preset, enabled_only=enabled_only)
        selected = [r for r in rows if (r["enabled"] if enabled_only else True)]
        return _ok({
            "file": path,
            "enabled_only": enabled_only,
            "total_tokens": sum(r["tokens"] for r in selected),
            "chars_div_4": sum(r["approx"] for r in selected),
            "blocks": rows,
        })
    except ImportError:
        return _err(
            "tokenizers package is required for real token counts",
            "Install with: python3 -m pip install --user tokenizers",
        )
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


# ---------------------------------------------------------------------------
# Validation / render / compare
# ---------------------------------------------------------------------------

@mcp.tool(
    name="preset_validate",
    annotations={
        "title": "Validate preset macros",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_validate(
    path: PathArg,
    min_severity: Annotated[Literal["info", "warning", "error"], Field(description="Minimum severity to report")] = "info",
) -> str:
    """Run macro syntax and variable-flow checks on a preset.

    Reports diagnostics for issues like unterminated macros, unclosed {{if}},
    variables read before set, etc.
    """
    try:
        result = validate_file(str(_resolve_path(path)))
        threshold = _SEV_RANK.get(min_severity, 1)
        diags = [
            {
                "severity": d.severity,
                "code": d.code,
                "message": d.message,
                "field": d.field_path,
                "block_index": d.block_index,
                "block_name": d.block_name,
                "enabled": d.enabled,
                "line": d.line,
                "col": d.col,
                "offset": d.offset,
                "snippet": d.snippet,
            }
            for d in result.diagnostics
            if _SEV_RANK.get(d.severity, 0) >= threshold
        ]
        return _ok({
            "file": path,
            "ok": result.ok,
            "counts": result.counts(),
            "diagnostics": diags,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_variable_report",
    annotations={
        "title": "Report variable usage",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_variable_report(path: PathArg) -> str:
    """Return a per-variable usage map showing which blocks read/write/check each variable."""
    try:
        preset = _load(path)
        report = variable_report(preset)
        return _ok({"file": path, "variables": report})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_render",
    annotations={
        "title": "Render a preset",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_render(
    path: PathArg,
    sample: Annotated[bool, Field(description="Use the built-in sample character/chat for data macros")] = True,
    by_block: Annotated[bool, Field(description="Include per-block rendered text and token counts")] = False,
    show_text: Annotated[bool, Field(description="Include the full rendered prompt text in the response")] = False,
    seed: Annotated[int, Field(description="RNG seed for dice/random/pick macros")] = 1234,
    unknown_policy: Annotated[Literal["keep", "blank"], Field(description="Policy for unresolved macros: keep literal or blank")] = "keep",
    prompt_variables: Annotated[
        Optional[dict[str, Any]],
        Field(
            description=(
                "Prompt-variable overrides for this render, keyed by variable name. "
                "Each value is coerced per the variable's type (switch→0/1, "
                "select/multiselect→option ids, number/slider→clamped). Wins over the "
                "preset's stored values, so a conditional that reads {{var::name}} "
                "can be tested against a specific value."
            ),
        ),
    ] = None,
    live: Annotated[
        bool,
        Field(
            description=(
                "Render with the user's live Lumiverse install (on-device, via bun) "
                "instead of the bundled offline port. Requires a local Lumiverse "
                "checkout discoverable via lumiverse_root or PRESET_TOOLS_LUMIVERSE_ROOT."
            ),
        ),
    ] = False,
    lumiverse_root: Annotated[
        Optional[str],
        Field(description="Path to the local Lumiverse checkout (used with live=True)"),
    ] = None,
) -> str:
    """Render a preset's macros to final text and tokenize the result.

    Use sample=True for a realistic render with sample character data, or
    sample=False to leave identity/persona macros unresolved. The full rendered
    text can be large; use show_text=False and by_block=True to inspect per-block
    token budgets instead.

    Pass prompt_variables={name: value} to test how a conditional or macro that
    reads that variable behaves under a specific value. Pass live=True to render
    with the actual Lumiverse engine from a local checkout (ground truth).
    """
    try:
        preset = _load(path)
        if live:
            result = render_preset_live(
                preset,
                prompt_var_overrides=prompt_variables,
                sample=sample,
                root=lumiverse_root,
                path=path,
                tokenize=True,
            )
            out: dict[str, Any] = {
                "file": path,
                "engine": "live",
                "backend_root": result.backend_root,
                "rendered_blocks": len(result.blocks),
                "total_chars": result.total_chars,
                "total_tokens": result.total_tokens,
                "tokenizer_error": result.tokenizer_error,
                "diagnostics": result.diagnostics,
            }
            if by_block:
                out["blocks"] = [
                    {
                        "index": rb.index,
                        "name": rb.name,
                        "role": rb.role,
                        "marker": rb.marker,
                        "chars": rb.chars,
                        "tokens": rb.tokens,
                        "text": rb.text if show_text else None,
                    }
                    for rb in result.blocks
                ]
            if show_text:
                out["text"] = result.text
            return _ok(out)

        env = RenderEnv.sample() if sample else RenderEnv.empty()
        env.seed = seed
        env.unknown_policy = unknown_policy
        env.__post_init__()
        result = render_preset(preset, env, prompt_var_overrides=prompt_variables)
        out: dict[str, Any] = {
            "file": path,
            "engine": "offline",
            "rendered_blocks": len(result.blocks),
            "total_chars": result.total_chars,
            "total_tokens": result.total_tokens,
            "unresolved": result.unresolved,
            "tokenizer_error": result.tokenizer_error,
            "diagnostics": result.diagnostics,
        }
        if by_block:
            out["blocks"] = [
                {
                    "index": rb.index,
                    "name": rb.name,
                    "role": rb.role,
                    "marker": rb.marker,
                    "chars": rb.chars,
                    "tokens": rb.tokens,
                    "text": rb.text if show_text else None,
                }
                for rb in result.blocks
            ]
        if show_text:
            out["text"] = result.text
        return _ok(out)
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_render_block",
    annotations={
        "title": "Render a single block in isolation",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_render_block(
    path: PathArg,
    name: Annotated[str, Field(description="Exact block name to render", min_length=1)],
    sample: Annotated[bool, Field(description="Use the built-in sample character/chat for data macros")] = True,
    seed: Annotated[int, Field(description="RNG seed for dice/random/pick macros")] = 1234,
    unknown_policy: Annotated[Literal["keep", "blank"], Field(description="Policy for unresolved macros: keep literal or blank")] = "keep",
    prompt_variables: Annotated[
        Optional[dict[str, Any]],
        Field(
            description=(
                "Prompt-variable overrides for this render, keyed by variable name. "
                "Each value is coerced per the variable's type (switch→0/1, "
                "select/multiselect→option ids, number/slider→clamped). Wins over the "
                "preset's stored values, so a conditional that reads {{var::name}} "
                "can be tested against a specific value."
            ),
        ),
    ] = None,
    variables: Annotated[
        Optional[dict[str, Any]],
        Field(
            description=(
                "Seed engine-local variables — the state {{setvar}} writes and "
                "{{getvar}} reads. Lets a conditional like "
                "{{if::{{getvar::x}} == 1}} be tested directly, e.g. "
                "variables={\"plot_active\": 1}."
            ),
        ),
    ] = None,
    with_prior_state: Annotated[
        bool,
        Field(
            description=(
                "Render every enabled block ordered before the target first "
                "(keeping setvar side effects, discarding output) so chained "
                "variable state reproduces exactly."
            ),
        ),
    ] = False,
) -> str:
    """Render one block in isolation and report its text, tokens, and resulting variable state.

    The debugging companion to preset_render: instead of rendering the whole
    preset, render exactly one block — even a disabled one — with seeded
    variables, to see how a conditional or macro behaves under specific state.
    """
    try:
        preset = _load(path)
        env = RenderEnv.sample() if sample else RenderEnv.empty()
        env.seed = seed
        env.unknown_policy = unknown_policy
        env.__post_init__()
        result = render_block(
            preset,
            name,
            env,
            variables=variables,
            prompt_var_overrides=prompt_variables,
            with_prior_state=with_prior_state,
        )
        return _ok({"file": path, **result})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_compare",
    annotations={
        "title": "Compare two presets",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_compare(
    path_a: Annotated[str, Field(description="Path to the first preset, relative to the workspace root", min_length=1)],
    path_b: Annotated[str, Field(description="Path to the second preset, relative to the workspace root", min_length=1)],
    label_a: Annotated[Optional[str], Field(description="Label for preset A")] = None,
    label_b: Annotated[Optional[str], Field(description="Label for preset B")] = None,
) -> str:
    """Compare two presets block-by-block: totals, shared blocks, and only-in-A/only-in-B blocks."""
    try:
        a = _load(path_a)
        b = _load(path_b)
        label_a = label_a or path_a
        label_b = label_b or path_b

        chars_a, toks_a = token_count(a)
        chars_b, toks_b = token_count(b)
        blocks_a = preset_blocks(a)
        blocks_b = preset_blocks(b)

        a_names = {b["name"]: b for b in blocks_a}
        b_names = {b["name"]: b for b in blocks_b}
        shared = sorted(set(a_names) & set(b_names))
        only_a = sorted(set(a_names) - set(b_names))
        only_b = sorted(set(b_names) - set(a_names))

        shared_rows = []
        for name in shared:
            wa = len(a_names[name]["content"].split())
            wb = len(b_names[name]["content"].split())
            shared_rows.append({"name": name, f"{label_a}_words": wa, f"{label_b}_words": wb, "diff": wb - wa})

        return _ok({
            "label_a": label_a,
            "label_b": label_b,
            "totals": {
                label_a: {"blocks": len(blocks_a), "enabled": sum(1 for b in blocks_a if b.get("enabled")),
                          "chars": chars_a, "approx_tokens": toks_a},
                label_b: {"blocks": len(blocks_b), "enabled": sum(1 for b in blocks_b if b.get("enabled")),
                          "chars": chars_b, "approx_tokens": toks_b},
            },
            "shared": shared_rows,
            f"only_in_{label_a}": only_a,
            f"only_in_{label_b}": only_b,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_diff",
    annotations={
        "title": "Content-level diff of two presets",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_diff(
    path_a: Annotated[str, Field(description="Path to the first preset, relative to the workspace root", min_length=1)],
    path_b: Annotated[str, Field(description="Path to the second preset, relative to the workspace root", min_length=1)],
    label_a: Annotated[Optional[str], Field(description="Label for preset A")] = None,
    label_b: Annotated[Optional[str], Field(description="Label for preset B")] = None,
    context: Annotated[int, Field(description="Lines of context around each diff hunk", ge=0, le=20)] = 3,
) -> str:
    """Diff two presets block-by-block with real content diffs.

    Unlike preset_compare (word-count summary), this returns a unified diff of
    each changed shared block's content, plus word/char deltas, enabled-state
    changes, and which blocks exist in only one preset.
    """
    try:
        a = _load(path_a)
        b = _load(path_b)
        result = diff_presets(
            a, b,
            label_a=label_a or path_a,
            label_b=label_b or path_b,
            context=context,
        )
        return _ok(result)
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


# ---------------------------------------------------------------------------
# Regex script tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="regex_list_scripts",
    annotations={
        "title": "List Lumiverse regex scripts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def regex_list_scripts(path: PathArg) -> str:
    """List regex scripts in a preset or standalone regex export.

    The document shape is detected automatically. Presets use
    ``extensions.regex_scripts``; standalone exports use ``scripts``.
    """
    try:
        document = _load(path)
        scripts, container = regex_scripts(document)
        return _ok({
            "file": path,
            "container": container,
            "scripts": [script_summary(script, index) for index, script in enumerate(scripts)],
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="regex_get_script",
    annotations={
        "title": "Get a Lumiverse regex script",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def regex_get_script(
    path: PathArg,
    identifier: Annotated[
        str,
        Field(description="Exact script_id (preferred) or exact unique script name", min_length=1),
    ],
) -> str:
    """Return one complete regex script from a preset or standalone export."""
    try:
        document = _load(path)
        script, index, container = find_regex_script(document, identifier)
        return _ok({
            "file": path,
            "container": container,
            "index": index,
            "script": script,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="regex_validate",
    annotations={
        "title": "Validate Lumiverse regex scripts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def regex_validate(
    path: PathArg,
    check_patterns: Annotated[
        bool,
        Field(
            description=(
                "Also lint every find_regex with the JavaScript syntax linter, compile it "
                "with a real engine when available, and verify $-references against the "
                "pattern's capture groups"
            ),
        ),
    ] = True,
) -> str:
    """Validate regex script structure, field types, flags, and unique IDs.

    This performs structural validation rather than compiling patterns with
    Python, because Lumiverse uses JavaScript regex syntax. With
    ``check_patterns`` (default) each pattern is additionally checked by a
    conservative JavaScript syntax linter and, when node or osascript is
    available, compiled by a real JavaScript engine whose verdict is
    authoritative.
    """
    try:
        document = _load(path)
        result: dict[str, Any] = {"file": path, **validate_regex_document(document)}

        if check_patterns:
            scripts, _ = regex_scripts(document)
            compiled = engine_compile_many(
                [(s.get("find_regex") or "", s.get("flags") or "") for s in scripts]
            )
            for index, script in enumerate(scripts):
                label = script.get("script_id") or script.get("name") or str(index)
                findings = lint_script(script, use_engine=True, compile_result=compiled[index] if compiled else None)
                for finding in findings:
                    message = f"script[{index}] ({label}) {finding['field']}: {finding['message']}"
                    if finding["severity"] == "error":
                        result["errors"].append(message)
                    elif finding["severity"] == "warning":
                        result["warnings"].append(message)
            result["ok"] = not result["errors"]
            result["pattern_lint"] = True
            result["engine"] = engine_kind()
        return _ok(result)
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="regex_check_pattern",
    annotations={
        "title": "Pre-flight check a Lumiverse regex pattern",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def regex_check_pattern(
    pattern: Annotated[
        str,
        Field(
            description=(
                "JavaScript regex pattern to check. Provide the pattern body; a /.../flags "
                "literal is also accepted and stripped automatically"
            ),
            min_length=1,
        ),
    ],
    flags: Annotated[str, Field(description="JavaScript regex flags to check with, usually gi")] = "",
    replace_string: Annotated[
        Optional[str],
        Field(
            description=(
                "Optional replacement string; enables $<name>/\" \"$N\" reference checking "
                "and, with sample_text, a real render preview"
            ),
        ),
    ] = None,
    sample_text: Annotated[
        Optional[str],
        Field(description="Optional text to match against; with replace_string, renders the substituted output"),
    ] = None,
    repair_escapes: Annotated[
        bool,
        Field(description="Repair doubled backslashes, /.../ literals, and Python (?P< groups, reporting each repair"),
    ] = True,
) -> str:
    """Pre-flight check a regex pattern without touching any files.

    Runs the same repair and validation pipeline as ``regex_create_script``:
    common escaping mistakes are repaired and reported, the pattern is linted
    structurally and compiled by a real JavaScript engine when available
    (node, or osascript JXA on macOS), and replacement ``$``-references are
    verified against the capture groups the pattern defines. When both
    ``replace_string`` and ``sample_text`` are given, the tool also runs the
    actual substitution and returns the rendered output plus per-match capture
    details, so card HTML can be verified before embedding it in a preset.
    """
    try:
        diagnostics: list[Any] = []
        pattern, flags, notes = normalize_pattern_input(pattern, flags, repair=repair_escapes)
        diagnostics += notes
        if isinstance(replace_string, str) and repair_escapes:
            replace_string, notes = normalize_replacement_input(replace_string)
            diagnostics += notes

        compile_result = engine_compile(pattern, flags)
        script_view = {"find_regex": pattern, "flags": flags, "replace_string": replace_string or ""}
        findings = lint_script(script_view, use_engine=True, compile_result=compile_result)
        diagnostics += findings

        result: dict[str, Any] = {
            "pattern": pattern,
            "flags": flags,
            "engine": engine_kind(),
            "diagnostics": diagnostics,
        }
        if compile_result is not None:
            result["compiles"] = compile_result["ok"]
            if not compile_result["ok"]:
                result["compile_error"] = compile_result.get("message")

        _, names, count = lint_js_pattern(pattern, flags)
        result["capture_group_count"] = count
        if names:
            result["group_names"] = names

        if replace_string is not None and sample_text is not None:
            render = engine_render(pattern, flags, replace_string, sample_text)
            result["render"] = render if render is not None else "sample rendering requires a node-compatible engine"
        return _ok(result)
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="regex_create_script",
    annotations={
        "title": "Create a Lumiverse regex script",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def regex_create_script(
    path: PathArg,
    name: Annotated[str, Field(description="Display name for the regex script", min_length=1)],
    script_id: Annotated[str, Field(description="Unique stable script identifier", min_length=1)],
    find_regex: Annotated[
        Optional[str],
        Field(
            description=(
                "JavaScript regex pattern body, WITHOUT /.../ delimiters (a /.../flags literal "
                "is auto-stripped). Escaping contract: this string arrives after JSON decoding, "
                "so the final value must contain single backslashes — write \\d, \\s, \\S directly "
                "and let the tool-call JSON layer double them. Over-escaped input (double "
                "backslashes) is auto-repaired and reported. For long patterns prefer find_regex_file."
            ),
            min_length=1,
        ),
    ] = None,
    replace_string: Annotated[
        Optional[str],
        Field(
            description=(
                "Replacement text or HTML; may be empty. $<name> inserts a named capture group "
                "and $1..$N a numbered one (both verified against find_regex). Literal \\n / \\t / "
                "\\\" sequences from over-escaping are converted to real characters. For large "
                "HTML prefer replace_string_file."
            ),
        ),
    ] = None,
    find_regex_file: Annotated[
        Optional[str],
        Field(
            description=(
                "Path to a workspace file containing the pattern body (whitespace-trimmed). "
                "Avoids JSON escaping entirely for long patterns; mutually exclusive with find_regex."
            ),
        ),
    ] = None,
    replace_string_file: Annotated[
        Optional[str],
        Field(
            description=(
                "Path to a workspace file containing the replacement HTML, read verbatim. "
                "Avoids JSON escaping entirely for large payloads; mutually exclusive with replace_string."
            ),
        ),
    ] = None,
    container: Annotated[
        Literal["auto", "preset", "standalone"],
        Field(description="Target JSON shape. Use standalone when creating a new file; auto detects an existing file."),
    ] = "auto",
    flags: Annotated[str, Field(description="JavaScript regex flags, usually gi")] = "gi",
    placement: Annotated[
        Optional[list[str]],
        Field(description="Where the script runs, usually ['ai_output']"),
    ] = None,
    target: Annotated[
        Optional[list[str]],
        Field(description="Output targets, usually ['display'] or ['prompt']"),
    ] = None,
    scope: Annotated[str, Field(description="Regex scope, usually global")] = "global",
    disabled: Annotated[bool, Field(description="Whether the script starts disabled")] = False,
    description: Annotated[str, Field(description="Human-readable purpose of the script")] = "",
    sort_order: Annotated[int, Field(description="Execution/display ordering value")] = 100,
    options: Annotated[
        Optional[dict[str, Any]],
        Field(
            description=(
                "Additional Lumiverse fields such as actions, scope_id, min_depth, max_depth, "
                "trim_strings, run_on_edit, substitute_macros, folder, and metadata"
            ),
        ),
    ] = None,
    index: Annotated[
        Optional[int],
        Field(description="Zero-based insertion index. Omit to append.", ge=0),
    ] = None,
    repair_escapes: Annotated[
        bool,
        Field(
            description=(
                "Repair common tool-call escaping mistakes — doubled backslashes, /.../flags "
                "literals, Python (?P<name> groups, literal \\n in replacements — and report "
                "each repair in the diagnostics"
            ),
        ),
    ] = True,
    strict: Annotated[
        bool,
        Field(
            description=(
                "When true (default) refuse to save a script whose pattern fails JavaScript "
                "syntax validation or that references capture groups the pattern does not define"
            ),
        ),
    ] = True,
) -> str:
    """Create and save a reference-complete Lumiverse regex script.

    Existing preset and standalone files are detected with ``container=auto``.
    To create a new standalone JSON export, provide ``container=standalone``;
    the export wrapper is initialized automatically. This tool will not create
    a blank preset and rejects duplicate script IDs.

    Payloads can be passed inline or read from files (``find_regex_file`` /
    ``replace_string_file``), which sidesteps JSON escaping for long patterns
    and large HTML replacements. Before saving, the pattern is compiled by a
    real JavaScript engine when one is available (node, or osascript JXA on
    macOS) and $-references are verified against the pattern's capture groups.
    Every repair or warning is listed in the returned diagnostics.
    """
    try:
        resolved = _resolve_path(path)
        if resolved.exists():
            document = _load(path)
        elif container == "standalone":
            document = new_regex_export()
        else:
            return _err("a missing path can only be created with container='standalone'")

        diagnostics: list[Any] = []

        pattern = find_regex
        if find_regex_file is not None:
            if find_regex is not None:
                return _err("provide either find_regex or find_regex_file, not both")
            pattern = _resolve_path(find_regex_file).read_text(encoding="utf-8").strip()
        if pattern is None:
            return _err("find_regex or find_regex_file is required")

        replacement = replace_string
        if replace_string_file is not None:
            if replace_string is not None:
                return _err("provide either replace_string or replace_string_file, not both")
            replacement = _resolve_path(replace_string_file).read_text(encoding="utf-8")
        if replacement is None:
            return _err("replace_string or replace_string_file is required (an empty string is allowed)")

        pattern, flags, notes = normalize_pattern_input(pattern, flags, repair=repair_escapes)
        diagnostics += notes
        replacement, notes = normalize_replacement_input(replacement, repair=repair_escapes)
        diagnostics += notes

        script = new_regex_script(
            name=name,
            script_id=script_id,
            find_regex=pattern,
            replace_string=replacement,
            flags=flags,
            placement=placement,
            target=target,
            scope=scope,
            disabled=disabled,
            description=description,
            sort_order=sort_order,
            options=options,
        )

        findings = lint_script(script, use_engine=True)
        diagnostics += findings
        if strict and any(f["severity"] == "error" for f in findings):
            return _err(
                "regex script failed validation; fix the flagged issues and retry "
                "(or pass strict=false to save anyway)",
                {"findings": [f for f in findings if f["severity"] == "error"]},
            )

        inserted_index, detected = insert_regex_script(
            document,
            script,
            container=container,
            index=index,
        )
        _save(document, path)
        return _ok({
            "file": path,
            "container": detected,
            "script_id": script_id,
            "inserted_index": inserted_index,
            "script": script,
            "diagnostics": diagnostics,
            "saved": True,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="regex_update_script",
    annotations={
        "title": "Update a Lumiverse regex script",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def regex_update_script(
    path: PathArg,
    identifier: Annotated[
        str,
        Field(description="Exact script_id (preferred) or exact unique script name", min_length=1),
    ],
    updates: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Fields to set. Supports find_regex, replace_string, actions, flags, placement, "
                "target, depth settings, metadata, and other Lumiverse regex fields. find_regex "
                "and replace_string get the same escape repair and validation as regex_create_script."
            ),
        ),
    ],
    remove_fields: Annotated[
        Optional[list[str]],
        Field(description="Optional non-required fields to remove entirely"),
    ] = None,
    find_regex_file: Annotated[
        Optional[str],
        Field(
            description=(
                "Path to a workspace file containing the new pattern body (whitespace-trimmed); "
                "mutually exclusive with updates.find_regex"
            ),
        ),
    ] = None,
    replace_string_file: Annotated[
        Optional[str],
        Field(
            description=(
                "Path to a workspace file containing the new replacement HTML, read verbatim; "
                "mutually exclusive with updates.replace_string"
            ),
        ),
    ] = None,
    repair_escapes: Annotated[
        bool,
        Field(
            description=(
                "Repair common tool-call escaping mistakes in updates.find_regex / "
                "updates.replace_string — doubled backslashes, /.../flags literals, Python "
                "(?P<name> groups, literal \\n sequences — and report each repair"
            ),
        ),
    ] = True,
    strict: Annotated[
        bool,
        Field(
            description=(
                "When true (default) refuse to save when the merged script fails JavaScript "
                "syntax validation or references undefined capture groups; the file is left untouched"
            ),
        ),
    ] = True,
) -> str:
    """Atomically patch one regex script and save its containing JSON file.

    Required fields cannot be removed, and changing ``script_id`` to a
    duplicate is rejected. Fields not mentioned are preserved.

    Large payloads can be provided through ``find_regex_file`` /
    ``replace_string_file`` instead of the ``updates`` object. The merged
    script is validated with a real JavaScript engine (when available) and
    $-references are checked against the pattern's groups before anything is
    written; on failure the file is not modified.
    """
    try:
        document = _load(path)
        updates = dict(updates)
        diagnostics: list[Any] = []

        current, _, _ = find_regex_script(document, identifier)
        if find_regex_file is not None:
            if "find_regex" in updates:
                return _err("provide either updates.find_regex or find_regex_file, not both")
            updates["find_regex"] = _resolve_path(find_regex_file).read_text(encoding="utf-8").strip()
        if replace_string_file is not None:
            if "replace_string" in updates:
                return _err("provide either updates.replace_string or replace_string_file, not both")
            updates["replace_string"] = _resolve_path(replace_string_file).read_text(encoding="utf-8")

        if repair_escapes:
            if isinstance(updates.get("find_regex"), str):
                current_flags = current.get("flags")
                flags = updates.get("flags", current_flags if isinstance(current_flags, str) else "")
                if not isinstance(flags, str):
                    flags = ""
                updates["find_regex"], flags, notes = normalize_pattern_input(updates["find_regex"], flags)
                if flags != current_flags or "flags" in updates:
                    updates["flags"] = flags
                diagnostics += notes
            if isinstance(updates.get("replace_string"), str):
                updates["replace_string"], notes = normalize_replacement_input(updates["replace_string"])
                diagnostics += notes

        script, index, container = update_regex_script(
            document,
            identifier,
            updates,
            remove_fields=remove_fields,
        )

        findings = lint_script(script, use_engine=True)
        diagnostics += findings
        if strict and any(f["severity"] == "error" for f in findings):
            return _err(
                "updated regex script failed validation; the file was NOT modified. Fix the "
                "flagged issues and retry (or pass strict=false to save anyway)",
                {"findings": [f for f in findings if f["severity"] == "error"]},
            )

        _save(document, path)
        return _ok({
            "file": path,
            "container": container,
            "index": index,
            "script": script,
            "diagnostics": diagnostics,
            "saved": True,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="regex_delete_script",
    annotations={
        "title": "Delete a Lumiverse regex script",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def regex_delete_script(
    path: PathArg,
    identifier: Annotated[
        str,
        Field(description="Exact script_id (preferred) or exact unique script name", min_length=1),
    ],
) -> str:
    """Delete one regex script from a preset or standalone export and save."""
    try:
        document = _load(path)
        removed, index, container = _delete_regex_script(document, identifier)
        _save(document, path)
        return _ok({
            "file": path,
            "container": container,
            "removed_index": index,
            "removed": {"name": removed.get("name"), "script_id": removed.get("script_id")},
            "saved": True,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


# ---------------------------------------------------------------------------
# Write / edit tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="preset_modify_block",
    annotations={
        "title": "Modify a block (unified diff or whole content)",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_modify_block(
    path: PathArg,
    name: Annotated[str, Field(description="Exact name of the block to modify", min_length=1)],
    content: Annotated[
        str,
        Field(
            description=(
                "A unified diff patch for this block (preferred) or complete replacement content. "
                "A patch may contain multiple @@ hunks; each hunk's unchanged/context and removed "
                "lines must exactly match the current block. The named block is the target, so file "
                "headers are optional."
            )
        ),
    ],
) -> str:
    """Apply a unified diff to a named block, or replace it wholesale, and save.

    Prefer a standard unified diff when changing existing content. It can
    express multiple independent multi-line hunks in one atomic write. Pass
    full replacement content only when deliberately rewriting the whole block.
    """
    try:
        preset = _load(path)
        block = find_block(preset, name)
        if block is None:
            raise ValueError(f"Block '{name}' not found")
        before = block.get("content", "") or ""
        patch_mode = is_unified_diff(content)
        after = apply_unified_diff(before, content) if patch_mode else content
        block = modify_block(preset, name, after)
        _save(preset, path)
        diff = "".join(unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"before/{name}",
            tofile=f"after/{name}",
            n=3,
        ))
        return _ok({
            "file": path,
            "block": name,
            "saved": True,
            "mode": "unified_diff" if patch_mode else "replace",
            "additions": sum(line.startswith("+") and not line.startswith("+++") for line in diff.splitlines()),
            "deletions": sum(line.startswith("-") and not line.startswith("---") for line in diff.splitlines()),
            "diff": diff,
            "chars": len(block.get("content", "")),
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


_SURFACE_ARG = Annotated[
    Optional[list[Literal["block_content", "block_title", "category_content", "category_title"]]],
    Field(
        description=(
            "Text surfaces to replace across: block_content (non-category block contents), "
            "block_title (non-category block names), category_content (category block contents), "
            "category_title (category block names). Defaults to all four"
        ),
    ),
]


@mcp.tool(
    name="preset_check_replace",
    annotations={
        "title": "Pre-flight check a search & replace",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_check_replace(
    pattern: Annotated[
        str,
        Field(
            description=(
                "Find pattern. regex mode: a regular expression (JS-style /.../flags literals and "
                "$1/$<name> replacement refs are accepted and translated to Python re). "
                "literal mode: matched verbatim as plain text"
            ),
            min_length=1,
        ),
    ],
    replacement: Annotated[str, Field(description="Replacement text", min_length=1)],
    mode: Annotated[Literal["regex", "literal"], Field(description="Matching mode; literal skips all regex interpretation")] = "regex",
    path: Annotated[
        Optional[str],
        Field(
            description=(
                "Optional preset file to preview against. When given, the pattern is run on every "
                "matching surface (dry-run, nothing written) and over-broad matches are flagged "
                "per block"
            ),
        ),
    ] = None,
    surfaces: _SURFACE_ARG = None,
    category: Annotated[Optional[str], Field(description="Restrict to one category section (by category block name)")] = None,
    enabled_only: Annotated[bool, Field(description="Only match inside enabled blocks")] = False,
    case_sensitive: Annotated[bool, Field(description="Match case-sensitively (default: insensitive)")] = False,
    multiline: Annotated[bool, Field(description="Regex mode: ^ and $ anchor per line instead of per field")] = False,
    dot_all: Annotated[bool, Field(description="Regex mode: . also matches newlines (JS /s flag)")] = False,
    allow_broad_matches: Annotated[
        bool,
        Field(description="Permit single matches that swallow 60%+ of a field (dangerous; validate the preview first)"),
    ] = False,
    repair_escapes: Annotated[bool, Field(description="Repair common tool-call escaping mistakes (doubled backslashes, /.../ literals, JS named groups), reporting each repair")] = True,
) -> str:
    """Pre-flight check a search & replace without writing anything.

    Compiles the pattern (translating JS-flavored input to Python re),
    translates ``$1``/``$<name>`` replacement references, and reports every
    problem with actionable messages: syntax errors with position and hint,
    patterns that can match an empty string, references to groups the pattern
    does not define, nested-quantifier backtracking risks, and — when ``path``
    is given — over-broad matches measured against the preset's real content,
    plus anchor/dot-all hints when a pattern found nothing.
    """
    try:
        result: dict[str, Any]
        if path is None:
            gate = check_replace(
                pattern,
                replacement,
                mode=mode,
                case_sensitive=case_sensitive,
                multiline=multiline,
                dot_all=dot_all,
                allow_broad=allow_broad_matches,
                repair=repair_escapes,
            )
            gate.pop("_compiled", None)
            result = dict(gate)
        else:
            preset = _load(path)
            report = replace_in_preset(
                preset,
                pattern,
                replacement,
                mode=mode,
                surfaces=surfaces,
                category=category,
                enabled_only=enabled_only,
                case_sensitive=case_sensitive,
                multiline=multiline,
                dot_all=dot_all,
                allow_broad=allow_broad_matches,
                dry_run=True,
                repair=repair_escapes,
            )
            result = {"file": path, "dry_run": True, "report": report}
        result["valid"] = not any(f.get("severity") == "error" for f in result.get("findings", []))
        if "report" in result:
            result["valid"] = not any(f.get("severity") == "error" for f in result["report"].get("findings", []))
        return _ok(result)
    except ReplaceRejected as exc:
        return _ok({
            "valid": False,
            "file": path if path else None,
            "findings": exc.findings,
            "hint": "fix the error findings and re-run this check before applying",
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_replace_text",
    annotations={
        "title": "Search & replace text across a preset",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_replace_text(
    path: PathArg,
    pattern: Annotated[
        str,
        Field(
            description=(
                "Find pattern. regex mode: a regular expression (JS-style /.../flags literals and "
                "$1/$<name> replacement refs are accepted and translated to Python re). "
                "literal mode: matched verbatim as plain text"
            ),
            min_length=1,
        ),
    ],
    replacement: Annotated[str, Field(description="Replacement text", min_length=1)],
    mode: Annotated[Literal["regex", "literal"], Field(description="Matching mode; literal skips all regex interpretation")] = "regex",
    surfaces: _SURFACE_ARG = None,
    category: Annotated[Optional[str], Field(description="Restrict to one category section (by category block name)")] = None,
    enabled_only: Annotated[bool, Field(description="Only match inside enabled blocks")] = False,
    case_sensitive: Annotated[bool, Field(description="Match case-sensitively (default: insensitive)")] = False,
    multiline: Annotated[bool, Field(description="Regex mode: ^ and $ anchor per line instead of per field")] = False,
    dot_all: Annotated[bool, Field(description="Regex mode: . also matches newlines (JS /s flag)")] = False,
    allow_broad_matches: Annotated[
        bool,
        Field(description="Permit single matches that swallow 60%+ of a field; only set after reviewing preset_check_replace"),
    ] = False,
    dry_run: Annotated[bool, Field(description="Preview the replacement (full report) without saving")] = False,
    repair_escapes: Annotated[bool, Field(description="Repair common tool-call escaping mistakes (doubled backslashes, /.../ literals, JS named groups), reporting each repair")] = True,
) -> str:
    """Search & replace text across preset block contents, block titles,
    category contents, and category titles, then save.

    The same validation gate as ``preset_check_replace`` runs first with the
    preset's real content as samples: a malformed or over-broad pattern is
    rejected with actionable findings and the file is left untouched. Use
    ``preset_check_replace`` (or ``dry_run=true``) to preview before applying.
    """
    try:
        preset = _load(path)
        report = replace_in_preset(
            preset,
            pattern,
            replacement,
            mode=mode,
            surfaces=surfaces,
            category=category,
            enabled_only=enabled_only,
            case_sensitive=case_sensitive,
            multiline=multiline,
            dot_all=dot_all,
            allow_broad=allow_broad_matches,
            dry_run=dry_run,
            repair=repair_escapes,
        )
        if not dry_run and report["changed"]:
            _save(preset, path)
        return _ok({
            "file": path,
            "dry_run": dry_run,
            "saved": (not dry_run) and report["changed"],
            **report,
        })
    except ReplaceRejected as exc:
        return _err(
            "replacement rejected; the file was NOT modified. Fix the flagged issues and retry "
            "(or pass allow_broad_matches=true if the large capture is intentional)",
            {"findings": exc.findings},
        )
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())



@mcp.tool(
    name="preset_insert_prompt_variable",
    annotations={
        "title": "Insert a prompt variable into a block",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_insert_prompt_variable(
    path: PathArg,
    block_name: Annotated[str, Field(description="Exact name of the block that will own the variable", min_length=1)],
    name: Annotated[str, Field(description="Variable name referenced in macros as {{var::name}}", min_length=1)],
    label: Annotated[str, Field(description="Human-readable label shown in the Lumiverse UI", min_length=1)],
    var_type: Annotated[
        Literal["text", "textarea", "number", "slider", "select", "switch", "multiselect"],
        Field(description="Prompt variable type"),
    ],
    default_value: Annotated[
        Optional[str],
        Field(description="Default value. For multiselect use a JSON array or comma-separated option ids; for switch use 0/1/true/false; for number/slider use a number string."),
    ] = None,
    description: Annotated[Optional[str], Field(description="Optional tooltip/description for the UI control")] = None,
    min_value: Annotated[Optional[float], Field(description="Minimum value for number/slider")] = None,
    max_value: Annotated[Optional[float], Field(description="Maximum value for number/slider")] = None,
    step: Annotated[Optional[float], Field(description="Step size for number/slider")] = None,
    rows: Annotated[Optional[int], Field(description="Number of rows for textarea")] = None,
    options: Annotated[
        Optional[list[dict[str, Any]]],
        Field(
            description=(
                "Structured option list for select/multiselect: [{id, label, value}, ...]. "
                "Preferred over options_json — pass real objects, not a JSON string, so no "
                "quote escaping is needed"
            ),
        ),
    ] = None,
    options_json: Annotated[
        Optional[str],
        Field(
            description=(
                "JSON array string of {id, label, value} objects for select/multiselect. "
                "Required for those types unless options is given. Common escaping mistakes "
                "(over-escaped quotes, single quotes, Python True/False/None, trailing commas) "
                "are auto-repaired and reported; prefer the structured options parameter"
            ),
        ),
    ] = None,
    separator: Annotated[Optional[str], Field(description="Separator between joined multiselect values (default two newlines)")] = None,
    insert_macro: Annotated[bool, Field(description="Also insert a {{var::name}} reference into the block content")] = True,
    insert_macro_at: Annotated[Literal["start", "end"], Field(description="Where to place the macro in the content")] = "end",
    macro_template: Annotated[
        Optional[str],
        Field(description="Custom macro template. Use {name} as the variable-name placeholder. Defaults to '{{var::{name}}}'"),
    ] = None,
    repair_escapes: Annotated[
        bool,
        Field(description="Repair common escaping mistakes in options_json / default_value strings and report each repair"),
    ] = True,
    strict: Annotated[
        bool,
        Field(description="When true (default), refuse to save variables that fail validation (unknown option ids, reversed min/max, duplicate names)"),
    ] = True,
) -> str:
    """Add a Lumiverse prompt variable definition to a block and optionally inject
    its {{var::name}} macro into the block content.

    This mirrors the prompt variable types assembled by Lumiverse
    (text, textarea, number, slider, select, switch, multiselect). Values are
    coerced/clamped the same way the backend does before being published to
    env.extra.promptVariables and seeded into {{var::name}} resolution.

    Escaping guidance: pass select/multiselect options through the structured
    ``options`` array (no JSON-in-JSON string to mangle). ``options_json`` is
    still accepted and repaired when the model sends it with over-escaped
    quotes or Python-literal syntax. Before saving, the definition is
    validated — defaultValue must reference a real option id, option ids must
    be unique, min must not exceed max, and parameters that do not apply to
    var_type are reported as warnings instead of being dropped silently.
    Every repair or warning is listed in the returned diagnostics.

    Examples:
        - switch: var_type='switch', default_value='1', label='Gooner Mode'
        - slider: var_type='slider', default_value='50', min_value=0, max_value=100
        - select: var_type='select', default_value='clinical', options=[{"id":"clinical","label":"Clinical","value":"clinical prose"},{"id":"vivid","label":"Vivid","value":"vivid prose"}]
        - multiselect: var_type='multiselect', default_value='["concise","vivid"]', options=[...]
    """
    try:
        preset = _load(path)
        diagnostics: list[Any] = []

        if options is not None and options_json is not None:
            return _err("provide either options or options_json, not both")
        if options_json is not None:
            if repair_escapes:
                value, notes, error = repair_json_payload(options_json)
                diagnostics += notes
                if value is None:
                    return _err(
                        f"options_json is not valid JSON: {error}",
                        {"hint": 'pass the structured "options" array instead to avoid string escaping entirely'},
                    )
                options = value
            else:
                try:
                    options = json.loads(options_json)
                except json.JSONDecodeError as exc:
                    return _err(f"options_json is not valid JSON: {exc}")

        if default_value is not None:
            default_value, notes = normalize_default_value(var_type, default_value, repair=repair_escapes)
            diagnostics += notes
        diagnostics += default_value_warnings(var_type, default_value)

        ignored_fields: list[dict[str, str]] = []
        if var_type not in ("select", "multiselect") and (options is not None or options_json is not None):
            ignored_fields.append({"field": "options" if options is not None else "options_json",
                                   "reason": f"var_type '{var_type}' does not use options"})
        if var_type != "textarea" and rows is not None:
            ignored_fields.append({"field": "rows", "reason": f"rows only applies to textarea, not '{var_type}'"})
        if var_type not in ("number", "slider"):
            for field, value in (("min_value", min_value), ("max_value", max_value), ("step", step)):
                if value is not None:
                    ignored_fields.append({"field": field, "reason": f"{field} only applies to number/slider, not '{var_type}'"})
        if var_type != "multiselect" and separator is not None:
            ignored_fields.append({"field": "separator", "reason": f"separator only applies to multiselect, not '{var_type}'"})

        block = find_block(preset, block_name)
        if block is None:
            return _err(f"Block '{block_name}' not found")
        existing_names = [v.get("name") for v in (block.get("variables") or [])]

        var_def = add_prompt_variable(
            preset,
            block_name=block_name,
            name=name,
            label=label,
            var_type=var_type,
            default_value=default_value,
            description=description or "",
            min_value=min_value,
            max_value=max_value,
            step=step,
            rows=rows,
            options=options,
            separator=separator,
        )

        findings = lint_variable_def(var_def, existing_names=existing_names, ignored_fields=ignored_fields)
        diagnostics += findings
        if strict and any(f["severity"] == "error" for f in findings):
            return _err(
                "prompt variable failed validation; fix the flagged issues and retry "
                "(or pass strict=false to save anyway)",
                {"findings": [f for f in findings if f["severity"] == "error"]},
            )

        inserted_macro = None
        if insert_macro:
            template = macro_template or "{{var::{name}}}"
            macro = template.replace("{name}", name)
            content = block.get("content", "") or ""

            if macro in content:
                diagnostics.append({
                    "severity": "info", "code": "macro_already_present", "field": "insert_macro",
                    "message": f"'{macro}' is already present in the block content; macro insertion skipped",
                })
            else:
                if insert_macro_at == "start":
                    if content and not content.startswith("\n"):
                        content = "\n\n" + content
                    content = macro + content
                else:  # end
                    if content and not content.endswith("\n"):
                        content += "\n\n"
                    content += macro
                block["content"] = content
                inserted_macro = macro

        _save(preset, path)
        return _ok({
            "file": path,
            "block": block_name,
            "variable": var_def,
            "inserted_macro": inserted_macro,
            "diagnostics": diagnostics,
            "saved": True,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_list_prompt_variables",
    annotations={
        "title": "List prompt variables in a preset",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_list_prompt_variables(path: PathArg) -> str:
    """List every block's prompt variables: name, type, default, option ids,
    and whether the block's content actually references the variable's
    {{var::name}} macro."""
    try:
        preset = _load(path)
        blocks = list_prompt_variables(preset)
        return _ok({
            "file": path,
            "blocks_with_variables": len(blocks),
            "total_variables": sum(len(b["variables"]) for b in blocks),
            "blocks": blocks,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


_UPDATE_FIELD_ALIASES = {
    "var_type": "type",
    "default_value": "defaultValue",
    "min_value": "min",
    "max_value": "max",
}
_UPDATE_ALLOWED_FIELDS = {
    "name", "label", "description", "type", "defaultValue",
    "min", "max", "step", "rows", "options", "separator",
}


@mcp.tool(
    name="preset_update_prompt_variable",
    annotations={
        "title": "Update a prompt variable",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_update_prompt_variable(
    path: PathArg,
    block_name: Annotated[str, Field(description="Exact name of the block that owns the variable", min_length=1)],
    var_name: Annotated[str, Field(description="Exact name of the variable to update", min_length=1)],
    updates: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Fields to set on the variable definition: name, label, description, type, "
                "defaultValue, min, max, step, rows, separator, and options (structured array "
                "preferred; a JSON string is accepted and repaired). Tool-style aliases "
                "var_type/default_value/min_value/max_value are also recognized. Unmentioned "
                "fields are preserved"
            ),
        ),
    ],
    repair_escapes: Annotated[
        bool,
        Field(description="Repair escaping mistakes in string-form options/defaultValue and report each repair"),
    ] = True,
    strict: Annotated[
        bool,
        Field(description="When true (default), refuse to save when the merged variable fails validation; the file is left untouched"),
    ] = True,
    rewrite_references: Annotated[
        bool,
        Field(
            description=(
                "When renaming, also rewrite every {{var::old}}/{{getvar::old}}-family macro "
                "reference (including sub-syntax like {{var::old::ison::keys}}) in ALL block "
                "contents and migrate the stored prompt-variable value key to the new name "
                "(default true)"
            ),
        ),
    ] = True,
) -> str:
    """Atomically patch one prompt variable definition and save the preset.

    The merged definition is rebuilt with Lumiverse's coercion rules (so
    changing ``type`` re-coerces ``defaultValue``) while keeping the stable
    variable ``id``. Options can be passed as a structured array or a JSON
    string (repaired when malformed). Validation runs before anything is
    written: unknown option ids, duplicate option ids, reversed min/max, and
    duplicate variable names are rejected with actionable messages, and
    fields that do not apply to the variable's type are reported as warnings
    instead of vanishing. Renaming a variable also rewrites every
    {{var::old}}/{{getvar::old}}-family macro reference in all block contents
    and migrates the stored value key (unless rewrite_references=false).
    """
    try:
        preset = _load(path)
        updates = dict(updates)
        diagnostics: list[Any] = []

        normalized: dict[str, Any] = {}
        unknown: list[str] = []
        for key, value in updates.items():
            canonical = _UPDATE_FIELD_ALIASES.get(key, key)
            if canonical in _UPDATE_ALLOWED_FIELDS:
                normalized[canonical] = value
            else:
                unknown.append(key)
        if unknown:
            return _err(
                f"unknown updates field(s): {', '.join(sorted(unknown))}",
                {"hint": f"allowed fields: {', '.join(sorted(_UPDATE_ALLOWED_FIELDS))} (aliases: {', '.join(sorted(_UPDATE_FIELD_ALIASES))})"},
            )

        if isinstance(normalized.get("options"), str):
            if repair_escapes:
                value, notes, error = repair_json_payload(normalized["options"])
                diagnostics += notes
                if value is None:
                    return _err(
                        f"updates.options is not valid JSON: {error}",
                        {"hint": "pass options as a structured array of {id, label, value} objects"},
                    )
                normalized["options"] = value
            else:
                try:
                    normalized["options"] = json.loads(normalized["options"])
                except json.JSONDecodeError as exc:
                    return _err(f"updates.options is not valid JSON: {exc}")

        final_type = str(normalized.get("type", "")).lower()
        if not final_type:
            block = find_block(preset, block_name)
            if block is None:
                return _err(f"Block '{block_name}' not found")
            current = next((v for v in (block.get("variables") or []) if v.get("name") == var_name), None)
            if current is None:
                return _err(f"Variable '{var_name}' not found in block '{block_name}'")
            final_type = str(current.get("type", "text")).lower()
        if "defaultValue" in normalized and normalized["defaultValue"] is not None:
            normalized["defaultValue"], notes = normalize_default_value(final_type, normalized["defaultValue"], repair=repair_escapes)
            diagnostics += notes
            diagnostics += default_value_warnings(final_type, normalized["defaultValue"])

        var_def = update_prompt_variable(preset, block_name, var_name, normalized)

        block = find_block(preset, block_name)
        existing_names = [v.get("name") for v in (block.get("variables") or []) if v.get("name") != var_def.get("name")]

        ignored_fields = []
        if final_type not in ("select", "multiselect") and var_def.get("options") is not None:
            ignored_fields.append({"field": "options", "reason": f"var_type '{final_type}' does not use options"})
        if final_type != "textarea" and var_def.get("rows") is not None:
            ignored_fields.append({"field": "rows", "reason": f"rows only applies to textarea, not '{final_type}'"})
        if final_type not in ("number", "slider"):
            for field in ("min", "max", "step"):
                if var_def.get(field) is not None:
                    ignored_fields.append({"field": field, "reason": f"{field} only applies to number/slider, not '{final_type}'"})
        if final_type != "multiselect" and var_def.get("separator") is not None:
            ignored_fields.append({"field": "separator", "reason": f"separator only applies to multiselect, not '{final_type}'"})

        findings = lint_variable_def(var_def, existing_names=existing_names, ignored_fields=ignored_fields)
        diagnostics += findings

        if var_name != var_def.get("name"):
            new_name = var_def.get("name") or var_name
            old_macro = "{{var::" + var_name + "}}"
            new_macro = "{{var::" + new_name + "}}"
            content = block.get("content") or ""
            old_refs = content.count(old_macro) + content.count("{{getvar::" + var_name + "}}")
            if rewrite_references:
                rewritten = rewrite_variable_references(preset, var_name, new_name)
                if rewritten["content_references"] or rewritten["stored_values"]:
                    stored_note = (
                        f" and migrated {rewritten['stored_values']} stored value key(s)"
                        if rewritten["stored_values"] else ""
                    )
                    note = {
                        "severity": "info", "code": "rewrote_macro_references", "field": "name",
                        "message": (
                            f"rewrote {rewritten['content_references']} macro reference(s) to "
                            f"{old_macro} across block contents{stored_note} to {new_macro}"
                        ),
                    }
                    findings.append(note)
                    diagnostics.append(note)
            elif old_refs:
                findings.append({
                    "severity": "warning", "code": "stale_macro_reference", "field": "name",
                    "message": f"block content still references the old name {old_macro} {old_refs} time(s); update the content separately",
                })
                diagnostics.append(findings[-1])

        if strict and any(f["severity"] == "error" for f in findings):
            return _err(
                "updated prompt variable failed validation; the file was NOT modified. Fix the "
                "flagged issues and retry (or pass strict=false to save anyway)",
                {"findings": [f for f in findings if f["severity"] == "error"]},
            )

        _save(preset, path)
        return _ok({
            "file": path,
            "block": block_name,
            "variable": var_def,
            "diagnostics": diagnostics,
            "saved": True,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_remove_prompt_variable",
    annotations={
        "title": "Remove a prompt variable from a block",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_remove_prompt_variable(
    path: PathArg,
    block_name: Annotated[str, Field(description="Exact name of the block that owns the variable", min_length=1)],
    var_name: Annotated[str, Field(description="Exact name of the variable to remove", min_length=1)],
) -> str:
    """Remove a prompt variable definition from a block and save the preset.

    This only deletes the variable definition from the block's variables array;
    it does not remove any {{var::name}} references already present in content.
    """
    try:
        preset = _load(path)
        removed = remove_prompt_variable(preset, block_name, var_name)
        _save(preset, path)
        return _ok({
            "file": path,
            "block": block_name,
            "variable": removed,
            "saved": True,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_get_stored_prompt_variables",
    annotations={
        "title": "Get stored prompt-variable values",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_get_stored_prompt_variables(path: PathArg) -> str:
    """Return the end-user's stored prompt-variable values, resolved to blocks.

    These are the saved values (as opposed to the creator's defaults) that the
    renderer merges over defaults at assembly time.
    """
    try:
        preset = _load(path)
        rows = stored_variable_report(preset)
        return _ok({
            "file": path,
            "blocks_with_stored_values": len(rows),
            "blocks": rows,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_set_stored_prompt_variable",
    annotations={
        "title": "Set a stored prompt-variable value",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_set_stored_prompt_variable(
    path: PathArg,
    block_name: Annotated[str, Field(description="Exact name of the block that owns the variable", min_length=1)],
    var_name: Annotated[str, Field(description="Exact name of the variable", min_length=1)],
    value: Annotated[
        Any,
        Field(
            description=(
                "New stored value. Coerced per the variable's type: switch→0/1, "
                "select→option id, multiselect→list of option ids, number/slider→number, "
                "text/textarea→string."
            ),
        ),
    ],
) -> str:
    """Set the stored (end-user) value of a prompt variable and save.

    Distinct from preset_update_prompt_variable, which edits the variable
    definition's default. This writes the per-block saved value.
    """
    try:
        preset = _load(path)
        result = set_stored_prompt_variable(preset, block_name, var_name, value)
        _save(preset, path)
        return _ok({"file": path, "saved": True, **result})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_remove_stored_prompt_variable",
    annotations={
        "title": "Remove a stored prompt-variable value",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_remove_stored_prompt_variable(
    path: PathArg,
    block_name: Annotated[str, Field(description="Exact name of the block that owns the variable", min_length=1)],
    var_name: Annotated[str, Field(description="Exact name of the variable", min_length=1)],
) -> str:
    """Remove a stored value so the variable falls back to its default and save."""
    try:
        preset = _load(path)
        result = set_stored_prompt_variable(preset, block_name, var_name, None, remove=True)
        _save(preset, path)
        return _ok({"file": path, "saved": True, **result})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_insert_block",
    annotations={
        "title": "Insert a new block",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_insert_block(
    path: PathArg,
    name: Annotated[str, Field(description="Name for the new block", min_length=1)],
    content: Annotated[str, Field(description="Content for the new block")],
    position: Annotated[Literal["pre_history", "post_history"], Field(description="Block position")] = "pre_history",
    role: Annotated[Literal["system", "user", "assistant_append"], Field(description="Block role")] = "system",
    enabled: Annotated[bool, Field(description="Whether the block starts enabled")] = True,
    marker: Annotated[Optional[str], Field(description="Optional marker (e.g. 'category')")] = None,
    after: Annotated[Optional[str], Field(description="Insert after this named block")] = None,
    before: Annotated[Optional[str], Field(description="Insert before this named block")] = None,
) -> str:
    """Insert a new block into the preset and save.

    Specify exactly one of `after` or `before` to position it relative to an
    existing block. If neither is given, the block is appended at the end.
    """
    try:
        preset = _load(path)
        block = new_block(
            name=name,
            content=content,
            role=role,
            enabled=enabled,
            position=position,
            marker=marker,
        )
        if after and before:
            return _err("specify at most one of 'after' or 'before'")
        if after:
            idx = insert_block(preset, block, after=after)
        elif before:
            idx = insert_block(preset, block, before=before)
        else:
            b_list = preset_blocks(preset)
            idx = len(b_list)
            b_list.append(block)
        _save(preset, path)
        return _ok({"file": path, "block": name, "inserted_index": idx, "saved": True})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_delete_block",
    annotations={
        "title": "Delete a block",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_delete_block(
    path: PathArg,
    name: Annotated[str, Field(description="Exact name of the block to delete", min_length=1)],
) -> str:
    """Remove a named block from the preset and save."""
    try:
        preset = _load(path)
        removed = delete_block(preset, name)
        _save(preset, path)
        return _ok({"file": path, "block": name, "saved": True,
                    "removed": {"id": removed.get("id"), "marker": removed.get("marker")}})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_move_block",
    annotations={
        "title": "Move a block to a new position",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_move_block(
    path: PathArg,
    name: Annotated[str, Field(description="Exact name of the block to move", min_length=1)],
    after: Annotated[Optional[str], Field(description="Move to immediately after this named block")] = None,
    before: Annotated[Optional[str], Field(description="Move to immediately before this named block")] = None,
    at_index: Annotated[Optional[int], Field(description="Move to this 0-based index", ge=0)] = None,
) -> str:
    """Move a block to a new position and save. Specify exactly one of after, before, or at_index."""
    try:
        preset = _load(path)
        block = move_block(preset, name, after=after, before=before, at_index=at_index)
        new_index = find_block_index(preset, name)
        _save(preset, path)
        return _ok({"file": path, "block": name, "new_index": new_index, "saved": True})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_clone_block",
    annotations={
        "title": "Clone a block",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_clone_block(
    path: PathArg,
    name: Annotated[str, Field(description="Exact name of the block to clone", min_length=1)],
    new_name: Annotated[Optional[str], Field(description="Name for the clone (defaults to '{name} (copy)')")] = None,
    after: Annotated[Optional[str], Field(description="Insert the clone after this named block (defaults to the source block)")] = None,
    before: Annotated[Optional[str], Field(description="Insert the clone before this named block")] = None,
    at_index: Annotated[Optional[int], Field(description="Insert the clone at this 0-based index", ge=0)] = None,
) -> str:
    """Deep-copy a block (fresh id, new name) and save.

    The clone is inserted right after the source block unless after/before/
    at_index is given. Sealed blocks get a regenerated sealedKey.
    """
    try:
        preset = _load(path)
        clone = clone_block(preset, name, new_name, after=after, before=before, at_index=at_index)
        idx = find_block_index(preset, clone["name"])
        _save(preset, path)
        return _ok({
            "file": path,
            "block": name,
            "clone": {"name": clone["name"], "id": clone["id"], "index": idx},
            "saved": True,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_rename_block",
    annotations={
        "title": "Rename a block",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_rename_block(
    path: PathArg,
    old_name: Annotated[str, Field(description="Current block name", min_length=1)],
    new_name: Annotated[str, Field(description="New block name", min_length=1)],
) -> str:
    """Rename a block in place and save the preset."""
    try:
        preset = _load(path)
        rename_block(preset, old_name, new_name)
        _save(preset, path)
        return _ok({"file": path, "old_name": old_name, "new_name": new_name, "saved": True})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_toggle_block",
    annotations={
        "title": "Toggle a block",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_toggle_block(
    path: PathArg,
    name: Annotated[str, Field(description="Exact name of the block to toggle", min_length=1)],
    enabled: Annotated[bool, Field(description="Target enabled state")],
) -> str:
    """Enable or disable a named block and save the preset."""
    try:
        preset = _load(path)
        toggle_block(preset, name, enabled)
        _save(preset, path)
        return _ok({"file": path, "block": name, "enabled": enabled, "saved": True})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_set_seal",
    annotations={
        "title": "Set or remove seal on specific blocks",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_set_seal(
    path: PathArg,
    names: Annotated[list[str], Field(description="Exact names of blocks to seal or unseal", min_length=1)],
    sealed: Annotated[bool, Field(description="True to seal, False to unseal")] = True,
    sealed_key: Annotated[
        Optional[str],
        Field(description="Explicit sealedKey to assign (optional; auto-generated from block name if omitted)"),
    ] = None,
) -> str:
    """Selectively apply or remove sealed status on one or more named blocks.

    When sealing, if ``sealed_key`` is omitted the tool auto-generates a
    kebab-case key from each block's name (e.g. "Kill the Sycophant" →
    "kill-the-sycophant").
    """
    try:
        preset = _load(path)
        results = []
        for name in names:
            block = set_block_seal(preset, name, sealed=sealed, sealed_key=sealed_key)
            results.append({
                "name": name,
                "sealed": block.get("sealed"),
                "sealedKey": block.get("sealedKey"),
            })
        _save(preset, path)
        return _ok({"file": path, "sealed": sealed, "blocks": results, "saved": True})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_mass_seal",
    annotations={
        "title": "Mass apply or remove seals",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_mass_seal(
    path: PathArg,
    sealed: Annotated[bool, Field(description="True to seal, False to unseal")] = True,
    pattern: Annotated[
        Optional[str],
        Field(description="Regex pattern matched against block names (e.g. 'POV|Character')"),
    ] = None,
    names: Annotated[
        Optional[list[str]],
        Field(description="Optional explicit block names to include alongside the pattern"),
    ] = None,
    sealed_key_prefix: Annotated[
        Optional[str],
        Field(description="Prefix for auto-generated sealedKey values (e.g. 'v2')"),
    ] = None,
    auto_key: Annotated[
        bool,
        Field(description="Force regeneration of sealedKey even if block already has one"),
    ] = False,
) -> str:
    """Mass apply or remove seals on blocks matching filters.

    If neither ``pattern`` nor ``names`` is provided, the operation targets
    **all** blocks in the preset.

    When ``sealed=True`` and a block lacks a ``sealedKey``, one is generated
    automatically from the block name in kebab-case. Use ``sealed_key_prefix``
    to prepend a version or namespace (e.g. "v2-kill-the-sycophant").
    """
    try:
        preset = _load(path)
        affected = mass_set_seal(
            preset,
            names=names or None,
            pattern=pattern or None,
            sealed=sealed,
            sealed_key_prefix=sealed_key_prefix or None,
            auto_key=auto_key,
        )
        _save(preset, path)
        return _ok({
            "file": path,
            "sealed": sealed,
            "affected_count": len(affected),
            "blocks": affected,
            "saved": True,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_check_seals",
    annotations={
        "title": "Check sealing status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_check_seals(
    path: PathArg,
) -> str:
    """Check sealing status for every block in the preset.

    Returns a full report showing which blocks are sealed, their sealedKey
    values, and summary counts.
    """
    try:
        preset = _load(path)
        rows = get_seal_status(preset)
        sealed_count = sum(1 for r in rows if r.get("sealed"))
        unsealed_count = len(rows) - sealed_count
        return _ok({
            "file": path,
            "total_blocks": len(rows),
            "sealed_count": sealed_count,
            "unsealed_count": unsealed_count,
            "blocks": rows,
        })
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_dump_enabled",
    annotations={
        "title": "Dump enabled blocks to file",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def preset_dump_enabled(
    path: PathArg,
    output_path: Annotated[
        str,
        Field(
            description=(
                "Path to write the dump to. Relative paths are resolved against "
                "the workspace root; absolute paths are accepted verbatim."
            ),
            min_length=1,
        ),
    ],
) -> str:
    """Write all enabled block contents to a single text file for review."""
    try:
        preset = _load(path)
        out = _resolve_path(output_path)
        dump_enabled_to_file(preset, str(out))
        return _ok({"file": path, "output": output_path, "saved": True})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------

@mcp.tool(
    name="preset_backup",
    annotations={
        "title": "Back up a preset file",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_backup(path: PathArg) -> str:
    """Create a timestamped backup copy of a file and return its path.

    Backups are stored in a .preset-backups directory next to the file (or
    PRESET_TOOLS_BACKUP_DIR when set).
    """
    try:
        resolved = _resolve_path(path)
        backup_path = backup_file(str(resolved))
        if backup_path is None:
            return _err(f"file '{path}' does not exist")
        return _ok({"file": path, "backup": backup_path, "saved": True})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_list_backups",
    annotations={
        "title": "List backups for a file",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_list_backups(path: PathArg) -> str:
    """List the available backup copies for a file, oldest first."""
    try:
        _resolve_path(path)
        backups = list_backups(path)
        return _ok({"file": path, "count": len(backups), "backups": backups})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="preset_restore_backup",
    annotations={
        "title": "Restore a preset from backup",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def preset_restore_backup(
    path: PathArg,
    backup: Annotated[
        str,
        Field(
            description=(
                "Backup to restore: a filename from preset_list_backups, or an "
                "absolute path to a backup file."
            ),
            min_length=1,
        ),
    ],
) -> str:
    """Restore a file from a backup, snapshotting the current file first."""
    try:
        resolved = _resolve_path(path)
        restored = restore_backup(str(resolved), backup)
        return _ok({"file": path, "restored": restored, "saved": True})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


# ---------------------------------------------------------------------------
# Macro reference
# ---------------------------------------------------------------------------

_BUNDLED_MACRO_REF_DIR = Path(__file__).resolve().parent
_CONFIGURED_MACRO_REF_DIR = Path(
    os.environ.get("PRESET_TOOLS_MACRO_DIR", _BUNDLED_MACRO_REF_DIR)
).resolve()
_LIVE_MACRO_REF_DIR: Optional[Path] = None

_LUMIVERSE_ROOT = os.environ.get("PRESET_TOOLS_LUMIVERSE_ROOT")
if _LUMIVERSE_ROOT:
    import tempfile
    from . import macro_updater

    root_path = Path(_LUMIVERSE_ROOT).resolve()
    if root_path.exists():
        live_ref_dir = Path(tempfile.mkdtemp(prefix="preset_tools_macros_"))
        try:
            macro_updater.convert(root_path, live_ref_dir / "macro_reference.json", quiet=True)
            _LIVE_MACRO_REF_DIR = live_ref_dir
            logging.getLogger("mcp").info(
                f"Auto-generated live macro reference from {root_path} into {live_ref_dir}"
            )
        except Exception as e:
            logging.getLogger("mcp").error(f"Failed to auto-generate macro reference: {e}")


def _macro_reference_dir(source: Literal["auto", "bundled", "live"]) -> Path:
    """Resolve the macro catalog selected by a macro-reference tool call."""
    if source == "bundled":
        return _BUNDLED_MACRO_REF_DIR
    if source == "live":
        if _LIVE_MACRO_REF_DIR is None:
            raise ValueError(
                "live macro reference is unavailable; set PRESET_TOOLS_LUMIVERSE_ROOT "
                "to a valid Lumiverse checkout and restart the server"
            )
        return _LIVE_MACRO_REF_DIR
    return _LIVE_MACRO_REF_DIR or _CONFIGURED_MACRO_REF_DIR

@mcp.tool(
    name="preset_macro_reference",
    annotations={
        "title": "Get macro reference",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def preset_macro_reference(
    format: Annotated[Literal["json", "markdown"], Field(description="Output format")] = "markdown",
    category: Annotated[Optional[str], Field(description="Filter to a single category (e.g. 'String' or 'Iteration')")] = None,
    search: Annotated[Optional[str], Field(description="Filter macros whose purpose/usage contains this substring")] = None,
    limit: Annotated[int, Field(description="Maximum macros to return when filtering", ge=1, le=500)] = 100,
    source: Annotated[
        Literal["auto", "bundled", "live"],
        Field(
            description=(
                "Catalog to query: 'live' uses the configured Lumiverse checkout's "
                "runtime registry, 'bundled' uses this package's checked-in digest, "
                "and 'auto' (default) prefers live when available. Use 'live' for "
                "questions about the current checkout; use 'bundled' for the shipped "
                "versioned reference."
            )
        ),
    ] = "auto",
) -> str:
    """Return the Lumiverse macro reference digest.

    Use this when you need to know what a macro does, what arguments it takes,
    or what aliases exist. Select ``source="live"`` to inspect a configured
    checkout's current runtime registry. The default markdown format is
    human-readable; use json for structured data.
    """
    try:
        ref_dir = _macro_reference_dir(source)
    except ValueError as exc:
        return _err(str(exc))

    try:
        if format == "markdown":
            text = (ref_dir / "macro_reference.md").read_text(encoding="utf-8")
            if category:
                # Return the single category section if found
                pattern = re.compile(rf"(## {re.escape(category)}\n.*?)(?=\n## |\Z)", re.S)
                m = pattern.search(text)
                if not m:
                    return _err(f"category '{category}' not found")
                section = m.group(1)
                if search:
                    lines = section.splitlines()
                    filtered = []
                    in_entry = False
                    buf: list[str] = []
                    for line in lines:
                        if line.startswith("### `{{"):
                            if buf:
                                filtered.extend(buf)
                            buf = [line]
                            in_entry = True
                        elif in_entry:
                            buf.append(line)
                    if buf:
                        filtered.extend(buf)
                    matches = []
                    for entry in "\n".join(filtered).split("\n### `{{"):
                        if not entry.strip():
                            continue
                        full = "### `{{" + entry if not entry.startswith("### `{{") else entry
                        if search.lower() in full.lower():
                            matches.append(full)
                    section = "\n".join(matches[:limit])
                return section
            if search:
                entries = []
                for entry in text.split("\n### `{{"):
                    if not entry.strip():
                        continue
                    full = "### `{{" + entry if not entry.startswith("### `{{") else entry
                    if search.lower() in full.lower():
                        entries.append(full)
                return "# Macro search results\n\n" + "\n".join(entries[:limit])
            return text

        # json format
        data = json.loads((ref_dir / "macro_reference.json").read_text(encoding="utf-8"))
        macros = data["macros"]
        if category:
            macros = [m for m in macros if m["category"] == category]
        if search:
            s = search.lower()
            macros = [
                m for m in macros
                if s in m["macro"].lower()
                or s in m.get("name", "").lower()
                or s in m["purpose"].lower()
                or s in m.get("description", "").lower()
                or s in m.get("usage", "").lower()
                or any(s in alias.lower() for alias in m.get("aliases", []))
            ]
        macros = macros[:limit]
        return _ok({"categories": data["categories"], "macros": macros})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


# ---------------------------------------------------------------------------
# Character card tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="character_card_read",
    annotations={
        "title": "Read a character card",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def character_card_read(
    path: PathArg,
    fields: Annotated[
        Optional[list[str]],
        Field(description="Specific data fields to return (e.g. ['name','description']). If omitted, returns the whole data object."),
    ] = None,
) -> str:
    """Read a chara_card_v3 file.

    Returns the contents of the ``data`` section.  If ``fields`` is provided,
    only those keys are returned, which keeps the response small for large
    cards.
    """
    try:
        resolved = _resolve_path(path)
        card = _char.load_card(str(resolved))
        data = card.get("data", {})
        if fields:
            out = {}
            for f in fields:
                try:
                    out[f] = _char.get_field(card, f)
                except (KeyError, ValueError):
                    out[f] = None
            return _ok({"file": path, "fields": out})
        return _ok({"file": path, "data": data})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="character_card_get_field",
    annotations={
        "title": "Get a character card field",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def character_card_get_field(
    path: PathArg,
    field: Annotated[str, Field(description="Field name, supports dot notation (e.g. 'extensions.talkativeness')", min_length=1)],
) -> str:
    """Retrieve a single field from a character card's data section."""
    try:
        resolved = _resolve_path(path)
        card = _char.load_card(str(resolved))
        value = _char.get_field(card, field)
        return _ok({"file": path, "field": field, "value": value})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="character_card_set_field",
    annotations={
        "title": "Set a character card field",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def character_card_set_field(
    path: PathArg,
    field: Annotated[str, Field(description="Field name, supports dot notation (e.g. 'extensions.talkativeness')", min_length=1)],
    value: Annotated[Any, Field(description="New value for the field. Strings, numbers, lists, and objects are all accepted.")],
) -> str:
    """Set a single field in a character card and save the file.

    Supports dot notation for nested fields (e.g. ``extensions.world``).
    Missing intermediate dicts are created automatically.
    """
    try:
        resolved = _resolve_path(path)
        card = _char.load_card(str(resolved))
        _char.set_field(card, field, value)
        _save_card(card, path)
        return _ok({"file": path, "field": field, "saved": True})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="character_card_get_summary",
    annotations={
        "title": "Summarise core character card fields",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def character_card_get_summary(
    path: PathArg,
) -> str:
    """Return all core v3 fields (name, description, personality, scenario,
    first_mes, mes_example, etc.) with character counts.

    This is the best tool to call first when exploring a character card,
    because it gives a compact overview without dumping the full JSON."""
    try:
        resolved = _resolve_path(path)
        card = _char.load_card(str(resolved))
        summary = _char.get_summary(card)
        return _ok({"file": path, "summary": summary})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="character_card_set_fields",
    annotations={
        "title": "Batch-update character card fields",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
@_guard_preset_write
async def character_card_set_fields(
    path: PathArg,
    updates: Annotated[
        dict[str, Any],
        Field(description="Mapping of field names to new values. Field names support dot notation."),
    ],
) -> str:
    """Update multiple fields in a character card at once and save the file.

    Example updates:
        {
          "description": "New description text...",
          "extensions.alternate_character_name": "Kate"
        }
    """
    try:
        resolved = _resolve_path(path)
        card = _char.load_card(str(resolved))
        for field, value in updates.items():
            _char.set_field(card, field, value)
        _save_card(card, path)
        return _ok({"file": path, "updated_fields": list(updates.keys()), "saved": True})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="character_card_validate",
    annotations={
        "title": "Validate a character card",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def character_card_validate(
    path: PathArg,
) -> str:
    """Check whether a JSON file conforms to basic chara_card_v3 expectations."""
    try:
        resolved = _resolve_path(path)
        card = _char.load_card(str(resolved))
        result = _char.validate_card(card)
        return _ok({"file": path, **result})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


@mcp.tool(
    name="character_card_field_stats",
    annotations={
        "title": "Character card field stats",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def character_card_field_stats(
    path: PathArg,
    field: Annotated[str, Field(description="Field name, supports dot notation", min_length=1)],
) -> str:
    """Return character count and rough token estimate for a single field."""
    try:
        resolved = _resolve_path(path)
        card = _char.load_card(str(resolved))
        stats = _char.field_stats(card, field)
        return _ok({"file": path, **stats})
    except Exception as exc:
        return _err(type(exc).__name__, traceback.format_exc())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.getLogger("mcp").setLevel(logging.WARNING)
    mcp.run()


if __name__ == "__main__":
    main()
