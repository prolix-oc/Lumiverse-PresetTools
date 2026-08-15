# preset_tools — Lumiverse preset editing utilities

This module exists because editing Lumiverse preset JSON files by hand (or via the Edit tool) is fragile. Three recurring problems made these utilities necessary:

1. **Unicode corruption** — Python's default `json.dump` escapes em-dashes (`—`), smart quotes (`'`), and other non-ASCII characters to `\uXXXX` sequences. This corrupts presets that rely on literal Unicode for stylistic consistency.
2. **Two preset schemas** — ThreadBare stores blocks at `preset['blocks']`. Lucid Loom stores them at `preset['preset']['blocks']`. Code that hardcodes either path breaks on the other.
3. **String-based edits fail on smart quotes** — The Edit tool's old_string matching frequently fails because em-dashes and smart quotes look identical but use different code points. Programmatic edits via `get_block_lines` + `modify_block_lines` (or whole-block `modify_block`) sidestep this entirely.

## When to use these tools vs. the Edit tool

| Situation | Tool |
|---|---|
| Tweaking a few lines in a long block | `get_block_lines` + `modify_block_lines` |
| Tweaking a few ASCII-safe words with a unique match | `Edit` |
| Replacing entire block content | `modify_block` |
| Adding new blocks anywhere | `insert_block` |
| Deleting blocks | `delete_block` |
| Bulk audit / token counting | `audit`, `token_count` |
| Comparing two preset versions | `diff_block_counts`, `side_by_side` |
| Anything involving em-dashes, smart quotes, or CJK | always `preset_tools` |

## Quick start

```python
from preset_tools import (
    audit,
    get_block_lines,
    insert_block,
    load,
    modify_block_lines,
    new_block,
    save,
)

preset = load('ThreadBare 1.0.json')
audit(preset)                              # visual overview

# Read a numbered slice from a long block
snippet = get_block_lines(preset, 'Voice Shaping', start_line=8, end_line=12)
for row in snippet['lines']:
    print(row['line'], row['text'])

# Replace just those lines
modify_block_lines(
    preset,
    'Voice Shaping',
    start_line=10,
    end_line=11,
    new_content='Rewritten line 10.\nRewritten line 11.',
)

# Insert a new block after another
nb = new_block(
    name='My New Block',
    content='<my_tag>\nInstructions here.\n</my_tag>',
    enabled=True,
)
insert_block(preset, nb, after='Anti-Echo')

# Save (CRITICAL — preserves Unicode)
save(preset, 'ThreadBare 1.0.json')
```

## MCP server

`preset_tools` also ships as a Model Context Protocol (MCP) server, so LLM clients
(opencode, Claude Desktop, etc.) can call the utilities directly.

### Setup

```bash
# Create the virtual environment (Python 3.10+ required)
python3.10 -m venv .venv
source .venv/bin/activate

# Install the package
pip install -e .

# Optional: install real Claude tokenizer support
pip install -e ".[tokenizer]"
```

### Run

```bash
# stdio transport (for local MCP clients)
python -m preset_tools.mcp_server

# or the installed console script
preset-tools-mcp
```

### Configure in OpenCode

OpenCode uses a top-level `mcp` key (not `mcpServers`). You can configure it globally in `~/.config/opencode/opencode.json` (or `opencode.jsonc`), **or project-only by placing an `opencode.json` file in this project root**.

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "preset_tools": {
      "type": "local",
      "command": [
        "/path/to/preset-tools/.venv/bin/python",
        "-m",
        "preset_tools.mcp_server"
      ],
      "cwd": "/path/to/preset-tools",
      "environment": {
        "PRESET_TOOLS_WORKSPACE": "/path/to/preset-tools"
      },
      "enabled": true
    }
  }
}
```

Or use the installed console script:

```jsonc
{
  "mcp": {
    "preset_tools": {
      "type": "local",
      "command": ["/path/to/preset-tools/.venv/bin/preset-tools-mcp"],
      "cwd": "/path/to/preset-tools",
      "enabled": true
    }
  }
}
```

**Key points for OpenCode:**

- `command` is an array of strings.
- `cwd` sets the server's working directory; relative preset paths are resolved against this (or against `PRESET_TOOLS_WORKSPACE`).
- `environment` sets env vars for the server process. Useful variables:
  - `PRESET_TOOLS_WORKSPACE` — root directory for relative preset paths.
  - `PRESET_TOOLS_MACRO_DIR` — directory containing `macro_reference.json` and `macro_reference.md` if you want the server to read macro docs from a custom location. See [Targeting a Live Lumiverse Install](#targeting-a-live-lumiverse-install) below.
  - `PRESET_TOOLS_LUMIVERSE_ROOT` — absolute path to your local Lumiverse checkout. When set, the MCP server will automatically regenerate the macro reference on startup and serve it from a temporary directory.
- After saving, run `opencode mcp list` to verify the server starts.
- You can disable the whole server with `"enabled": false`, or toggle its tools globally with `"tools": { "preset_tools_*": false }`.
- To enable only for a specific agent, disable globally and then enable in that agent's `tools` block.

#### Project-only config

This repo now includes an `opencode.json` in its root that enables the MCP only when OpenCode is running inside this project. OpenCode merges it with your global config and project settings take precedence. The paths are relative to the project root, so it is portable across machines as long as `.venv` exists at the project root.

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "preset_tools": {
      "type": "local",
      "command": [
        ".venv/bin/python",
        "-m",
        "preset_tools.mcp_server"
      ],
      "cwd": ".",
      "environment": {
        "PRESET_TOOLS_WORKSPACE": "."
      },
      "enabled": true,
      "timeout": 10000
    }
  },
  "tools": {
    "preset_tools_*": true
  }
}
```

### Configure in Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "preset_tools": {
      "command": "/path/to/preset-tools/.venv/bin/python",
      "args": ["-m", "preset_tools.mcp_server"]
    }
  }
}
```

Set the working directory of the server to your project root, or set the
`PRESET_TOOLS_WORKSPACE` environment variable. Relative preset paths are
resolved against that workspace root. Absolute paths are also accepted, so you
can reference presets outside the workspace directory.

### Available tools

| Tool | Purpose |
|---|---|
| `preset_audit` | Structural overview with block counts, enabled state, markers |
| `preset_list_blocks` | List blocks with words/chars/enabled/marker |
| `preset_get_block_lines` | Inspect numbered lines from a start line onward |
| `preset_get_block_line_range` | Preferred way to inspect an exact numbered line range |
| `preset_find_block` | Get a single block by name |
| `preset_show_block` | Pretty-print a block's content |
| `preset_find_blocks_referencing` | Find blocks containing a substring |
| `preset_get_section` | Get all blocks under a category marker |
| `preset_extract_macros` | List `{{...}}` macros used in a block |
| `preset_token_count` | Estimate tokens (chars // 4) |
| `preset_count_tokens` | Count real Claude tokens (needs `tokenizers`) |
| `preset_validate` | Macro syntax + variable-flow checker |
| `preset_variable_report` | Per-variable read/write/check map |
| `preset_render` | Render macros and tokenize the final prompt |
| `preset_compare` | Compare two presets block-by-block |
| `preset_edit_block_lines` | Edit a line, or a range if you explicitly provide `end_line` |
| `preset_edit_block_line_range` | Preferred way to replace an exact numbered line range and save |
| `preset_modify_block` | Replace a block's content and save |
| `preset_insert_block` | Add a new block and save |
| `preset_delete_block` | Remove a block and save |
| `preset_rename_block` | Rename a block and save |
| `preset_toggle_block` | Enable/disable a block and save |
| `preset_dump_enabled` | Write enabled blocks to a text file |
| `preset_insert_prompt_variable` | Add a prompt variable definition to a block and optionally inject `{{var::name}}` into its content |
| `preset_remove_prompt_variable` | Remove a prompt variable definition from a block |
| `preset_macro_reference` | Look up Lumiverse macro purpose, aliases, args, and usage |
| `regex_list_scripts` | List embedded or standalone Lumiverse regex scripts |
| `regex_get_script` | Read one complete regex script by `script_id` or exact name |
| `regex_validate` | Validate regex fields, JavaScript flags, actions, and unique IDs |
| `regex_create_script` | Add a regex to a preset or create/add to a standalone export |
| `regex_update_script` | Patch selected fields without replacing the rest of the script |
| `regex_delete_script` | Remove a regex from a preset or standalone export |

All tools accept file paths relative to `PRESET_TOOLS_WORKSPACE` (or the
server's working directory) as well as absolute paths. Write tools modify the
JSON and save it with Unicode preserved.

For exact range work, prefer the range-specific pair:

1. `preset_get_block_line_range`
2. `preset_edit_block_line_range`

Use `preset_get_block_lines` when you want "from this line onward", and
`preset_edit_block_lines` when you intentionally want single-line editing or a
fallback tool with optional `end_line`.

Keep `preset_find_block`, `preset_show_block`, and `preset_modify_block` for
whole-block inspection or replacement.

### Regex script editing

Regex tools understand both Lumiverse storage shapes automatically:

- Presets store scripts at `extensions.regex_scripts`.
- Standalone exports use `{ "version": 1, "type": "lumiverse_regex_scripts", "scripts": [...] }`.

To add to an existing preset or export, call `regex_create_script` with the
path plus `name`, `script_id`, and the two payloads (`find_regex` /
`replace_string`). The default `container="auto"` detects the file shape. To
create a new standalone JSON file, set `container="standalone"` explicitly.
New scripts receive the complete modern field set used by `ThreadBare.json`,
including `scope_id`, depth limits, `trim_strings`, `run_on_edit`, `folder`,
and `metadata`. Supply less-common values such as `actions` through the
structured `options` object.

Use `regex_update_script` for partial edits. Its `updates` object can contain
any Lumiverse regex field, so long replacement HTML and interactive `actions`
can be changed without disturbing unrelated settings. `remove_fields` deletes
optional fields entirely. All writes preserve literal Unicode.

#### Escaping-safe payloads

Regex payloads are the hardest thing for an LLM to pass through a JSON tool
call — patterns are full of backslashes and replacements are full of quotes —
so the regex tools are built to survive the common mistakes:

- **File-based payloads.** Write the pattern or replacement HTML to a
  workspace file first, then pass `find_regex_file` / `replace_string_file`
  (create and update tools both accept them). This bypasses JSON escaping
  entirely and is the recommended route for large card HTML. Pattern files
  are whitespace-trimmed; replacement files are read verbatim.
- **Automatic repairs** (`repair_escapes=true`, the default, with every
  repair reported in the returned `diagnostics`):
  `/.../flags` regex literals are stripped and their flags merged,
  `new RegExp("...", "gi")` wrappers unwrapped, Python `(?P<name>` groups
  converted to JavaScript `(?<name>`, JSON over-escaped doubled backslashes
  sequences collapsed to single backslashes, and literal `\n` / `\t` / `\"`
  sequences in replacements converted to real characters.
  Pass `repair_escapes=false` for verbatim handling.
- **Real syntax validation** (`strict=true`, the default). Before anything
  is written, the pattern is compiled by an actual JavaScript engine when
  one is available — `node` if on PATH, otherwise osascript JXA on macOS,
  tunable via the `PRESET_TOOLS_JS` environment variable (`none` disables).
  A conservative structural linter covers engines-less environments, and
  when an engine is present its verdict wins. `$<name>` / `$1..$N`
  references in `replace_string` and in `actions[].title` / `subtitle` /
  `content` are verified against the capture groups the pattern actually
  defines, which catches typo'd group names before they ship. A failing
  script is rejected without modifying the file; pass `strict=false` to
  save anyway.

`regex_check_pattern` is a stateless pre-flight for this same pipeline:
repair, lint, engine-compile, and — given `replace_string` plus
`sample_text` — run the real substitution and return the rendered output and
per-match capture details, so card HTML can be iterated on before touching a
preset.

`regex_validate` checks document structure, field types, JavaScript flag
metadata, and unique IDs, and (by default, `check_patterns`) lints every
script's pattern and references as described above. It never compiles
patterns with Python — that is intentional, because Lumiverse uses
JavaScript syntax such as named captures (`(?<name>...)`).

## Macro reference digest

The Lumiverse macro reference is shipped in two LLM-friendly forms inside this
package:

- **`preset_tools/macro_reference.json`** — structured JSON with one entry per
  built-in macro from Lumiverse's runtime registry, including aliases,
  descriptions, args, returns, and usage.
- **`preset_tools/macro_reference.md`** — the same data as a readable Markdown
  cheat sheet.

Regenerate both from a local Lumiverse checkout with:

```bash
python3 -m preset_tools.macro_updater \
  /path/to/Lumiverse \
  preset_tools/macro_reference.json
```

Passing the backend's `user-docs/docs/presets/macros-reference.md` path also
works; the script will still prefer the runtime registry when it can infer the
repo root.

## Targeting a Live Lumiverse Install

If you are a Lumiverse developer and want the MCP server to always use the absolute latest macros from your local backend checkout instead of the bundled static digest, you have two options:

### Option A: Fully Automated (Recommended)

Simply add the `PRESET_TOOLS_LUMIVERSE_ROOT` environment variable to your `opencode.json` configuration, pointing to your backend directory:

```jsonc
"environment": {
  "PRESET_TOOLS_WORKSPACE": ".",
  "PRESET_TOOLS_LUMIVERSE_ROOT": "/path/to/your/Lumiverse"
}
```

When the MCP server starts, it will automatically detect the backend, use `bun` to extract the live macro registry, generate a fresh reference digest into a temporary folder, and serve that to the LLM. 

### Option B: Manual Cache

If you prefer not to pay the extraction cost on every server start, you can generate it manually into a folder inside your backend directory (e.g., `preset_tools_ref`):

1. Generate the digest:
   ```bash
   export LUMIVERSE_DIR="/path/to/your/Lumiverse"
   mkdir -p "$LUMIVERSE_DIR/preset_tools_ref"
   
   python3 -m preset_tools.macro_updater \
     "$LUMIVERSE_DIR" \
     "$LUMIVERSE_DIR/preset_tools_ref/macro_reference.json"
   ```

2. Update your `opencode.json` by setting `PRESET_TOOLS_MACRO_DIR`:
   ```jsonc
   "environment": {
     "PRESET_TOOLS_WORKSPACE": ".",
     "PRESET_TOOLS_MACRO_DIR": "/path/to/your/Lumiverse/preset_tools_ref"
   }
   ```

## API reference

### IO (`preset_tools.io`)

- **`load(path) -> dict`** — Load a preset JSON file.
- **`save(preset, path) -> None`** — Save with `ensure_ascii=False`. Always use this instead of raw `json.dump`.
- **`preset_blocks(preset) -> list[dict]`** — Get blocks array regardless of schema (ThreadBare vs Loom).

### Audit (`preset_tools.audit`)

- **`audit(preset, show_disabled=True) -> None`** — Print visual block-by-block summary with word counts, enabled state, markers, variables indicator.
- **`token_count(preset, enabled_only=True) -> (chars, tokens)`** — Returns char count and approx token count (chars // 4).
- **`list_blocks(preset, enabled_only=False) -> list[dict]`** — Programmatic list of block summaries.

### Blocks (`preset_tools.blocks`)

- **`find_block(preset, name) -> dict | None`** — First block with name.
- **`find_block_index(preset, name) -> int | None`** — Index of first match.
- **`new_block(name, content, ...) -> dict`** — Construct a new block with fresh UUID. Defaults: `role='system'`, `enabled=True`, `position='pre_history'`.
- **`insert_block(preset, block, after=..., before=..., at_index=...) -> int`** — Insert at named position. Specify exactly one of after/before/at_index.
- **`get_block_lines(preset, name, start_line=1, end_line=None) -> dict`** — Return numbered lines from a block. Line numbers are 1-based and inclusive; if `end_line` is omitted, the slice runs to the end of the block.
- **`modify_block(preset, name, new_content) -> dict`** — Replace block content. Returns the updated block.
- **`modify_block_lines(preset, name, start_line, *, new_content, end_line=None) -> dict`** — Replace a specific line or line range in-place. Use this for surgical edits instead of re-sending the whole block.
- **`delete_block(preset, name) -> dict`** — Remove and return the block.
- **`rename_block(preset, old_name, new_name) -> dict`** — Rename in place.
- **`toggle_block(preset, name, enabled: bool) -> dict`** — Enable/disable.

### Inspect (`preset_tools.inspect`)

- **`show_block(preset, name, max_chars=None) -> None`** — Pretty-print block contents.
- **`get_section(preset, category_name) -> list[dict]`** — Get all blocks in a category section (between two `marker='category'` blocks).
- **`extract_macros(content) -> list[str]`** — Pull all `{{...}}` macros from a string.
- **`find_blocks_referencing(preset, pattern) -> list[str]`** — Find all blocks containing a substring (e.g. `'@plotEvent'`).
- **`dump_enabled_to_file(preset, output_path) -> None`** — Write all enabled block contents to a single text file for review.

### Compare (`preset_tools.compare`)

- **`diff_block_counts(preset_a, preset_b, label_a, label_b) -> None`** — Print totals comparison.
- **`side_by_side(preset_a, preset_b, label_a, label_b) -> None`** — Block-by-block alignment, showing shared / only-in-A / only-in-B.

### Validate (`preset_tools.validate`, `preset_tools.macros`)

Macro **syntax + structure + variable-flow** checker. See the dedicated section
[Validating presets](#validating-presets--macro-syntax--variable-flow-checker) below.

- **`validate(preset, *, source='') -> ValidationResult`** — Validate a loaded preset dict.
- **`validate_file(path) -> ValidationResult`** — Load + validate a file.
- **`print_report(result, *, min_severity='info', show_snippets=True) -> None`** — Human-readable report.
- **`variable_report(preset) -> dict`** — Per-variable usage map (`{scope: {name: {declared, read_in, written_in, checked_in}}}`).
- **`ValidationResult`** — `.diagnostics`, `.errors`, `.warnings`, `.infos`, `.ok`, `.counts()`.
- **`Diagnostic`** — `.severity`, `.code`, `.message`, `.field_path`, `.block_index`, `.block_name`, `.line`, `.col`, `.snippet`.
- **`parse_template(content) -> list[Node]`** (`preset_tools.macros`) — Full macro AST (a faithful port of the engine's lexer/parser). Use this instead of the regex in `extract_macros` when you need correct handling of nested macros, scoped `{{if}}...{{/if}}` pairs, and `.x`/`$x`/`@x` shorthand.

## Schema reference — block structure

Every block is a dict with this shape:

```python
{
    'id': '<uuid>',
    'name': 'Block Name',
    'content': 'The actual prompt text',
    'role': 'system' | 'user' | 'assistant_append',
    'enabled': True | False,
    'position': 'pre_history' | 'post_history',
    'depth': 0,
    'marker': None | 'category' | 'chat_history' | 'main_prompt' | 'jailbreak' | ...,
    'isLocked': False,
    'color': None,
    'injectionTrigger': [],
    'categoryMode': None,
    'variables': [...]  # optional, only for blocks with UI sliders/toggles
}
```

### Markers explained

- **`category`** — Visual separator in the Lumiverse UI. Content usually contains XML tags like `</prev_tag>\n\n<new_tag>` to structure prompt sections.
- **`chat_history`** — Inserts the chat history at this point. Only one per preset.
- **`main_prompt`**, **`jailbreak`**, **`nsfw_prompt`**, **`enhance_definitions`**, **`scenario`**, **`persona_description`**, **`char_description`**, **`char_personality`**, **`dialogue_examples`** — Legacy card-format slots. Lumiverse may or may not populate these depending on context.
- **`world_info_before`**, **`world_info_after`** — Lorebook injection points.

### Variables array

Some blocks expose UI controls via `variables`:

```python
{
    'id': '<uuid>',
    'name': 'words_target',
    'label': 'Target Words to Reach',
    'description': 'How many words per response should the LLM target?',
    'type': 'number' | 'slider' | 'text' | 'switch',
    'defaultValue': 700,
    'min': 100,        # for number/slider
    'max': 10000,      # for number/slider
    'step': 100,       # for number/slider
}
```

Reference these inside content with `{{var::name}}` or `{{getvar::name}}`.

## Lumiverse macro reference

### Variable scopes

| Syntax | Scope | Lifetime |
|---|---|---|
| `{{setvar::name::value}}` / `{{getvar::name}}` | Render-scoped | Lives only for the current prompt render |
| `{{setchatvar::name::value}}` / `{{@name}}` | Chat-scoped | Persists across the current chat session |
| `{{setgvar::name::value}}` / `{{$name}}` | Global | Persists across chats |
| `{{var::name}}` | UI-defined | Reads from the block's `variables` array |

**Important**: prefer render-scoped (`setvar`/`getvar`) for ephemeral computation like dice rolls. Chat-scoped (`@`) is for state that should survive multiple turns in one chat. Global (`$`) survives across chats.

### Control flow

```
{{if::condition}}...{{else}}...{{/if}}
{{if::condition}}{{if::nested}}...{{/if}}{{/if}}    # nested if, no native elif
{{if .var <= 50}}...{{/if}}                          # dot-prefix reads setvar value
{{trim}}...{{/trim}}                                  # strip whitespace
```

### Built-in macros

- `{{user}}` — User persona name
- `{{char}}` — Active character name
- `{{description}}` — Character description field
- `{{personality}}` — Character personality field
- `{{persona}}` — User persona description
- `{{scenario}}` — Scenario field
- `{{userColorMode}}` — Light/dark theme
- `{{groupCardMode}}` — `solo` | `swap` | `merge` | `merge_ignore_muted`
- `{{charGroupFocused}}`, `{{groupOthers}}` — For group cards
- `{{reasoningPrefix::raw}}`, `{{reasoningSuffix::raw}}` — Native reasoning trigger tokens
- `{{rcounter::name}}` — Auto-incrementing counter (use for numbered steps)
- `{{roll::1d100}}` — Dice roll
- `{{pick::A::B::C}}` — Random choice from list
- `{{lumiaOOC}}`, `{{lumiaOOCErotic}}`, `{{lumiaOOCEroticBleed}}`, `{{lumiaCouncilInst}}`, `{{lumiaDef}}`, `{{lumiaPersonality}}`, `{{lumiaBehavior}}` — Lumiverse-app-only macros that inject content from the app's persona system

## Inserting prompt variables via MCP

`preset_insert_prompt_variable` adds a Lumiverse prompt variable definition to a block's `variables` array and optionally injects the matching `{{var::name}}` macro into the block content.

Supported types mirror Lumiverse exactly:

| `var_type` | Extra params | Default value format |
|---|---|---|
| `text` / `textarea` | `rows` for textarea | plain string |
| `number` / `slider` | `min_value`, `max_value`, `step` | number string |
| `switch` | — | `0`, `1`, `true`, `false`, `on`, `off` |
| `select` | `options` or `options_json` (required) | option `id` string |
| `multiselect` | `options` or `options_json` (required), `separator` | JSON array string or comma-separated option ids |

### Escaping-safe payloads

`options` (and multiselect `default_value`) are the JSON-in-JSON traps of the
variable world, so they get the same treatment as the regex tools:

- **Pass options as the structured `options` array** — real objects, no quote
  escaping at all. This is the preferred form. `options_json` (a string) is
  still accepted for backward compatibility and is repaired when malformed:
  over-escaped `\"` sequences, smart quotes, Python-literal syntax (single
  quotes, `True`/`False`/`None`, trailing commas), and bare object keys are
  all fixed and reported in `diagnostics` (`repair_escapes=true`, default).
- **Validation before saving** (`strict=true`, default): `defaultValue` must
  reference a real option id (select and multiselect), option ids must be
  unique, `min` must not exceed `max`, `step` must be positive, and duplicate
  variable names in a block are rejected. A failing insert leaves the file
  untouched.
- **Nothing is dropped silently**: parameters that do not apply to
  `var_type` (e.g. `rows` on a `text` variable, `options` on a `switch`)
  produce `ignored_field` warnings instead of vanishing, and a
  `default_value` string that will be coerced to 0 (a non-numeric number
  default, an unrecognized switch value) is flagged.
- **Macro insertion is idempotent**: if `{{var::name}}` is already in the
  block content, insertion is skipped with a note instead of duplicating it.

`preset_list_prompt_variables` reports every block's variables — name, type,
default, option ids, and whether the block content actually references the
variable's macro — which is the quickest way to see the current state before
editing.

`preset_update_prompt_variable` patches one variable atomically: pass an
`updates` object using the stored field names (`label`, `description`,
`type`, `defaultValue`, `min`, `max`, `step`, `rows`, `options`,
`separator`, `name`; the tool-style aliases `var_type` / `default_value` /
`min_value` / `max_value` also work). The definition is rebuilt with
Lumiverse's coercion rules — changing `type` re-coerces the default — the
stable `id` is preserved, unknown field names are rejected (typos like
`defualt_value` fail loudly), and renaming a variable warns when the content
still references the old macro name. Validation failures leave the file
untouched.

### Examples

```python
# Toggle switch appended at the end of the block
preset_insert_prompt_variable(
    path='ThreadBare 1.0.json',
    block_name='Full CoT (Claude/Gemini)',
    name='nsfw_on',
    label='Gooner Mode',
    var_type='switch',
    default_value='0',
    description='Do you wanna fuck or what?',
    insert_macro=True,
    insert_macro_at='end',
)

# Slider controlling narration/speech ratio
preset_insert_prompt_variable(
    path='ThreadBare 1.0.json',
    block_name='Dialogue Balance',
    name='speech_ratio',
    label='Dialogue to Speech Ratio',
    var_type='slider',
    default_value='50',
    min_value=30,
    max_value=80,
    step=1,
)

# Select with structured options (preferred — no JSON-in-JSON string)
preset_insert_prompt_variable(
    path='ThreadBare 1.0.json',
    block_name='Voice Shaping',
    name='prose_style',
    label='Prose Style',
    var_type='select',
    default_value='vivid',
    options=[
        {"id": "clinical", "label": "Clinical", "value": "Use detached, clinical prose."},
        {"id": "vivid", "label": "Vivid", "value": "Use lush, vivid prose."},
    ],
)

# Multiselect with default selections
preset_insert_prompt_variable(
    path='ThreadBare 1.0.json',
    block_name='Voice Shaping',
    name='style_flags',
    label='Style Flags',
    var_type='multiselect',
    default_value='["concise","vivid"]',
    options=[
        {"id": "concise", "label": "Concise", "value": "Keep it concise."},
        {"id": "vivid", "label": "Vivid", "value": "Make it vivid."},
        {"id": "polite", "label": "Polite", "value": "Keep it polite."},
    ],
    separator='\n\n',
)
```

Use `insert_macro=False` if you only want to register the variable definition without changing the block content. Use `macro_template` to insert something more elaborate than the default `{{var::{name}}}` — for example, `macro_template='{{if {{var::{name}}} == 1}}...{{/if}}'`.

To remove a variable definition later, use `preset_remove_prompt_variable(path, block_name, var_name)`.

## Validating presets — macro syntax & variable-flow checker

`preset_tools.validate` parses every macro-bearing field with a faithful Python
port of the engine's lexer/parser (`preset_tools.macros`), then runs structural
and variable-flow checks. It mirrors the real engine semantics:

- the three variable scopes — local `{{.x}}` / `{{getvar::x}}`, global `{{$x}}`, chat `{{@x}}`;
- creator-defined **prompt variables** (a block's `variables[]`) are pre-seeded before any block renders, so reading them is always safe;
- block **render order** (`pre_history` → `in_history` → `post_history`), so "read before set" is order-aware;
- **disabled blocks don't run**, so a var whose only setter is disabled is treated as unset.

### CLI

```bash
# Run as a module (recommended — avoids the local inspect.py shadowing issue)
python -m preset_tools.validate "ThreadBare 1.0.json"

python -m preset_tools.validate *.json            # validate many at once
python -m preset_tools.validate preset.json --quiet      # errors + warnings only
python -m preset_tools.validate preset.json --errors-only
python -m preset_tools.validate preset.json --strict     # exit 1 on warnings too
python -m preset_tools.validate preset.json --json       # machine-readable
```

Exit codes: `0` = clean (or warnings/info only), `2` = errors found,
`1` = `--strict` and warnings found. (Run via `-m`, not
`python preset_tools/validate.py` — the package's own `inspect.py` shadows the
stdlib `inspect` when the file is run directly.)

### Programmatic

```python
from preset_tools import validate_file, print_report, variable_report, load

result = validate_file('ThreadBare 1.0.json')
print_report(result)                       # full report
print_report(result, min_severity='warning')   # hide info

if not result.ok:                          # ok is False only when there are errors
    for d in result.errors:
        print(d.severity, d.code, d.location(), d.message)

# Audit variable plumbing
vr = variable_report(load('ThreadBare 1.0.json'))
print(vr['local']['util_chaos'])   # {'declared': False, 'read_in': [...], 'written_in': [...], ...}
```

### Diagnostic codes

| Code | Severity | Meaning |
|---|---|---|
| `unterminated-macro` | error | `{{...` with no closing `}}` |
| `parse-error` | error | the template could not be parsed at all |
| `empty-macro` | warning | `{{` with no macro name — usually a stray/unescaped `{{` that swallows text to the next `}}` |
| `unclosed-if` | warning | `{{if}}` with no matching `{{/if}}`; the body renders **unconditionally** (watch for `{{//if}}` typos) |
| `else-outside-if` | warning | `{{else}}` with no enclosing `{{if}}...{{/if}}` |
| `else-if-unsupported` | warning | `{{else if::...}}` — the engine **ignores the condition** and treats it as a plain `{{else}}` |
| `orphan-close` | warning | a `{{/name}}` close tag with no matching opener (silently dropped) |
| `never-set` | warning | a local var is read but never set anywhere and isn't a declared prompt variable → resolves to `""` |
| `set-only-in-disabled` | warning | a var is read in an enabled block but its only setter block is **disabled** → empty until you enable it |
| `read-before-set` | info | a var is read before the block that sets it (in render order) |
| `conditional-set-before-read` | info | a var was only set inside an `{{if}}` branch before being read |
| `never-set-external` | info | a global/chat var is never set here — fine if a prior turn or another preset sets it |
| `unknown-macro` | info | not a built-in macro — renders literally unless a Spindle extension/dynamic macro provides it (catches typos) |

Most findings are **warnings/info, not errors**, because the engine is lenient:
unknown macros pass through as literal text and unset reads resolve to `""`. A
preset with warnings still renders — the checker surfaces likely *authoring
mistakes*, not crashes. Real examples it catches in the shipped presets:
`{{//if}}` typo'd from `{{/if}}` (leaves the `if` unclosed), `{{else if::...}}`
(silently unconditional), and CoT blocks reading `util_*`/`plot_*` flags whose
setter blocks are toggled off.

## Rendering presets — render + tokenize

`preset_tools.render` runs the macro engine the way the backend does, then
tokenizes the **rendered** output. `tokenizer.count_preset` counts raw block
content (macros unexpanded), so it misjudges whatever a `{{if}}` drops or a
`{{getvar}}` expands. Rendering first gives the *true* token cost under a given
set of variable/flag values.

It threads variable state across blocks in render order **exactly** like
assembly — so a `{{setvar}}` in one block reaches a `{{getvar}}` in a later one,
and a flag whose only setter is a **disabled** block reads empty, collapsing its
`{{if}}` just like production.

### What renders vs. what needs values

| Category | Behaviour |
|---|---|
| Control flow `{{if}}/{{else}}/{{trim}}`, variables, logic, math, strings, formatting, dice | Fully evaluated (dice seeded for reproducibility) |
| Prompt variables (`variables[]`) | Seeded from defaults; override with `--var name=value` |
| Identity/persona/chat `{{char}}`, `{{description}}`, … | From `--sample`, or `--value name=text`, else `--unknown` policy |
| App/extension `{{memories}}`, `{{loomStyle}}`, `{{spotify_*}}`, … | From `--value name=text`, else `--unknown` policy |

`--unknown keep` (default) leaves unresolved macros literal — exactly what the
engine does with unknown macros — so the count is "structure-accurate,
data-as-literal." `--unknown blank` drops them. Either way, every unresolved
macro is listed so the count's fidelity is transparent.

### CLI

```bash
python -m preset_tools.render "ThreadBare 1.0.json" --sample            # sample character
python -m preset_tools.render preset.json --sample --by-block           # per-block token table
python -m preset_tools.render preset.json --sample --show               # print rendered prompt
python -m preset_tools.render preset.json --sample --out rendered.txt    # write to file

# See the token impact of toggling a flag / changing a prompt variable:
python -m preset_tools.render preset.json --sample --set util_chaos=1 --var words_target=900

# Supply data/app macro values:
python -m preset_tools.render preset.json --value char=Stella --value spotify_track_name="Blue Monday"
```

`--set` accepts an optional scope: `--set global:streak=3`, `--set chat:turn=10`
(default scope is local). `--seed N` controls dice. `--json` emits a summary.

### Programmatic

```python
from preset_tools import load, render_preset, RenderEnv
from preset_tools.tokenizer import count_preset

preset = load('ThreadBare 1.0.json')

env = RenderEnv.sample()          # or RenderEnv.empty()
env.set_var('util_spotify', '1')  # local var
env.set_value('char', 'Stella')   # data macro

result = render_preset(preset, env)
print(result.total_tokens)        # real Claude tokens of the rendered prompt
print(result.text)                # the assembled, rendered prompt
for rb in result.blocks:          # per-block: .name .role .chars .tokens .text
    print(rb.name, rb.tokens)
print(result.unresolved)          # macros left literal (no value supplied)

# raw vs rendered — how much the macro layer changes the budget:
_, raw = count_preset(preset, enabled_only=True)
print(raw, '->', result.total_tokens)   # e.g. 10463 -> 9453
```

`render_text(template, env)` renders a single string if you just want to expand
one block's content. Token counting needs the `tokenizers` package + a Claude
`tokenizer.json` (see the tokenizer section); without them, rendering still
works and `result.total_tokens` is `None` with `result.tokenizer_error` set.

## Common patterns

### Audit current state

```python
from preset_tools import load, audit, token_count

preset = load('ThreadBare 1.0.json')
audit(preset)
chars, tokens = token_count(preset)
print(f'Enabled: {tokens} tokens')
```

### Edit a line range inside a long block

```python
from preset_tools import get_block_lines, load, modify_block_lines, save

preset = load('ThreadBare 1.0.json')
snippet = get_block_lines(preset, 'Voice Shaping', start_line=15, end_line=19)
for row in snippet['lines']:
    print(f"{row['line']}: {row['text']}")

modify_block_lines(
    preset,
    'Voice Shaping',
    start_line=17,
    end_line=18,
    new_content='Two replacement lines.\nStill scoped to the same block.',
)
save(preset, 'ThreadBare 1.0.json')
```

### Replace an entire block (bypassing smart-quote issues)

```python
from preset_tools import load, save, modify_block

preset = load('ThreadBare 1.0.json')
modify_block(preset, 'Voice Shaping', '''<voice_authenticity>
New content here with em-dashes — and smart quotes 'work fine'.
</voice_authenticity>''')
save(preset, 'ThreadBare 1.0.json')
```

### Insert a new block in a specific section

```python
from preset_tools import load, save, new_block, insert_block

preset = load('ThreadBare 1.0.json')
block = new_block(
    name='My Addition',
    content='<my_tag>\nInstructions in Stella\'s voice.\n</my_tag>',
    enabled=False,  # ship disabled, let user toggle on
)
insert_block(preset, block, after='Anti-Echo')
save(preset, 'ThreadBare 1.0.json')
```

### Create a dice-roll block with render-scoped variables

```python
content = '''<my_chaos>
{{setvar::roll::{{roll::1d100}}}}
{{if .roll <= 50}}{{setvar::result::none}}{{else}}{{setvar::result::{{pick::a::b::c}}}}{{/if}}

{{if {{getvar::result}} != none}}- Event: {{getvar::result}}
{{else}}- No event this beat.
{{/if}}
</my_chaos>'''
```

Render-scoped means the variables die when this render ends — no persistence problems if the block gets toggled off.

### Compare ThreadBare vs Loom

```python
from preset_tools import load, diff_block_counts, side_by_side

tb = load('ThreadBare 1.0.json')
ll = load('Lucid_Loom_v3.4.2.json')

diff_block_counts(tb, ll, 'ThreadBare', 'Loom')
side_by_side(tb, ll, 'ThreadBare', 'Loom')
```

## Gotchas

1. **Never use `json.dump(preset, f)` directly** — defaults escape Unicode. Always `save(preset, path)`.
2. **Edits via the Edit tool may fail silently on Unicode mismatches.** If a string-replace fails and looks correct, check for smart-quote / em-dash mismatches and use `modify_block` instead.
3. **Lumiverse macros are case-sensitive.** `{{user}}` works, `{{User}}` does not.
4. **`{{setchatvar::name::value}}` and `{{@name = value}}` are chat-scoped — they persist.** If the block holding that write gets disabled mid-chat, the variable keeps its last value. Use `setvar`/`getvar` for state that should die with the render.
5. **Some Lumiverse macros (`{{lumiaOOC}}`, `{{lumiaDef}}`, etc.) only resolve inside the Lumiverse app.** Anywhere else they render as raw text, so provide non-macro alternatives for contexts outside Lumiverse (see ThreadBare's "Stella OOC" standalone block as an example).
6. **Category markers create visual sections in the UI but don't actually do anything mechanically.** Their content typically contains XML tags that wrap the section for the model. Get this wrong and the XML structure breaks.
