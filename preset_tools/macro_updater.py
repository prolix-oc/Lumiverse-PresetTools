#!/usr/bin/env python3
"""
Generate the LLM-friendly Lumiverse macro reference.

Preferred source of truth: the live macro registry in a local Lumiverse
checkout. This mirrors what `GET /api/v1/macros` returns in the app, so the
result tracks the backend's actual registered macros, aliases, categories, and
descriptions instead of relying solely on the user docs.

Usage:
    python3 -m preset_tools.macro_updater \
        /path/to/Lumiverse \
        preset_tools/macro_reference.json

Backward-compatible usage also works:
    python3 -m preset_tools.macro_updater \
        /path/to/Lumiverse/user-docs/docs/presets/macros-reference.md \
        preset_tools/macro_reference.json

If the given path lives inside a Lumiverse checkout, the runtime
registry export is used. Only when no backend root can be inferred does the
script fall back to parsing the Markdown docs directly.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_BACKEND_EXPORT_SCRIPT = r"""
import path from "node:path";
import { pathToFileURL } from "node:url";

const root = Bun.argv[1];
if (!root) {
  throw new Error("backend root path required");
}

const baseUrl = pathToFileURL(path.resolve(root) + path.sep);
const mod = await import(new URL("./src/macros/index.ts", baseUrl).href);

mod.initMacros();

const macros = mod.registry.getAllMacros().map((m) => ({
  name: m.name,
  category: m.category,
  description: m.description,
  args: (m.args ?? []).map((a) => ({
    name: a.name,
    optional: a.optional ?? false,
    defaultValue: a.defaultValue ?? "",
    description: a.description ?? "",
    type: a.type ?? "",
  })),
  aliases: m.aliases ?? [],
  returns: m.returns ?? "",
  returnType: m.returnType ?? "",
  isList: m.isList ?? false,
}));

console.log(JSON.stringify({
  backendRoot: path.resolve(root),
  totalMacros: macros.length,
  macros,
}, null, 2));
"""


_CATEGORY_MAP = {
    "state": "State",
    "State": "State",
    "memory": "Memory",
    "Memory": "Memory",
    "Chat Utils": "Chat Utilities",
}

_SPECIAL_USAGE = {
    "if": "{{if::condition}}...{{else}}...{{/if}}",
    "trim": "{{trim}}...{{/trim}}",
    "foreach": "{{foreach::list::[var]::[delimiter]}}...{{/foreach}}",
    "filter": "{{filter::list::var::[delimiter]}}...{{/filter}}",
    "some": "{{some::list::var::[delimiter]}}...{{/some}}",
    "every": "{{every::list::var::[delimiter]}}...{{/every}}",
    "foreachMessage": "{{foreachMessage::[count_or_var]::[var]}}...{{/foreachMessage}}",
    "foreachVar": "{{foreachVar::prefix::[var]}}...{{/foreachVar}}",
    "foreachChatVar": "{{foreachChatVar::prefix::[var]}}...{{/foreachChatVar}}",
    "foreachGlobalVar": "{{foreachGlobalVar::prefix::[var]}}...{{/foreachGlobalVar}}",
}


def _normalize_category(category: str) -> str:
    category = category.strip()
    if not category:
        return "Uncategorized"
    return _CATEGORY_MAP.get(category, category)


def _format_syntax(name: str, args: list[dict[str, Any]], *, is_list: bool = False) -> str:
    if name in _SPECIAL_USAGE:
        return _SPECIAL_USAGE[name]
    if is_list:
        return f"{{{{{name}::item1::item2}}}}"

    syntax = f"{{{{{name}"
    for arg in args:
        arg_name = str(arg.get("name", "")).strip()
        if not arg_name:
            continue
        syntax += f"::{'[' + arg_name + ']' if arg.get('optional') else arg_name}"
    syntax += "}}"
    return syntax


def _replace_usage_name(usage: str, canonical: str, alias: str) -> str:
    pattern = re.compile(rf"(\{{\{{/?){re.escape(canonical)}(?=(?:[:\s}}]))")
    swapped = pattern.sub(rf"\1{alias}", usage)
    return swapped if swapped != usage else usage.replace(f"{{{{{canonical}", f"{{{{{alias}", 1)


def _format_arg_summary(args: list[dict[str, Any]]) -> str:
    if not args:
        return ""

    out: list[str] = []
    for arg in args:
        name = str(arg.get("name", "")).strip()
        if not name:
            continue
        label = f"[{name}]" if arg.get("optional") else name
        desc = str(arg.get("description", "")).strip()
        if desc:
            label += f" — {desc}"
        out.append(label)
    return "; ".join(out)


def _purpose_from_description(description: str) -> str:
    text = description.strip()
    if "Usage:" in text:
        head = text.split("Usage:", 1)[0].strip()
        if head:
            return head
    return text


def _find_backend_root(src: Path) -> Path | None:
    src = src.resolve()
    if src.is_dir() and (src / "src" / "macros" / "index.ts").exists():
        return src
    for parent in [src.parent, *src.parents]:
        if (parent / "src" / "macros" / "index.ts").exists():
            return parent
    return None


def _export_runtime_catalog(backend_root: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["bun", "-e", _BACKEND_EXPORT_SCRIPT, str(backend_root)],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("bun is required to export the Lumiverse runtime macro registry") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise RuntimeError(f"failed to export runtime macro catalog: {detail}") from exc

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("runtime macro export did not produce valid JSON") from exc


def _entries_from_runtime(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    macros = catalog.get("macros", [])

    for macro in sorted(macros, key=lambda m: (_normalize_category(str(m.get("category", ""))).lower(), str(m.get("name", "")).lower())):
        name = str(macro.get("name", "")).strip()
        if not name:
            continue

        args = list(macro.get("args") or [])
        usage = _format_syntax(name, args, is_list=bool(macro.get("isList")))
        aliases = [
            _replace_usage_name(usage, name, str(alias).strip())
            for alias in (macro.get("aliases") or [])
            if str(alias).strip()
        ]

        entry = {
            "category": _normalize_category(str(macro.get("category", ""))),
            "subcategory": "",
            "source_category": str(macro.get("category", "")),
            "name": name,
            "syntax": _format_syntax(name, args, is_list=bool(macro.get("isList"))),
            "macro": usage,
            "aliases": aliases,
            "purpose": _purpose_from_description(str(macro.get("description", ""))),
            "description": str(macro.get("description", "")).strip(),
            "args": _format_arg_summary(args),
            "returns": str(macro.get("returns") or macro.get("returnType") or ""),
            "usage": usage,
        }
        entries.append(entry)

    return entries


def _extract_backticked(text: str) -> list[str]:
    return re.findall(r"`([^`]+)`", text.strip())


def _split_aliases(cell: str) -> list[str]:
    out = []
    for piece in re.split(r"[,;]", cell):
        piece = piece.strip()
        if not piece:
            continue
        if piece.startswith("`") and piece.endswith("`"):
            piece = piece[1:-1]
        if piece and piece not in {"—", "-"}:
            out.append(piece)
    return out


def _clean_cell(cell: str) -> str:
    return cell.strip().replace("\n", " ")


def _parse_table(lines: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    headers = [_clean_cell(c) for c in lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        if not line.strip():
            continue
        cells = [_clean_cell(c) for c in line.strip("|").split("|")]
        if len(cells) != len(headers):
            cells = cells[: len(headers)]
            cells += [""] * (len(headers) - len(cells))
        rows.append(dict(zip(headers, cells)))
    return headers, rows


def _row_to_entry(category: str, subcategory: str, row: dict[str, str]) -> dict[str, Any] | None:
    macro_cell = row.get("Macro", "").strip()
    if not macro_cell:
        return None

    macros = _extract_backticked(macro_cell)
    if not macros:
        return None

    primary = macros[0]
    aliases: list[str] = []
    if "Aliases" in row:
        aliases = _split_aliases(row["Aliases"])

    purpose = ""
    for key in ("Description", "Returns", "True When", "Same As"):
        if key in row:
            purpose = row[key]
            if key == "Same As":
                purpose = f"Same as {purpose}"
            break

    args = row.get("Args", "")
    returns = row.get("Returns", "")

    return {
        "category": category,
        "subcategory": subcategory,
        "macro": primary,
        "aliases": aliases,
        "purpose": purpose,
        "description": purpose,
        "args": args,
        "returns": returns,
        "usage": primary,
    }


def _entries_from_markdown(src: Path) -> list[dict[str, Any]]:
    text = src.read_text(encoding="utf-8")
    lines = text.splitlines()

    entries: list[dict[str, Any]] = []
    category = ""
    subcategory = ""

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("## "):
            category = stripped[3:].strip()
            subcategory = ""
        elif stripped.startswith("### "):
            subcategory = stripped[4:].strip()

        if stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
            table_lines = [line]
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            try:
                headers, rows = _parse_table(table_lines)
            except Exception:
                continue
            if "Macro" not in headers:
                continue
            for row in rows:
                entry = _row_to_entry(category, subcategory, row)
                if entry:
                    entries.append(entry)
            continue

        i += 1

    manual = [
        {
            "category": "Core Macros",
            "subcategory": "Conditional Logic",
            "macro": "{{if}}...{{else}}...{{/if}}",
            "aliases": [],
            "purpose": "Conditional block. Renders the true branch only if the condition is truthy; otherwise the else branch.",
            "description": "Conditional block. Renders the true branch only if the condition is truthy; otherwise the else branch.",
            "args": "condition (truthy unless empty, 0, false, null, undefined)",
            "returns": "selected branch content",
            "usage": "{{if}}...{{else}}...{{/if}}",
        },
        {
            "category": "Iteration",
            "subcategory": "{{foreach}}",
            "macro": "{{foreach::list::var::delimiter}}",
            "aliases": [],
            "purpose": "Loop over a delimiter-split list. Inside the body, {{.var}} is the current item and {{.var_index}}, {{.var_number}}, {{.var_count}}, {{.var_first}}, {{.var_last}} are available.",
            "description": "Loop over a delimiter-split list. Inside the body, {{.var}} is the current item and {{.var_index}}, {{.var_number}}, {{.var_count}}, {{.var_first}}, {{.var_last}} are available.",
            "args": "list string; optional loop variable name (default 'item'); optional delimiter (default ',')",
            "returns": "rendered body for each item",
            "usage": "{{foreach::list::var::delimiter}}",
        },
    ]

    seen = {e["macro"] for e in entries}
    for item in manual:
        if item["macro"] not in seen:
            entries.append(item)

    return entries


def _load_entries(src: Path) -> tuple[list[dict[str, Any]], str, str]:
    backend_root = _find_backend_root(src)
    if backend_root is not None:
        catalog = _export_runtime_catalog(backend_root)
        entries = _entries_from_runtime(catalog)
        return entries, str(backend_root), "runtime_registry"

    if src.is_file():
        entries = _entries_from_markdown(src)
        return entries, str(src), "markdown_docs_fallback"

    raise FileNotFoundError(f"could not find Lumiverse root or markdown reference at {src}")


def convert(src: Path, dst: Path, quiet: bool = False) -> None:
    entries, source, source_mode = _load_entries(src)

    generated_at = datetime.now(timezone.utc).isoformat()
    categories = sorted({e["category"] for e in entries}, key=str.lower)

    output = {
        "source": source,
        "source_mode": source_mode,
        "generated_at": generated_at,
        "total_macros": len(entries),
        "categories": categories,
        "macros": entries,
    }

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    if not quiet:
        print(f"Wrote {len(entries)} macros to {dst}")

    md_dst = dst.with_suffix(".md")
    md_lines = [
        "# Lumiverse Macro Reference (LLM Digest)",
        "",
        f"Generated from `{source}` ({source_mode}) at {generated_at}.",
        f"Built-in macros: **{len(entries)}**.",
        "",
        "This catalog is sourced from the backend macro registry when available, so aliases and descriptions track the actual runtime implementation.",
        "",
    ]

    by_category: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_category.setdefault(entry["category"], []).append(entry)

    for category in sorted(by_category, key=str.lower):
        md_lines.append(f"## {category}")
        md_lines.append("")
        for entry in sorted(by_category[category], key=lambda item: item["name"].lower() if item.get("name") else item["macro"].lower()):
            md_lines.append(f"### `{entry['macro']}`")
            if entry.get("aliases"):
                md_lines.append(f"- **Aliases:** {', '.join(f'`{alias}`' for alias in entry['aliases'])}")
            md_lines.append(f"- **Purpose:** {entry.get('purpose', '')}")
            if entry.get("args"):
                md_lines.append(f"- **Args:** {entry['args']}")
            if entry.get("returns"):
                md_lines.append(f"- **Returns:** {entry['returns']}")
            if entry.get("usage"):
                md_lines.append(f"- **Usage:** `{entry['usage']}`")
            md_lines.append("")

    md_dst.write_text("\n".join(md_lines), encoding="utf-8")
    if not quiet:
        print(f"Wrote Markdown digest to {md_dst}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        root = os.environ.get("PRESET_TOOLS_LUMIVERSE_ROOT")
        if not root:
            sys.exit(
                "usage: python3 -m preset_tools.macro_updater "
                "<lumiverse-root> <output.json>\n"
                "       (or set PRESET_TOOLS_LUMIVERSE_ROOT and re-run with no args)"
            )
        src = Path(root)
        dst = Path("preset_tools/macro_reference.json")
    else:
        src = Path(sys.argv[1])
        dst = Path(sys.argv[2])
    convert(src, dst)
