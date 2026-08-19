# Changelog


## Unreleased

- New search & replace: `preset_replace_text` MCP tool +
  `preset_tools.replace` library module. Regex or plain-string (literal) mode,
  applied to block contents, block titles, category contents, and category
  titles, with `category` / `enabled_only` / `case_sensitive` / `multiline` /
  `dot_all` filters and a `dry_run` preview. Every run passes a validation
  gate first — syntax errors (position + hint), empty-string matches,
  over-broad captures (a single match swallowing ≥60% of a field, reported
  with what it grabbed), invalid group references, duplicate/empty title
  results, match limits, and `$1$1`-style explosive growth — and the file is
  left untouched on rejection. `preset_check_replace` is the read-only
  pre-flight twin (works with or without a preset file).
- Prompt variables: renaming via `preset_update_prompt_variable` now rewrites
  every `{{var::old}}`/`{{getvar::old}}`-family macro reference in all block
  contents (including `{{var::old::ison::keys}}` sub-syntax) and migrates the
  stored prompt-variable value key, so a rename can no longer silently break
  the preset; `rewrite_references=false` restores the old warning-only
  behavior.
- New `preset_render_block` MCP tool + `preset_tools.render.render_block`:
  render a single block in isolation (enabled or disabled) with seeded
  engine-local variables (`variables={"x": 1}` seeds what `{{setvar}}` writes
  and `{{getvar}}` reads) and optional `with_prior_state` to reproduce chained
  `setvar` state from earlier blocks — no more hand-built test harnesses for
  debugging one conditional.
- Validation: unclosed wrapper macros are now errors. `{{if}}` keeps its
  `unclosed-if` code; any other open/close-style macro left unclosed (today
  `{{trim}}`, via the extended `SCOPED_HINT`) reports `unclosed-wrapper`.
  Orphan close tags (`orphan-close`) were already errors. Found three dead
  bare `{{trim}}` macros in ThreadBare's CoT blocks on first run.
- Docs: corrected stale severities in the diagnostics table (unclosed-if,
  empty-macro, else-outside-if, else-if-unsupported, and orphan-close are
  errors, not warnings) and documented the new tool and check.

## 0.1.0 — 2026-08-15

Initial packaged release.

- Python library for editing Lumiverse preset JSON in place:
  block CRUD, line-range editing, sealing, comparison, validation, rendering,
  and character-card field tools.
- 45-tool MCP server (`preset_tools.mcp_server`) exposing the whole library
  over stdio MCP with structured JSON responses.
- Escaping-safe regex script tooling: file-based payloads, automatic repair of
  over/under-escaped patterns and replacements, capture-group reference
  checking, and real JavaScript compilation via Node.js (with an osascript
  fallback on macOS).
- Escaping-safe prompt variable tooling: structured `options` arrays, JSON
  repair for mangled `options_json` strings, default-value coercion checks,
  duplicate-name and unknown-option-default detection.
- Bundled Lumiverse macro reference digest (JSON + Markdown), with optional
  regeneration from a local Lumiverse checkout at server startup.
- Optional tokenizer extra for accurate token counts.
