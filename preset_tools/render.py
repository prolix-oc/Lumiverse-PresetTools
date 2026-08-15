"""
render.py — render a preset's macros to final text, then tokenize it.

`tokenizer.count_preset` counts the RAW block content (macros unexpanded), so
it over- or under-counts whatever a `{{if}}` would drop or a `{{var}}` would
expand. This module first *renders* the macros — running the same machinery
the engine does — and then tokenizes the result, giving the true token cost of
a preset under a given set of variable/flag values.

What renders faithfully (deterministic, offline):
    - control flow: {{if::cond}}…{{else}}…{{/if}} (incl. nested), {{trim}}
    - the full variable system: {{setvar}}/{{getvar}}/{{addvar}}/{{incvar}}/…
      and the .x / $x / @x shorthand, with state threaded across blocks in
      render order EXACTLY like the engine (so a setter in block 3 affects a
      reader in block 9, and a var whose only setter is a DISABLED block reads
      empty — collapsing its {{if}} just like production).
    - logic ({{and}}/{{or}}/{{not}}/{{eq}}/{{switch}}/{{default}}…), math
      ({{calc}}/{{min}}/{{round}}…), strings ({{upper}}/{{replace}}/{{len}}…),
      formatting ({{repeat}}/{{bullets}}…), dice ({{random}}/{{pick}}/{{roll}},
      seeded for reproducibility), and basic temporal macros.
    - creator-defined prompt variables (a block's `variables[]`) seeded from
      their defaults (override with --var name=value).

What can't render offline (needs the live app): identity/persona/chat macros
({{char}}, {{description}}, …) and app macros ({{memories}}, {{loomStyle}},
{{spotify_*}}, …). Supply values with --value name=text (or --sample for a
built-in sample character), otherwise they follow --unknown policy: `keep`
(default — left literal, exactly like the engine treats unknown macros) or
`blank`. Whatever stays unresolved is reported so the token count's fidelity is
transparent.

CLI:
    python -m preset_tools.render "ThreadBare 1.0.json"
    python -m preset_tools.render preset.json --sample --show
    python -m preset_tools.render preset.json --var words_target=900 --set util_chaos=1
    python -m preset_tools.render preset.json --value char=Stella --by-block --seed 7

Programmatic:
    from preset_tools import render_preset, RenderEnv, load
    env = RenderEnv.sample()
    env.set_var("util_spotify", "1")
    result = render_preset(load("ThreadBare 1.0.json"), env)
    print(result.text)            # the rendered prompt
    print(result.total_tokens)    # real Claude token count (if tokenizer available)
"""

from __future__ import annotations

import ast as _ast
import operator as _op
import random as _random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .io import preset_blocks
from .macros import (
    Macro, Scoped, Text, parse_template, VAR_OPS, static_arg_text,
    ESCAPED_OPEN, ESCAPED_CLOSE,
)

_MAX_DEPTH = 20
# Macros whose output is guaranteed not to contain further `{{...}}` — skip the
# recursive re-expansion check (mirrors the engine's `terminal` flag).
_TERMINAL = frozenset({
    "space", "newline", "nl", "n", "noop", "trim", "comment", "note", "//",
    "reverse", "banned",
    "len", "length", "upper", "uppercase", "toupper", "lower", "lowercase",
    "tolower", "capitalize", "titlecase", "substr", "substring", "split",
    "join", "find", "count", "index", "truncate", "wrap",
    "calc", "math", "evaluate", "min", "max", "clamp", "abs", "floor", "ceil",
    "round", "decimals", "mod", "arc",
    "random", "pick", "roll",
    "time", "date", "weekday", "isotime", "isodate", "datetimeformat",
    "eq", "ne", "gt", "gte", "lt", "lte", "and", "or", "not",
})
# Macros that receive raw (unresolved) args so they can short-circuit / pick a
# branch without evaluating the others (mirrors `delayArgResolution`).
_DELAY_ARGS = frozenset({"if", "and", "or", "default", "fallback", "coalesce", "switch"})

_FALSY = {"", "0", "false", "null", "undefined", "no", "off"}
_COMPARISON_OPS = ("==", "!=", ">=", "<=", ">", "<")


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

@dataclass
class RenderEnv:
    """Context for a render. Variables are mutated in place across blocks."""
    names: dict = field(default_factory=dict)        # user, char, group, …
    character: dict = field(default_factory=dict)    # description, personality, …
    chat: dict = field(default_factory=dict)         # lastMessage, messageCount, …
    system: dict = field(default_factory=dict)       # model, maxContext, …
    values: dict = field(default_factory=dict)       # explicit overrides, any macro name
    local: dict = field(default_factory=dict)        # {{.x}} scope
    glob: dict = field(default_factory=dict)         # {{$x}} scope
    chatvars: dict = field(default_factory=dict)     # {{@x}} scope
    prompt_var_defaults: dict = field(default_factory=dict)
    seed: int = 1234
    now: Optional[datetime] = None
    unknown_policy: str = "keep"                     # 'keep' | 'blank'
    # populated during a render:
    unresolved: set = field(default_factory=set)
    diagnostics: list = field(default_factory=list)

    def __post_init__(self):
        if self.now is None:
            self.now = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)
        self._rng = _random.Random(self.seed)

    # convenience setters used by the CLI / callers
    def set_var(self, name: str, value, scope: str = "local") -> "RenderEnv":
        {"local": self.local, "global": self.glob, "chat": self.chatvars}[scope][name] = str(value)
        return self

    def set_value(self, macro_name: str, text: str) -> "RenderEnv":
        self.values[macro_name.lower()] = text
        return self

    def scope_map(self, scope: str) -> dict:
        return {"local": self.local, "global": self.glob, "chat": self.chatvars}[scope]

    @classmethod
    def empty(cls, **kw) -> "RenderEnv":
        """Identity/persona/app macros resolve to empty unless overridden."""
        env = cls(**kw)
        return env

    @classmethod
    def sample(cls, **kw) -> "RenderEnv":
        """A realistic sample character/chat so a render reads naturally."""
        env = cls(**kw)
        env.names.update({
            "user": "Alex", "char": "Stella", "group": "Stella",
            "groupNotMuted": "Stella", "notChar": "Alex",
            "charGroupFocused": "Stella", "groupOthers": "",
            "groupMemberCount": "0", "isGroupChat": "no", "isNarrator": "no",
            "groupLastSpeaker": "", "groupCardMode": "solo",
            "isMultiplayer": "no", "playerCount": "1",
            "players": "Alex", "hostName": "Alex", "currentPlayer": "",
        })
        env.character.update({
            "name": "Stella", "description": "A sharp-tongued starship mechanic "
            "with grease under her nails and a soft spot she'd never admit to.",
            "personality": "Wry, loyal, allergic to sentiment.",
            "scenario": "The two of you are stranded dockside waiting on a part "
            "that may never come.",
            "persona": "Alex — a drifter with more debts than answers.",
            "mesExamples": "", "systemPrompt": "", "postHistoryInstructions": "",
            "depthPrompt": "", "creatorNotes": "", "version": "1.0",
            "creator": "studio", "firstMessage": "You're late.",
        })
        env.chat.update({
            "id": "sample-chat", "messageCount": "12",
            "lastMessage": "\"Hand me the wrench,\" she said.",
            "lastMessageName": "Stella",
            "lastUserMessage": "What's taking so long?",
            "lastCharMessage": "\"Hand me the wrench,\" she said.",
            "lastMessageId": "11", "firstIncludedMessageId": "0",
            "lastSwipeId": "0", "currentSwipeId": "0",
        })
        env.system.update({
            "model": "claude-opus-4-8", "maxPrompt": "200000",
            "maxContext": "200000", "maxResponse": "8192",
            "lastGenerationType": "normal", "isMobile": "no",
        })
        return env


# Maps a macro name (lowercased) to (env-section, key) for direct data lookups.
_DATA_FIELDS: dict[str, tuple[str, str]] = {}


def _reg_data(section: str, key: str, *names: str) -> None:
    for n in names:
        _DATA_FIELDS[n.lower()] = (section, key)


_reg_data("names", "user", "user")
_reg_data("names", "char", "char", "charName", "name")
_reg_data("names", "group", "group")
_reg_data("names", "groupNotMuted", "groupNotMuted", "group_not_muted")
_reg_data("names", "notChar", "notChar", "not_char")
_reg_data("names", "charGroupFocused", "charGroupFocused", "charFocused", "char_group_focused")
_reg_data("names", "groupOthers", "groupOthers", "group_others")
_reg_data("names", "groupMemberCount", "groupMemberCount", "group_member_count")
_reg_data("names", "isGroupChat", "isGroupChat", "is_group_chat")
_reg_data("names", "isNarrator", "isNarrator", "is_narrator")
_reg_data("names", "groupLastSpeaker", "groupLastSpeaker", "group_last_speaker")
_reg_data("names", "groupCardMode", "groupCardMode", "group_card_mode")
_reg_data("names", "isMultiplayer", "isMultiplayer", "is_multiplayer", "is_multiplayer_room")
_reg_data("names", "playerCount", "playerCount", "player_count", "players_count")
_reg_data("names", "players", "players", "player_names")
_reg_data("names", "hostName", "hostName", "host_name")
_reg_data("names", "currentPlayer", "currentPlayer", "current_player", "current_turn")
_reg_data("character", "description", "description", "charDescription")
_reg_data("character", "personality", "personality", "charPersonality")
_reg_data("character", "scenario", "scenario", "charScenario")
_reg_data("character", "persona", "persona", "userPersona")
_reg_data("character", "mesExamples", "mesExamples", "mes_examples", "exampleMessages")
_reg_data("character", "systemPrompt", "charPrompt", "charSystem")
_reg_data("character", "postHistoryInstructions", "charPostHistoryInstructions")
_reg_data("character", "depthPrompt", "charDepthPrompt", "depth_prompt")
_reg_data("character", "creatorNotes", "charCreatorNotes", "creatorNotes")
_reg_data("character", "version", "charVersion")
_reg_data("character", "creator", "charCreator")
_reg_data("character", "firstMessage", "firstMessage", "firstMes", "first_message")
_reg_data("chat", "id", "chatId", "chat_id")
_reg_data("chat", "messageCount", "messageCount", "message_count", "messagecount")
_reg_data("chat", "lastMessage", "lastMessage", "last_message")
_reg_data("chat", "lastMessageName", "lastMessageName")
_reg_data("chat", "lastUserMessage", "lastUserMessage", "last_user_message", "input")
_reg_data("chat", "lastCharMessage", "lastCharMessage", "last_char_message", "lastBotMessage")
_reg_data("chat", "lastMessageId", "lastMessageId", "last_message_id")
_reg_data("chat", "firstIncludedMessageId", "firstIncludedMessageId")
_reg_data("chat", "lastSwipeId", "lastSwipeId")
_reg_data("chat", "currentSwipeId", "currentSwipeId")
_reg_data("system", "model", "model")
_reg_data("system", "maxPrompt", "maxPrompt", "maxPromptTokens", "max_prompt")
_reg_data("system", "maxContext", "maxContext", "maxContextTokens", "max_context")
_reg_data("system", "maxResponse", "maxResponse", "maxResponseTokens", "max_response")
_reg_data("system", "lastGenerationType", "lastGenerationType", "last_generation_type")
_reg_data("system", "isMobile", "isMobile", "is_mobile")


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class _Ctx:
    """Handler execution context (mirrors MacroExecContext)."""
    __slots__ = ("name", "args", "raw_args", "scoped", "body", "body_raw",
                 "flags", "env", "_ev", "_depth")

    def __init__(self, name, args, raw_args, scoped, body, body_raw, flags, ev, depth):
        self.name = name
        self.args = args
        self.raw_args = raw_args
        self.scoped = scoped
        self.body = body
        self.body_raw = body_raw
        self.flags = flags
        self.env = ev.env
        self._ev = ev
        self._depth = depth

    def resolve(self, text: str) -> str:
        return self._ev.eval_nodes(parse_template(text), self._depth + 1)

    def resolve_nodes(self, nodes) -> str:
        return self._ev.eval_nodes(nodes, self._depth + 1)


class Evaluator:
    def __init__(self, env: RenderEnv):
        self.env = env
        self.handlers: dict[str, Callable[[_Ctx], str]] = {}
        _register_handlers(self)

    # -- core walk ---------------------------------------------------------

    def eval_nodes(self, nodes, depth: int) -> str:
        if depth > _MAX_DEPTH:
            self.env.diagnostics.append("max nesting depth exceeded")
            return ""
        out = []
        for node in nodes:
            if isinstance(node, Text):
                out.append(node.value)
            elif isinstance(node, Scoped):
                out.append(self._eval_scoped(node, depth))
            else:
                out.append(self._eval_macro(node, depth))
        return "".join(out)

    def _expand_if_needed(self, text: str, terminal: bool, depth: int) -> str:
        if terminal or "{{" not in text or depth >= _MAX_DEPTH:
            return text
        expanded = self.eval_nodes(parse_template(text), depth + 1)
        return expanded if expanded != text else text

    def _eval_macro(self, node: Macro, depth: int) -> str:
        nm = node.name.lower()
        if not nm:
            return _reconstruct(node)
        handler = self.handlers.get(nm)
        delay = nm in _DELAY_ARGS
        if handler is not None:
            args = [] if delay else [self.eval_nodes(a, depth + 1) for a in node.args]
            ctx = _Ctx(node.name, args, node.args, False, "", [], node.flags, self, depth)
            try:
                raw = str(handler(ctx))
            except Exception as exc:  # be resilient; report and continue
                self.env.diagnostics.append(f"error in {{{{{node.name}}}}}: {exc}")
                return ""
            return self._expand_if_needed(raw, nm in _TERMINAL, depth)
        # No handler: variable op? (covers all 30+ var macro names/aliases)
        if nm in VAR_OPS:
            args = [self.eval_nodes(a, depth + 1) for a in node.args]
            ctx = _Ctx(node.name, args, node.args, False, "", [], node.flags, self, depth)
            return self._var_op(ctx)
        # Data / identity / app macro, or genuinely unknown.
        return self._resolve_data(node, depth)

    def _eval_scoped(self, node: Scoped, depth: int) -> str:
        nm = node.name.lower()
        handler = self.handlers.get(nm)
        delay = nm in _DELAY_ARGS
        if handler is None and nm not in VAR_OPS:
            # Unknown scoped macro — engine evaluates the body and returns it.
            return self.eval_nodes(node.body, depth + 1)
        args = [] if delay else [self.eval_nodes(a, depth + 1) for a in node.args]
        body = "" if delay else self.eval_nodes(node.body, depth + 1)
        ctx = _Ctx(node.name, args, node.args, True, body, node.body, node.flags, self, depth)
        if handler is not None:
            try:
                raw = str(handler(ctx))
            except Exception as exc:
                self.env.diagnostics.append(f"error in scoped {{{{{node.name}}}}}: {exc}")
                return ""
            return self._expand_if_needed(raw, nm in _TERMINAL, depth)
        return self._var_op(ctx)

    # -- variable ops (generic over VAR_OPS) -------------------------------

    def _var_op(self, ctx: _Ctx) -> str:
        spec = VAR_OPS[ctx.name.lower()]
        m = self.env.scope_map(spec.scope)
        key = (ctx.args[0].strip() if ctx.args else "")
        role = spec.role
        if role in ("read",):
            if not key:
                return ""
            if key in m:
                return m[key]
            # prompt-var fallback for {{var::x}} (local) when not yet set
            if spec.scope == "local" and key in self.env.prompt_var_defaults:
                return str(self.env.prompt_var_defaults[key])
            return ""
        if role == "read_safe":  # varDefault
            return str(self.env.prompt_var_defaults.get(key, ""))
        if role == "exists":
            return "true" if key in m else "false"
        if role == "delete":
            m.pop(key, None)
            return ""
        if role == "write":  # setvar
            m[key] = ctx.body if ctx.scoped else (ctx.args[1] if len(ctx.args) > 1 else "")
            return ""
        if role == "rw":  # addvar / incvar / decvar
            base = _to_num(m.get(key, "0"))
            name = ctx.name.lower()
            if "add" in name:
                res = base + _to_num(ctx.args[1] if len(ctx.args) > 1 else "0")
            elif "inc" in name:
                res = base + 1
            else:  # dec
                res = base - 1
            s = _numstr(res)
            m[key] = s
            return s
        return ""

    # -- data / unknown ----------------------------------------------------

    def _resolve_data(self, node: Macro, depth: int) -> str:
        nm = node.name.lower()
        # 1) explicit override by name
        if nm in self.env.values:
            return self._expand_if_needed(self.env.values[nm], False, depth)
        # 2) built-in env field
        field_ref = _DATA_FIELDS.get(nm)
        if field_ref:
            section, key = field_ref
            val = getattr(self.env, section).get(key)
            if val is not None:
                return str(val)
            # known data macro but no value provided → policy
            self.env.unresolved.add(node.name)
            return _reconstruct(node) if self.env.unknown_policy == "keep" else ""
        # 3) genuinely unknown (incl. app/extension macros)
        self.env.unresolved.add(node.name)
        return _reconstruct(node) if self.env.unknown_policy == "keep" else ""


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _register_handlers(ev: Evaluator) -> None:
    h = ev.handlers

    def reg(fn, *names):
        for n in names:
            h[n.lower()] = fn

    # --- core ---
    reg(lambda c: " ", "space")
    reg(lambda c: "\n", "newline", "nl", "n")
    reg(lambda c: "", "noop", "banned")
    reg(lambda c: "", "comment", "note", "//")
    reg(_h_trim, "trim")
    reg(lambda c: (c.body[::-1] if c.scoped else (c.args[0][::-1] if c.args else "")), "reverse")

    # --- conditionals / logic ---
    reg(_h_if, "if")
    reg(lambda c: _ELSE_MARKER, "else")
    reg(_h_switch, "switch")
    reg(_h_default, "default", "fallback", "coalesce")
    reg(_h_and, "and")
    reg(_h_or, "or")
    reg(lambda c: "true" if not _truthy(_arg(c, 0)) else "", "not")
    reg(lambda c: _cmp(c, "=="), "eq")
    reg(lambda c: _cmp(c, "!="), "ne")
    reg(lambda c: _cmp(c, ">"), "gt")
    reg(lambda c: _cmp(c, ">="), "gte")
    reg(lambda c: _cmp(c, "<"), "lt")
    reg(lambda c: _cmp(c, "<="), "lte")

    # --- strings ---
    reg(lambda c: str(len(_body_or_arg(c))), "len", "length")
    reg(lambda c: _body_or_arg(c).upper(), "upper", "uppercase", "toupper")
    reg(lambda c: _body_or_arg(c).lower(), "lower", "lowercase", "tolower")
    reg(lambda c: _capitalize(_body_or_arg(c)), "capitalize", "titlecase")
    reg(_h_replace, "replace")
    reg(_h_substr, "substr", "substring")
    reg(_h_join, "join")
    reg(_h_truncate, "truncate")
    reg(_h_wrap, "wrap")
    reg(lambda c: str(_arg(c, 0).count(_arg(c, 1))), "count")

    # --- math ---
    reg(_h_calc, "calc", "math", "evaluate")
    reg(lambda c: _numstr(min(_nums(c))) if _nums(c) else "", "min")
    reg(lambda c: _numstr(max(_nums(c))) if _nums(c) else "", "max")
    reg(_h_clamp, "clamp")
    reg(lambda c: _numstr(abs(_to_num(_arg(c, 0)))), "abs")
    reg(lambda c: _numstr(_mfloor(_to_num(_arg(c, 0)))), "floor")
    reg(lambda c: _numstr(_mceil(_to_num(_arg(c, 0)))), "ceil")
    reg(_h_round, "round")
    reg(lambda c: _numstr(_to_num(_arg(c, 0)) % _to_num(_arg(c, 1) or "1")), "mod")

    # --- formatting ---
    reg(_h_repeat, "repeat")
    reg(_h_bullets, "bullets")
    reg(_h_numbered, "numbered")

    # --- entropy (seeded) ---
    reg(lambda c: _h_random(ev, c), "random")
    reg(lambda c: _h_pick(ev, c), "pick")
    reg(lambda c: _h_roll(ev, c), "roll")

    # --- counters (simple, render-scoped) ---
    reg(lambda c: _h_counter(ev, c, reset=False), "rcounter", "counter")

    # --- temporal ---
    reg(lambda c: ev.env.now.strftime("%H:%M:%S"), "time")
    reg(lambda c: ev.env.now.strftime("%Y-%m-%d"), "date")
    reg(lambda c: ev.env.now.strftime("%A"), "weekday")
    reg(lambda c: ev.env.now.strftime("%H:%M:%S"), "isotime")
    reg(lambda c: ev.env.now.strftime("%Y-%m-%d"), "isodate")


# -- handler implementations -------------------------------------------------

_ELSE_MARKER = "\x00ELSE\x00"


def _arg(c: _Ctx, i: int) -> str:
    return c.args[i] if i < len(c.args) else ""


def _body_or_arg(c: _Ctx) -> str:
    return c.body if c.scoped else _arg(c, 0)


def _h_trim(c: _Ctx) -> str:
    if c.scoped:
        if "#" in c.flags:
            return c.body
        return _dedent(c.body).strip()
    return ""


def _h_if(c: _Ctx) -> str:
    # Build condition from raw args joined by spaces (matches {{if .x == 5}}).
    if len(c.raw_args) > 1:
        parts = []
        for i, a in enumerate(c.raw_args):
            if i:
                parts.append(" ")
            parts.append(c.resolve_nodes(a))
        cond = "".join(parts).strip()
    else:
        cond = c.resolve_nodes(c.raw_args[0]).strip() if c.raw_args else ""
    if "{{" in cond:
        nxt = c.resolve(cond).strip()
        if nxt != cond:
            cond = nxt
    negate = False
    if cond.startswith("!"):
        negate = True
        cond = cond[1:].strip()
    cond = _resolve_inline_shorthands(cond, c.env)
    result = _evaluate_condition(cond)
    if negate:
        result = not result
    if c.scoped:
        truthy_nodes, falsy_nodes = _split_else(c.body_raw)
        return c.resolve_nodes(truthy_nodes if result else falsy_nodes)
    return "true" if result else ""


def _split_else(body):
    for i, node in enumerate(body):
        if isinstance(node, Macro) and not node.is_close and node.name.lower() == "else":
            return body[:i], body[i + 1:]
    return body, []


def _h_switch(c: _Ctx) -> str:
    if not c.raw_args:
        return ""
    value = c.resolve_nodes(c.raw_args[0]).strip()
    rest = c.raw_args[1:]
    i = 0
    while i + 1 < len(rest):
        case = c.resolve_nodes(rest[i]).strip()
        if case == value:
            return c.resolve_nodes(rest[i + 1])
        i += 2
    if len(rest) % 2 == 1:  # trailing default
        return c.resolve_nodes(rest[-1])
    return ""


def _h_default(c: _Ctx) -> str:
    for a in c.raw_args:
        v = c.resolve_nodes(a)
        if _truthy(v):
            return v
    return ""


def _h_and(c: _Ctx) -> str:
    for a in c.raw_args:
        if not _truthy(c.resolve_nodes(a)):
            return ""
    return "true"


def _h_or(c: _Ctx) -> str:
    for a in c.raw_args:
        if _truthy(c.resolve_nodes(a)):
            return "true"
    return ""


def _cmp(c: _Ctx, op: str) -> str:
    a, b = _arg(c, 0), _arg(c, 1)
    an, bn = _try_num(a), _try_num(b)
    if an is not None and bn is not None:
        a, b = an, bn
    res = {
        "==": a == b, "!=": a != b, ">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b,
    }[op]
    return "true" if res else ""


def _h_replace(c: _Ctx) -> str:
    text = c.body if c.scoped else _arg(c, 0)
    if c.scoped:
        find, repl = _arg(c, 0), _arg(c, 1)
    else:
        text, find, repl = _arg(c, 0), _arg(c, 1), _arg(c, 2)
    return text.replace(find, repl)


def _h_substr(c: _Ctx) -> str:
    text = _body_or_arg(c)
    start = int(_to_num(_arg(c, 1 if not c.scoped else 0) or "0"))
    length_s = _arg(c, 2 if not c.scoped else 1)
    if length_s == "":
        return text[start:]
    return text[start:start + int(_to_num(length_s))]


def _h_join(c: _Ctx) -> str:
    if not c.args:
        return ""
    sep = c.args[-1]
    return sep.join(c.args[:-1]) if len(c.args) > 1 else c.args[0]


def _h_truncate(c: _Ctx) -> str:
    text, n = _arg(c, 0), int(_to_num(_arg(c, 1) or "0"))
    return text if len(text) <= n else text[:n] + "…"


def _h_wrap(c: _Ctx) -> str:
    wrapper = _arg(c, 1) if not c.scoped else _arg(c, 0)
    text = c.body if c.scoped else _arg(c, 0)
    return f"{wrapper}{text}{wrapper}"


def _h_calc(c: _Ctx) -> str:
    expr = c.body if c.scoped else _arg(c, 0)
    try:
        return _numstr(_safe_arith(expr))
    except Exception:
        c.env.diagnostics.append(f"calc could not evaluate: {expr!r}")
        return ""


def _h_clamp(c: _Ctx) -> str:
    v, lo, hi = _to_num(_arg(c, 0)), _to_num(_arg(c, 1)), _to_num(_arg(c, 2))
    return _numstr(max(lo, min(hi, v)))


def _h_round(c: _Ctx) -> str:
    v = _to_num(_arg(c, 0))
    digits = _arg(c, 1)
    if digits == "":
        return _numstr(_mfloor(v + 0.5)) if v >= 0 else _numstr(_mceil(v - 0.5))
    return _numstr(round(v, int(_to_num(digits))))


def _h_repeat(c: _Ctx) -> str:
    text = c.body if c.scoped else _arg(c, 0)
    times = int(_to_num(_arg(c, 1) if not c.scoped else _arg(c, 0) or "0"))
    if c.scoped:
        times = int(_to_num(_arg(c, 0) or "0"))
    return text * max(0, times)


def _h_bullets(c: _Ctx) -> str:
    items = c.args
    return "\n".join(f"- {it}" for it in items if it != "")


def _h_numbered(c: _Ctx) -> str:
    items = [a for a in c.args if a != ""]
    return "\n".join(f"{i+1}. {it}" for i, it in enumerate(items))


def _h_random(ev: Evaluator, c: _Ctx) -> str:
    if len(c.args) >= 2 and _try_num(c.args[0]) is not None and _try_num(c.args[1]) is not None and len(c.args) == 2:
        lo, hi = int(_to_num(c.args[0])), int(_to_num(c.args[1]))
        return str(ev.env._rng.randint(min(lo, hi), max(lo, hi)))
    if c.args:
        return ev.env._rng.choice(c.args)
    return str(ev.env._rng.randint(0, 1))


def _h_pick(ev: Evaluator, c: _Ctx) -> str:
    return ev.env._rng.choice(c.args) if c.args else ""


def _h_roll(ev: Evaluator, c: _Ctx) -> str:
    spec = _arg(c, 0).strip().lower()
    m = re.fullmatch(r"(\d*)d(\d+)", spec)
    if not m:
        n = _try_num(spec)
        return str(ev.env._rng.randint(1, int(n))) if n else ""
    count = int(m.group(1) or "1")
    sides = int(m.group(2))
    return str(sum(ev.env._rng.randint(1, sides) for _ in range(count)))


def _h_counter(ev: Evaluator, c: _Ctx, reset: bool) -> str:
    key = "__counter__" + (_arg(c, 0) or "default")
    cur = int(ev.env.local.get(key, "0"))
    cur += 1
    ev.env.local[key] = str(cur)
    return str(cur)


# ---------------------------------------------------------------------------
# Condition evaluation (port of primitives.ts evaluateCondition)
# ---------------------------------------------------------------------------

def _find_comparison(value: str):
    best_i, best_op = -1, None
    for op in _COMPARISON_OPS:
        i = value.find(op)
        if i == -1:
            continue
        if best_i == -1 or i < best_i or (i == best_i and len(op) > len(best_op or "")):
            best_i, best_op = i, op
    return (best_op, best_i) if best_op else None


def _evaluate_condition(value: str) -> bool:
    if "{{" in value and "}}" in value:
        return False
    found = _find_comparison(value)
    if found:
        op, i = found
        lv, rv = value[:i].strip(), value[i + len(op):].strip()
        ln, rn = _try_num(lv), _try_num(rv)
        both = ln is not None and rn is not None
        if op == "==":
            return ln == rn if both else lv == rv
        if op == "!=":
            return ln != rn if both else lv != rv
        if op == ">":
            return ln > rn if both else lv > rv
        if op == ">=":
            return ln >= rn if both else lv >= rv
        if op == "<":
            return ln < rn if both else lv < rv
        if op == "<=":
            return ln <= rn if both else lv <= rv
    if not value:
        return False
    return value.lower() not in _FALSY


def _truthy(value: str) -> bool:
    return value.strip().lower() not in _FALSY if value is not None else False


def _resolve_inline_shorthands(cond: str, env: RenderEnv) -> str:
    cond = re.sub(r"(^|\s)\.([a-zA-Z][\w-]*)",
                  lambda m: m.group(1) + env.local.get(m.group(2), ""), cond)
    cond = re.sub(r"(^|\s)\$([a-zA-Z][\w-]*)",
                  lambda m: m.group(1) + env.glob.get(m.group(2), ""), cond)
    return cond


# ---------------------------------------------------------------------------
# Numeric / string helpers
# ---------------------------------------------------------------------------

def _try_num(s: str):
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_num(s) -> float:
    n = _try_num(str(s))
    return n if n is not None else 0.0


def _nums(c: _Ctx) -> list:
    return [_to_num(a) for a in c.args if _try_num(a) is not None]


def _numstr(x) -> str:
    """Format like JS String(): integers without a trailing .0."""
    f = float(x)
    if f == int(f) and abs(f) < 1e16:
        return str(int(f))
    return repr(f)


def _mfloor(x: float) -> int:
    import math
    return math.floor(x)


def _mceil(x: float) -> int:
    import math
    return math.ceil(x)


def _capitalize(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _dedent(text: str) -> str:
    lines = text.split("\n")
    start, end = 0, len(lines) - 1
    while start < len(lines) and lines[start].strip() == "":
        start += 1
    while end > start and lines[end].strip() == "":
        end -= 1
    trimmed = lines[start:end + 1]
    nonempty = [l for l in trimmed if l.strip()]
    if not nonempty:
        return ""
    indent = min(len(l) - len(l.lstrip()) for l in nonempty)
    if indent == 0:
        return "\n".join(trimmed)
    return "\n".join(l[indent:] for l in trimmed)


_ARITH_OPS = {
    _ast.Add: _op.add, _ast.Sub: _op.sub, _ast.Mult: _op.mul,
    _ast.Div: _op.truediv, _ast.FloorDiv: _op.floordiv, _ast.Mod: _op.mod,
    _ast.Pow: _op.pow, _ast.USub: _op.neg, _ast.UAdd: _op.pos,
}


def _safe_arith(expr: str) -> float:
    """Evaluate a pure-arithmetic expression safely (no names/calls)."""
    node = _ast.parse(expr, mode="eval").body

    def ev(n):
        if isinstance(n, _ast.BinOp):
            return _ARITH_OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, _ast.UnaryOp):
            return _ARITH_OPS[type(n.op)](ev(n.operand))
        if isinstance(n, _ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        # Python <3.8 numbers
        if isinstance(n, getattr(_ast, "Num", ())):
            return n.n
        raise ValueError("unsupported expression")
    return float(ev(node))


def _reconstruct(node: Macro) -> str:
    s = "{{" + (node.flags or "") + node.name
    for arg in node.args:
        s += "::" + _reconstruct_nodes(arg)
    return s + "}}"


def _reconstruct_nodes(nodes) -> str:
    out = []
    for n in nodes:
        if isinstance(n, Text):
            out.append(n.value.replace(ESCAPED_OPEN, "{").replace(ESCAPED_CLOSE, "}"))
        elif isinstance(n, Macro):
            out.append(_reconstruct(n))
        elif isinstance(n, Scoped):
            out.append(_reconstruct(Macro(n.name, n.args, n.flags, n.offset))
                       + _reconstruct_nodes(n.body) + "{{/" + n.name + "}}")
    return "".join(out)


def _postprocess(text: str) -> str:
    return text.replace(ESCAPED_OPEN, "{").replace(ESCAPED_CLOSE, "}")


# ---------------------------------------------------------------------------
# Public render API
# ---------------------------------------------------------------------------

def render_text(template: str, env: RenderEnv) -> str:
    """Render a single template string to final text using `env`."""
    if not template or "{{" not in template and "<user>" not in template.lower() \
            and "<char>" not in template.lower():
        return template
    ev = Evaluator(env)
    text = template
    for _ in range(2):  # outer convergence pass (matches engine MAX_ITERATIONS)
        result = ev.eval_nodes(parse_template(text), 0)
        if result == text:
            break
        text = result
        if "{{" not in text:
            break
    return _postprocess(text)


@dataclass
class RenderedBlock:
    index: int
    name: str
    role: str
    marker: Optional[str]
    text: str
    chars: int
    tokens: Optional[int] = None


@dataclass
class RenderResult:
    text: str                                   # full assembled rendered prompt
    blocks: list = field(default_factory=list)  # list[RenderedBlock] (enabled, non-empty)
    total_chars: int = 0
    total_tokens: Optional[int] = None
    unresolved: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    tokenizer_error: Optional[str] = None


_POSITION_RANK = {"pre_history": 0, "in_history": 1, "post_history": 2}


def _seed_prompt_vars(preset: dict, env: RenderEnv, overrides: dict) -> None:
    """Seed declared prompt-variable values into the local scope (enabled blocks)."""
    for b in preset_blocks(preset):
        if not b.get("enabled"):
            continue
        for v in (b.get("variables") or []):
            name = v.get("name")
            if not name:
                continue
            rendered = _coerce_prompt_var(v, overrides.get(name))
            env.prompt_var_defaults[name] = _coerce_prompt_var(v, None)
            env.local.setdefault(name, rendered)
            if name in overrides:
                env.local[name] = rendered


def _coerce_prompt_var(defn: dict, override) -> str:
    t = defn.get("type", "text")
    val = override if override is not None else defn.get("defaultValue", "")
    if t == "switch":
        try:
            return "1" if int(float(val)) else "0"
        except (ValueError, TypeError):
            return "1" if str(val).lower() in ("1", "true", "on", "yes") else "0"
    if t in ("number", "slider"):
        n = _try_num(str(val))
        return _numstr(n) if n is not None else str(val)
    if t == "multiselect":
        if isinstance(val, list):
            sep = defn.get("separator", ", ")
            labels = {o.get("id", o.get("value")): o.get("label", o.get("value"))
                      for o in defn.get("options", [])}
            return sep.join(str(labels.get(x, x)) for x in val)
        return str(val)
    return str(val)


def render_preset(preset: dict, env: Optional[RenderEnv] = None, *,
                  tokenize: bool = True, tokenizer_path: str = None,
                  prompt_var_overrides: dict = None) -> RenderResult:
    """Render every enabled block in render order, threading variable state,
    and (optionally) tokenize the result.

    The returned RenderResult has `.text` (full prompt), `.blocks` (per-block
    rendered text + token counts), `.total_tokens`, and `.unresolved` (macros
    that had no value and followed the unknown policy)."""
    env = env or RenderEnv.sample()
    _seed_prompt_vars(preset, env, prompt_var_overrides or {})

    blocks = preset_blocks(preset)
    ordered = sorted(enumerate(blocks),
                     key=lambda it: _POSITION_RANK.get(it[1].get("position", "pre_history"), 0))

    result = RenderResult(text="")
    rendered_chunks: list[str] = []
    for orig_idx, b in ordered:
        if not b.get("enabled"):
            continue
        content = b.get("content") or ""
        if not content.strip():
            continue
        text = render_text(content, env)
        text_stripped = text.strip()
        rb = RenderedBlock(
            index=orig_idx, name=b.get("name", f"#{orig_idx}"),
            role=b.get("role", "system"), marker=b.get("marker"),
            text=text, chars=len(text),
        )
        result.blocks.append(rb)
        if text_stripped:
            rendered_chunks.append(text_stripped)

    result.text = "\n\n".join(rendered_chunks)
    result.total_chars = sum(rb.chars for rb in result.blocks)
    result.unresolved = sorted(env.unresolved)
    result.diagnostics = list(env.diagnostics)

    if tokenize:
        try:
            from .tokenizer import get_tokenizer
            tok = get_tokenizer(tokenizer_path)
            for rb in result.blocks:
                rb.tokens = len(tok.encode(rb.text, add_special_tokens=False).ids)
            result.total_tokens = sum(rb.tokens for rb in result.blocks)
        except (ImportError, FileNotFoundError) as exc:
            result.tokenizer_error = str(exc)

    return result


def render_and_tokenize(preset: dict, env: Optional[RenderEnv] = None,
                        **kw) -> RenderResult:
    """Alias for render_preset(..., tokenize=True)."""
    return render_preset(preset, env, tokenize=True, **kw)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_render_report(result: RenderResult, *, by_block: bool = False,
                        show_text: bool = False, file=None) -> None:
    import sys
    out = file or sys.stdout
    print("\n=== Render + tokenize ===", file=out)
    if by_block:
        print(f'{"#":>3}  {"name":<34} {"role":<10} {"chars":>6} {"tokens":>7}', file=out)
        print("-" * 68, file=out)
        for rb in result.blocks:
            tok = "—" if rb.tokens is None else str(rb.tokens)
            mark = f" [{rb.marker}]" if rb.marker else ""
            print(f"{rb.index+1:>3}  {rb.name[:34]:<34} {rb.role[:10]:<10} "
                  f"{rb.chars:>6} {tok:>7}{mark}", file=out)
        print("-" * 68, file=out)

    print(f"  Rendered blocks: {len(result.blocks)}", file=out)
    print(f"  Total chars:     {result.total_chars}", file=out)
    if result.total_tokens is not None:
        approx = result.total_chars // 4
        print(f"  Real tokens:     {result.total_tokens}  (chars//4 ≈ {approx})", file=out)
    elif result.tokenizer_error:
        print(f"  Tokens:          unavailable ({result.tokenizer_error.splitlines()[0]})", file=out)

    if result.unresolved:
        print(f"\n  Unresolved macros ({len(result.unresolved)}) — no value supplied, "
              f"counted as-is per policy:", file=out)
        preview = ", ".join("{{" + u + "}}" for u in result.unresolved[:18])
        if len(result.unresolved) > 18:
            preview += f", … (+{len(result.unresolved) - 18} more)"
        print(f"    {preview}", file=out)
    if result.diagnostics:
        print(f"\n  Evaluator notes ({len(result.diagnostics)}):", file=out)
        for d in result.diagnostics[:10]:
            print(f"    • {d}", file=out)

    if show_text:
        print("\n" + "=" * 68, file=out)
        print(result.text, file=out)
        print("=" * 68, file=out)
    print("", file=out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_kv(items, scope_aware=False):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"expected name=value, got {it!r}")
        k, v = it.split("=", 1)
        out[k.strip()] = v
    return out


def main(argv: Optional[list] = None) -> int:
    import argparse
    import json
    import sys
    from .io import load

    p = argparse.ArgumentParser(
        prog="preset_tools.render",
        description="Render a preset's macros to final text and tokenize the result.")
    p.add_argument("file", help="preset JSON file")
    p.add_argument("--sample", action="store_true",
                   help="use a built-in sample character/chat for data macros")
    p.add_argument("--var", action="append", metavar="NAME=VALUE", default=[],
                   help="set a declared prompt variable (repeatable)")
    p.add_argument("--set", action="append", metavar="[SCOPE:]NAME=VALUE", default=[],
                   help="pre-set a variable; SCOPE is local|global|chat (default local)")
    p.add_argument("--value", action="append", metavar="MACRO=TEXT", default=[],
                   help="provide a value for a data/app macro, e.g. char=Stella (repeatable)")
    p.add_argument("--seed", type=int, default=1234, help="RNG seed for random/pick/roll")
    p.add_argument("--unknown", choices=["keep", "blank"], default="keep",
                   help="policy for macros with no value (default: keep literal)")
    p.add_argument("--by-block", action="store_true", help="per-block token table")
    p.add_argument("--show", action="store_true", help="print the rendered prompt text")
    p.add_argument("--out", metavar="FILE", help="write rendered text to a file")
    p.add_argument("--no-tokenize", action="store_true", help="skip tokenizing")
    p.add_argument("--tokenizer", metavar="FILE", help="explicit tokenizer.json")
    p.add_argument("--json", action="store_true", help="emit JSON summary")
    args = p.parse_args(argv)

    env = RenderEnv.sample() if args.sample else RenderEnv.empty()
    env.seed = args.seed
    env.unknown_policy = args.unknown
    env.__post_init__()  # rebuild rng with new seed

    for k, v in _parse_kv(args.value).items():
        env.set_value(k, v)
    for it in args.set:
        scope = "local"
        name_part = it
        if ":" in it.split("=", 1)[0]:
            scope, name_part = it.split(":", 1)
        if "=" not in name_part:
            raise SystemExit(f"expected NAME=VALUE in --set, got {it!r}")
        name, val = name_part.split("=", 1)
        env.set_var(name.strip(), val, scope=scope.strip())
    var_overrides = _parse_kv(args.var)

    preset = load(args.file)
    result = render_preset(preset, env, tokenize=not args.no_tokenize,
                           tokenizer_path=args.tokenizer,
                           prompt_var_overrides=var_overrides)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(result.text)

    if args.json:
        print(json.dumps({
            "total_chars": result.total_chars,
            "total_tokens": result.total_tokens,
            "rendered_blocks": len(result.blocks),
            "unresolved": result.unresolved,
            "tokenizer_error": result.tokenizer_error,
        }, indent=2, ensure_ascii=False))
    else:
        print_render_report(result, by_block=args.by_block,
                            show_text=args.show and not args.out)
        if args.out:
            print(f"  Rendered text written to {args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
