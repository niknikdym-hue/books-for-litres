#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'manuscript'
FILES = sorted(ROOT.glob('*.md'))
texts = [p.read_text(encoding='utf-8') for p in FILES]
total = sum(len(t) for t in texts)
words = sum(len(t.split()) for t in texts)
print(f'files={len(FILES)} chars_with_spaces={total} words={words}')
for p,t in zip(FILES,texts):
    print(f'{p.name}: chars={len(t)} words={len(t.split())}')
if not (280000 <= total <= 320000):
    raise SystemExit(f'FULL_BOOK_LENGTH FAIL: {total} chars; target 280000..320000')
print('FULL_BOOK_LENGTH PASS')
