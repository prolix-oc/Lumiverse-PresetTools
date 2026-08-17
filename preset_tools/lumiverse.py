"""
lumiverse.py — render a preset against the user's *live* Lumiverse install.

The bundled `render.py` is a faithful-but-offline Python port of the macro
engine. It can drift from the real backend, and it can never know about
macros shipped by a newer build. This module closes that gap by shelling out
to the actual engine in a local Lumiverse checkout — the same `bun` trick
`macro_updater.py` uses to extract the live macro registry — so a preset is
rendered with the *exact* code that runs in production, seeded with the
prompt-variable values the author declared and any test overrides you pass.

This is deliberately **on-device**: it imports the backend's own
`src/macros/index.ts` and runs it under `bun`. No HTTP route, no auth, no
running server, no database. The only bits re-implemented inline are the pure
prompt-variable seeding helpers from `prompt-assembly.service.ts`
(`coercePromptVariable` / `resolvePromptVariables` / placements / reorder),
kept as verbatim copies because that module pulls in the entire service graph
(chats, cortex, databank, …) which cannot be imported in isolation.

Public API:
    find_lumiverse_root(path=None) -> Path
    render_preset_live(preset, *, prompt_var_overrides=..., sample=False, ...)
    diff_render(preset, *, ...) -> dict
    available() -> bool

CLI:
    python -m preset_tools.lumiverse preset.json --var name=value --sample
    python -m preset_tools.lumiverse preset.json --diff --sample
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .io import preset_blocks, stored_prompt_vars

# ---------------------------------------------------------------------------
# The Bun host script. Imported modules come straight from the live checkout;
# only the pure prompt-variable helpers are mirrored inline (see module docs).
# ---------------------------------------------------------------------------

_LIVE_SCRIPT = r"""
import { pathToFileURL } from "node:url";
import path from "node:path";

const root = Bun.argv[1];
const payloadPath = Bun.argv[2];
if (!root || !payloadPath) {
  throw new Error("usage: bun -e <script> <backendRoot> <payloadFile>");
}

const baseUrl = pathToFileURL(path.resolve(root) + path.sep);
const { initMacros, buildEnv, registry, evaluate, withPromptBlockContext } =
  await import(new URL("./src/macros/index.ts", baseUrl).href);
const { makeAssistantCharacter } =
  await import(new URL("./src/types/character.ts", baseUrl).href);

initMacros();

const payload = await Bun.file(payloadPath).json();

// --- verbatim ports from src/services/prompt-assembly.service.ts ------------

function clampNumber(value, min, max) {
  let v = value;
  if (typeof min === "number" && v < min) v = min;
  if (typeof max === "number" && v > max) v = max;
  return v;
}

function coercePromptVariable(def, raw) {
  switch (def.type) {
    case "text":
    case "textarea": {
      if (raw === undefined || raw === null) {
        return { rendered: def.defaultValue ?? "", selectedIds: [] };
      }
      return { rendered: String(raw), selectedIds: [] };
    }
    case "number": {
      const fallback = typeof def.defaultValue === "number" ? def.defaultValue : 0;
      const n = raw === undefined || raw === null ? fallback : Number(raw);
      const v = Number.isFinite(n) ? n : fallback;
      return { rendered: clampNumber(v, def.min, def.max), selectedIds: [] };
    }
    case "slider": {
      const fallback = def.defaultValue;
      const n = raw === undefined || raw === null ? fallback : Number(raw);
      const v = Number.isFinite(n) ? n : fallback;
      return { rendered: clampNumber(v, def.min, def.max), selectedIds: [] };
    }
    case "select": {
      const options = def.options ?? [];
      const validIds = new Set(options.map((o) => o.id));
      const fallback = validIds.has(def.defaultValue)
        ? def.defaultValue
        : options[0]?.id ?? "";
      const candidate =
        raw === undefined || raw === null ? fallback : String(raw);
      const selectedId = validIds.has(candidate) ? candidate : fallback;
      const match = options.find((o) => o.id === selectedId);
      return {
        rendered: match?.value ?? "",
        selectedIds: selectedId ? [selectedId] : [],
      };
    }
    case "switch": {
      const fallback = def.defaultValue === 1 ? 1 : 0;
      if (raw === undefined || raw === null) {
        return { rendered: fallback, selectedIds: [] };
      }
      let on = false;
      if (typeof raw === "boolean") on = raw;
      else if (typeof raw === "number") on = raw === 1;
      else {
        const s = String(raw).trim().toLowerCase();
        on = s === "1" || s === "true" || s === "on" || s === "yes";
      }
      return { rendered: on ? 1 : 0, selectedIds: [] };
    }
    case "multiselect": {
      const options = def.options ?? [];
      const validIds = new Set(options.map((o) => o.id));
      let rawIds;
      if (Array.isArray(raw)) {
        rawIds = raw.map((v) => String(v));
      } else if (raw === undefined || raw === null) {
        rawIds = Array.isArray(def.defaultValue) ? def.defaultValue.slice() : [];
      } else if (typeof raw === "string" && raw.length > 0) {
        rawIds = raw.split(",").map((s) => s.trim()).filter(Boolean);
      } else {
        rawIds = [];
      }
      const selectedSet = new Set(rawIds.filter((id) => validIds.has(id)));
      const orderedSelected = options.filter((o) => selectedSet.has(o.id));
      const separator = typeof def.separator === "string" ? def.separator : "\n\n";
      return {
        rendered: orderedSelected.map((o) => o.value).join(separator),
        selectedIds: orderedSelected.map((o) => o.id),
      };
    }
  }
  return { rendered: "", selectedIds: [] };
}

function resolvePromptVariables(env, blocks, presetValues, overrides) {
  const values = {};
  const defaults = {};
  const byBlock = {};
  const defaultsByBlock = {};
  const selections = {};
  const selectionsByBlock = {};

  for (const block of blocks) {
    if (!block.enabled || !block.variables?.length) continue;
    const bucket = presetValues[block.id] ?? {};
    const perBlock = {};
    const perBlockDefaults = {};
    const perBlockSelections = {};
    for (const def of block.variables) {
      if (!def?.name) continue;
      const hasOverride = overrides && Object.prototype.hasOwnProperty.call(overrides, def.name);
      const raw = hasOverride
        ? overrides[def.name]
        : (Object.prototype.hasOwnProperty.call(bucket, def.name) ? bucket[def.name] : undefined);
      const resolved = coercePromptVariable(def, raw);
      perBlock[def.name] = resolved.rendered;
      values[def.name] = resolved.rendered;
      const defaultValue = coercePromptVariable(def, undefined).rendered;
      perBlockDefaults[def.name] = defaultValue;
      defaults[def.name] = defaultValue;
      if (def.type === "multiselect") {
        perBlockSelections[def.name] = resolved.selectedIds;
        selections[def.name] = resolved.selectedIds;
      }
    }
    if (Object.keys(perBlock).length) {
      byBlock[block.id] = perBlock;
      defaultsByBlock[block.id] = perBlockDefaults;
    }
    if (Object.keys(perBlockSelections).length) {
      selectionsByBlock[block.id] = perBlockSelections;
    }
  }

  env.extra.promptVariables = values;
  env.extra.promptVariablesByBlock = byBlock;
  env.extra.promptVariableDefaults = defaults;
  env.extra.promptVariableDefaultsByBlock = defaultsByBlock;
  env.extra.promptVariableSelections = selections;
  env.extra.promptVariableSelectionsByBlock = selectionsByBlock;

  for (const [name, value] of Object.entries(values)) {
    env.variables.local.set(name, String(value));
  }
}

const PROMPT_BLOCK_ROLES = new Set([
  "system", "user", "assistant", "user_append", "assistant_append",
]);
const PROMPT_BLOCK_POSITIONS = new Set([
  "pre_history", "post_history", "in_history",
]);

function isPromptBlockPlacement(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const placement = value;
  return (
    typeof placement.role === "string" &&
    PROMPT_BLOCK_ROLES.has(placement.role) &&
    typeof placement.position === "string" &&
    PROMPT_BLOCK_POSITIONS.has(placement.position) &&
    typeof placement.depth === "number" &&
    Number.isFinite(placement.depth) &&
    placement.depth >= 0
  );
}

function resolvePromptBlockPlacements(blocks, presetValues, overrides) {
  return blocks.map((block) => {
    const binding = block.placementBinding;
    if (
      !binding ||
      typeof binding.variableId !== "string" ||
      !binding.variableId ||
      !binding.options ||
      typeof binding.options !== "object" ||
      Array.isArray(binding.options)
    ) {
      return block;
    }
    const selector = block.variables?.find(
      (v) => v.id === binding.variableId && v.type === "select",
    );
    if (!selector) return block;
    const bucket = presetValues[block.id] ?? {};
    const hasOverride = overrides && Object.prototype.hasOwnProperty.call(overrides, selector.name);
    const raw = hasOverride ? overrides[selector.name] : bucket[selector.name];
    const selectedId = coercePromptVariable(selector, raw).selectedIds[0];
    if (!selectedId || !Object.prototype.hasOwnProperty.call(binding.options, selectedId)) {
      return block;
    }
    const placement = binding.options[selectedId];
    if (!isPromptBlockPlacement(placement)) return block;
    return {
      ...block,
      role: placement.role,
      position: placement.position,
      depth: Math.floor(placement.depth),
    };
  });
}

function isAppendRole(role) {
  return role === "user_append" || role === "assistant_append";
}

function reorderBlocksByPosition(blocks) {
  const chatHistoryIdx = blocks.findIndex((b) => b.marker === "chat_history");
  if (chatHistoryIdx < 0) return blocks;

  const moveToAfter = new Set();
  const moveToBefore = new Set();

  for (let i = 0; i < blocks.length; i++) {
    if (i === chatHistoryIdx) continue;
    const b = blocks[i];
    if (b.marker || isAppendRole(b.role)) continue;
    if (
      i < chatHistoryIdx &&
      (b.position === "post_history" || b.position === "in_history")
    ) {
      moveToAfter.add(i);
    } else if (i > chatHistoryIdx && b.position === "pre_history") {
      moveToBefore.add(i);
    }
  }

  if (moveToAfter.size === 0 && moveToBefore.size === 0) return blocks;

  const result = [];
  for (let i = 0; i < chatHistoryIdx; i++) {
    if (!moveToAfter.has(i)) result.push(blocks[i]);
  }
  for (const idx of moveToBefore) result.push(blocks[idx]);
  result.push(blocks[chatHistoryIdx]);
  for (const idx of moveToAfter) result.push(blocks[idx]);
  for (let i = chatHistoryIdx + 1; i < blocks.length; i++) {
    if (!moveToBefore.has(i)) result.push(blocks[i]);
  }
  return result;
}

const STRUCTURAL_MARKERS = new Set([
  "chat_history",
  "world_info_before",
  "world_info_after",
  "char_description",
  "char_personality",
  "persona_description",
  "scenario",
  "dialogue_examples",
]);

const MARKER_TO_MACRO = {
  char_description: "{{description}}",
  char_personality: "{{personality}}",
  persona_description: "{{persona}}",
  scenario: "{{scenario}}",
  dialogue_examples: "{{mesExamples}}",
};

function normalizePromptBlockText(content) {
  return content.replace(/\n{3,}/g, "\n\n").trim();
}

// --- environment construction ----------------------------------------------

function makeSampleCharacter() {
  return {
    id: "sample-stella",
    name: "Stella",
    avatar_path: null,
    image_id: null,
    description: "A sharp-tongued starship mechanic with grease under her nails and a soft spot she'd never admit to.",
    personality: "Wry, loyal, allergic to sentiment.",
    scenario: "The two of you are stranded dockside waiting on a part that may never come.",
    first_mes: "You're late.",
    mes_example: "",
    creator: "studio",
    creator_notes: "",
    system_prompt: "",
    post_history_instructions: "",
    folder: "",
    tags: [],
    alternate_greetings: [],
    extensions: { version: "1.0" },
    library_scope: "mine",
    created_at: 0,
    updated_at: 0,
  };
}

function makeSamplePersona() {
  return {
    id: "sample-persona",
    name: "Alex",
    description: "Alex — a drifter with more debts than answers.",
    metadata: {},
    is_narrator: false,
  };
}

function resolveCharacter() {
  if (payload.character !== undefined && payload.character !== null) {
    return payload.character;
  }
  if (payload.sample) return makeSampleCharacter();
  return makeAssistantCharacter();
}

function resolvePersona() {
  if (payload.persona !== undefined) return payload.persona;
  if (payload.sample) return makeSamplePersona();
  return null;
}

function resolveChat() {
  if (payload.sample) {
    return { id: "sample-chat", character_id: "sample-stella", name: "", metadata: {} };
  }
  return { id: "", character_id: null, name: "", metadata: {} };
}

function resolveMessages() {
  if (payload.sample) {
    return [
      { id: "0", is_user: true, name: "Alex", content: "What's taking so long?", swipes: ["What's taking so long?"], swipe_id: 0 },
      { id: "1", is_user: false, name: "Stella", content: "\"Hand me the wrench,\" she said.", swipes: ["\"Hand me the wrench,\" she said."], swipe_id: 0 },
    ];
  }
  return [];
}

const env = buildEnv({
  character: resolveCharacter(),
  persona: resolvePersona(),
  chat: resolveChat(),
  messages: resolveMessages(),
  generationType: "normal",
  connection: payload.sample ? { model: "claude-opus-4-8" } : null,
  commit: false,
});

// --- render -----------------------------------------------------------------

const blocks = Array.isArray(payload.blocks) ? payload.blocks : [];
for (let i = 0; i < blocks.length; i++) blocks[i]._origIndex = i;

const presetValues = (payload.promptVariables && typeof payload.promptVariables === "object")
  ? payload.promptVariables
  : {};
const overrides = (payload.overrides && typeof payload.overrides === "object")
  ? payload.overrides
  : {};

resolvePromptVariables(env, blocks, presetValues, overrides);
const effectiveBlocks = resolvePromptBlockPlacements(blocks, presetValues, overrides);
const ordered = reorderBlocksByPosition(effectiveBlocks);

const outBlocks = [];
const chunks = [];
const diagnostics = [];
let totalChars = 0;

for (const block of ordered) {
  if (!block.enabled) continue;
  const role = block.role || "system";
  let content;
  if (block.marker && STRUCTURAL_MARKERS.has(block.marker)) {
    if (MARKER_TO_MACRO[block.marker]) {
      content = MARKER_TO_MACRO[block.marker];
    } else {
      continue;
    }
  } else {
    content = block.content || "";
  }
  if (!content) continue;

  const res = await withPromptBlockContext(env, block, () =>
    evaluate(content, env, registry, {
      phase: "prompt",
      sourceOwner: "host",
      sourceHint: "prompt_source:preset_block",
    }),
  );
  const text = normalizePromptBlockText(res.text);
  if (!text) continue;

  const index = typeof block._origIndex === "number" ? block._origIndex : 0;
  const record = {
    index,
    name: block.name || "#" + index,
    role,
    marker: block.marker ?? null,
    text,
    chars: text.length,
  };
  outBlocks.push(record);
  chunks.push(text);
  totalChars += text.length;
  for (const d of res.diagnostics ?? []) {
    diagnostics.push({ block: record.name, block_index: index, ...d });
  }
}

console.log(JSON.stringify({
  backendRoot: path.resolve(root),
  blocks: outBlocks,
  text: chunks.join("\n\n"),
  totalChars,
  diagnostics,
}, null, 2));
"""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class LiveBlock:
    index: int
    name: str
    role: str
    marker: Optional[str]
    text: str
    chars: int
    tokens: Optional[int] = None


@dataclass
class LiveRenderResult:
    text: str
    blocks: list = field(default_factory=list)
    total_chars: int = 0
    total_tokens: Optional[int] = None
    diagnostics: list = field(default_factory=list)
    tokenizer_error: Optional[str] = None
    backend_root: str = ""


# ---------------------------------------------------------------------------
# Root discovery
# ---------------------------------------------------------------------------

def _looks_like_lumiverse(path: Path) -> bool:
    return (path / "src" / "macros" / "index.ts").exists()


def find_lumiverse_root(path: Optional[str] = None) -> Path:
    """Locate the local Lumiverse checkout.

    Resolution order:
      1. `path` (a directory, or a file whose ancestors are searched)
      2. the `PRESET_TOOLS_LUMIVERSE_ROOT` environment variable
      3. walking the parents of the current working directory
    """
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path).expanduser())
    env_root = os.environ.get("PRESET_TOOLS_LUMIVERSE_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.append(Path.cwd())

    for cand in candidates:
        cand = cand.resolve()
        if _looks_like_lumiverse(cand):
            return cand
        if cand.is_file():
            cand = cand.parent
        for parent in [cand, *cand.parents]:
            if _looks_like_lumiverse(parent):
                return parent

    raise FileNotFoundError(
        "could not locate a Lumiverse checkout. Pass `root=`, set "
        "PRESET_TOOLS_LUMIVERSE_ROOT, or run from inside the checkout."
    )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _bun() -> str:
    return os.environ.get("PRESET_TOOLS_BUN", "bun")


def available(root: Optional[str] = None, bun: Optional[str] = None) -> bool:
    """True when a live Lumiverse checkout and a `bun` binary are both found."""
    if shutil.which(bun or _bun()) is None:
        return False
    try:
        find_lumiverse_root(root)
    except FileNotFoundError:
        return False
    return True


def render_preset_live(
    preset: dict,
    *,
    prompt_var_overrides: Optional[dict] = None,
    sample: bool = False,
    character: Optional[dict] = None,
    persona: Optional[dict] = None,
    root: Optional[str] = None,
    path: Optional[str] = None,
    bun: Optional[str] = None,
    timeout: int = 120,
    tokenize: bool = False,
    tokenizer_path: Optional[str] = None,
) -> LiveRenderResult:
    """Render a preset with the live Lumiverse macro engine.

    `prompt_var_overrides` maps a declared prompt-variable name to a test value
    (e.g. ``{"scene_card_on": 1, "tags": ["slow-burn", "banter"]}``). Each value
    is coerced exactly as the backend coerces a user-supplied value for that
    variable's type, then seeded before any block renders — so conditionals and
    macros that read it (`{{var::name}}`, `{{getvar::name}}`, `{{.name}}`) see
    the overridden value.

    `sample=True` supplies a realistic character/chat (Stella/Alex) so
    identity/persona macros resolve; otherwise an empty assistant context is
    used and those macros render to empty strings, exactly as the live engine
    treats a bare context.
    """
    backend_root = find_lumiverse_root(root or path)
    bun_bin = bun or _bun()
    if shutil.which(bun_bin) is None:
        raise FileNotFoundError(f"bun not found on PATH (looked for {bun_bin!r})")

    payload = {
        "blocks": preset_blocks(preset),
        "promptVariables": stored_prompt_vars(preset),
        "overrides": prompt_var_overrides or {},
        "sample": bool(sample),
    }
    if character is not None:
        payload["character"] = character
    if persona is not None:
        payload["persona"] = persona

    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", encoding="utf-8", delete=False
    ) as f:
        json.dump(payload, f, ensure_ascii=False)
        payload_path = f.name

    try:
        proc = subprocess.run(
            [bun_bin, "-e", _LIVE_SCRIPT, str(backend_root), payload_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"live render timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"bun not found: {bun_bin}") from exc
    finally:
        try:
            os.unlink(payload_path)
        except OSError:
            pass

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"live render failed: {detail}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"live render produced invalid JSON: {exc} (stdout: {proc.stdout[:400]!r})"
        ) from exc

    result = LiveRenderResult(
        text=data.get("text", ""),
        blocks=[LiveBlock(**b) for b in data.get("blocks", [])],
        total_chars=data.get("totalChars", 0),
        diagnostics=data.get("diagnostics", []),
        backend_root=data.get("backendRoot", str(backend_root)),
    )

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


# ---------------------------------------------------------------------------
# Consistency check (Python port vs live engine)
# ---------------------------------------------------------------------------

def diff_render(
    preset: dict,
    *,
    prompt_var_overrides: Optional[dict] = None,
    sample: bool = True,
    root: Optional[str] = None,
    path: Optional[str] = None,
    bun: Optional[str] = None,
    timeout: int = 120,
) -> dict:
    """Render a preset twice — offline (Python port) and live — and diff them.

    Returns a dict with ``backend_root``, ``identical``, ``matched_blocks``,
    ``divergent_blocks``, and a per-block ``diffs`` list of
    ``{index, name, identical, python_text, live_text}``. Identity/persona/chat
    and dice macros are expected to differ (the live engine has real names and
    unseeded randomness); app/context macros (``{{lumia*}}``,
    ``{{reasoningPrefix}}``, chat-history turn boundaries) resolve to empty in a
    bare context on the live side while the offline port keeps them literal.
    Blocks are compared by their original preset index, not render order (the
    offline port sorts by position while the live engine reorders relative to
    the ``chat_history`` marker).
    """
    from .render import RenderEnv, render_preset

    backend_root = find_lumiverse_root(root or path)

    env = RenderEnv.sample() if sample else RenderEnv.empty()
    python = render_preset(
        preset, env, tokenize=False, prompt_var_overrides=prompt_var_overrides or {}
    )
    live = render_preset_live(
        preset,
        prompt_var_overrides=prompt_var_overrides,
        sample=sample,
        root=str(backend_root),
        bun=bun,
        timeout=timeout,
    )

    python_by_idx = {rb.index: rb for rb in python.blocks}
    live_by_idx = {rb.index: rb for rb in live.blocks}

    diffs: list[dict] = []
    divergent = 0
    matched = 0
    for idx in sorted(set(python_by_idx) | set(live_by_idx)):
        p = python_by_idx.get(idx)
        l = live_by_idx.get(idx)
        p_text = p.text.strip() if p else ""
        l_text = l.text.strip() if l else ""
        identical = p_text == l_text
        if identical:
            matched += 1
        else:
            divergent += 1
        diffs.append({
            "index": idx,
            "name": (p.name if p else l.name),
            "identical": identical,
            "python_text": p.text if p else None,
            "live_text": l.text if l else None,
        })

    return {
        "backend_root": str(backend_root),
        "identical": divergent == 0,
        "matched_blocks": matched,
        "divergent_blocks": divergent,
        "diffs": [d for d in diffs if not d["identical"]],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    import argparse
    import sys

    from .io import load

    p = argparse.ArgumentParser(
        prog="preset_tools.lumiverse",
        description="Render a preset with the live Lumiverse engine (on-device).",
    )
    p.add_argument("file", help="preset JSON file")
    p.add_argument("--var", action="append", metavar="NAME=VALUE", default=[],
                   help="set a declared prompt variable (repeatable)")
    p.add_argument("--sample", action="store_true",
                   help="use a realistic sample character/chat")
    p.add_argument("--root", metavar="DIR",
                   help="path to the Lumiverse checkout (default: auto-detect)")
    p.add_argument("--diff", action="store_true",
                   help="compare the Python port against the live engine")
    p.add_argument("--show", action="store_true", help="print rendered text")
    p.add_argument("--by-block", action="store_true", help="per-block table")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.add_argument("--tokenize", action="store_true", help="tokenize the output")
    args = p.parse_args(argv)

    overrides: dict = {}
    for it in args.var:
        if "=" not in it:
            print(f"error: expected name=value, got {it!r}", file=sys.stderr)
            return 2
        k, v = it.split("=", 1)
        overrides[k.strip()] = v

    try:
        preset = load(args.file)
    except FileNotFoundError:
        print(f"error: file not found: {args.file}", file=sys.stderr)
        return 2

    try:
        if args.diff:
            result = diff_render(preset, prompt_var_overrides=overrides,
                                 sample=args.sample, root=args.root, path=args.file)
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(f"\n=== Live vs offline render: {args.file} ===")
                print(f"  backend: {result['backend_root']}")
                print(f"  matched: {result['matched_blocks']}  divergent: {result['divergent_blocks']}")
                for d in result["diffs"]:
                    print(f"\n  [{d['index']}] {d['name']}  <divergent>")
                    _print_side_by_side(d["python_text"], d["live_text"])
            return 0

        live = render_preset_live(preset, prompt_var_overrides=overrides,
                                  sample=args.sample, root=args.root,
                                  path=args.file, tokenize=args.tokenize)
        if args.json:
            print(json.dumps({
                "backend_root": live.backend_root,
                "total_chars": live.total_chars,
                "total_tokens": live.total_tokens,
                "rendered_blocks": len(live.blocks),
                "diagnostics": live.diagnostics,
                "blocks": [
                    {"index": b.index, "name": b.name, "role": b.role,
                     "marker": b.marker, "chars": b.chars, "tokens": b.tokens}
                    for b in live.blocks
                ],
            }, indent=2, ensure_ascii=False))
        else:
            print(f"\n=== Live render: {args.file} ===")
            print(f"  backend: {live.backend_root}")
            print(f"  rendered blocks: {len(live.blocks)}")
            print(f"  total chars: {live.total_chars}")
            if live.total_tokens is not None:
                print(f"  real tokens: {live.total_tokens}")
            if args.by_block:
                print(f"\n  {'#':>3}  {'name':<34} {'role':<12} {'chars':>6}")
                for b in live.blocks:
                    print(f"  {b.index:>3}  {b.name[:34]:<34} {b.role[:12]:<12} {b.chars:>6}")
            if live.diagnostics:
                print(f"\n  diagnostics ({len(live.diagnostics)}):")
                for d in live.diagnostics[:20]:
                    print(f"    • [{d.get('level', '?')}] {d.get('message', '')}")
            if args.show:
                print("\n" + "=" * 68)
                print(live.text)
                print("=" * 68)
        return 0
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _print_side_by_side(py_text, live_text) -> None:
    import difflib
    py_lines = (py_text or "").splitlines()
    live_lines = (live_text or "").splitlines()
    for line in difflib.unified_diff(
        py_lines, live_lines,
        fromfile="python", tofile="live", lineterm="",
    ):
        print(f"      {line}")


if __name__ == "__main__":
    raise SystemExit(main())
