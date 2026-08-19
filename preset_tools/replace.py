"""
Replace module — validated search & replace across a preset's text surfaces.

The only text this module ever touches:

  block_content     content of non-category blocks
  block_title       name of non-category blocks
  category_content  content of category-marker blocks
  category_title    name of category-marker blocks

Prompt variable definitions, stored values, regex scripts, and every other
preset field are ignored.

Two modes:

  regex    Python ``re`` substitution.  JavaScript-style replacement
           references (``$1``, ``$<name>``, ``${name}``) are translated to
           Python ``\\g<...>`` form; Python-native ``\\1`` / ``\\g<name>``
           works too.
  literal  plain find/replace; the pattern is matched verbatim and the
           replacement is inserted verbatim (no group interpretation).

Every replacement — dry run or not — first passes a validation gate
(``check_replace``) that compiles the pattern, rejects patterns that can
match the empty string, verifies group references, and, using the actual
target text as samples, rejects matches that swallow most of a field
(over-broad capture: the classic failure when anchors or quantifiers are
wrong).  Rejected replacements raise ``ReplaceRejected`` before any
mutation happens.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Union

from .io import preset_blocks
from .regex_lint import strip_regex_literal
from .search import _snippet, block_categories, list_categories

REPLACE_SURFACES = ("block_content", "block_title", "category_content", "category_title")
REPLACE_MODES = ("regex", "literal")

# A single match that swallows this much of a non-trivial field is treated as
# over-broad (regex mode only; a literal that large was pasted on purpose).
_BROAD_FRACTION = 0.6
_BROAD_MIN_TEXT = 40
# How many target texts feed the pre-flight gate.
_SAMPLE_TEXT_CAP = 400
# Hard cap on total matches across the whole preset.
MAX_TOTAL_MATCHES = 5000
# A replacement may expand its matches by at most this much before the run is
# rejected (regex mode only): the smaller of a flat char budget and half the
# matched text (so legitimate wrappers pass, $1$1-style duplication fails).
_MAX_GROWTH_CHARS = 2000

_JS_FLAG_MAP = {
    "i": "case-insensitive matching",
    "m": "multiline (^ and $ match per line)",
    "s": "dot-all (. matches newlines)",
}

_PY_HINTS = (
    ("look-behind requires fixed-width", (
        "Python's re only allows fixed-width lookbehind; JS variable-length "
        "lookbehind like (?<=\\w+) is not supported — use a capture group "
        "and a $1 reference instead"
    )),
    ("multiple repeat", "a quantifier is applied twice (e.g. a** or (a+){2,3}?); remove one"),
    ("nothing to repeat", "a quantifier (*, +, ?, {n,m}) has nothing to repeat — it is at the start of the pattern or group"),
    ("missing ), unterminated subpattern", "an opening '(' is never closed"),
    ("missing ], unterminated character class", "an opening '[' is never closed"),
    ("min-repeat greater than max-repeat", "a {n,m} quantifier has n greater than m (e.g. {3,2}) — reverse them"),
    ("invalid group name", "named group names must be alphanumeric/underscore and cannot be empty: (?P<name>...)"),
    ("unexpected end of pattern", "the pattern ends in the middle of a construct (often an unclosed '(' or '[' or a dangling '\\' escape)"),
)


def _finding(severity: str, code: str, message: str, field: str = "pattern", **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"severity": severity, "code": code, "message": message, "field": field}
    out.update(extra)
    return out


class ReplaceRejected(ValueError):
    """Raised when the validation gate blocks a replacement.

    ``.findings`` carries the structured diagnostics (severity/code/message
    dicts) so callers can report exactly what was wrong.
    """

    def __init__(self, findings: list[dict[str, Any]]):
        self.findings = findings
        errors = [f for f in findings if f.get("severity") == "error"]
        summary = "; ".join(f.get("message", str(f)) for f in errors[:3])
        if len(errors) > 3:
            summary += f"; (+{len(errors) - 3} more)"
        super().__init__(summary or "replacement rejected by validation")


# ---------------------------------------------------------------------------
# Pattern normalization (JS-flavored input -> Python re)
# ---------------------------------------------------------------------------

def _py_flags(case_sensitive: bool, multiline: bool, dot_all: bool) -> int:
    flags = 0
    if not case_sensitive:
        flags |= re.IGNORECASE
    if multiline:
        flags |= re.M
    if dot_all:
        flags |= re.S
    return flags


def _try_compile(pattern: str, flags: int) -> Optional[re.error]:
    try:
        re.compile(pattern, flags)
        return None
    except re.error as exc:
        return exc


def _syntax_error_finding(exc: re.error, pattern: str) -> dict[str, Any]:
    msg = str(exc) or "invalid pattern"
    pos = getattr(exc, "pos", None)
    hint: Optional[str] = None
    for needle, text in _PY_HINTS:
        if needle in msg:
            hint = text
            break
    if hint is None and "bad escape" in msg:
        hint = (
            "unknown escape sequence — Python re supports \\d \\D \\s \\S \\w \\W \\b \\B \\A \\Z "
            "but not \\p{...} unicode classes or \\h; use explicit classes like [a-zA-Z] or \\w"
        )
    out: dict[str, Any] = _finding("error", "syntax_error", f"pattern does not compile: {msg}", "pattern")
    if isinstance(pos, int) and 0 <= pos < len(pattern):
        excerpt = pattern[max(0, pos - 24):pos + 24]
        caret = " " * min(pos, 24) + "^"
        out["position"] = pos
        out["excerpt"] = f"{excerpt}\n{caret}"
    if hint:
        out["hint"] = hint
    return out


def _normalize_pattern(
    pattern: str,
    *,
    case_sensitive: bool,
    multiline: bool,
    dot_all: bool,
    repair: bool,
) -> tuple[str, int, list[dict[str, Any]]]:
    """Normalize an LLM-provided pattern for the Python re engine.

    Applies (and reports) the same escaping repairs as the Lumiverse regex
    script tools — surrounding whitespace, ``/.../flags`` literals, JSON
    over-escaped backslashes — plus the JS→Python named-group flip
    (``(?<name>`` → ``(?P<name>``).  Returns ``(pattern, flags, findings)``.
    """
    findings: list[dict[str, Any]] = []
    flags = _py_flags(case_sensitive, multiline, dot_all)
    p = pattern

    if not repair:
        return p, flags, findings

    if p != p.strip():
        p = p.strip()
        findings.append(_finding("info", "trimmed", "trimmed surrounding whitespace from the pattern"))

    p, js_flags, notes = strip_regex_literal(p, "")
    for note in notes:
        note = dict(note)
        note["field"] = "pattern"
        findings.append(note)
    for ch in js_flags:
        if ch == "i":
            if case_sensitive:
                findings.append(_finding(
                    "warning", "flag_conflict",
                    "literal /i flag requests case-insensitive matching but case_sensitive=true was set; "
                    "keeping case-sensitive matching",
                ))
            else:
                flags |= re.IGNORECASE
        elif ch == "m":
            flags |= re.M
            findings.append(_finding("info", "flag_applied", "applied m flag from the /.../ literal: multiline anchoring"))
        elif ch == "s":
            flags |= re.S
            findings.append(_finding("info", "flag_applied", "applied s flag from the /.../ literal: dot-all"))
        elif ch in _JS_FLAG_MAP:
            findings.append(_finding(
                "info", "flag_ignored",
                f"ignored '{ch}' flag from the /.../ literal ({_JS_FLAG_MAP[ch]} is not a Python re flag)",
            ))

    # JS named groups -> Python.  (?<= and (?<! are lookbehinds, not names.
    named = re.compile(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)")
    p, n_named = named.subn(r"(?P<\1", p)
    if n_named:
        findings.append(_finding(
            "info", "js_named_group",
            f"converted {n_named} JavaScript named group(s) '(?<name>' to Python '(?P<name>'",
        ))

    # JSON over-escaping: collapse doubled backslashes when doing so does not
    # introduce a syntax error (mirrors the regex script tool behavior).
    if "\\\\" in p:
        collapsed = p.replace("\\\\", "\\")
        if collapsed != p:
            err_before = _try_compile(p, flags)
            err_after = _try_compile(collapsed, flags)
            if err_after is not None and err_before is None:
                findings.append(_finding(
                    "warning", "doubled_backslashes",
                    "pattern contains doubled backslashes that look like literal backslash escapes; left as-is "
                    "because collapsing them would introduce syntax errors (resend single backslashes if JSON "
                    "over-escaping was intended)",
                ))
            else:
                findings.append(_finding(
                    "info", "collapsed_backslashes",
                    f"collapsed {p.count('\\\\')} doubled backslash(es) (JSON over-escaping repair)",
                ))
                p = collapsed

    return p, flags, findings


# ---------------------------------------------------------------------------
# Replacement templates
# ---------------------------------------------------------------------------

def translate_replacement(replacement: str) -> str:
    """Translate JS-style ``$N`` / ``$<name>`` / ``${name}`` / ``$$`` references
    in a replacement string to Python ``\\g<...>`` template form.

    Python-native ``\\1`` / ``\\g<name>`` references pass through untouched;
    a ``$`` not followed by a reference stays literal.
    """
    out: list[str] = []
    i, n = 0, len(replacement)
    while i < n:
        c = replacement[i]
        if c != "$" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        nxt = replacement[i + 1]
        if nxt == "$":
            out.append("$")
            i += 2
        elif nxt.isdigit():
            j = i + 1
            while j < n and replacement[j].isdigit():
                j += 1
            out.append(f"\\g<{replacement[i + 1:j]}>")
            i = j
        elif nxt in ("<", "{"):
            close = ">" if nxt == "<" else "}"
            j = replacement.find(close, i + 2)
            if j == -1:
                out.append(c)
                i += 1
            else:
                name = replacement[i + 2:j]
                if name:
                    out.append(f"\\g<{name}>")
                else:
                    out.append(c)
                    out.append(nxt)
                i = j + 1 if name else i + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


_TEMPLATE_REF_RE = re.compile(r"\\g<([A-Za-z0-9_]+)>|\\(\d+)")


def _check_template_refs(
    template: str,
    group_count: int,
    group_names: set[str],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for m in _TEMPLATE_REF_RE.finditer(template):
        name = m.group(1)
        if name is not None:
            if name.isdigit():
                if not (1 <= int(name) <= group_count):
                    findings.append(_finding(
                        "error", "invalid_group_reference",
                        f"replacement references group {name} but the pattern only defines {group_count} group(s)",
                        "replacement",
                    ))
            elif name not in group_names:
                known = f"; named groups: {', '.join(sorted(group_names))}" if group_names else ""
                findings.append(_finding(
                    "error", "invalid_group_reference",
                    f"replacement references group '{name}' which the pattern does not define{known}",
                    "replacement",
                ))
        else:
            num = int(m.group(2))
            if not (1 <= num <= group_count):
                findings.append(_finding(
                    "error", "invalid_group_reference",
                    f"replacement references group \\{num} but the pattern only defines {group_count} group(s)",
                    "replacement",
                ))
    return findings


_NESTED_QUANT_RE = re.compile(r"[\(\[]([^()\[\]]*(?:\*|\+|\{\d+,\})[^()\[\]]*)[\)\]](?:\*|\+|\{\d+,\})")


def _nested_quantifier_findings(pattern: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in _NESTED_QUANT_RE.finditer(pattern):
        out.append(_finding(
            "warning", "nested_quantifier",
            f"nested quantifier near '{m.group(0)}' risks catastrophic backtracking and usually captures "
            "more than intended; flatten it (e.g. drop the outer quantifier or make the inner match specific)",
        ))
    return out


# ---------------------------------------------------------------------------
# Validation gate
# ---------------------------------------------------------------------------

SampleEntry = Union[str, dict[str, Any]]


def _coerce_samples(samples: Optional[list[SampleEntry]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for i, s in enumerate(samples or []):
        if isinstance(s, dict):
            out.append((str(s.get("label") or f"sample {i + 1}"), str(s.get("text") or "")))
        else:
            out.append((f"sample {i + 1}", str(s)))
    return out


def check_replace(
    pattern: str,
    replacement: str,
    *,
    mode: str = "regex",
    case_sensitive: bool = False,
    multiline: bool = False,
    dot_all: bool = False,
    samples: Optional[list[SampleEntry]] = None,
    allow_broad: bool = False,
    repair: bool = True,
) -> dict[str, Any]:
    """Validate a pattern/replacement pair without touching any preset.

    Returns a dict with ``ok`` (no error-severity findings), the normalized
    ``pattern``, the compiled-flag summary, the ``replacement_template``
    (regex mode), ``group_count`` / ``group_names``, and the full
    ``findings`` list.  When ``samples`` are provided, the pattern is run
    against them and over-broad matches (a single match swallowing
    ``_BROAD_FRACTION`` of a non-trivial sample) are reported as errors
    unless ``allow_broad`` is set.
    """
    findings: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "mode": mode,
        "case_sensitive": case_sensitive,
        "multiline": multiline,
        "dot_all": dot_all,
        "flags": {"case_sensitive": case_sensitive, "multiline": multiline, "dot_all": dot_all},
    }

    if mode not in REPLACE_MODES:
        findings.append(_finding(
            "error", "unknown_mode",
            f"unknown mode '{mode}'; expected one of {list(REPLACE_MODES)}",
        ))
        result.update({"ok": False, "findings": findings})
        return result

    if not pattern:
        findings.append(_finding("error", "empty_pattern", "the pattern is empty"))

    normalized = pattern
    compiled: Optional[re.Pattern] = None
    if pattern and mode == "regex":
        normalized, flags, notes = _normalize_pattern(
            pattern,
            case_sensitive=case_sensitive,
            multiline=multiline,
            dot_all=dot_all,
            repair=repair,
        )
        findings += notes
        result["pattern"] = normalized
        if normalized:
            try:
                compiled = re.compile(normalized, flags)
            except re.error as exc:
                findings.append(_syntax_error_finding(exc, normalized))
    else:
        result["pattern"] = pattern
        if pattern and mode == "literal":
            compiled = re.compile(re.escape(pattern), _py_flags(case_sensitive, False, False))

    group_count = 0
    group_names: set[str] = set()
    if compiled is not None:
        group_count = compiled.groups
        group_names = set(compiled.groupindex)
        result["group_count"] = group_count
        if group_names:
            result["group_names"] = sorted(group_names)

    template: Optional[str] = None
    if mode == "regex" and not any(f["severity"] == "error" and f["code"] == "syntax_error" for f in findings):
        template = translate_replacement(replacement)
        result["replacement_template"] = template
        findings += _check_template_refs(template, group_count, group_names)
        if compiled is not None:
            if compiled.search("") is not None:
                findings.append(_finding(
                    "error", "empty_match_possible",
                    "the pattern can match an empty string, so a replace would insert the replacement at "
                    "unintended positions; require at least one character (prefer + over *) or anchor around "
                    "literal text",
                ))
        findings += _nested_quantifier_findings(normalized)
    elif mode == "literal":
        if pattern == replacement:
            findings.append(_finding("warning", "no_op", "literal pattern and replacement are identical; nothing will change"))

    # --- sample scan -----------------------------------------------------
    sample_list = _coerce_samples(samples)
    if compiled is not None and sample_list:
        total = 0
        matched = 0
        zero_width: list[str] = []
        broad: list[dict[str, Any]] = []
        first_matches: list[dict[str, Any]] = []
        for label, text in sample_list:
            if not text:
                continue
            spans = list(compiled.finditer(text))
            if not spans:
                continue
            matched += 1
            total += len(spans)
            m0 = spans[0]
            first_matches.append({
                "label": label,
                "match_count": len(spans),
                "match": _snippet(text, m0.start(), m0.end(), 60),
            })
            if m0.end() == m0.start():
                zero_width.append(label)
            if mode == "regex" and len(text) >= _BROAD_MIN_TEXT:
                for m in spans:
                    frac = (m.end() - m.start()) / len(text)
                    if frac >= _BROAD_FRACTION:
                        broad.append({
                            "label": label,
                            "matched": m.end() - m.start(),
                            "length": len(text),
                            "fraction": round(frac, 2),
                            "excerpt": _snippet(text, m.start(), m.end(), 60),
                        })
                        break
        result["match_preview"] = first_matches[:5]
        result["matched_samples"] = matched
        result["total_matches"] = total
        if zero_width:
            findings.append(_finding(
                "error", "zero_width_match",
                f"the pattern matches an empty span in: {', '.join(zero_width[:3])}; a replace would only insert "
                "the replacement without consuming anything — make the pattern require literal text",
            ))
        if not allow_broad and broad:
            worst = max(b["fraction"] for b in broad)
            detail = "; ".join(
                f"{b['label']}: {b['matched']}/{b['length']} chars ({b['fraction']:.0%}), matched \"{b['excerpt']}\""
                for b in broad[:3]
            )
            findings.append(_finding(
                "error", "over_broad_match",
                f"a single match swallows up to {worst:.0%} of a whole field — {detail}. Tighten the pattern "
                "(required literals, tighter quantifiers, or anchors) or pass allow_broad_matches=true if the "
                "large capture is intentional. For rewriting an entire field, use preset_modify_block",
                "pattern", offenders=[{k: b[k] for k in ("label", "fraction")} for b in broad[:5]],
            ))
        elif allow_broad and broad:
            findings.append(_finding(
                "info", "broad_match_allowed",
                f"{len(broad)} field(s) have matches swallowing ≥{_BROAD_FRACTION:.0%} of their text; allowed via allow_broad",
                offenders=[{k: b[k] for k in ("label", "fraction")} for b in broad[:5]],
            ))
        if total > MAX_TOTAL_MATCHES:
            findings.append(_finding(
                "error", "match_limit_exceeded",
                f"the pattern matches {total} times in the sampled targets (cap {MAX_TOTAL_MATCHES}); narrow it "
                "or split the work per block",
            ))

        # Anchor / dotall hints when nothing matched at all.
        if matched == 0 and mode == "regex":
            if ("^" in normalized or "$" in normalized) and not (multiline or compiled.flags & re.M):
                alt = re.compile(normalized, (compiled.flags & ~re.M) | re.M)
                hits = sum(1 for _, text in sample_list if text and alt.search(text))
                if hits:
                    findings.append(_finding(
                        "warning", "multiline_hint",
                        f"no matches, but the pattern uses ^/$ anchors and matches in {hits} sample(s) with "
                        "multiline=true — without it, ^ and $ only anchor at the very start/end of each field",
                    ))
            if "." in normalized and not (dot_all or compiled.flags & re.S):
                alt = re.compile(normalized, (compiled.flags & ~re.S) | re.S)
                hits = sum(1 for _, text in sample_list if text and alt.search(text))
                if hits:
                    findings.append(_finding(
                        "warning", "dotall_hint",
                        f"no matches, but the pattern matches in {hits} sample(s) with dot_all=true — by default "
                        "'.' does not match newlines; use [\\s\\S] instead, or dot_all",
                    ))
            if not any(f["code"] in ("multiline_hint", "dotall_hint") for f in findings):
                findings.append(_finding(
                    "warning", "no_matches",
                    "the pattern matched none of the sampled targets; double-check spelling, whitespace, and flags",
                ))

    result["findings"] = findings
    result["ok"] = not any(f.get("severity") == "error" for f in findings)
    if compiled is not None:
        result["_compiled"] = compiled  # private: reuse so gate and apply cannot drift
    return result


# ---------------------------------------------------------------------------
# Replace engine
# ---------------------------------------------------------------------------

_SURFACE_BY_KIND = {
    True: ("category_title", "category_content"),   # category-marker blocks
    False: ("block_title", "block_content"),        # regular blocks
}
_FIELD_OF_SURFACE = {"block_content": "content", "block_title": "name",
                     "category_content": "content", "category_title": "name"}


def _targets(preset: dict, surfaces: list[str], category: Optional[str], enabled_only: bool) -> list[dict[str, Any]]:
    """Collect the replaceable (block, field) targets in preset order."""
    out: list[dict[str, Any]] = []
    blocks = preset_blocks(preset)
    cats = block_categories(preset)
    for i, b in enumerate(blocks):
        meta = cats[i]
        enabled = bool(b.get("enabled", True))
        if enabled_only and not enabled:
            continue
        if category is not None and meta["category"] != category:
            continue
        title_surface, content_surface = _SURFACE_BY_KIND[bool(meta["is_category"])]
        for surface in (title_surface, content_surface):
            if surface not in surfaces:
                continue
            field = _FIELD_OF_SURFACE[surface]
            text = b.get(field)
            if not isinstance(text, str) or not text:
                continue
            out.append({
                "block": b.get("name") or "",
                "index": i,
                "surface": surface,
                "field": field,
                "enabled": enabled,
                "category": meta["category"],
                "text": text,
            })
    return out


def _substitute(
    compiled: re.Pattern,
    text: str,
    template: Optional[str],
    literal_replacement: str,
    preview: int,
) -> tuple[str, int, list[dict[str, str]], int, int]:
    """Run one substitution, tracking exact before/after spans per match.

    ``template`` set means regex mode (``Match.expand``); otherwise the
    literal replacement is inserted verbatim.  Returns (new_text, count,
    previews, matched_chars, replacement_chars).
    """
    out: list[str] = []
    previews: list[dict[str, str]] = []
    pos = 0
    out_len = 0
    count = 0
    matched = 0
    produced = 0
    for m in compiled.finditer(text):
        gap = text[pos:m.start()]
        out.append(gap)
        out_len += len(gap)
        piece = literal_replacement if template is None else m.expand(template)
        out.append(piece)
        if len(previews) < preview:
            previews.append({
                "before": _snippet(text, m.start(), m.end(), 60),
                "after": _snippet("".join(out), out_len, out_len + len(piece), 60),
            })
        out_len += len(piece)
        matched += m.end() - m.start()
        produced += len(piece)
        pos = m.end()
        count += 1
    if count == 0:
        return text, 0, [], 0, 0
    out.append(text[pos:])
    return "".join(out), count, previews, matched, produced


def replace_in_preset(
    preset: dict,
    pattern: str,
    replacement: str,
    *,
    mode: str = "regex",
    surfaces: Optional[list[str]] = None,
    category: Optional[str] = None,
    enabled_only: bool = False,
    case_sensitive: bool = False,
    multiline: bool = False,
    dot_all: bool = False,
    allow_broad: bool = False,
    dry_run: bool = False,
    repair: bool = True,
    preview: int = 3,
) -> dict[str, Any]:
    """Search & replace across a preset's text surfaces, in place.

    Runs ``check_replace`` first with the actual target texts as samples; if
    any error-severity finding is produced, ``ReplaceRejected`` is raised and
    the preset is not modified.  On success every matching field is rewritten
    (unless ``dry_run``) and a report is returned:

        {mode, pattern, replacement, surfaces, dry_run, changed,
         counts: {surface: changed fields}, total_matches,
         changes: [{block, index, surface, field, match_count,
                    previews: [{before, after}]}],
         findings: [non-blocking warnings/info]}

    ``surfaces`` defaults to all four (``block_content``, ``block_title``,
    ``category_content``, ``category_title``).  Title results are validated:
    a rename that empties a title or collides with another block name is
    rejected.
    """
    if surfaces is None:
        surfaces = list(REPLACE_SURFACES)
    surfaces = list(dict.fromkeys(surfaces))
    unknown = [s for s in surfaces if s not in REPLACE_SURFACES]
    if unknown:
        raise ValueError(f"unknown surfaces: {unknown}; expected subset of {list(REPLACE_SURFACES)}")

    if category is not None:
        available = list_categories(preset)
        if category not in available:
            raise ValueError(f"category '{category}' not found; available categories: {available}")

    targets = _targets(preset, surfaces, category, enabled_only)

    samples = [
        {"label": f"'{t['block']}' {t['field']}", "text": t["text"]}
        for t in targets[:_SAMPLE_TEXT_CAP]
    ]
    gate = check_replace(
        pattern,
        replacement,
        mode=mode,
        case_sensitive=case_sensitive,
        multiline=multiline,
        dot_all=dot_all,
        samples=samples,
        allow_broad=allow_broad,
        repair=repair,
    )
    errors = [f for f in gate["findings"] if f.get("severity") == "error"]
    if errors:
        raise ReplaceRejected(gate["findings"])

    compiled = gate.pop("_compiled")
    template = gate.get("replacement_template") if mode == "regex" else None
    literal_replacement = replacement

    # Pass 1: build every rewritten field in memory; validate titles + growth.
    blocks = preset_blocks(preset)
    changes: list[dict[str, Any]] = []
    counts: dict[str, int] = {s: 0 for s in REPLACE_SURFACES}
    total_matches = 0
    matched_chars = 0
    replacement_chars = 0
    new_names: dict[int, str] = {}
    for t in targets:
        text = t["text"]
        new_text, n, previews, matched, produced = _substitute(
            compiled, text, template, literal_replacement, preview
        )
        total_matches += n
        matched_chars += matched
        replacement_chars += produced
        if n == 0:
            continue
        counts[t["surface"]] += 1
        changes.append({
            "block": t["block"],
            "index": t["index"],
            "surface": t["surface"],
            "field": t["field"],
            "category": t["category"],
            "enabled": t["enabled"],
            "match_count": n,
            "previews": previews,
        })
        t["new_text"] = new_text
        if t["field"] == "name":
            new_names[t["index"]] = new_text
            if not new_text.strip():
                raise ReplaceRejected([_finding(
                    "error", "empty_title_result",
                    f"the pattern would erase the name of block '{t['block']}' entirely; block names cannot be empty",
                )])

    if total_matches > MAX_TOTAL_MATCHES:
        raise ReplaceRejected([_finding(
            "error", "match_limit_exceeded",
            f"the pattern matches {total_matches} times across the preset (cap {MAX_TOTAL_MATCHES}); narrow it or "
            "split the work per block",
        )])

    if (
        mode == "regex"
        and matched_chars
        and (replacement_chars - matched_chars) > max(_MAX_GROWTH_CHARS, matched_chars // 2)
    ):
        raise ReplaceRejected([_finding(
            "error", "explosive_growth",
            f"the replacement expands {matched_chars} chars of matches into {replacement_chars} chars "
            f"({replacement_chars / matched_chars:.1f}x); check for runaway group references (e.g. $1$1) "
            "or a replacement that duplicates whole matches",
        )])

    if new_names:
        final_names = [
            new_names.get(i, (b.get("name") or ""))
            for i, b in enumerate(blocks)
        ]
        seen: dict[str, str] = {}
        for idx, name in new_names.items():
            if final_names.count(name) > 1:
                seen.setdefault(name, blocks[idx].get("name") or "")
        if seen:
            raise ReplaceRejected([_finding(
                "error", "duplicate_title_result",
                "the replacement would create duplicate block names: "
                + ", ".join(f"'{old}' -> '{new}'" for new, old in seen.items())
                + "; block names must stay unique (use preset_rename_block semantics)",
            )])

    # Pass 2: apply the already-built texts.
    if not dry_run:
        for t in targets:
            new_text = t.get("new_text")
            if new_text is not None and new_text != t["text"]:
                blocks[t["index"]][t["field"]] = new_text

    return {
        "mode": mode,
        "pattern": gate["pattern"],
        "replacement": replacement,
        "surfaces": surfaces,
        "category": category,
        "enabled_only": enabled_only,
        "case_sensitive": case_sensitive,
        "dry_run": dry_run,
        "changed": bool(changes),
        "changed_fields": len(changes),
        "total_matches": total_matches,
        "counts": {s: c for s, c in counts.items() if c},
        "changes": changes,
        "findings": [f for f in gate["findings"] if f.get("severity") != "error"],
    }
