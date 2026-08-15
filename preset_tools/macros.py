"""
macros.py — a faithful Python port of the Lumiverse macro lexer/parser, plus
the authoritative macro registry.

This mirrors the grammar implemented in the backend at:
    src/macros/MacroLexer.ts
    src/macros/MacroParser.ts
    src/macros/definitions/*.ts

The goal is *structural fidelity*: parse a template string the same way the
engine does so the validator (validate.py) can reason about macro structure,
nesting, scoped open/close pairing, and variable reads/writes.

We do NOT evaluate macros (no rendering, no side effects) — we only build the
AST and classify nodes.

Public API:
    parse_template(s) -> list[Node]      faithful AST (Text / Macro / Scoped)
    walk(nodes)       -> iterator         pre-order walk over every node
    static_arg_text(arg_nodes) -> str|None   literal text of an arg, or None if dynamic
    KNOWN_MACROS      -> frozenset[str]   every recognised macro name + alias (lowercased)
    VAR_OPS           -> dict[str, VarOp] variable-macro classification (scope + role)
    SCOPED_HINT       -> frozenset[str]   macros that are usually used as open/close pairs
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional


# ---------------------------------------------------------------------------
# AST node types
# ---------------------------------------------------------------------------

@dataclass
class Text:
    """A run of literal text between macros."""
    value: str
    offset: int = -1


@dataclass
class Macro:
    """A `{{name::arg::arg}}` macro invocation (before scoped pairing)."""
    name: str                       # canonical-ish name (shorthand already translated)
    args: list[list["Node"]] = field(default_factory=list)
    flags: str = ""                 # subset of "!?~>/#"
    offset: int = -1                # start offset of `{{` within the field text
    raw: str = ""                   # best-effort original source slice
    is_close: bool = False          # had the `/` close flag
    terminated: bool = True         # found a real `}}`
    from_shorthand: bool = False    # produced by .x / $x / @x translation
    var_scope: Optional[str] = None  # 'local' | 'global' | 'chat' for shorthand
    operator: Optional[str] = None   # shorthand operator, e.g. '=', '+=', '++'


@dataclass
class Scoped:
    """A paired `{{name}}...{{/name}}` block produced by the pairing pass."""
    name: str
    args: list[list["Node"]] = field(default_factory=list)
    body: list["Node"] = field(default_factory=list)
    flags: str = ""
    offset: int = -1
    raw: str = ""


Node = object  # Text | Macro | Scoped (kept loose to avoid heavy Union noise)


# ---------------------------------------------------------------------------
# Lexer / parser (faithful to MacroLexer.ts + MacroParser.ts)
# ---------------------------------------------------------------------------

# Sentinels for escaped braces, matching ESCAPED_OPEN / ESCAPED_CLOSE.
ESCAPED_OPEN = "\x01"
ESCAPED_CLOSE = "\x02"

_FLAG_CHARS = set("!?~>/#")
_IDENT_RE = re.compile(r"[a-zA-Z0-9_\-]")
_VARNAME_RE = re.compile(r"[\w\-]")
_LEGACY_RE = re.compile(r"<(user|char|bot)>", re.IGNORECASE)

# Two-char operators recognised in variable shorthand (MacroLexer.lexOperator).
_TWO_CHAR_OPS = {"++", "--", "+=", "-=", "||", "??", "==", "!=", ">=", "<="}
# Operators whose right-hand value is scanned as an argument.
_OPS_WITH_VALUE = {"+=", "-=", "==", "!=", ">=", "<=", "||", "??", "=", ">", "<"}


class _Scanner:
    """Single-pass recursive scanner. Combines lex + parse for our purposes."""

    def __init__(self, src: str):
        self.s = src
        self.n = len(src)
        self.pos = 0

    # -- low-level helpers --------------------------------------------------

    def _at(self, i: int) -> str:
        return self.s[i] if 0 <= i < self.n else ""

    def _is_open(self, i: int) -> bool:
        return self._at(i) == "{" and self._at(i + 1) == "{"

    def _is_close(self, i: int) -> bool:
        return self._at(i) == "}" and self._at(i + 1) == "}"

    def _is_escape(self, i: int) -> bool:
        return self._at(i) == "\\" and self._at(i + 1) in ("{", "}")

    def _skip_ws(self) -> None:
        while self.pos < self.n and self.s[self.pos] in (" ", "\t"):
            self.pos += 1

    # -- top level ----------------------------------------------------------

    def parse(self) -> list[Node]:
        return self._parse_until_close(top_level=True)

    def _parse_until_close(self, top_level: bool) -> list[Node]:
        """Parse text + macros. At top level there is no closing brace."""
        nodes: list[Node] = []
        text_start = self.pos
        while self.pos < self.n:
            if self._is_escape(self.pos):
                self._flush_text(nodes, text_start, self.pos)
                ch = self.s[self.pos + 1]
                nodes.append(Text(ESCAPED_OPEN if ch == "{" else ESCAPED_CLOSE,
                                  offset=self.pos))
                self.pos += 2
                text_start = self.pos
                continue
            if self._is_open(self.pos):
                self._flush_text(nodes, text_start, self.pos)
                nodes.append(self._parse_macro())
                text_start = self.pos
                continue
            self.pos += 1
        self._flush_text(nodes, text_start, self.pos)
        return nodes

    def _flush_text(self, nodes: list[Node], start: int, end: int) -> None:
        if end <= start:
            return
        self._push_text(nodes, self.s[start:end], start)

    def _push_text(self, nodes: list[Node], value: str, offset: int) -> None:
        """Push text, splitting legacy <user>/<char>/<bot> into macro nodes."""
        if "<" not in value:
            nodes.append(Text(value, offset=offset))
            return
        last = 0
        for m in _LEGACY_RE.finditer(value):
            if m.start() > last:
                nodes.append(Text(value[last:m.start()], offset=offset + last))
            name = m.group(1).lower()
            if name == "bot":
                name = "char"
            nodes.append(Macro(name=name, raw=m.group(0), offset=offset + m.start()))
            last = m.end()
        if last < len(value):
            nodes.append(Text(value[last:], offset=offset + last))

    # -- macro --------------------------------------------------------------

    def _parse_macro(self) -> Macro:
        start = self.pos
        self.pos += 2  # consume {{
        self._skip_ws()

        # Comment shorthand: {{// ...}}. Checked before flag-scanning: the
        # engine technically lexes the `/`s as close flags and then drops the
        # node as an orphan close (so it renders empty), but treating it as a
        # comment here yields the same empty result without a spurious
        # "orphaned close tag" warning. Real presets use {{// ...}} liberally.
        if self._at(self.pos) == "/" and self._at(self.pos + 1) == "/":
            return self._parse_comment(start, "")

        flags = ""
        while self.pos < self.n and self.s[self.pos] in _FLAG_CHARS:
            flags += self.s[self.pos]
            self.pos += 1
        self._skip_ws()

        # Variable shorthand: .name $name @name
        if self.pos < self.n and self.s[self.pos] in (".", "$", "@"):
            return self._parse_shorthand(start, flags)

        # Identifier
        id_start = self.pos
        while self.pos < self.n and _IDENT_RE.match(self.s[self.pos]):
            self.pos += 1
        name = self.s[id_start:self.pos]
        self._skip_ws()

        args: list[list[Node]] = []

        # Space-delimited args (only if next char isn't a separator/close).
        if self.pos < self.n and self.s[self.pos] not in (":",) and not self._is_close(self.pos):
            if self.s[self.pos] not in ("}",):
                self._parse_space_args(args)

        # `::` / `:` separated args.
        while self.pos < self.n:
            if self._is_close(self.pos):
                break
            if self.s[self.pos] == ":" and self._at(self.pos + 1) == ":":
                self.pos += 2
                args.append(self._parse_arg())
            elif self.s[self.pos] == ":":
                self.pos += 1
                args.append(self._parse_arg())
            else:
                # Unexpected char — consume defensively (mirrors lexer).
                self.pos += 1

        terminated = self._is_close(self.pos)
        if terminated:
            self.pos += 2
        raw = self.s[start:self.pos]

        return Macro(
            name=name,
            args=args,
            flags=flags,
            offset=start,
            raw=raw,
            is_close="/" in flags,
            terminated=terminated,
        )

    def _parse_comment(self, start: int, flags: str) -> Macro:
        self.pos += 2  # consume //
        close_idx = self.s.find("}}", self.pos)
        if close_idx >= 0:
            comment = self.s[self.pos:close_idx]
            self.pos = close_idx + 2
            terminated = True
        else:
            comment = self.s[self.pos:]
            self.pos = self.n
            terminated = False
        return Macro(
            name="//",
            args=[[Text(comment.strip())]] if comment.strip() else [],
            flags=flags,
            offset=start,
            raw=self.s[start:self.pos],
            terminated=terminated,
        )

    def _parse_shorthand(self, start: int, flags: str) -> Macro:
        scope_ch = self.s[self.pos]
        scope = {"$": "global", "@": "chat", ".": "local"}[scope_ch]
        self.pos += 1

        name_start = self.pos
        while self.pos < self.n and _VARNAME_RE.match(self.s[self.pos]):
            # stop before -- or -= operator sequences
            if self.s[self.pos] == "-" and self._at(self.pos + 1) in ("-", "="):
                break
            self.pos += 1
        varname = self.s[name_start:self.pos]
        self._skip_ws()

        operator = ""
        operand: list[Node] = []
        if self.pos < self.n:
            operator = self._read_operator(operand)

        terminated = self._is_close(self.pos)
        if terminated:
            self.pos += 2
        raw = self.s[start:self.pos]

        macro_name = _translate_shorthand(scope, operator)
        args: list[list[Node]] = [[Text(varname)]]
        if operand:
            # `-=` subtracts: negate the operand so addvar adds a negative.
            if operator == "-=":
                _negate_operand(operand)
            args.append(operand)

        return Macro(
            name=macro_name,
            args=args,
            flags=flags,
            offset=start,
            raw=raw,
            terminated=terminated,
            from_shorthand=True,
            var_scope=scope,
            operator=operator or None,
        )

    def _read_operator(self, operand: list[Node]) -> str:
        two = self.s[self.pos:self.pos + 2]
        if two in _TWO_CHAR_OPS:
            self.pos += 2
            if two in _OPS_WITH_VALUE:
                self._skip_ws()
                self._read_operand_into(operand)
            return two
        one = self.s[self.pos]
        if one in ("=", ">", "<"):
            self.pos += 1
            self._skip_ws()
            self._read_operand_into(operand)
            return one
        return ""

    def _read_operand_into(self, operand: list[Node]) -> None:
        """Read an operand value (may contain nested macros) until `}}`."""
        text_start = self.pos
        while self.pos < self.n and not self._is_close(self.pos):
            if self._is_escape(self.pos):
                self._flush_text(operand, text_start, self.pos)
                ch = self.s[self.pos + 1]
                operand.append(Text(ESCAPED_OPEN if ch == "{" else ESCAPED_CLOSE))
                self.pos += 2
                text_start = self.pos
                continue
            if self._is_open(self.pos):
                self._flush_text(operand, text_start, self.pos)
                operand.append(self._parse_macro())
                text_start = self.pos
                continue
            self.pos += 1
        self._flush_text(operand, text_start, self.pos)
        # Trim trailing whitespace on the final text node.
        if operand and isinstance(operand[-1], Text):
            operand[-1].value = operand[-1].value.rstrip()
            if operand[-1].value == "":
                operand.pop()

    def _parse_arg(self) -> list[Node]:
        """Parse one argument; stops at top-level `::` or `}}`."""
        nodes: list[Node] = []
        text_start = self.pos
        while self.pos < self.n:
            if self._is_escape(self.pos):
                self._flush_text(nodes, text_start, self.pos)
                ch = self.s[self.pos + 1]
                nodes.append(Text(ESCAPED_OPEN if ch == "{" else ESCAPED_CLOSE))
                self.pos += 2
                text_start = self.pos
                continue
            if self._is_open(self.pos):
                self._flush_text(nodes, text_start, self.pos)
                nodes.append(self._parse_macro())
                text_start = self.pos
                continue
            if self._is_close(self.pos):
                break
            if self.s[self.pos] == ":" and self._at(self.pos + 1) == ":":
                break
            self.pos += 1
        self._flush_text(nodes, text_start, self.pos)
        return nodes

    def _parse_space_args(self, args: list[list[Node]]) -> None:
        """Parse space-delimited arguments (legacy compat)."""
        while self.pos < self.n:
            self._skip_ws()
            if self.pos >= self.n:
                break
            if self.s[self.pos] == ":":
                break
            if self._is_close(self.pos):
                break
            # Variable shorthand as a space arg: .x $x @x (followed by a letter)
            ch = self.s[self.pos]
            if ch in (".", "$", "@") and self._at(self.pos + 1) and self._at(self.pos + 1).isalpha():
                sh_start = self.pos
                scope = {"$": "global", "@": "chat", ".": "local"}[ch]
                self.pos += 1
                nm_start = self.pos
                while self.pos < self.n and _VARNAME_RE.match(self.s[self.pos]):
                    self.pos += 1
                varname = self.s[nm_start:self.pos]
                args.append([Macro(
                    name=_translate_shorthand(scope, ""),
                    args=[[Text(varname)]],
                    offset=sh_start,
                    raw=self.s[sh_start:self.pos],
                    from_shorthand=True,
                    var_scope=scope,
                )])
                continue
            # Regular word arg.
            args.append(self._parse_space_word())

    def _parse_space_word(self) -> list[Node]:
        nodes: list[Node] = []
        text_start = self.pos
        while self.pos < self.n:
            if self._is_escape(self.pos):
                self._flush_text(nodes, text_start, self.pos)
                ch = self.s[self.pos + 1]
                nodes.append(Text(ESCAPED_OPEN if ch == "{" else ESCAPED_CLOSE))
                self.pos += 2
                text_start = self.pos
                continue
            if self._is_open(self.pos):
                self._flush_text(nodes, text_start, self.pos)
                nodes.append(self._parse_macro())
                text_start = self.pos
                continue
            if self._is_close(self.pos):
                break
            if self.s[self.pos] == ":" and self._at(self.pos + 1) == ":":
                break
            if self.s[self.pos] in (" ", "\t"):
                break
            self.pos += 1
        self._flush_text(nodes, text_start, self.pos)
        return nodes


def _translate_shorthand(scope: str, operator: str) -> str:
    """Mirror MacroParser.translateVarShorthand."""
    if scope == "chat":
        return {
            "": "getchatvar", "++": "incchatvar", "--": "decchatvar",
            "=": "setchatvar", "+=": "addchatvar", "-=": "addchatvar",
            "||": "getchatvar", "??": "getchatvar",
        }.get(operator, "getchatvar")
    is_global = scope == "global"
    if not operator:
        return "getgvar" if is_global else "getvar"
    return {
        "++": "incgvar" if is_global else "incvar",
        "--": "decgvar" if is_global else "decvar",
        "=": "setgvar" if is_global else "setvar",
        "+=": "addgvar" if is_global else "addvar",
        "-=": "addgvar" if is_global else "addvar",
        "||": "getgvar" if is_global else "getvar",
        "??": "getgvar" if is_global else "getvar",
    }.get(operator, "getgvar" if is_global else "getvar")


def _negate_operand(operand: list[Node]) -> None:
    first = operand[0]
    if isinstance(first, Text):
        first.value = first.value[1:] if first.value.startswith("-") else "-" + first.value
    else:
        operand.insert(0, Text("-"))


def _pair_scoped(nodes: list[Node]) -> list[Node]:
    """Pair {{name}}...{{/name}} into Scoped nodes (mirrors pairScopedMacros)."""
    result: list[Node] = []
    i = 0
    while i < len(nodes):
        node = nodes[i]
        if isinstance(node, Macro) and not node.is_close:
            close_idx = _find_close(nodes, i + 1, node.name)
            if close_idx >= 0:
                body = _pair_scoped(nodes[i + 1:close_idx])
                result.append(Scoped(
                    name=node.name, args=node.args, body=body,
                    flags=node.flags, offset=node.offset, raw=node.raw,
                ))
                i = close_idx + 1
                continue
        if isinstance(node, Macro) and node.is_close:
            # Orphaned close tag — engine silently drops it. Keep it so the
            # validator can warn; mark via is_close.
            result.append(node)
            i += 1
            continue
        result.append(node)
        i += 1
    return result


def _find_close(nodes: list[Node], start: int, name: str) -> int:
    depth = 0
    lower = name.lower()
    for i in range(start, len(nodes)):
        node = nodes[i]
        if isinstance(node, Macro) and node.name.lower() == lower:
            if node.is_close:
                if depth == 0:
                    return i
                depth -= 1
            else:
                depth += 1
    return -1


def parse_template(src: str) -> list[Node]:
    """Parse a macro template string into a paired AST."""
    if not src:
        return []
    flat = _Scanner(src).parse()
    return _pair_scoped(flat)


def walk(nodes: list[Node]) -> Iterator[Node]:
    """Pre-order walk over a node list, descending into args and scoped bodies."""
    for node in nodes:
        yield node
        if isinstance(node, Macro):
            for arg in node.args:
                yield from walk(arg)
        elif isinstance(node, Scoped):
            for arg in node.args:
                yield from walk(arg)
            yield from walk(node.body)


def static_arg_text(arg_nodes: list[Node]) -> Optional[str]:
    """Return the literal text of an argument if it has no nested macros.

    Returns None when the argument contains macros (i.e. it is computed at
    runtime and cannot be statically known — e.g. a dynamic variable name).
    """
    parts: list[str] = []
    for n in arg_nodes:
        if isinstance(n, Text):
            v = n.value.replace(ESCAPED_OPEN, "{").replace(ESCAPED_CLOSE, "}")
            parts.append(v)
        else:
            return None
    return "".join(parts)


# ---------------------------------------------------------------------------
# Variable-macro classification (scope + role)
# ---------------------------------------------------------------------------

# Roles:
#   read   — reads a value; an unset var yields "" (read-before-set is a smell)
#   write  — definitively sets a value
#   rw     — reads-then-writes, initialising from 0 if unset (add/inc/dec)
#   exists — existence check; reading an unset var is intentional (no warning)
#   delete — unsets a variable
#   read_safe — read that always has a fallback (varDefault) — never warns
@dataclass(frozen=True)
class VarOp:
    scope: str   # 'local' | 'global' | 'chat'
    role: str    # 'read' | 'write' | 'rw' | 'exists' | 'delete' | 'read_safe'


def _build_var_ops() -> dict[str, VarOp]:
    ops: dict[str, VarOp] = {}

    def add(scope: str, role: str, *names: str) -> None:
        for nm in names:
            ops[nm.lower()] = VarOp(scope, role)

    # Local scope ({{.x}})
    add("local", "read", "getvar", "var", "promptVar", "presetVar")
    add("local", "read_safe", "varDefault", "promptVarDefault", "presetVarDefault")
    add("local", "write", "setvar")
    add("local", "rw", "addvar", "incvar", "decvar")
    add("local", "exists", "hasvar", "varexists", "hasVar", "hasPromptVar", "hasPresetVar")
    add("local", "delete", "deletevar", "flushvar")

    # Global scope ({{$x}})
    add("global", "read", "getgvar", "getglobalvar")
    add("global", "write", "setgvar", "setglobalvar")
    add("global", "rw", "addgvar", "addglobalvar", "incgvar", "incglobalvar",
        "decgvar", "decglobalvar")
    add("global", "exists", "hasgvar", "hasglobalvar", "gvarexists")
    add("global", "delete", "deletegvar", "flushgvar", "flushglobalvar", "deleteglobalvar")

    # Chat scope ({{@x}})
    add("chat", "read", "getchatvar")
    add("chat", "write", "setchatvar")
    add("chat", "rw", "addchatvar", "incchatvar", "decchatvar")
    add("chat", "exists", "haschatvar")
    add("chat", "delete", "deletechatvar", "flushchatvar")

    return ops


VAR_OPS: dict[str, VarOp] = _build_var_ops()


# ---------------------------------------------------------------------------
# Registry of recognised macro names (canonical names + every alias).
# Derived from src/macros/definitions/*.ts. Unknown macros are NOT errors in
# the engine (they pass through as literal text), so this set drives *info*
# notes about likely typos, not hard failures.
# ---------------------------------------------------------------------------

_CANONICAL = [
    # core / primitives
    "space", "newline", "noop", "trim", "comment", "//", "input", "reverse",
    "outlet", "wi_marker", "banned", "if", "else",
    # variables (local/global/chat)
    "getvar", "setvar", "addvar", "incvar", "decvar", "hasvar", "deletevar",
    "getgvar", "setgvar", "addgvar", "incgvar", "decgvar", "hasgvar", "deletegvar",
    "getchatvar", "setchatvar", "addchatvar", "incchatvar", "decchatvar",
    "haschatvar", "deletechatvar",
    # prompt variables
    "var", "varDefault", "hasVar",
    # identity / names
    "user", "char", "group", "groupNotMuted", "notChar", "charGroupFocused",
    "isGroupChat", "isNarrator", "groupOthers", "groupMemberCount",
    "groupLastSpeaker", "groupCardMode",
    "charGroupFocusedDescription", "charGroupFocusedPersonality",
    # multiplayer
    "isMultiplayer", "playerCount", "players", "hostName", "currentPlayer",
    # persona card
    "description", "personality", "scenario", "persona", "mesExamples",
    "mesExamplesRaw", "charPostHistoryInstructions", "charDepthPrompt",
    "charCreatorNotes", "charVersion", "charCreator", "firstMessage",
    "charTag", "charTags", "characterColors", "userColorMode",
    "sub", "obj", "poss",
    # conversation
    "lastMessage", "lastMessageName", "lastUserMessage", "lastCharMessage",
    "messageCount", "chatId", "messageAt", "messagesBy", "lastMessageId",
    "firstIncludedMessageId", "firstDisplayedMessageId", "lastSwipeId",
    "currentSwipeId", "chatAge",
    # temporal
    "time", "date", "weekday", "isotime", "isodate", "datetimeformat",
    "idleDuration", "timeDiff",
    # entropy
    "random", "pick", "roll",
    # logic
    "switch", "default", "and", "or", "not", "eq", "ne", "gt", "gte", "lt", "lte",
    # strings
    "len", "upper", "lower", "capitalize", "replace", "substr", "split", "join",
    "find", "count", "index", "truncate", "wrap", "format", "regex",
    # math
    "calc", "min", "max", "clamp", "abs", "floor", "ceil", "round", "decimals",
    "mod", "arc",
    # formatting
    "bullets", "numbered", "repeat", "delimiter",
    # memory / cortex / databank
    "memories", "memoriesActive", "memoriesCount", "memoriesRaw", "memorySalience",
    "cortexActive", "entities", "entityCount", "entityFacts", "relationships",
    "databank", "databankActive", "databankCount", "databankRaw",
    # loom
    "loomStyle", "loomUtils", "loomSovHand", "loomSovHandActive",
    "loomContinuePrompt", "loomCouncilResult", "loomLastCharMessage",
    "loomLastMessageName", "loomLastUserMessage", "loomRetrofits", "loomSummary",
    "loomSummaryPrompt",
    # lumia
    "lumiaDef", "lumiaPersonality", "lumiaQuirks", "lumiaSelf",
    "lumiaStateSynthesis", "lumiaMessageCount", "lumiaOOC", "lumiaOOCErotic",
    "lumiaOOCEroticBleed", "lumiaOOCTrigger", "lumiaBehavior",
    "lumiaCouncilModeActive", "lumiaCouncilToolsActive", "lumiaCouncilToolsList",
    "lumiaCouncilDeliberation", "lumiaCouncilInst", "randomLumia",
    # cot
    "reasoningPrefix", "reasoningSuffix",
    # runtime / system
    "model", "maxPrompt", "maxContext", "maxResponse", "lastGenerationType",
    "isMobile", "tokenCount",
    # regex-ref / extensions / chat-utils
    "regexInstalled", "hasExtension", "counter", "rcounter", "toggle",
    "system", "obj", "original",
    # app / extension macros (Spindle-provided but conventionally known)
    "spotify_is_playing", "spotify_track_name", "spotify_artists",
    "spotify_album_name", "spotify_has_lyrics", "spotify_lyrics",
    "spotify_album_art",
    "sim_tracker",
    "wi_marker",
]

# Every alias declared across the definition files (alias -> canonical name is
# not needed here; we only need the set membership for "unknown macro" checks).
_ALIASES = [
    "charDescription", "last_message", "substring", "group_member_count",
    "varexists", "charInstruction", "jailbreak", "charJailbreak",
    "group_last_speaker", "hasPromptVar", "hasPresetVar", "idle_duration",
    "depth_prompt", "math", "evaluate", "flushvar", "group_card_mode",
    "creatorNotes", "promptVarDefault", "presetVarDefault", "time_diff",
    "getglobalvar", "char_tags", "characterTags", "firstMes", "first_message",
    "length", "message_at", "msgAt", "setglobalvar", "char_tag", "hasTag",
    "has_tag", "addglobalvar", "charPersonality", "last_message_id",
    "incglobalvar", "is_mobile", "charName", "nl", "n", "decglobalvar",
    "token_count", "tokens", "hasglobalvar", "gvarexists", "flushgvar",
    "flushglobalvar", "deleteglobalvar", "charScenario", "last_user_message",
    "ol", "enumerate", "uppercase", "toUpper", "maxPromptTokens", "max_prompt",
    "regex_installed", "hasRegex", "has_regex", "messages_by", "msgBy",
    "flushchatvar", "group_not_muted", "last_char_message", "lastBotMessage",
    "userPersona", "fallback", "coalesce", "maxContextTokens", "max_context",
    "lowercase", "toLower", "not_char", "subjectivePronoun",
    "personaSubjectivePronoun", "maxResponseTokens", "max_response",
    "databankMemory", "documents", "knowledgeBank", "message_count",
    "messagecount", "objectivePronoun", "personaObjectivePronoun", "chat_age",
    "titlecase", "charFocused", "char_group_focused", "note",
    "last_generation_type", "chat_id", "possessivePronoun",
    "personaPossessivePronoun", "is_group_chat", "has_extension",
    "longTermMemory", "chatMemory", "ltm", "mes_examples", "exampleMessages",
    "is_narrator", "lumiaCouncilQuirks", "promptVar", "presetVar",
    "user_color_mode", "colorMode", "color_mode", "group_others", "charPrompt",
    "charSystem", "name",
    # multiplayer aliases
    "is_multiplayer", "is_multiplayer_room", "player_count", "players_count",
    "player_names", "current_player", "current_turn", "host_name",
]

# Extract the macro identifier from a pattern like '{{name::arg}}',
# '{{name}}...{{/name}}', or '{{/name}}'.
_MACRO_NAME_RE = re.compile(r"\{\{/?\s*([a-zA-Z0-9_\-]+)")


def _extract_macro_name(pattern: str) -> Optional[str]:
    """Pull the canonical name out of a macro reference pattern.

    Handles scoped forms ('{{if}}...{{else}}...{{/if}}') and aliases by
    capturing only the first identifier after the opening '{{'. The comment
    shorthand '{{// ...}}' is captured as the name '//'.
    """
    s = pattern.strip()
    if s.startswith("{{//"):
        return "//"
    m = _MACRO_NAME_RE.match(s)
    if not m:
        return None
    return m.group(1).lower() if m.group(1) else None


def _load_known_macros_from_reference() -> Optional[frozenset[str]]:
    """Load the authoritative macro registry from macro_reference.json.

    Returns None if the reference file is missing or malformed so callers can
    fall back to the inline list.
    """
    import os

    try:
        here = Path(
            os.environ.get("PRESET_TOOLS_MACRO_DIR", Path(__file__).resolve().parent)
        ).resolve()
        ref_path = here / "macro_reference.json"
        with ref_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    names: set[str] = set()
    for entry in data.get("macros", []):
        macro = entry.get("macro")
        if macro:
            name = _extract_macro_name(macro)
            if name:
                names.add(name)
        for alias in entry.get("aliases", []):
            name = _extract_macro_name(alias)
            if name:
                names.add(name)

    if not names:
        return None
    return frozenset(names | {n.lower() for n in VAR_OPS.keys()})


_REFERENCE_MACROS = _load_known_macros_from_reference()

KNOWN_MACROS: frozenset[str] = (
    _REFERENCE_MACROS if _REFERENCE_MACROS is not None else frozenset(
        n.lower() for n in (_CANONICAL + _ALIASES + list(VAR_OPS.keys()))
    )
)

# Macros that are typically used as scoped open/close pairs. A bare opener with
# no matching close is usually an authoring mistake (the body then renders
# unconditionally / the macro degrades to an inline form).
SCOPED_HINT: frozenset[str] = frozenset({"if"})
