"""
validate.py — macro syntax + structure checker for Lumiverse preset JSON.

What it checks
--------------
1. STRUCTURE (can it parse / will it render the way the author intends?)
   - unterminated macros: `{{getvar::x` with no closing `}}`            [error]
   - empty macros: `{{}}` / `{{::x}}` (no macro name)                    [warning]
   - orphaned close tags: `{{/if}}` with no matching opener             [warning]
   - unclosed `{{if}}`: opens a conditional but never `{{/if}}` it       [warning]
     (the engine degrades it to an inline true/empty and the "body" is
      emitted unconditionally — almost always a bug)
   - `{{else}}` outside of an `{{if}}` block                            [warning]
   - unknown macro names (likely typos; render literally in the prompt)  [warning]

2. VARIABLE FLOW (are variables that are read actually set first?)
   Mirrors the engine's three scopes — local `{{.x}}`, global `{{$x}}`,
   chat `{{@x}}` — and the assembly ordering:
   - prompt variables declared in a block's `variables[]` are pre-seeded
     before any block renders, so reading them is always safe.
   - a local variable that is read but NEVER set anywhere (and isn't a
     declared prompt variable) is almost always a typo / missing setter   [warning]
   - a variable read *before* the block that sets it (in render order)    [info]
   - a variable only set inside an `{{if}}` branch, then read later        [info]
   - global/chat variables read but never set in this preset may be set
     in a previous turn or another preset, so they're only flagged        [info]

Unknown macros and unset reads are NOT fatal in the engine (unknown macros
pass through as literal text; unset reads resolve to ""), so most findings
are warnings/info, not errors. Use --strict to fail on warnings too.

Usage
-----
    python -m preset_tools.validate "ThreadBare 1.0.json"
    python -m preset_tools.validate *.json --strict
    python -m preset_tools.validate preset.json --json

Programmatic
------------
    from preset_tools import validate, validate_file, print_report
    result = validate_file("ThreadBare 1.0.json")
    print_report(result)
    if not result.ok:
        ...
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Iterator, Optional

from .macros import (
    Macro, Scoped, Text, Node,
    parse_template, VAR_OPS, KNOWN_MACROS, SCOPED_HINT, static_arg_text,
)

# Severity ordering for filtering/exit codes.
ERROR = "error"
WARNING = "warning"
INFO = "info"
_SEV_RANK = {ERROR: 3, WARNING: 2, INFO: 1}
_SEV_ICON = {ERROR: "✗", WARNING: "⚠", INFO: "ℹ"}


@dataclass
class Diagnostic:
    severity: str
    code: str
    message: str
    field_path: str               # e.g. "blocks[12] 'Voice Shaping'.content"
    block_index: Optional[int] = None
    block_name: Optional[str] = None
    enabled: bool = True
    offset: int = -1              # char offset within the field text
    line: int = 0                 # 1-based line within the field text
    col: int = 0                  # 1-based column
    snippet: str = ""

    def location(self) -> str:
        loc = self.field_path
        if self.line:
            loc += f":{self.line}:{self.col}"
        return loc


@dataclass
class ValidationResult:
    diagnostics: list[Diagnostic] = field(default_factory=list)
    source: str = ""

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == WARNING]

    @property
    def infos(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == INFO]

    @property
    def ok(self) -> bool:
        """True when there are no errors (warnings/info do not fail)."""
        return not self.errors

    def counts(self) -> dict[str, int]:
        return {
            ERROR: len(self.errors),
            WARNING: len(self.warnings),
            INFO: len(self.infos),
        }


# ---------------------------------------------------------------------------
# Schema helpers (handle both ThreadBare-flat and Lucid-nested layouts)
# ---------------------------------------------------------------------------

def _root(preset: dict) -> dict:
    """Return the dict that actually holds blocks/promptBehavior/etc."""
    inner = preset.get("preset")
    if isinstance(inner, dict) and ("blocks" in inner or "prompt_order" in inner):
        return inner
    return preset


def _blocks(preset: dict) -> list[dict]:
    root = _root(preset)
    return root.get("blocks") or root.get("prompt_order") or []


_TEMPLATE_CONTAINERS = ("promptBehavior", "completionSettings", "advancedSettings")


def _oob_template_fields(preset: dict) -> list[tuple[str, str]]:
    """Out-of-band template fields (nudges, prefills) as (path, text) pairs.

    These render outside the linear block order, so variable-flow ordering
    does not apply to them — only "is this var ever set" matters.
    """
    root = _root(preset)
    out: list[tuple[str, str]] = []
    for container in _TEMPLATE_CONTAINERS:
        obj = root.get(container)
        if not isinstance(obj, dict):
            continue
        for key, value in obj.items():
            if isinstance(value, str) and "{{" in value:
                out.append((f"{container}.{key}", value))
    return out


def _declared_prompt_vars(preset: dict) -> set[str]:
    """Names of creator-defined prompt variables seeded before assembly.

    Only enabled blocks contribute (mirrors resolvePromptVariables, which
    skips disabled blocks)."""
    names: set[str] = set()
    for b in _blocks(preset):
        if not b.get("enabled"):
            continue
        for v in (b.get("variables") or []):
            nm = v.get("name")
            if isinstance(nm, str) and nm:
                names.add(nm)
    return names


_POSITION_RANK = {"pre_history": 0, "in_history": 1, "post_history": 2}


def _render_order(blocks: list[dict]) -> list[tuple[int, dict]]:
    """Approximate the engine's reorderBlocksByPosition: stable sort by
    position group (pre_history → in_history → post_history). Returns
    (original_index, block) pairs so diagnostics keep authoring indices."""
    indexed = list(enumerate(blocks))
    return sorted(indexed, key=lambda it: _POSITION_RANK.get(it[1].get("position", "pre_history"), 0))


# ---------------------------------------------------------------------------
# Location helpers
# ---------------------------------------------------------------------------

def _line_col(text: str, offset: int) -> tuple[int, int, str]:
    """Return (line, col, snippet_line) for a char offset within text."""
    if offset < 0 or offset > len(text):
        return (0, 0, "")
    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    if line_end == -1:
        line_end = len(text)
    line = text.count("\n", 0, offset) + 1
    col = offset - line_start + 1
    snippet = text[line_start:line_end].strip()
    if len(snippet) > 100:
        # Center the snippet around the offset.
        rel = offset - line_start
        start = max(0, rel - 48)
        snippet = ("…" if start > 0 else "") + snippet[start:start + 96] + "…"
    return (line, col, snippet)


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------

def _check_structure(
    text: str,
    field_path: str,
    block_index: Optional[int],
    block_name: Optional[str],
    enabled: bool,
    declared: set[str],
    diags: list[Diagnostic],
) -> None:
    if "{{" not in text and "<user>" not in text.lower() and "<char>" not in text.lower():
        return
    try:
        ast = parse_template(text)
    except Exception as exc:  # parser should never throw; be defensive
        diags.append(_mk(ERROR, "parse-error", f"failed to parse template: {exc}",
                         field_path, block_index, block_name, enabled, text, 0))
        return
    _walk_structure(ast, text, field_path, block_index, block_name, enabled,
                    declared, diags, inside_if=False)


def _walk_structure(nodes, text, field_path, block_index, block_name, enabled,
                    declared, diags, inside_if: bool) -> None:
    def add(sev, code, msg, offset):
        diags.append(_mk(sev, code, msg, field_path, block_index, block_name,
                         enabled, text, offset))

    for node in nodes:
        if isinstance(node, Text):
            continue

        if isinstance(node, Scoped):
            _check_macro_node(node, add, declared)
            # descend: args are unconditional; body inherits if-context
            for arg in node.args:
                _walk_structure(arg, text, field_path, block_index, block_name,
                                enabled, declared, diags,
                                inside_if=inside_if)
            _walk_structure(node.body, text, field_path, block_index, block_name,
                            enabled, declared, diags,
                            inside_if=inside_if or node.name.lower() == "if")
            continue

        # Macro node
        nm = node.name.lower()

        if not node.terminated:
            add(ERROR, "unterminated-macro",
                f"`{_short(node.raw)}` is missing its closing `}}}}`", node.offset)

        if node.name == "" and not node.is_close:
            tail = _short(node.raw, 24)
            add(WARNING, "empty-macro",
                f"`{{{{` with no macro name (`{tail}`) — likely a stray/unescaped "
                f"`{{{{`. It swallows text up to the next `}}}}`; escape a literal "
                f"brace as `\\{{` if intended", node.offset)

        if node.is_close:
            if nm == "else":
                add(WARNING, "orphan-close",
                    "`{{/else}}` is not valid — `else` takes no close tag", node.offset)
            else:
                add(WARNING, "orphan-close",
                    f"`{{{{/{node.name}}}}}` has no matching opening `{{{{{node.name}...}}}}`",
                    node.offset)
            continue

        if nm == "else" and not inside_if:
            add(WARNING, "else-outside-if",
                "`{{else}}` appears outside any `{{if}}...{{/if}}` block", node.offset)

        if nm == "else" and node.args:
            add(WARNING, "else-if-unsupported",
                "`{{else}}` takes no arguments — `{{else if::...}}` is NOT "
                "supported. The condition is silently dropped and this behaves "
                "as a plain `{{else}}`. Nest an `{{if}}` inside the else branch "
                "instead.", node.offset)

        if nm == "if":
            # A non-scoped, non-close `if` means there was no matching {{/if}}.
            add(WARNING, "unclosed-if",
                "`{{if}}` has no matching `{{/if}}` — the conditional degrades "
                "to an inline true/empty value and any following text is NOT "
                "conditional", node.offset)

        _check_macro_node(node, add, declared)

        # descend into args
        for arg in node.args:
            _walk_structure(arg, text, field_path, block_index, block_name,
                            enabled, declared, diags, inside_if=inside_if)


def _check_macro_node(node, add, declared: set[str]) -> None:
    """Unknown-macro check shared by Macro and Scoped nodes."""
    nm = node.name.lower()
    if not nm or node.name == "":
        return
    if nm in KNOWN_MACROS:
        return
    if node.name in declared:           # creator-defined prompt variable used bare
        return
    # INFO, not warning: unknown macros pass through as literal text and many
    # are legitimately provided by Spindle extensions / dynamic macros at
    # runtime (e.g. spotify_*, sim_tracker). Surfaced so typos are findable.
    add(INFO, "unknown-macro",
        f"`{{{{{node.name}}}}}` is not a built-in macro — it renders literally "
        f"unless a Spindle extension/dynamic macro provides it (typo?)",
        node.offset)


# ---------------------------------------------------------------------------
# Variable-flow analysis
# ---------------------------------------------------------------------------

@dataclass
class _Unit:
    field_path: str
    text: str
    block_index: Optional[int]
    block_name: Optional[str]
    enabled: bool


def _iter_var_events(nodes, conditional: bool) -> Iterator[tuple[str, str, Optional[str], bool, int]]:
    """Yield (role, scope, var_name|None, conditional, offset) in document order.

    `var_name` is None when the name is computed at runtime (nested macros).
    Reads inside an `{{if}}` body are flagged conditional; the if-condition
    args are unconditional. Scoped setters emit their body events first, then
    the write (matching evaluation order)."""
    for node in nodes:
        if isinstance(node, Text):
            continue
        op = VAR_OPS.get(node.name.lower())
        if isinstance(node, Scoped):
            for arg in node.args:
                yield from _iter_var_events(arg, conditional)
            body_cond = conditional or node.name.lower() == "if"
            yield from _iter_var_events(node.body, body_cond)
            if op:
                name = static_arg_text(node.args[0]) if node.args else None
                yield (op.role, op.scope, (name.strip() if name else None) or None,
                       conditional, node.offset)
        else:  # Macro
            for arg in node.args:
                yield from _iter_var_events(arg, conditional)
            if op:
                name = static_arg_text(node.args[0]) if node.args else None
                yield (op.role, op.scope, (name.strip() if name else None) or None,
                       conditional, node.offset)


def _collect_writes(units: list[_Unit]) -> dict[str, set[str]]:
    writes = {"local": set(), "global": set(), "chat": set()}
    for u in units:
        for role, scope, name, _cond, _off in _iter_var_events(parse_template(u.text), False):
            if name and role in ("write", "rw"):
                writes[scope].add(name)
    return writes


def _disabled_writes(preset: dict) -> dict[str, dict[str, list[str]]]:
    """Vars written only in DISABLED blocks → {scope: {name: [block names]}}.

    These setters never run at assembly time, so a read of such a var in an
    enabled block resolves to empty until the setter block is enabled."""
    out: dict[str, dict[str, list[str]]] = {"local": {}, "global": {}, "chat": {}}
    for b in _blocks(preset):
        if b.get("enabled"):
            continue
        content = b.get("content") or ""
        if "{{" not in content:
            continue
        bname = b.get("name", "?")
        for role, scope, name, _c, _o in _iter_var_events(parse_template(content), False):
            if name and role in ("write", "rw"):
                lst = out[scope].setdefault(name, [])
                if bname not in lst:
                    lst.append(bname)
    return out


def _analyze_flow(units: list[_Unit], declared: set[str],
                  disabled_writes: dict, diags: list[Diagnostic]) -> None:
    """Order-sensitive read-before-set analysis over enabled content blocks."""
    writes_anywhere = _collect_writes(units)
    written = {"local": set(declared), "global": set(), "chat": set()}
    maybe = {"local": set(), "global": set(), "chat": set()}

    for u in units:
        for role, scope, name, cond, off in _iter_var_events(parse_template(u.text), False):
            if name is None:
                # dynamic write still establishes *something*, but we can't name it
                continue
            if role == "read":
                _classify_read(scope, name, written, maybe, writes_anywhere,
                               declared, disabled_writes, u, off, diags)
            elif role in ("write", "rw"):
                if cond:
                    maybe[scope].add(name)
                else:
                    written[scope].add(name)
                    maybe[scope].discard(name)
            # exists / delete / read_safe → no flow consequence


def _classify_read(scope, name, written, maybe, writes_anywhere, declared,
                   disabled_writes, unit: "_Unit", offset, diags) -> None:
    if name in written[scope]:
        return
    if scope == "local" and name in declared:
        return
    if name in maybe[scope]:
        diags.append(_mk(
            INFO, "conditional-set-before-read",
            f"{_scope_sigil(scope)}{name} is read here but has only been set "
            f"inside a conditional `{{{{if}}}}` branch so far — it may be unset",
            unit.field_path, unit.block_index, unit.block_name, unit.enabled,
            unit.text, offset))
        return
    if name in writes_anywhere[scope]:
        diags.append(_mk(
            INFO, "read-before-set",
            f"{_scope_sigil(scope)}{name} is read before it is set — the "
            f"assignment appears later in render order (or only in another block)",
            unit.field_path, unit.block_index, unit.block_name, unit.enabled,
            unit.text, offset))
        return
    diags.append(_never_set_diag(scope, name, declared, disabled_writes, unit, offset))


def _never_set_diag(scope, name, declared, disabled_writes, unit, offset) -> Diagnostic:
    """Build the right diagnostic for a var read that has no enabled setter."""
    disabled_in = disabled_writes.get(scope, {}).get(name)
    if disabled_in:
        where = ", ".join(repr(b) for b in disabled_in[:4])
        return _mk(
            WARNING, "set-only-in-disabled",
            f"{_scope_sigil(scope)}{name} is read here but is only set in "
            f"DISABLED block(s) [{where}] — it resolves to empty until you "
            f"enable a setter block",
            unit.field_path, unit.block_index, unit.block_name, unit.enabled,
            unit.text, offset)
    if scope == "local":
        return _mk(
            WARNING, "never-set",
            f"{_scope_sigil(scope)}{name} is read but never set anywhere in this "
            f"preset and is not a declared prompt variable — it will resolve to "
            f"an empty string (typo, or a missing setter?)",
            unit.field_path, unit.block_index, unit.block_name, unit.enabled,
            unit.text, offset)
    return _mk(
        INFO, "never-set-external",
        f"{_scope_sigil(scope)}{name} ({scope}) is read but never set in this "
        f"preset — fine if a previous turn or another preset sets it, otherwise "
        f"it resolves to empty",
        unit.field_path, unit.block_index, unit.block_name, unit.enabled,
        unit.text, offset)


def _analyze_oob(oob_units: list[_Unit], declared: set[str],
                 writes_anywhere: dict[str, set[str]], disabled_writes: dict,
                 diags: list[Diagnostic]) -> None:
    """Reads in nudge/prefill fields: only 'ever set?' matters (no ordering)."""
    for u in oob_units:
        for role, scope, name, _cond, off in _iter_var_events(parse_template(u.text), False):
            if name is None or role != "read":
                continue
            if scope == "local" and name in declared:
                continue
            if name in writes_anywhere[scope]:
                continue
            diags.append(_never_set_diag(scope, name, declared, disabled_writes, u, off))


def _scope_sigil(scope: str) -> str:
    return {"local": ".", "global": "$", "chat": "@"}.get(scope, "")


# ---------------------------------------------------------------------------
# Top-level validate
# ---------------------------------------------------------------------------

def validate(preset: dict, *, source: str = "") -> ValidationResult:
    """Validate a loaded preset dict. Returns a ValidationResult."""
    result = ValidationResult(source=source)
    diags = result.diagnostics
    declared = _declared_prompt_vars(preset)
    blocks = _blocks(preset)

    # 1. Structural checks over EVERY block (enabled or not) + oob fields.
    for i, b in enumerate(blocks):
        content = b.get("content") or ""
        name = b.get("name", f"block#{i}")
        enabled = bool(b.get("enabled"))
        fp = f"blocks[{i}] {name!r}.content"
        _check_structure(content, fp, i, name, enabled, declared, diags)

    oob = _oob_template_fields(preset)
    for path, txt in oob:
        _check_structure(txt, path, None, None, True, declared, diags)

    # 2. Variable-flow over ENABLED content blocks, in render order.
    enabled_units: list[_Unit] = []
    for orig_idx, b in _render_order(blocks):
        if not b.get("enabled"):
            continue
        content = b.get("content") or ""
        if "{{" not in content:
            continue
        enabled_units.append(_Unit(
            field_path=f"blocks[{orig_idx}] {b.get('name', '')!r}.content",
            text=content, block_index=orig_idx,
            block_name=b.get("name"), enabled=True))

    disabled_writes = _disabled_writes(preset)
    _analyze_flow(enabled_units, declared, disabled_writes, diags)

    # 3. Out-of-band reads (nudges/prefills) against "ever set?".
    writes_anywhere = _collect_writes(enabled_units)
    oob_units = [_Unit(p, t, None, None, True) for p, t in oob]
    _analyze_oob(oob_units, declared, writes_anywhere, disabled_writes, diags)

    return result


def validate_file(path: str) -> ValidationResult:
    """Load a preset JSON file and validate it."""
    with open(path, encoding="utf-8") as f:
        preset = json.load(f)
    return validate(preset, source=path)


# ---------------------------------------------------------------------------
# Diagnostic factory
# ---------------------------------------------------------------------------

def _mk(severity, code, message, field_path, block_index, block_name, enabled,
        text, offset) -> Diagnostic:
    line, col, snippet = _line_col(text, offset)
    return Diagnostic(
        severity=severity, code=code, message=message, field_path=field_path,
        block_index=block_index, block_name=block_name, enabled=enabled,
        offset=offset, line=line, col=col, snippet=snippet,
    )


def _short(s: str, n: int = 40) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(result: ValidationResult, *, min_severity: str = INFO,
                 show_snippets: bool = True, file=None) -> None:
    """Print a human-readable report. min_severity filters output
    ('error' | 'warning' | 'info')."""
    out = file or sys.stdout
    threshold = _SEV_RANK.get(min_severity, 1)
    shown = [d for d in result.diagnostics if _SEV_RANK[d.severity] >= threshold]

    header = result.source or "preset"
    print(f"\n=== Macro validation: {header} ===", file=out)

    if not shown:
        c = result.counts()
        if sum(c.values()) == 0:
            print("✓ No issues found.", file=out)
        else:
            print(f"✓ No issues at or above '{min_severity}'. "
                  f"(suppressed: {c[INFO]} info, {c[WARNING]} warning, {c[ERROR]} error)",
                  file=out)
        _print_summary(result, out)
        return

    # Group by block for readability.
    shown.sort(key=lambda d: (d.block_index if d.block_index is not None else 1_000_000,
                              d.offset))
    last_group = object()
    for d in shown:
        group = (d.block_index, d.field_path)
        if group != last_group:
            tag = "" if d.enabled else " (disabled)"
            print(f"\n  {d.field_path}{tag}", file=out)
            last_group = group
        loc = f"L{d.line}:{d.col}" if d.line else "-"
        print(f"    {_SEV_ICON[d.severity]} [{d.code}] {loc}  {d.message}", file=out)
        if show_snippets and d.snippet:
            print(f"        | {d.snippet}", file=out)

    _print_summary(result, out)


def _print_summary(result: ValidationResult, out) -> None:
    c = result.counts()
    print(f"\n  Summary: {c[ERROR]} error(s), {c[WARNING]} warning(s), "
          f"{c[INFO]} info", file=out)
    status = "OK" if result.ok else "FAILED"
    print(f"  Status: {status}\n", file=out)


def _result_to_dict(result: ValidationResult) -> dict:
    return {
        "source": result.source,
        "ok": result.ok,
        "counts": result.counts(),
        "diagnostics": [
            {
                "severity": d.severity, "code": d.code, "message": d.message,
                "field": d.field_path, "block_index": d.block_index,
                "block_name": d.block_name, "enabled": d.enabled,
                "line": d.line, "col": d.col, "offset": d.offset,
                "snippet": d.snippet,
            }
            for d in result.diagnostics
        ],
    }


# ---------------------------------------------------------------------------
# Variable usage report (handy for studying a preset, not just validating it)
# ---------------------------------------------------------------------------

def variable_report(preset: dict) -> dict:
    """Return a per-variable usage map: {scope: {name: {...}}}.

    Each entry records whether it's a declared prompt var, the block indices
    that read it and write it. Useful for auditing variable plumbing."""
    declared = _declared_prompt_vars(preset)
    blocks = _blocks(preset)
    report: dict[str, dict[str, dict]] = {"local": {}, "global": {}, "chat": {}}

    def entry(scope, name):
        return report[scope].setdefault(name, {
            "declared": (scope == "local" and name in declared),
            "read_in": [], "written_in": [], "checked_in": [],
        })

    for orig_idx, b in _render_order(blocks):
        if not b.get("enabled"):
            continue
        content = b.get("content") or ""
        if "{{" not in content:
            continue
        bname = b.get("name", f"#{orig_idx}")
        for role, scope, name, _cond, _off in _iter_var_events(parse_template(content), False):
            if not name:
                continue
            e = entry(scope, name)
            if role == "read":
                if bname not in e["read_in"]:
                    e["read_in"].append(bname)
            elif role in ("write", "rw"):
                if bname not in e["written_in"]:
                    e["written_in"].append(bname)
            elif role == "exists":
                if bname not in e["checked_in"]:
                    e["checked_in"].append(bname)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="preset_tools.validate",
        description="Validate macro syntax and variable flow in Lumiverse preset JSON.")
    p.add_argument("files", nargs="+", help="preset JSON file(s) to validate")
    p.add_argument("--strict", action="store_true",
                   help="exit non-zero if any warnings are found (not just errors)")
    p.add_argument("--quiet", action="store_true",
                   help="only show errors and warnings (suppress info)")
    p.add_argument("--errors-only", action="store_true",
                   help="only show errors")
    p.add_argument("--no-snippets", action="store_true",
                   help="don't print source snippets")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable JSON instead of text")
    args = p.parse_args(argv)

    min_sev = INFO
    if args.errors_only:
        min_sev = ERROR
    elif args.quiet:
        min_sev = WARNING

    results: list[ValidationResult] = []
    for path in args.files:
        try:
            results.append(validate_file(path))
        except FileNotFoundError:
            print(f"error: file not found: {path}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            print(f"error: {path}: invalid JSON: {exc}", file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps([_result_to_dict(r) for r in results], indent=2, ensure_ascii=False))
    else:
        for r in results:
            print_report(r, min_severity=min_sev, show_snippets=not args.no_snippets)

    total_errors = sum(len(r.errors) for r in results)
    total_warnings = sum(len(r.warnings) for r in results)
    if total_errors:
        return 2
    if args.strict and total_warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
