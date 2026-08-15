"""
Audit module — structural overview, token counts, block listings.

Use these to get a quick picture of preset state before/after edits.
"""

from .io import preset_blocks


def token_count(preset: dict, enabled_only: bool = True) -> tuple[int, int]:
    """
    Return (char_count, approx_token_count) for the preset.

    Tokens are estimated as chars // 4, which is the standard rough
    approximation for English text in BPE tokenizers.

    Set enabled_only=False to count all blocks regardless of toggle state.
    """
    blocks = preset_blocks(preset)
    chars = sum(
        len(b.get('content', ''))
        for b in blocks
        if (not enabled_only) or b.get('enabled')
    )
    return chars, chars // 4


def list_blocks(preset: dict, enabled_only: bool = False) -> list[dict]:
    """
    Return a list of block summaries with name, words, chars, enabled, marker.

    Useful for programmatic filtering. For visual output, use audit().
    """
    blocks = preset_blocks(preset)
    out = []
    for i, b in enumerate(blocks):
        if enabled_only and not b.get('enabled'):
            continue
        content = b.get('content', '')
        out.append({
            'index': i,
            'name': b['name'],
            'words': len(content.split()),
            'chars': len(content),
            'enabled': b.get('enabled', False),
            'role': b.get('role', 'system'),
            'position': b.get('position', 'pre_history'),
            'marker': b.get('marker'),
            'has_variables': bool(b.get('variables')),
        })
    return out


def audit(preset: dict, show_disabled: bool = True) -> None:
    """
    Print a visual structural overview of the preset.

    Shows each block with: index, enabled state (✅/❌), name, word count,
    char count, marker tag, and a 📊 indicator if it has UI variables.

    At the end, prints totals and a comparison to original ThreadBare
    baseline (27354 chars / 6838 tokens) if applicable.
    """
    blocks = preset_blocks(preset)
    total_enabled_chars = 0

    for i, b in enumerate(blocks):
        content = b.get('content', '')
        words = len(content.split())
        chars = len(content)
        enabled_flag = '✅' if b.get('enabled') else '❌'

        if not show_disabled and not b.get('enabled'):
            continue

        marker = b.get('marker', '')
        marker_str = f' [{marker}]' if marker else ''
        has_vars = ' 📊' if b.get('variables') else ''

        print(f'{i+1:3}. {enabled_flag} {b["name"]:<35} ~{words:>4}w {chars:>5}c{marker_str}{has_vars}')

        if b.get('enabled'):
            total_enabled_chars += chars

    enabled_count = sum(1 for b in blocks if b.get('enabled'))
    print(f'\nTotal blocks: {len(blocks)}')
    print(f'Enabled blocks: {enabled_count}')
    print(f'Enabled chars: {total_enabled_chars} ≈ {total_enabled_chars // 4} tokens')
