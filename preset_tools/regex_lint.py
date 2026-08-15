"""Repair, lint, and compile Lumiverse regex script payloads.

LLM callers routinely mangle JSON escaping when passing ``find_regex`` and
``replace_string`` through a tool call: patterns arrive over-escaped
(``\\\\d`` where ``\\d`` was meant), wrapped in JavaScript ``/.../flags``
literals, or using Python syntax (``(?P<name>...)``).  This module normalizes
those inputs, reports every repair it applied, and validates the result.

Validation happens in two layers:

* A structural scanner (:func:`lint_js_pattern`) that understands JavaScript
  regex syntax — named groups, lookbehind, classes, quantifiers, u-flag
  rules — without compiling anything.  It is conservative: only constructs
  that are definitely JavaScript syntax errors produce error findings.
* An optional real compile via a JavaScript engine (node, or osascript JXA
  on macOS).  When an engine is available its verdict is authoritative for
  pattern syntax; structural errors that the engine accepts are downgraded
  to warnings.

Replacement strings and ``actions`` fields are checked for ``$<name>`` /
``$N`` references against the capture groups the pattern actually defines,
which catches the most common authoring mistake: a typo'd group name in an
otherwise valid script.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

_JS_FLAGS = frozenset("dgimsuvy")
_NAME_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_QUANT_RE = re.compile(r"\{(\d+)(,(\d*))?\}")
_HEX = frozenset("0123456789abcdefABCDEF")
_PYTHON_ISM_ESCAPES = frozenset("AZz")
# Two-character sequences in a replace_string that are almost always
# over-escaped JSON rather than intentional literal text.
_REPLACEMENT_UNESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\", "/": "/"}
# Same idea for patterns: a doubled backslash before one of these is a
# strong signal of JSON over-escaping.
_SUSPICIOUS_DOUBLE_ESCAPES = re.compile(r"\\\\(?=[dDsSwWbB0-9nrtfv.<>()\[\]{}$*+?|^/\\\\])")
_MAX_ENGINE_PATTERN = 200_000


def _finding(severity: str, code: str, message: str, pos: Optional[int] = None, field: str = "find_regex") -> dict[str, Any]:
    out: dict[str, Any] = {"severity": severity, "code": code, "message": message, "field": field}
    if pos is not None:
        out["pos"] = pos
    return out


def _errors(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in findings if f["severity"] == "error"]


# ---------------------------------------------------------------------------
# Input normalization / repair
# ---------------------------------------------------------------------------

def _merge_flags(*flag_strings: str) -> str:
    merged: list[str] = []
    for flags in flag_strings:
        for flag in flags:
            if flag not in merged:
                merged.append(flag)
    return "".join(merged)


def _parse_js_string_literal(text: str, start: int, quote: str) -> tuple[Optional[str], int]:
    """Parse a JS string literal at ``start``; return (value, end_index_after_quote)."""
    simple = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
    i = start + 1
    out: list[str] = []
    while i < len(text):
        c = text[i]
        if c == quote:
            return "".join(out), i + 1
        if c == "\\":
            if i + 1 >= len(text):
                return None, i
            e = text[i + 1]
            if e == "x" and i + 3 < len(text) and text[i + 2] in _HEX and text[i + 3] in _HEX:
                out.append(chr(int(text[i + 2 : i + 4], 16)))
                i += 4
            elif e == "u" and text[i + 2 : i + 6] and all(ch in _HEX for ch in text[i + 2 : i + 6]):
                out.append(chr(int(text[i + 2 : i + 6], 16)))
                i += 6
            elif e in simple:
                out.append(simple[e])
                i += 2
            elif e == "\n":
                i += 2  # line continuation
            else:
                out.append(e)
                i += 2
        else:
            out.append(c)
            i += 1
    return None, i


def strip_regex_literal(pattern: str, flags: str = "") -> tuple[str, str, list[dict[str, Any]]]:
    """Strip ``/.../flags`` delimiters (and ``new RegExp("...", "gi")`` wrappers).

    Returns ``(pattern, flags, notes)``.  When the input does not look like a
    regex literal it is returned unchanged.
    """
    notes: list[dict[str, Any]] = []
    s = pattern

    wrapper = re.match(r"\s*new\s+RegExp\s*\(", s)
    if wrapper:
        rest = s[wrapper.end():]
        if rest[:1] in ("'", '"'):
            value, end = _parse_js_string_literal(rest, 0, rest[0])
            if value is not None:
                tail = rest[end:]
                m = re.match(r"\s*(?:,\s*(['\"])([a-z]*)\1)?\s*\)\s*$", tail)
                if m:
                    merged = _merge_flags(flags, m.group(2) or "")
                    notes.append(_finding(
                        "info", "unwrapped_new_regexp",
                        'unwrapped new RegExp(...) constructor; flags merged',
                        field="find_regex",
                    ))
                    return value, merged, notes
        notes.append(_finding(
            "warning", "new_regexp_wrapper",
            'input looks like a new RegExp(...) call but could not be unwrapped; provide the bare pattern body instead',
            field="find_regex",
        ))
        return s, flags, notes

    if not s.startswith("/"):
        return s, flags, notes

    for idx in range(len(s) - 1, 0, -1):
        if s[idx] != "/":
            continue
        backslashes = 0
        j = idx - 1
        while j >= 0 and s[j] == "\\":
            backslashes += 1
            j -= 1
        if backslashes % 2 == 1:
            continue  # escaped slash, not a delimiter
        suffix = s[idx + 1:]
        if not all(c in _JS_FLAGS for c in suffix):
            continue
        if len(set(suffix)) != len(suffix):
            continue
        body = s[1:idx]
        if not body:
            continue
        merged = _merge_flags(flags, suffix)
        message = "stripped /.../ regex literal delimiters"
        if suffix:
            message += f"; merged flags '{suffix}'"
        notes.append(_finding("info", "stripped_literal", message, field="find_regex"))
        return body, merged, notes

    notes.append(_finding(
        "warning", "unterminated_literal",
        "pattern starts with '/' but no matching unescaped '/flags' terminator was found; "
        "if a /.../ literal was intended, interior \\/ escapes may have been consumed by JSON decoding",
        field="find_regex",
    ))
    return s, flags, notes


def lint_js_pattern(pattern: str, flags: str = "") -> tuple[list[dict[str, Any]], list[str], int]:
    """Structurally lint a JavaScript regex.

    Returns ``(findings, group_names, capture_group_count)``.  Only constructs
    that are definitely JS syntax errors yield ``error`` findings; anything
    uncertain is a ``warning`` so legitimate patterns are never blocked.
    """
    findings: list[dict[str, Any]] = []
    names: list[str] = []
    numeric_backrefs: list[tuple[int, int]] = []
    named_backrefs: list[tuple[str, int]] = []
    capture_count = 0
    has_u = "u" in (flags or "")

    def err(code: str, message: str, pos: int) -> None:
        findings.append(_finding("error", code, message, pos))

    def warn(code: str, message: str, pos: int) -> None:
        findings.append(_finding("warning", code, message, pos))

    i, n = 0, len(pattern)
    open_groups = 0
    in_class = False
    prev_quantifiable = False
    prev_was_quantifier = False

    while i < n:
        c = pattern[i]

        if in_class:
            if c == "\\":
                i += 2  # any escaped char is valid inside a class
            elif c == "]":
                in_class = False
                prev_quantifiable, prev_was_quantifier = True, False
                i += 1
            else:
                i += 1
            continue

        if c == "\\":
            if i + 1 >= n:
                err("trailing_backslash", "pattern ends with a lone backslash", i)
                break
            e = pattern[i + 1]
            if e == "c":
                if i + 2 < n and pattern[i + 2].isalpha():
                    i += 3
                else:
                    (err if has_u else warn)("invalid_control_escape", "\\c must be followed by a letter", i)
                    i += 2
            elif e == "x":
                if i + 3 < n and pattern[i + 2] in _HEX and pattern[i + 3] in _HEX:
                    i += 4
                else:
                    (err if has_u else warn)("invalid_hex_escape", "\\x must be followed by two hex digits", i)
                    i += 2
            elif e == "u":
                if all(ch in _HEX for ch in pattern[i + 2 : i + 6]) and len(pattern[i + 2 : i + 6]) == 4:
                    i += 6
                elif i + 2 < n and pattern[i + 2] == "{":
                    end = pattern.find("}", i + 3)
                    inner = pattern[i + 3 : end] if end >= 0 else ""
                    if end < 0 or not inner or not all(ch in _HEX for ch in inner):
                        (err if has_u else warn)("invalid_unicode_escape", "\\u{...} must contain hex digits", i)
                    elif not has_u:
                        warn("unicode_braces_without_u", "\\u{...} is only an escape when the u flag is set; without it this matches literally", i)
                    i = end + 1 if end >= 0 else n
                else:
                    (err if has_u else warn)("invalid_unicode_escape", "\\u must be followed by four hex digits", i)
                    i += 2
            elif e in "pP":
                if i + 2 < n and pattern[i + 2] == "{":
                    end = pattern.find("}", i + 3)
                    if end < 0:
                        err("unterminated_escape", f"\\{e}{{...}} is missing '}}'", i)
                        i = n
                    else:
                        if not has_u:
                            warn("property_escape_without_u", f"\\{e}{{...}} requires the u flag in JavaScript", i)
                        i = end + 1
                else:
                    (err if has_u else warn)("invalid_property_escape", f"\\{e} must be followed by {{...}}", i)
                    i += 2
            elif e == "k":
                if i + 2 < n and pattern[i + 2] == "<":
                    end = pattern.find(">", i + 3)
                    if end < 0:
                        (err if has_u else warn)("invalid_backref", "\\k is missing '>'", i)
                        i += 2
                    else:
                        named_backrefs.append((pattern[i + 3 : end], i))
                        i = end + 1
                else:
                    warn("invalid_backref", "\\k must be followed by <name>", i)
                    i += 2
            elif e.isdigit():
                if e == "0":
                    i += 2
                else:
                    j = i + 1
                    while j < n and j - (i + 1) < 2 and pattern[j].isdigit():
                        j += 1
                    numeric_backrefs.append((int(pattern[i + 1 : j]), i))
                    i = j
            elif e in _PYTHON_ISM_ESCAPES:
                meaning = "'^'" if e == "A" else "'$'"
                warn("python_escape", f"\\{e} is a Python regex escape; JavaScript treats it as literal '{e}' — did you mean {meaning}?", i)
                i += 2
            else:
                i += 2  # \d \s \w \b, identity escapes, etc.
            prev_quantifiable, prev_was_quantifier = True, False
            continue

        if c == "[":
            in_class = True
            i += 1
            if i < n and pattern[i] == "^":
                i += 1
            prev_quantifiable, prev_was_quantifier = False, False
            continue

        if c == "(":
            j = i + 1
            is_capture = True
            if j < n and pattern[j] == "?":
                k = j + 1
                if k >= n:
                    err("unterminated_group", "group '(?' is incomplete", i)
                    i = k
                else:
                    ch = pattern[k]
                    if ch in "=:!":
                        i = k + 1
                        is_capture = False
                    elif ch == "<":
                        m = k + 1
                        if m < n and pattern[m] in "=!":
                            i = m + 1
                            is_capture = False
                        else:
                            end = pattern.find(">", m)
                            if end < 0:
                                err("invalid_group_name", "named group is missing '>'", i)
                                i = m
                            else:
                                name = pattern[m:end]
                                if not name:
                                    err("invalid_group_name", "named group has an empty name", i)
                                elif name in names:
                                    warn("duplicate_group_name", f"duplicate capture group name '{name}'", i)
                                elif all(ord(ch2) < 128 for ch2 in name) and not _NAME_RE.fullmatch(name):
                                    err("invalid_group_name", f"'{name}' is not a valid JavaScript group name", i)
                                names.append(name)
                                i = end + 1
                    else:
                        m = k
                        while m < n and (pattern[m].isalpha() or pattern[m] == "-"):
                            m += 1
                        mods = pattern[k:m]
                        if mods and set(mods) <= set("ims-") and m < n and pattern[m] == ":":
                            i = m + 1
                            is_capture = False
                        else:
                            err(
                                "invalid_group",
                                "unrecognized group syntax '(?" + pattern[k : k + 8] + "' — expected ?: ?= ?! ?<= ?<! ?<name> or (?flags:",
                                i,
                            )
                            i = k + 1
                            is_capture = False
            else:
                i = j
            if is_capture:
                capture_count += 1
            open_groups += 1
            prev_quantifiable, prev_was_quantifier = False, False
            continue

        if c == ")":
            if open_groups == 0:
                err("unmatched_paren", "unmatched ')'", i)
            else:
                open_groups -= 1
            prev_quantifiable, prev_was_quantifier = True, False
            i += 1
            continue

        if c in "*+?":
            if c == "?" and prev_was_quantifier:
                pass  # lazy quantifier (a*?, a+?, a??, a{2,5}?)
            elif not prev_quantifiable:
                err("nothing_to_repeat", f"quantifier '{c}' has nothing to repeat", i)
            prev_quantifiable, prev_was_quantifier = False, True
            i += 1
            continue

        if c == "{":
            m = _QUANT_RE.match(pattern, i)
            if m:
                lo = int(m.group(1))
                hi_text = m.group(3)
                if hi_text and lo > int(hi_text):
                    err("reversed_range", f"quantifier {{{lo},{hi_text}}} has a minimum above its maximum", i)
                if not prev_quantifiable:
                    err("nothing_to_repeat", f"quantifier '{m.group(0)}' has nothing to repeat", i)
                prev_quantifiable, prev_was_quantifier = False, True
                i = m.end()
            else:
                if has_u:
                    err("lone_brace", "'{' must be part of a quantifier or escaped when using the u flag", i)
                prev_quantifiable, prev_was_quantifier = True, False
                i += 1
            continue

        if c == "}":
            if has_u:
                err("lone_brace", "'}' must be part of a quantifier or escaped when using the u flag", i)
            prev_quantifiable, prev_was_quantifier = True, False
            i += 1
            continue

        if c == "|":
            prev_quantifiable, prev_was_quantifier = False, False
        else:
            # literal atom, ^, $, or a bare ] (legal in JS outside classes)
            prev_quantifiable, prev_was_quantifier = True, False
        i += 1

    if in_class:
        err("unterminated_class", "character class is missing ']'", n)
    if open_groups > 0:
        err("unclosed_group", f"{open_groups} unclosed group(s) '('", n)

    for num, pos in numeric_backrefs:
        if num > capture_count:
            if has_u:
                err("numeric_ref_out_of_range", f"\\{num} refers to a capture group that does not exist (pattern has {capture_count})", pos)
            else:
                warn("numeric_ref_out_of_range", f"\\{num} exceeds the {capture_count} capture group(s); without the u flag JavaScript reads it as a legacy octal escape", pos)
    for name, pos in named_backrefs:
        if name not in names:
            err("unknown_group_ref", f"\\k<{name}> does not match any named capture group" + (f" (defined: {', '.join(names)})" if names else ""), pos)

    return findings, names, capture_count


def check_replacement_refs(
    text: str,
    group_names: list[str],
    capture_count: int,
    field: str = "replace_string",
) -> list[dict[str, Any]]:
    """Check ``$<name>`` / ``$N`` references against the pattern's groups."""
    findings: list[dict[str, Any]] = []
    if "$" not in text:
        return findings
    i, n = 0, len(text)
    while i < n:
        if text[i] != "$":
            i += 1
            continue
        nxt = text[i + 1] if i + 1 < n else ""
        if nxt in ("$", "&", "`", "'"):
            i += 2
            continue
        if nxt == "<":
            end = text.find(">", i + 2)
            if end < 0:
                i += 2
                continue
            name = text[i + 2 : end]
            if name and name not in group_names:
                available = f"; available groups: {', '.join(group_names)}" if group_names else " and the pattern defines no named groups"
                findings.append(_finding(
                    "error", "unknown_group_ref",
                    f"'$<{name}>' in {field} does not match any named capture group in find_regex{available}",
                    i, field,
                ))
            i = end + 1
            continue
        if nxt.isdigit():
            j = i + 1
            while j < n and j - (i + 1) < 2 and text[j].isdigit():
                j += 1
            num = int(text[i + 1 : j])
            if num > capture_count:
                single = int(text[i + 1])
                if single <= capture_count:
                    findings.append(_finding(
                        "warning", "ambiguous_numeric_ref",
                        f"'${num}' in {field} exceeds the {capture_count} capture group(s); JavaScript will substitute group {single} followed by the literal '{text[i + 2 : j]}'",
                        i, field,
                    ))
                else:
                    findings.append(_finding(
                        "error", "numeric_ref_out_of_range",
                        f"'${num}' in {field} exceeds the {capture_count} capture group(s) in find_regex",
                        i, field,
                    ))
            i = j
            continue
        i += 1
    return findings


# ---------------------------------------------------------------------------
# JavaScript engine (node preferred, osascript JXA fallback)
# ---------------------------------------------------------------------------

_NODE_COMPILE_JS = """
const items = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = [];
for (const it of items) {
  try { new RegExp(it.pattern, it.flags || ''); out.push({ok: true}); }
  catch (e) { out.push({ok: false, message: String((e && e.message) || e)}); }
}
process.stdout.write(JSON.stringify(out));
"""

_NODE_RENDER_JS = """
const q = JSON.parse(require('fs').readFileSync(0, 'utf8'));
try {
  const re = new RegExp(q.pattern, q.flags || '');
  const matches = [];
  if (re.global || re.sticky) {
    let m, guard = 0;
    while ((m = re.exec(q.text)) !== null && guard++ < 2000) {
      matches.push({index: m.index, captured: m.slice(1), groups: Object.assign({}, m.groups)});
      if (m.index === re.lastIndex) re.lastIndex++;
    }
  } else {
    const m = re.exec(q.text);
    if (m) matches.push({index: m.index, captured: m.slice(1), groups: Object.assign({}, m.groups)});
  }
  const out = {ok: true, matched: matches.length > 0, matches};
  if (q.replacement !== undefined) out.rendered = q.text.replace(re, q.replacement);
  process.stdout.write(JSON.stringify(out));
} catch (e) {
  process.stdout.write(JSON.stringify({ok: false, message: String((e && e.message) || e)}));
}
"""

_JXA_COMPILE = (
    'function run() {'
    'var p = $.getenv("PT_PATTERN"), f = $.getenv("PT_FLAGS");'
    'try { new RegExp(p, f); return "ok"; }'
    'catch (e) { throw new Error("SyntaxError: " + e.message); }'
    '}'
)

_engine_state: dict[str, Any] = {"checked": False, "kind": None}


def _run_node(script: str, payload: Any, timeout: float = 15.0) -> Optional[Any]:
    binary = os.environ.get("PRESET_TOOLS_JS") or "node"
    try:
        proc = subprocess.run(
            [binary, "-e", script],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _osascript_compile_raw(pattern: str, flags: str) -> Optional[dict[str, Any]]:
    env = dict(os.environ, PT_PATTERN=pattern, PT_FLAGS=flags or "")
    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", _JXA_COMPILE],
            capture_output=True, text=True, timeout=15.0, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == 0:
        return {"ok": True}
    message = (proc.stderr or "").strip()
    match = re.search(r"SyntaxError: (.+?)(?:\s*\(-?\d+\))?\s*$", message, re.S)
    return {"ok": False, "message": match.group(1) if match else message or "invalid pattern"}


def engine_kind(refresh: bool = False) -> Optional[str]:
    """Return 'node', 'osascript', or None (no usable JavaScript engine).

    An explicit ``PRESET_TOOLS_JS`` environment variable wins: a path to a
    node-compatible binary enables it, while 'none'/'off'/'0' disables all
    engine checks.
    """
    if not refresh and _engine_state["checked"]:
        return _engine_state["kind"]

    kind: Optional[str] = None
    override = os.environ.get("PRESET_TOOLS_JS")
    if override:
        if override.lower() not in ("", "none", "off", "0", "false") and (
            shutil.which(override) or os.path.isfile(override)
        ):
            kind = "node"  # override must be a node-compatible binary
    elif shutil.which("node"):
        kind = "node"
    elif sys.platform == "darwin" and shutil.which("osascript"):
        kind = "osascript"

    # Functional probe so a broken or absent binary degrades gracefully.
    if kind == "node":
        if _run_node(_NODE_COMPILE_JS, [{"pattern": "a", "flags": ""}]) is None:
            kind = None
    elif kind == "osascript":
        if _osascript_compile_raw("a", "") is None:
            kind = None

    _engine_state["checked"] = True
    _engine_state["kind"] = kind
    return kind


def engine_compile_many(pairs: list[tuple[str, str]]) -> Optional[list[dict[str, Any]]]:
    """Compile ``(pattern, flags)`` pairs in one engine process.

    Returns one ``{"ok": bool, "message"?: str}`` per pair, or None when no
    engine is available.
    """
    if not pairs:
        return []
    kind = engine_kind()
    if kind is None:
        return None
    if kind == "node":
        if any(len(p) > _MAX_ENGINE_PATTERN for p, _ in pairs):
            return None
        result = _run_node(_NODE_COMPILE_JS, [{"pattern": p, "flags": f} for p, f in pairs])
        if result is None or len(result) != len(pairs):
            return None
        return result
    results = []
    for pattern, flags in pairs:
        result = _osascript_compile_raw(pattern, flags) if len(pattern) <= _MAX_ENGINE_PATTERN else None
        results.append(result or {"ok": False, "message": "engine check failed"})
    return results


def engine_compile(pattern: str, flags: str = "") -> Optional[dict[str, Any]]:
    """Compile one pattern.  None means no engine available."""
    results = engine_compile_many([(pattern, flags)])
    return results[0] if results is not None else None


def engine_render(pattern: str, flags: str, replacement: str, text: str) -> Optional[dict[str, Any]]:
    """Run a real replacement against sample text (node only).

    Returns ``{"ok", "matched", "matches", "rendered"}`` or an error dict;
    None when no node-compatible engine is available.
    """
    if engine_kind() != "node" or len(pattern) > _MAX_ENGINE_PATTERN:
        return None
    return _run_node(_NODE_RENDER_JS, {
        "pattern": pattern, "flags": flags, "replacement": replacement, "text": text,
    })


# ---------------------------------------------------------------------------
# Whole-script lint
# ---------------------------------------------------------------------------

_ACTION_TEXT_FIELDS = ("title", "subtitle", "content")
_UNSET = object()


def lint_script(
    script: dict[str, Any],
    use_engine: bool = True,
    compile_result: Any = _UNSET,
) -> list[dict[str, Any]]:
    """Lint one complete regex script (pattern, replacement, action refs).

    ``compile_result`` lets a caller that compiled the pattern in a batch
    pass the engine verdict in; the default sentinel means "compile it here
    when ``use_engine`` is set" and ``None`` disables engine checking.
    """
    pattern = script.get("find_regex") or ""
    flags = script.get("flags") or ""
    findings, names, capture_count = lint_js_pattern(pattern, flags)

    engine_result = compile_result
    if engine_result is _UNSET:
        engine_result = engine_compile(pattern, flags) if (use_engine and pattern) else None
    if engine_result is not None:
        if engine_result["ok"]:
            # The engine is authoritative: keep the findings for
            # transparency but do not let approximation block a script
            # that really compiles.
            for finding in findings:
                if finding["severity"] == "error":
                    finding["severity"] = "warning"
                    finding["message"] += " (structural linter flagged this, but the JavaScript engine compiled the pattern successfully)"
        else:
            findings.append(_finding(
                "error", "engine_syntax_error",
                f"JavaScript engine rejected the pattern: {engine_result.get('message', 'invalid pattern')}",
                field="find_regex",
            ))
    elif use_engine and pattern and _errors(findings):
        findings.append(_finding(
            "info", "engine_unavailable",
            "no JavaScript engine is available, so this structural lint is the only pattern check performed",
            field="find_regex",
        ))

    findings += check_replacement_refs(script.get("replace_string") or "", names, capture_count)

    actions = script.get("actions")
    if isinstance(actions, list):
        for a_index, action in enumerate(actions):
            if not isinstance(action, dict):
                continue
            for key in _ACTION_TEXT_FIELDS:
                value = action.get(key)
                if isinstance(value, str):
                    findings += check_replacement_refs(value, names, capture_count, field=f"actions[{a_index}].{key}")
    return findings


def normalize_pattern_input(
    pattern: str, flags: str = "", *, repair: bool = True
) -> tuple[str, str, list[dict[str, Any]]]:
    """Normalize an LLM-provided ``find_regex``.

    Applies (and reports) repairs for common tool-call escaping mistakes:
    surrounding whitespace, ``/.../flags`` literals, ``new RegExp()``
    wrappers, Python named-group syntax, and JSON over-escaped backslashes.
    """
    diagnostics: list[dict[str, Any]] = []
    p = pattern
    if not repair:
        return p, flags, diagnostics

    if p != p.strip():
        p = p.strip()
        diagnostics.append(_finding("info", "trimmed", "trimmed surrounding whitespace from find_regex", field="find_regex"))

    p, flags, notes = strip_regex_literal(p, flags)
    diagnostics += notes

    if "(?P<" in p:
        count = p.count("(?P<")
        p = p.replace("(?P<", "(?<")
        diagnostics.append(_finding(
            "info", "python_named_group",
            f"converted {count} Python named group(s) '(?P<name>' to JavaScript '(?<name>'", field="find_regex",
        ))
    if "(?P=" in p:
        diagnostics.append(_finding(
            "warning", "python_backref",
            "'(?P=name)' Python backreference syntax is not supported by JavaScript; rewrite the pattern", field="find_regex",
        ))

    if "\\" in p:
        collapsed = p.replace("\\\\", "\\")
        if collapsed != p:
            errs_before = _errors(lint_js_pattern(p, flags)[0])
            errs_after = _errors(lint_js_pattern(collapsed, flags)[0])
            if errs_after and not errs_before:
                diagnostics.append(_finding(
                    "warning", "doubled_backslashes",
                    "find_regex contains doubled backslashes that look like literal backslash escapes; left as-is "
                    "because collapsing them would introduce syntax errors (resend single backslashes if JSON over-escaping was intended)",
                    field="find_regex",
                ))
            else:
                pairs = p.count("\\\\")
                p = collapsed
                diagnostics.append(_finding(
                    "info", "collapsed_backslashes",
                    f"collapsed {pairs} doubled backslash(es) in find_regex (JSON over-escaping repair)",
                    field="find_regex",
                ))
    return p, flags, diagnostics


def normalize_replacement_input(replacement: str, *, repair: bool = True) -> tuple[str, list[dict[str, Any]]]:
    """Normalize an LLM-provided ``replace_string``.

    Converts literal two-character escape sequences (``\\n``, ``\\t``, ``\\r``,
    ``\\"``, ``\\'``, ``\\/``, ``\\\\``) that result from JSON over-escaping
    into their real characters, and reports the conversion.  Other sequences
    (``\\d`` etc.) are left untouched.
    """
    if not repair or "\\" not in replacement:
        return replacement, []
    out: list[str] = []
    converted = 0
    i, n = 0, len(replacement)
    while i < n:
        c = replacement[i]
        if c == "\\" and i + 1 < n and replacement[i + 1] in _REPLACEMENT_UNESCAPES:
            out.append(_REPLACEMENT_UNESCAPES[replacement[i + 1]])
            converted += 1
            i += 2
        else:
            out.append(c)
            i += 1
    if not converted:
        return replacement, []
    diagnostics = [_finding(
        "info", "unescaped_replacement",
        f"converted {converted} literal escape sequence(s) (\\n, \\t, \\\", \\/ ...) in replace_string to real characters "
        "(JSON over-escaping repair)",
        field="replace_string",
    )]
    return "".join(out), diagnostics
