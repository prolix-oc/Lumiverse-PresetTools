"""
tokenizer module — real Claude token counts instead of chars // 4.

`audit.token_count` uses the chars//4 heuristic, which is fine for prose but
badly *undercounts* the dense stuff ThreadBare is full of: macro soup
(`{{if::{{getvar::x}}}}...`) and inline-CSS HTML can run ~25-45% more tokens
than chars//4 predicts. This module counts with the actual Claude tokenizer.

It loads the legacy Claude byte-level BPE tokenizer (65k vocab) — the SAME
`tokenizer.json` that LenML's `@lenml/tokenizer-claude` ships for JS — through
HuggingFace's `tokenizers` library, which reproduces Anthropic's
NFKC + ByteLevel + BPE pipeline byte-for-byte. So counts match LenML.

Requirements:
    python3 -m pip install --user tokenizers

The tokenizer data file is resolved in this order:
    1. explicit `path=` argument
    2. $CLAUDE_TOKENIZER_JSON environment variable
    3. claude_tokenizer.json bundled next to this module  (the default)
    4. a LenML @lenml/tokenizer-claude install found under $HOME

Accuracy note: this is the *legacy* Claude tokenizer (claude-v1/v2 era) — the
only Claude tokenizer published in a loadable form, and what LenML exposes.
Claude 3/4 use an unpublished tokenizer; against it this runs within a few
percent, and the only ground truth is the Anthropic API `count_tokens`
endpoint. For offline preset budgeting it is far closer than chars//4.

Quick start:
    from preset_tools import load, count_preset, token_audit
    p = load('ThreadBare 1.0.json')
    chars, tokens = count_preset(p, enabled_only=True)   # real token total
    token_audit(p)                                        # per-block table

CLI:
    python3 -m preset_tools.tokenizer 'ThreadBare 1.0.json'
    python3 -m preset_tools.tokenizer 'ThreadBare 1.0.json' --enabled-only --top 15
"""

import os
import glob
import functools

from .io import preset_blocks

_BUNDLED = os.path.join(os.path.dirname(__file__), 'claude_tokenizer.json')

# Shallow (non-recursive) globs — fast, no deep filesystem walk.
_LENML_GLOBS = [
    '~/*/node_modules/@lenml/tokenizer-claude/models/tokenizer.json',
    '~/*/*/node_modules/@lenml/tokenizer-claude/models/tokenizer.json',
    '~/Documents/*/node_modules/@lenml/tokenizer-claude/models/tokenizer.json',
]


def find_tokenizer_json(path: str = None) -> str:
    """
    Resolve the path to a Claude tokenizer.json.

    Order: explicit path -> $CLAUDE_TOKENIZER_JSON -> bundled -> LenML install.
    Raises FileNotFoundError with guidance if none is found.
    """
    candidates = []
    if path:
        candidates.append(path)
    env = os.environ.get('CLAUDE_TOKENIZER_JSON')
    if env:
        candidates.append(env)
    candidates.append(_BUNDLED)
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    for pattern in _LENML_GLOBS:
        hits = glob.glob(os.path.expanduser(pattern))
        if hits:
            return hits[0]
    raise FileNotFoundError(
        "No Claude tokenizer.json found. Tried: "
        + ", ".join(repr(c) for c in candidates)
        + ". Pass path=, set $CLAUDE_TOKENIZER_JSON, or keep "
          "claude_tokenizer.json next to this module."
    )


@functools.lru_cache(maxsize=4)
def get_tokenizer(path: str = None):
    """Load and cache the Claude tokenizer. Lazily imports `tokenizers`."""
    try:
        from tokenizers import Tokenizer
    except ImportError as e:
        raise ImportError(
            "The `tokenizers` package is required for real token counts. "
            "Install it with:  python3 -m pip install --user tokenizers"
        ) from e
    return Tokenizer.from_file(find_tokenizer_json(path))


def count_tokens(text: str, path: str = None, add_special_tokens: bool = False) -> int:
    """Count Claude tokens in a string (special tokens excluded by default)."""
    if not text:
        return 0
    enc = get_tokenizer(path).encode(text, add_special_tokens=add_special_tokens)
    return len(enc.ids)


def count_preset(preset: dict, enabled_only: bool = True, path: str = None) -> tuple:
    """
    Return (char_count, real_token_count) for the preset.

    Same signature shape as audit.token_count, but uses the real tokenizer.
    Set enabled_only=False to count every block regardless of toggle state.
    """
    tok = get_tokenizer(path)
    chars = toks = 0
    for b in preset_blocks(preset):
        if enabled_only and not b.get('enabled'):
            continue
        c = b.get('content', '') or ''
        chars += len(c)
        toks += len(tok.encode(c, add_special_tokens=False).ids)
    return chars, toks


def count_blocks(preset: dict, enabled_only: bool = False, path: str = None) -> list:
    """
    Per-block real token counts.

    Returns a list of dicts: index, name, enabled, marker, chars, tokens
    (real), approx (chars//4), delta (tokens - approx).
    """
    tok = get_tokenizer(path)
    out = []
    for i, b in enumerate(preset_blocks(preset)):
        if enabled_only and not b.get('enabled'):
            continue
        c = b.get('content', '') or ''
        real = len(tok.encode(c, add_special_tokens=False).ids)
        approx = len(c) // 4
        out.append({
            'index': i,
            'name': b['name'],
            'enabled': b.get('enabled', False),
            'marker': b.get('marker'),
            'chars': len(c),
            'tokens': real,
            'approx': approx,
            'delta': real - approx,
        })
    return out


def token_audit(preset: dict, enabled_only: bool = False, path: str = None,
                top: int = None) -> None:
    """
    Print per-block real token counts next to the chars//4 estimate.

    `top` limits the listing to the N heaviest blocks (by real tokens);
    totals always reflect the full set selected by `enabled_only`.
    """
    rows = count_blocks(preset, enabled_only=enabled_only, path=path)

    enabled_real = sum(r['tokens'] for r in rows if r['enabled'])
    enabled_approx = sum(r['approx'] for r in rows if r['enabled'])
    all_real = sum(r['tokens'] for r in rows)
    all_approx = sum(r['approx'] for r in rows)

    listing = sorted(rows, key=lambda r: r['tokens'], reverse=True)[:top] if top else rows

    print(f'{"#":>3}  {"":1} {"name":<35} {"chars":>6} {"~c/4":>6} {"real":>6} {"Δ":>6}')
    print('-' * 70)
    for r in listing:
        flag = '✅' if r['enabled'] else '❌'
        mark = f' [{r["marker"]}]' if r['marker'] else ''
        print(f'{r["index"]+1:>3}  {flag} {r["name"]:<35} '
              f'{r["chars"]:>6} {r["approx"]:>6} {r["tokens"]:>6} {r["delta"]:>+6}{mark}')

    def pct(real, approx):
        return f'{(real - approx) / real * 100:+.1f}%' if real else 'n/a'

    print('-' * 70)
    print(f'ENABLED:  {enabled_real:>6} real tokens   vs chars//4 {enabled_approx:>6}   '
          f'(estimate off by {pct(enabled_real, enabled_approx)})')
    print(f'ALL:      {all_real:>6} real tokens   vs chars//4 {all_approx:>6}   '
          f'(estimate off by {pct(all_real, all_approx)})')


if __name__ == '__main__':
    import argparse
    from .io import load

    ap = argparse.ArgumentParser(
        description='Count real Claude tokens per preset block (vs the chars//4 estimate).')
    ap.add_argument('preset', help='path to the preset .json')
    ap.add_argument('--enabled-only', action='store_true',
                    help='only count enabled (active) blocks')
    ap.add_argument('--top', type=int, metavar='N',
                    help='list only the N heaviest blocks')
    ap.add_argument('--path', metavar='FILE',
                    help='explicit tokenizer.json (overrides discovery)')
    args = ap.parse_args()

    token_audit(load(args.preset), enabled_only=args.enabled_only,
                path=args.path, top=args.top)
