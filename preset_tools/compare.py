"""
Compare module — diff two presets to track changes or weight differences.
"""

from difflib import unified_diff
from typing import Optional

from .io import preset_blocks
from .audit import token_count


def diff_block_counts(preset_a: dict, preset_b: dict, label_a: str = 'A', label_b: str = 'B') -> None:
    """
    Print a comparative summary of two presets:
    - Total block counts
    - Enabled counts
    - Token estimates
    - Token ratio (B as % of A)

    Useful for tracking ThreadBare vs Loom weight, or comparing
    versions of the same preset across edits.
    """
    blocks_a = preset_blocks(preset_a)
    blocks_b = preset_blocks(preset_b)
    chars_a, tokens_a = token_count(preset_a)
    chars_b, tokens_b = token_count(preset_b)

    print(f'           {label_a:>15} {label_b:>15}')
    print(f'Blocks:    {len(blocks_a):>15} {len(blocks_b):>15}')
    print(f'Enabled:   {sum(1 for b in blocks_a if b.get("enabled")):>15} {sum(1 for b in blocks_b if b.get("enabled")):>15}')
    print(f'Chars:     {chars_a:>15} {chars_b:>15}')
    print(f'~Tokens:   {tokens_a:>15} {tokens_b:>15}')

    if chars_a > 0:
        ratio = chars_b / chars_a * 100
        print(f'\n{label_b} is {ratio:.1f}% of {label_a}\'s weight')


def side_by_side(preset_a: dict, preset_b: dict, label_a: str = 'A', label_b: str = 'B') -> None:
    """
    Print block-by-block comparison aligned by name.

    Shows blocks present in both, only-in-A, and only-in-B.
    Useful for verifying a migration or sanity-checking what's been
    added/removed between preset versions.
    """
    a_blocks = {b['name']: b for b in preset_blocks(preset_a)}
    b_blocks = {b['name']: b for b in preset_blocks(preset_b)}

    only_a = set(a_blocks) - set(b_blocks)
    only_b = set(b_blocks) - set(a_blocks)
    shared = set(a_blocks) & set(b_blocks)

    print(f'=== Shared ({len(shared)}) ===')
    for name in sorted(shared):
        wa = len(a_blocks[name]['content'].split())
        wb = len(b_blocks[name]['content'].split())
        diff = f'({wb - wa:+d})' if wa != wb else '(same)'
        print(f'  {name:<35} {label_a}:{wa:>4}w  {label_b}:{wb:>4}w  {diff}')

    if only_a:
        print(f'\n=== Only in {label_a} ({len(only_a)}) ===')
        for name in sorted(only_a):
            print(f'  {name}')

    if only_b:
        print(f'\n=== Only in {label_b} ({len(only_b)}) ===')
        for name in sorted(only_b):
            print(f'  {name}')


def diff_presets(
    preset_a: dict,
    preset_b: dict,
    label_a: str = "A",
    label_b: str = "B",
    context: int = 3,
) -> dict:
    """Return a structured content-level diff between two presets.

    Unlike :func:`side_by_side` (which only compares word counts), this
    produces a real per-block diff for shared blocks: a unified diff of the
    content, word/char deltas, enabled-state changes, and prompt-variable
    definition changes. Blocks present in only one preset are reported in
    ``only_in_a`` / ``only_in_b``.

    Returns a dict:
        {
          "label_a": ..., "label_b": ...,
          "summary": {"shared": n, "only_a": n, "only_b": n, "changed": n},
          "only_in_a": [names], "only_in_b": [names],
          "changed_blocks": [ {name, words, chars, enabled, variables_changed, diff}, ... ],
        }
    """
    a_blocks = {b["name"]: b for b in preset_blocks(preset_a)}
    b_blocks = {b["name"]: b for b in preset_blocks(preset_b)}

    only_a = sorted(set(a_blocks) - set(b_blocks))
    only_b = sorted(set(b_blocks) - set(a_blocks))
    shared = sorted(set(a_blocks) & set(b_blocks))

    changed_blocks = []
    for name in shared:
        ba = a_blocks[name]
        bb = b_blocks[name]
        ca = ba.get("content") or ""
        cb = bb.get("content") or ""
        ea = ba.get("enabled")
        eb = bb.get("enabled")
        vars_a = ba.get("variables") or []
        vars_b = bb.get("variables") or []
        content_changed = ca != cb
        enabled_changed = ea != eb
        variables_changed = vars_a != vars_b

        if not (content_changed or enabled_changed or variables_changed):
            continue

        entry = {
            "name": name,
            "words": {"a": len(ca.split()), "b": len(cb.split())},
            "chars": {"a": len(ca), "b": len(cb)},
            "enabled": {"a": ea, "b": eb} if enabled_changed else None,
            "variables_changed": variables_changed,
            "content_changed": content_changed,
        }
        if content_changed:
            entry["diff"] = _unified(name, ca, cb, label_a, label_b, context)
        changed_blocks.append(entry)

    return {
        "label_a": label_a,
        "label_b": label_b,
        "summary": {
            "shared": len(shared),
            "only_a": len(only_a),
            "only_b": len(only_b),
            "changed": len(changed_blocks),
        },
        "only_in_a": only_a,
        "only_in_b": only_b,
        "changed_blocks": changed_blocks,
    }


def _unified(name: str, ca: str, cb: str, label_a: str, label_b: str, context: int) -> str:
    """Return a unified diff string for one shared block's content."""
    lines = unified_diff(
        ca.splitlines(keepends=True),
        cb.splitlines(keepends=True),
        fromfile=f"{label_a}/{name}",
        tofile=f"{label_b}/{name}",
        n=context,
    )
    return "".join(lines)
