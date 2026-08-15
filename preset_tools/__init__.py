"""
preset_tools — utilities for editing Lumiverse preset JSON files.

Quick start:
    from preset_tools import (
        audit, get_block_lines, insert_block, load,
        modify_block, modify_block_lines, save,
    )

    preset = load('ThreadBare 1.0.json')
    audit(preset)                           # print structural overview
    print(get_block_lines(preset, 'Voice Shaping', 10, 14)['lines'])
    modify_block_lines(
        preset,
        'Voice Shaping',
        12,
        new_content=replacement_text,
        end_line=13,
    )
    modify_block(preset, 'Voice Shaping', new_content_string)  # whole block
    insert_block(preset, new_block_dict, after='Anti-Echo')
    save(preset, 'ThreadBare 1.0.json')

See README.md in this directory for full documentation.
"""

from .io import load, save
from .audit import audit, token_count, list_blocks
from .blocks import (
    find_block,
    find_block_index,
    new_block,
    insert_block,
    get_block_lines,
    modify_block,
    modify_block_lines,
    delete_block,
    add_prompt_variable,
    remove_prompt_variable,
)
from .inspect import (
    get_section,
    extract_macros,
    show_block,
    find_blocks_referencing,
    dump_enabled_to_file,
)
from .blocks import rename_block, toggle_block
from .compare import diff_block_counts, side_by_side
from .validate import (
    validate,
    validate_file,
    print_report,
    variable_report,
    ValidationResult,
    Diagnostic,
)
from .macros import parse_template
from .render import (
    render_text,
    render_preset,
    render_and_tokenize,
    print_render_report,
    RenderEnv,
    RenderResult,
)
from .character import (
    get_field as char_get_field,
    set_field as char_set_field,
    get_summary as char_get_summary,
    validate_card as char_validate_card,
    load_card as char_load,
    save_card as char_save,
    CORE_FIELDS,
)
from .regex_scripts import (
    STANDALONE_TYPE,
    delete_regex_script,
    find_regex_script,
    insert_regex_script,
    new_regex_export,
    new_regex_script,
    regex_scripts,
    script_summary,
    update_regex_script,
    validate_regex_document,
    validate_regex_script,
)

# Token-counting helpers live in .tokenizer, which depends on the optional
# `tokenizers` package. Expose them lazily (PEP 562) so editing scripts that
# never count tokens don't pay the import cost or require the dependency.
_LAZY_TOKENIZER = {
    'count_tokens', 'count_preset', 'count_blocks', 'token_audit', 'get_tokenizer',
}


def __getattr__(name):
    if name in _LAZY_TOKENIZER:
        from . import tokenizer
        return getattr(tokenizer, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


__all__ = [
    'load', 'save',
    'audit', 'token_count', 'list_blocks',
    'count_tokens', 'count_preset', 'count_blocks', 'token_audit', 'get_tokenizer',
    'find_block', 'find_block_index', 'new_block',
    'insert_block', 'get_block_lines', 'modify_block', 'modify_block_lines', 'delete_block',
    'add_prompt_variable', 'remove_prompt_variable',
    'rename_block', 'toggle_block',
    'get_section', 'extract_macros', 'show_block',
    'find_blocks_referencing', 'dump_enabled_to_file',
    'diff_block_counts', 'side_by_side',
    'validate', 'validate_file', 'print_report', 'variable_report',
    'ValidationResult', 'Diagnostic', 'parse_template',
    'render_text', 'render_preset', 'render_and_tokenize',
    'print_render_report', 'RenderEnv', 'RenderResult',
    'char_get_field', 'char_set_field', 'char_get_summary',
    'char_validate_card', 'char_load', 'char_save', 'CORE_FIELDS',
    'STANDALONE_TYPE', 'new_regex_export', 'new_regex_script',
    'regex_scripts', 'find_regex_script', 'insert_regex_script',
    'update_regex_script', 'delete_regex_script', 'script_summary',
    'validate_regex_script', 'validate_regex_document',
]
