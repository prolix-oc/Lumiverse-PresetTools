# Changelog

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
