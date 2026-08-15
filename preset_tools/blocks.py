"""
Blocks module — create, find, insert, modify, delete preset blocks.

All operations work in-place on the preset dict. Save with io.save() after.
"""

import re
import uuid
import json
from typing import Any, Optional
from .io import preset_blocks


def _slugify(name: str) -> str:
    """Convert a block name to a kebab-case sealedKey."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "block"


def find_block(preset: dict, name: str) -> Optional[dict]:
    """
    Return the first block with the given name, or None if not found.
    """
    for b in preset_blocks(preset):
        if b['name'] == name:
            return b
    return None


def find_block_index(preset: dict, name: str) -> Optional[int]:
    """
    Return the index of the first block with the given name, or None.
    """
    for i, b in enumerate(preset_blocks(preset)):
        if b['name'] == name:
            return i
    return None


def _line_separator(content: str) -> str:
    """Preserve the block's existing newline style when rewriting content."""
    if '\r\n' in content:
        return '\r\n'
    if '\n' in content:
        return '\n'
    if '\r' in content:
        return '\r'
    return '\n'


def _split_content_lines(content: str) -> list[str]:
    """Return logical lines, treating empty content as a single blank line."""
    return content.splitlines() or ['']


def _content_ends_with_newline(content: str) -> bool:
    return content.endswith(('\r\n', '\n', '\r'))


def _resolve_line_range(
    total_lines: int,
    start_line: int,
    end_line: Optional[int],
    *,
    default_to_end: bool,
) -> tuple[int, int]:
    if start_line < 1:
        raise ValueError("start_line must be >= 1")

    resolved_end = total_lines if default_to_end and end_line is None else (start_line if end_line is None else end_line)
    if resolved_end < start_line:
        raise ValueError("end_line must be >= start_line")
    if start_line > total_lines:
        raise ValueError(f"start_line {start_line} is past end of block ({total_lines} lines)")
    if resolved_end > total_lines:
        raise ValueError(f"end_line {resolved_end} is past end of block ({total_lines} lines)")
    return start_line, resolved_end


def _join_content_lines(lines: list[str], separator: str, ends_with_newline: bool) -> str:
    if not lines:
        return ''
    content = separator.join(lines)
    if ends_with_newline:
        content += separator
    return content


def new_block(
    name: str,
    content: str,
    role: str = 'system',
    enabled: bool = True,
    position: str = 'pre_history',
    marker: Optional[str] = None,
    depth: int = 0,
    is_locked: bool = False,
    variables: Optional[list[dict]] = None,
) -> dict:
    """
    Construct a new block dict with a fresh UUID.

    Default schema matches what Lumiverse expects:
        - role: 'system' | 'user' | 'assistant_append'
        - position: 'pre_history' | 'post_history'
        - marker: None | 'category' | 'chat_history' | 'main_prompt' | ...
        - enabled: True/False (default True, but new blocks are often
          inserted disabled — pass enabled=False explicitly)

    For category headers, set marker='category' and use content like
    '</prev_tag>\\n\\n<new_tag>' to bridge XML category sections.
    """
    block = {
        'id': str(uuid.uuid4()),
        'name': name,
        'content': content,
        'role': role,
        'enabled': enabled,
        'position': position,
        'depth': depth,
        'marker': marker,
        'isLocked': is_locked,
        'color': None,
        'injectionTrigger': [],
        'categoryMode': None,
    }
    if variables:
        block['variables'] = variables
    return block


def insert_block(
    preset: dict,
    block: dict,
    after: Optional[str] = None,
    before: Optional[str] = None,
    at_index: Optional[int] = None,
) -> int:
    """
    Insert a block into the preset. Returns the inserted index.

    Specify exactly ONE of:
        after='Block Name'      — insert immediately after named block
        before='Block Name'     — insert immediately before named block
        at_index=5              — insert at literal index

    Raises ValueError if the target block isn't found.
    """
    blocks = preset_blocks(preset)
    args = sum(x is not None for x in (after, before, at_index))
    if args != 1:
        raise ValueError("Specify exactly one of: after, before, at_index")

    if after is not None:
        idx = find_block_index(preset, after)
        if idx is None:
            raise ValueError(f"Block '{after}' not found")
        idx += 1
    elif before is not None:
        idx = find_block_index(preset, before)
        if idx is None:
            raise ValueError(f"Block '{before}' not found")
    else:
        idx = at_index

    blocks.insert(idx, block)
    return idx


def modify_block(preset: dict, name: str, new_content: str) -> dict:
    """
    Replace the content of the named block. Returns the updated block.

    Raises ValueError if the block isn't found.

    Use this instead of Edit tool when the content has tricky Unicode
    or template macros — string-matching edits often fail on smart quotes
    and em-dashes that look identical but use different code points.
    """
    block = find_block(preset, name)
    if block is None:
        raise ValueError(f"Block '{name}' not found")
    block['content'] = new_content
    return block


def get_block_lines(
    preset: dict,
    name: str,
    start_line: int = 1,
    end_line: Optional[int] = None,
) -> dict:
    """
    Return numbered lines from a block using 1-based inclusive line numbers.

    If end_line is omitted, the slice runs from start_line through the final
    line of the block.
    """
    block = find_block(preset, name)
    if block is None:
        raise ValueError(f"Block '{name}' not found")

    content = block.get('content', '')
    lines = _split_content_lines(content)
    total_lines = len(lines)
    start_line, end_line = _resolve_line_range(
        total_lines,
        start_line,
        end_line,
        default_to_end=True,
    )
    selected = lines[start_line - 1:end_line]
    text = _join_content_lines(
        selected,
        _line_separator(content),
        _content_ends_with_newline(content) and end_line == total_lines,
    )
    return {
        'start_line': start_line,
        'end_line': end_line,
        'total_lines': total_lines,
        'text': text,
        'lines': [
            {'line': line_no, 'text': line_text}
            for line_no, line_text in enumerate(selected, start=start_line)
        ],
    }


def modify_block_lines(
    preset: dict,
    name: str,
    start_line: int,
    *,
    new_content: str,
    end_line: Optional[int] = None,
) -> dict:
    """
    Replace a 1-based inclusive line or line range inside a block.

    If end_line is omitted, only start_line is replaced. Pass an empty string
    to delete the selected lines entirely.
    """
    block = find_block(preset, name)
    if block is None:
        raise ValueError(f"Block '{name}' not found")

    content = block.get('content', '')
    separator = _line_separator(content)
    lines = _split_content_lines(content)
    total_lines = len(lines)
    start_line, end_line = _resolve_line_range(
        total_lines,
        start_line,
        end_line,
        default_to_end=False,
    )

    replacement = [] if new_content == '' else new_content.splitlines()
    replacement_ends_with_newline = _content_ends_with_newline(new_content)
    original_ends_with_newline = _content_ends_with_newline(content)

    updated_lines = lines[:start_line - 1] + replacement + lines[end_line:]
    ends_with_newline = original_ends_with_newline
    if end_line == total_lines:
        ends_with_newline = replacement_ends_with_newline if replacement else False

    block['content'] = _join_content_lines(updated_lines, separator, ends_with_newline)
    return block


def delete_block(preset: dict, name: str) -> dict:
    """
    Remove the named block from the preset. Returns the deleted block.

    Raises ValueError if the block isn't found.
    """
    blocks = preset_blocks(preset)
    for i, b in enumerate(blocks):
        if b['name'] == name:
            return blocks.pop(i)
    raise ValueError(f"Block '{name}' not found")


def rename_block(preset: dict, old_name: str, new_name: str) -> dict:
    """
    Rename a block in place. Returns the updated block.
    """
    block = find_block(preset, old_name)
    if block is None:
        raise ValueError(f"Block '{old_name}' not found")
    block['name'] = new_name
    return block


def toggle_block(preset: dict, name: str, enabled: bool) -> dict:
    """
    Enable or disable a block by name. Returns the updated block.
    """
    block = find_block(preset, name)
    if block is None:
        raise ValueError(f"Block '{name}' not found")
    block['enabled'] = enabled
    return block


# ---------------------------------------------------------------------------
# Prompt variables
# ---------------------------------------------------------------------------

VALID_PROMPT_VARIABLE_TYPES = {
    'text', 'textarea', 'number', 'slider', 'select', 'switch', 'multiselect'
}


def _num(raw: Any) -> Any:
    """Coerce to a number, keeping whole values as ints like hand-authored presets."""
    value = float(raw) if isinstance(raw, str) else raw
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _coerce_default_value(var_type: str, raw: Any, options: Optional[list[dict]] = None) -> Any:
    """
    Coerce a user-supplied default value to the correct Python type for a
    Lumiverse prompt variable definition.
    """
    if var_type in ('text', 'textarea'):
        return '' if raw is None else str(raw)

    if var_type == 'number':
        if raw is None:
            return 0
        try:
            return _num(raw)
        except (ValueError, TypeError):
            return 0

    if var_type == 'slider':
        if raw is None:
            return 0
        try:
            return _num(raw)
        except (ValueError, TypeError):
            return 0

    if var_type == 'switch':
        if raw is None:
            return 0
        if isinstance(raw, bool):
            return 1 if raw else 0
        if isinstance(raw, (int, float)):
            return 1 if raw else 0
        s = str(raw).strip().lower()
        return 1 if s in ('1', 'true', 'on', 'yes') else 0

    if var_type == 'select':
        if raw is None:
            return options[0]['id'] if options else ''
        return str(raw)

    if var_type == 'multiselect':
        if raw is None:
            return []
        if isinstance(raw, list):
            return [str(v) for v in raw]
        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped.startswith('['):
                try:
                    return [str(v) for v in json.loads(stripped)]
                except json.JSONDecodeError:
                    return []
            return [v.strip() for v in stripped.split(',') if v.strip()]
        return []

    raise ValueError(f"Unsupported prompt variable type: {var_type}")


def _validate_options(options: Any) -> list[dict]:
    """
    Validate and normalize a list of select/multiselect options.
    Each option must have id, label, and value keys.
    """
    if options is None:
        return []
    if isinstance(options, str):
        options = json.loads(options)
    if not isinstance(options, list):
        raise ValueError("options must be a JSON array of {id, label, value} objects")
    normalized = []
    for i, opt in enumerate(options):
        if not isinstance(opt, dict):
            raise ValueError(f"Option {i} is not an object")
        if 'id' not in opt or 'label' not in opt or 'value' not in opt:
            raise ValueError(f"Option {i} must have id, label, and value keys")
        normalized.append({
            'id': str(opt['id']),
            'label': str(opt['label']),
            'value': str(opt['value']),
        })
    return normalized


def _build_variable_def(
    name: str,
    label: str,
    var_type: str,
    default_value: Any = None,
    description: str = '',
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    step: Optional[float] = None,
    rows: Optional[int] = None,
    options: Optional[Any] = None,
    separator: Optional[str] = None,
    stable_id: Optional[str] = None,
) -> dict:
    """
    Build a Lumiverse-style PromptVariableDef dict, mirroring the backend's
    coercion rules.  Shared by add_prompt_variable and update_prompt_variable.
    """
    var_type = var_type.lower()
    if var_type not in VALID_PROMPT_VARIABLE_TYPES:
        raise ValueError(
            f"Invalid prompt variable type '{var_type}'. "
            f"Supported: {', '.join(sorted(VALID_PROMPT_VARIABLE_TYPES))}"
        )

    normalized_options = _validate_options(options) if var_type in ('select', 'multiselect') else None

    var_def: dict[str, Any] = {
        'id': stable_id or str(uuid.uuid4()),
        'name': name,
        'label': label,
        'type': var_type,
        'defaultValue': _coerce_default_value(var_type, default_value, normalized_options),
    }

    if description:
        var_def['description'] = description

    if var_type in ('number', 'slider'):
        if min_value is not None:
            var_def['min'] = min_value
        if max_value is not None:
            var_def['max'] = max_value
        if step is not None:
            var_def['step'] = step

    if var_type == 'slider':
        if 'min' not in var_def or 'max' not in var_def:
            raise ValueError("slider variables require both min_value and max_value")

    if var_type == 'textarea' and rows is not None:
        var_def['rows'] = rows

    if var_type in ('select', 'multiselect'):
        if not normalized_options:
            raise ValueError(f"{var_type} variables require at least one option")
        var_def['options'] = normalized_options
        if var_type == 'multiselect' and separator is not None:
            var_def['separator'] = separator

    return var_def


def add_prompt_variable(
    preset: dict,
    block_name: str,
    name: str,
    label: str,
    var_type: str,
    default_value: Any = None,
    description: str = '',
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    step: Optional[float] = None,
    rows: Optional[int] = None,
    options: Optional[Any] = None,
    separator: Optional[str] = None,
) -> dict:
    """
    Add a Lumiverse-style prompt variable definition to a block's variables
    array. Returns the created variable definition dict.

    Supported types: text, textarea, number, slider, select, switch, multiselect.
    For select/multiselect, pass options as a JSON string or a list of dicts
    with id/label/value keys. Duplicate variable names in the same block are
    rejected.
    """
    block = find_block(preset, block_name)
    if block is None:
        raise ValueError(f"Block '{block_name}' not found")

    existing = block.get('variables') or []
    if any(v.get('name') == name for v in existing):
        raise ValueError(f"Variable '{name}' already exists in block '{block_name}'")

    var_def = _build_variable_def(
        name, label, var_type,
        default_value=default_value,
        description=description,
        min_value=min_value,
        max_value=max_value,
        step=step,
        rows=rows,
        options=options,
        separator=separator,
    )
    block['variables'] = existing
    block['variables'].append(var_def)
    return var_def


def update_prompt_variable(
    preset: dict,
    block_name: str,
    var_name: str,
    updates: dict,
) -> dict:
    """
    Atomically patch one prompt variable definition by variable name.

    ``updates`` keys use the stored field names (label, description, type,
    defaultValue, min, max, step, rows, options, separator, name); the type is
    re-validated and defaultValue re-coerced after merging. The variable's
    stable ``id`` is preserved. Returns the updated definition.
    """
    block = find_block(preset, block_name)
    if block is None:
        raise ValueError(f"Block '{block_name}' not found")

    variables = block.get('variables') or []
    index = next((i for i, v in enumerate(variables) if v.get('name') == var_name), None)
    if index is None:
        raise ValueError(f"Variable '{var_name}' not found in block '{block_name}'")

    merged = dict(variables[index])
    merged.update(updates)

    var_def = _build_variable_def(
        name=merged.get('name') or var_name,
        label=merged.get('label') or '',
        var_type=merged.get('type') or 'text',
        default_value=merged.get('defaultValue'),
        description=merged.get('description') or '',
        min_value=merged.get('min'),
        max_value=merged.get('max'),
        step=merged.get('step'),
        rows=merged.get('rows'),
        options=merged.get('options'),
        separator=merged.get('separator'),
        stable_id=merged.get('id'),
    )

    for i, v in enumerate(variables):
        if i != index and v.get('name') == var_def['name']:
            raise ValueError(f"Variable '{var_def['name']}' already exists in block '{block_name}'")
    variables[index] = var_def
    return var_def


def list_prompt_variables(preset: dict) -> list[dict]:
    """
    Return every block's prompt variables with a compact summary of each
    definition and whether the block's content references its macro.
    """
    out: list[dict] = []
    for block in preset_blocks(preset):
        variables = block.get('variables') or []
        if not variables:
            continue
        content = block.get('content') or ''
        entries = []
        for v in variables:
            name = v.get('name')
            entries.append({
                'name': name,
                'label': v.get('label'),
                'type': v.get('type'),
                'default': v.get('defaultValue'),
                'option_ids': [o.get('id') for o in (v.get('options') or [])] or None,
                'macro_in_content': (
                    name is not None
                    and (f'{{{{var::{name}}}}}' in content or f'{{{{getvar::{name}}}}}' in content)
                ),
            })
        out.append({'block': block.get('name'), 'variables': entries})
    return out


def remove_prompt_variable(preset: dict, block_name: str, var_name: str) -> dict:
    """
    Remove a prompt variable definition from a block by variable name.
    Returns the removed variable definition, or raises ValueError if not found.
    """
    block = find_block(preset, block_name)
    if block is None:
        raise ValueError(f"Block '{block_name}' not found")

    variables = block.get('variables') or []
    for i, var in enumerate(variables):
        if var.get('name') == var_name:
            return variables.pop(i)
    raise ValueError(f"Variable '{var_name}' not found in block '{block_name}'")


# ---------------------------------------------------------------------------
# Sealed blocks
# ---------------------------------------------------------------------------

def set_block_seal(preset: dict, name: str, sealed: bool = True, sealed_key: Optional[str] = None) -> dict:
    """
    Set or remove the sealed status on a named block.

    When ``sealed=True``:
        - Sets ``block['sealed'] = True``
        - If ``sealed_key`` is provided, sets ``block['sealedKey']`` to it.
        - If no ``sealed_key`` is provided and the block lacks ``sealedKey``,
          auto-generates one from the block name via kebab-case slugification.

    When ``sealed=False``:
        - Removes both ``sealed`` and ``sealedKey`` keys entirely.

    Returns the updated block. Raises ValueError if the block isn't found.
    """
    block = find_block(preset, name)
    if block is None:
        raise ValueError(f"Block '{name}' not found")

    if sealed:
        block['sealed'] = True
        if sealed_key:
            block['sealedKey'] = sealed_key
        elif 'sealedKey' not in block:
            block['sealedKey'] = _slugify(name)
    else:
        block.pop('sealed', None)
        block.pop('sealedKey', None)
    return block


def mass_set_seal(
    preset: dict,
    names: Optional[list[str]] = None,
    pattern: Optional[str] = None,
    sealed: bool = True,
    sealed_key_prefix: Optional[str] = None,
    auto_key: bool = False,
) -> list[dict]:
    """
    Apply or remove seals on multiple blocks.

    Filters (evaluated as OR):
        - ``names``: exact block names to target.
        - ``pattern``: regex matched against block names.

    If neither filter is given, ALL blocks are targeted.

    ``sealed_key_prefix`` prepends a prefix to auto-generated keys.
    ``auto_key`` forces key generation even when the block already has one.

    Returns a list of affected blocks (name, sealed, sealedKey).
    """
    blocks = preset_blocks(preset)
    affected: list[dict] = []

    compiled_pattern = re.compile(pattern, re.IGNORECASE) if pattern else None

    for block in blocks:
        name = block.get('name', '')
        matches = False
        if names is not None and name in names:
            matches = True
        if compiled_pattern is not None and compiled_pattern.search(name):
            matches = True
        if names is None and compiled_pattern is None:
            matches = True

        if not matches:
            continue

        if sealed:
            block['sealed'] = True
            if sealed_key_prefix or auto_key or 'sealedKey' not in block:
                key = _slugify(name)
                if sealed_key_prefix:
                    key = f"{sealed_key_prefix}-{key}"
                block['sealedKey'] = key
        else:
            block.pop('sealed', None)
            block.pop('sealedKey', None)

        affected.append({
            'name': name,
            'sealed': block.get('sealed'),
            'sealedKey': block.get('sealedKey'),
        })

    return affected


def get_seal_status(preset: dict) -> list[dict]:
    """
    Return a status report for every block in the preset.

    Each entry contains:
        - name
        - sealed (bool or None)
        - sealedKey (str or None)
    """
    return [
        {
            'name': block.get('name'),
            'sealed': block.get('sealed'),
            'sealedKey': block.get('sealedKey'),
        }
        for block in preset_blocks(preset)
    ]
