from pathlib import Path
import re

ROOT = Path('ne-ver-golosu/manuscript')
patterns = [
    r'атакующ', r'злоумышлен', r'мошенник', r'атака', r'атаке', r'атаки',
    r'его задача', r'задача —', r'задача:', r'ему достаточно', r'достаточно .*чтобы',
    r'контролир', r'легенд', r'перенос.*довер', r'наслед.*довер', r'порог довер',
    r'социальн.*инженер', r'фишинг', r'скомпрометирован', r'обход', r'обойти',
    r'срочност', r'секретност', r'изол', r'вход →', r'подтверждение легенды',
]
rx = re.compile('|'.join(f'(?:{p})' for p in patterns), re.I)

for path in sorted(ROOT.glob('*.md')):
    if path.name.startswith('.') or path.name == '17-SOURCES.md':
        continue
    lines = path.read_text(encoding='utf-8').splitlines()
    hits = []
    for i, line in enumerate(lines, 1):
        if rx.search(line):
            hits.append((i, line.strip()))
    if hits:
        print(f'\n## {path.name} — {len(hits)}')
        for i, line in hits:
            print(f'{i}: {line}')
