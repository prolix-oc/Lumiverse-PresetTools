# preset-tools

A Python library and [Model Context Protocol](https://modelcontextprotocol.io)
(MCP) server for editing **Lumiverse preset JSON** safely —
blocks, prompt variables, and embedded regex scripts — designed so that LLM
agents can do the editing without corrupting the file.

## Why this exists

Editing backslash-heavy regex patterns, giant HTML replacement blobs, and
JSON-in-JSON option strings through an MCP tool call means surviving several
layers of escaping. LLMs routinely get this wrong — doubled backslashes,
`/pattern/flags` literals, over-escaped quotes, Python-style `(?P<name>)`
groups — and nothing used to catch it before the file was saved.

This package is stout about that by default and transparent about it:

- **File-based payloads.** `regex_create_script` / `regex_update_script` /
  variable tools accept `*_file` paths (paths to `.txt`/`.json`/`.html` files)
  so big or escape-sensitive content never has to round-trip through JSON
  string escaping at all.
- **Auto-repair with receipts.** Over-escaped backslashes, literal delimiters,
  smart quotes, mangled JSON payloads, and Python-isms are repaired
  automatically, and every repair is reported in the response's
  `diagnostics`.
- **Real validation.** Patterns are compiled with an actual JavaScript engine
  (Node.js, with an osascript fallback on macOS), capture-group references
  (`$<name>`, `$1`) are checked against the pattern's groups, and variable
  defaults are checked against their options.
- **Strict gates.** With `strict=true` (the default), a failed validation
  leaves the file untouched and tells you why.

## What's inside

- **`preset_tools`** — an importable Python library (see the quick start below).
- **45 MCP tools** over stdio, grouped as:

| Group | Tools |
|---|---|
| Preset blocks | `preset_audit`, `preset_list_blocks`, `preset_find_block`, `preset_show_block`, `preset_get_section`, `preset_get_block_lines`, `preset_get_block_line_range`, `preset_insert_block`, `preset_modify_block`, `preset_edit_block_lines`, `preset_edit_block_line_range`, `preset_delete_block`, `preset_rename_block`, `preset_toggle_block` |
| Prompt variables | `preset_insert_prompt_variable`, `preset_list_prompt_variables`, `preset_update_prompt_variable`, `preset_remove_prompt_variable`, `preset_variable_report` |
| Regex scripts | `regex_list_scripts`, `regex_get_script`, `regex_create_script`, `regex_update_script`, `regex_delete_script`, `regex_validate`, `regex_check_pattern` |
| Validation & compare | `preset_validate`, `preset_compare`, `preset_check_seals`, `preset_set_seal`, `preset_mass_seal` |
| Rendering & tokens | `preset_render`, `preset_extract_macros`, `preset_macro_reference`, `preset_token_count`, `preset_count_tokens`, `preset_dump_enabled` |
| Character cards | `character_card_read`, `character_card_get_summary`, `character_card_get_field`, `character_card_field_stats`, `character_card_set_field`, `character_card_set_fields`, `character_card_validate` |

Full tool documentation lives in [`preset_tools/README.md`](preset_tools/README.md),
and the bundled Lumiverse macro digest in
[`preset_tools/macro_reference.md`](preset_tools/macro_reference.md).

## Requirements

- Python 3.10+
- `mcp` and `pydantic` (installed automatically)
- Optional: [Node.js](https://nodejs.org) on `PATH` for full JavaScript regex
  compilation. Without it the server falls back to `osascript` (JavaScript for
  Automation) on macOS, and to structural linting elsewhere.
- Optional: `tokenizers` (`pip install "preset-tools[tokenizer]"`) for accurate
  token counts.

## Install

From a checkout:

```bash
cd /path/to/preset-tools
python3 -m venv .venv
.venv/bin/pip install .
# console script:
.venv/bin/preset-tools-mcp
# or module form:
.venv/bin/python -m preset_tools.mcp_server   # `python -m preset_tools` also works
```

With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install /path/to/preset-tools          # installs the preset-tools-mcp command
uvx --from git+https://github.com/prolix-oc/Lumiverse-PresetTools preset-tools-mcp
```

From PyPI (once published):

```bash
pip install preset-tools
```

## Using as a Python library

```python
from preset_tools import load, save, get_block_lines, modify_block_lines

preset = load("My Preset.json")
print(get_block_lines(preset, "Voice Shaping", 10, 14)["lines"])
modify_block_lines(preset, "Voice Shaping", 12, end_line=13, new_content="...")
save(preset, "My Preset.json")   # writes UTF-8 with literal Unicode preserved
```

## Configuration

| Environment variable | Purpose |
|---|---|
| `PRESET_TOOLS_WORKSPACE` | Root directory that relative preset paths resolve against. Defaults to the server's working directory. Absolute paths always work. |
| `PRESET_TOOLS_JS` | Override the JavaScript engine: a path to a `node` binary, or `osascript` to force the macOS fallback. |
| `PRESET_TOOLS_MACRO_DIR` | Directory to read `macro_reference.json` / `macro_reference.md` from (defaults to the bundled copies). |
| `PRESET_TOOLS_LUMIVERSE_ROOT` | Optional path to a local Lumiverse checkout; regenerates the macro digest from its live registry at startup and enables `preset_render`'s `live=True` (on-device ground-truth rendering via `bun`). |

> **Tip:** point `PRESET_TOOLS_WORKSPACE` at a dedicated presets directory
> rather than your home directory. The server can read and write any JSON file
> you give it a path to — keep its blast radius intentional.

## Adding the server to your harness

Everything below assumes the venv install from the previous section, with the
repo at `/path/to/preset-tools` and your presets in `/path/to/presets`.
Substitute your own paths.

### Claude Code

```bash
claude mcp add preset-tools -s user \
  --env PRESET_TOOLS_WORKSPACE=/path/to/presets \
  -- /path/to/preset-tools/.venv/bin/preset-tools-mcp
```

Or directly from git once pushed:

```bash
claude mcp add preset-tools -s user \
  --env PRESET_TOOLS_WORKSPACE=/path/to/presets \
  -- uvx --from git+https://github.com/prolix-oc/Lumiverse-PresetTools preset-tools-mcp
```

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "preset-tools": {
      "command": "/path/to/preset-tools/.venv/bin/preset-tools-mcp",
      "env": {
        "PRESET_TOOLS_WORKSPACE": "/path/to/presets"
      }
    }
  }
}
```

### ZCode

User scope (all workspaces) — `~/.zcode/cli/config.json` — or workspace scope
(shared with a repo) — `<repo>/.zcode/config.json`. Both use the same shape and
auto-connect at session start:

```json
{
  "mcp": {
    "servers": {
      "preset-tools": {
        "command": "/path/to/preset-tools/.venv/bin/preset-tools-mcp",
        "env": {
          "PRESET_TOOLS_WORKSPACE": "/path/to/presets"
        }
      }
    }
  }
}
```

(`~/.agents/mcp.json` with a top-level `mcpServers` key also works as a
compatibility fallback at user scope.)

### OpenCode

This repo ships a portable [`opencode.json`](opencode.json) at its root, so
OpenCode picks the server up automatically when started inside the repo
(creates `.venv` at the repo root first). For a global setup in
`~/.config/opencode/opencode.json`:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "preset_tools": {
      "type": "local",
      "command": ["/path/to/preset-tools/.venv/bin/python", "-m", "preset_tools.mcp_server"],
      "environment": {
        "PRESET_TOOLS_WORKSPACE": "/path/to/presets"
      },
      "enabled": true,
      "timeout": 10000
    }
  }
}
```

Verify with `opencode mcp list`.

### Cursor

Global (`~/.cursor/mcp.json`) or per-project (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "preset-tools": {
      "command": "/path/to/preset-tools/.venv/bin/preset-tools-mcp",
      "env": {
        "PRESET_TOOLS_WORKSPACE": "/path/to/presets"
      }
    }
  }
}
```

### Any other stdio MCP client

Launch the server with no arguments over stdio:

- command: `preset-tools-mcp` (or `python -m preset_tools.mcp_server`)
- args: none
- env: any of the variables from the table above

## Development

```bash
cd /path/to/preset-tools
python3 -m venv .venv && .venv/bin/pip install -e ".[tokenizer]"
.venv/bin/python -m unittest discover -s tests -v
```

Tests are stdlib `unittest`, fully self-contained (`tests/fixtures/`), and
skip engine-dependent cases when no JavaScript engine is available.

Regenerate the macro digest from a
[Lumiverse](https://github.com/prolix-oc/Lumiverse) checkout:

```bash
python3 -m preset_tools.macro_updater /path/to/Lumiverse preset_tools/macro_reference.json
```

## Publishing this repo

One-time housekeeping:

1. Confirm the copyright line in `LICENSE.md`.
2. Bump `version` in `pyproject.toml` and add a `CHANGELOG.md` entry per release.

Push to GitHub:

```bash
git remote add origin git@github.com:prolix-oc/Lumiverse-PresetTools.git
git push -u origin main
```

Build and upload to PyPI:

```bash
python3 -m pip install --upgrade build twine
python3 -m build
twine check dist/*
twine upload dist/*
git tag v0.1.0 && git push --tags
```

(Optional dry run: `twine upload --repository-url https://test.pypi.org/legacy/ dist/*`.)

## License

Copyright © 2025–2026 Darran Hall (Prolix OCs). Licensed under the
**Lumiverse Community License 2.0** — see [`LICENSE.md`](LICENSE.md).

In short: you may use, run, and modify this software for personal, non-profit,
and internal use. You may **not** redistribute it, publish it, or host it
publicly; you may not use it commercially beyond internal use; improvements
must be contributed back to the Lumiverse project; and this source code may
not be used as AI/ML training data. The Licensor (the Lumiverse founder and
organization) retains all distribution rights.
