"""
Inspect module — examine block contents, sections, and macros.
"""

import re
from typing import Optional
from .io import preset_blocks
from .blocks import find_block_index


def show_block(preset: dict, name: str, max_chars: Optional[int] = None) -> None:
    """
    Pretty-print a block's content. Pass max_chars to truncate.
    """
    blocks = preset_blocks(preset)
    for b in blocks:
        if b['name'] == name:
            content = b['content']
            words = len(content.split())
            enabled = '✅' if b.get('enabled') else '❌'
            print(f'=== {b["name"]} ({words}w, {enabled}) ===')
            if max_chars and len(content) > max_chars:
                print(content[:max_chars] + '...')
            else:
                print(content)
            return
    print(f"Block '{name}' not found")


def get_section(preset: dict, category_name: str) -> list[dict]:
    """
    Return all blocks belonging to a category section.

    A category section starts at a block with marker='category' and the
    given name, and ends at the next block with marker='category'.

    Useful for analyzing entire functional sections (Pace, Character
    Shaping, NSFW, etc.) without manually finding indices.
    """
    blocks = preset_blocks(preset)
    section = []
    in_section = False

    for b in blocks:
        if b['name'] == category_name and b.get('marker') == 'category':
            in_section = True
            section.append(b)
            continue
        if in_section and b.get('marker') == 'category':
            break
        if in_section:
            section.append(b)

    return section


def extract_macros(content: str) -> list[str]:
    """
    Extract all Lumiverse template macros from a string.

    Returns a sorted unique list of macro patterns like:
        {{user}}, {{char}}, {{if::...}}, {{setvar::...}}, {{@plotEvent}}, etc.

    Useful for auditing what variables a block references before editing.
    """
    matches = re.findall(r'\{\{[^}]+\}\}', content)
    return sorted(set(matches))


def find_blocks_referencing(preset: dict, pattern: str) -> list[str]:
    """
    Return names of all blocks whose content contains the given pattern.

    Pattern is a literal substring, not a regex. Use this to find every
    block that touches a specific variable or macro before refactoring.

    Example:
        find_blocks_referencing(preset, '@plotEvent')
        # → ['Story Shake-Up', 'Full CoT (Claude/Gemini)', 'Tiered CoT (GLM/DeepSeek)']
    """
    blocks = preset_blocks(preset)
    return [b['name'] for b in blocks if pattern in b.get('content', '')]


def dump_enabled_to_file(preset: dict, output_path: str) -> None:
    """
    Write all enabled block contents to a single text file for review.

    Each block is preceded by a header with index, name, and word count.
    Useful for reading the full rendered prompt order without scrolling
    through JSON, or for piping to a model for review.
    """
    blocks = preset_blocks(preset)
    lines = []
    for i, b in enumerate(blocks):
        if not b.get('enabled'):
            continue
        content = b.get('content', '')
        if len(content.split()) < 5:
            continue  # skip empty category dividers
        lines.append(f'=== [{i+1}] {b["name"]} ({len(content.split())}w) ===')
        lines.append(content)
        lines.append('')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
