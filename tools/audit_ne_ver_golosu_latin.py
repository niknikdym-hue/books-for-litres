from pathlib import Path
import re
from collections import defaultdict

ROOT = Path('ne-ver-golosu/manuscript')
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'’.-]*")
URL = re.compile(r'https?://\S+|www\.\S+')
ITALIC = re.compile(r'\*[^*]+\*')
BOLD = re.compile(r'\*\*[^*]+\*\*')

hits = defaultdict(list)
for path in sorted(ROOT.glob('*.md')):
    if path.name.startswith('.'):
        continue
    for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        clean = URL.sub('', line)
        # In the bibliography, original publication/institution names are allowed
        # and should not be mistaken for untranslated reader-facing terminology.
        if path.name == '17-SOURCES.md':
            clean = BOLD.sub('', clean)
            clean = ITALIC.sub('', clean)
        tokens = TOKEN.findall(clean)
        if not tokens:
            continue
        for token in tokens:
            hits[token].append((path.name, lineno, line.strip()))

for token in sorted(hits, key=lambda t: (-len(hits[t]), t.lower())):
    print(f'\n### {token} — {len(hits[token])}')
    for fname, lineno, line in hits[token][:15]:
        print(f'{fname}:{lineno}: {line}')
    if len(hits[token]) > 15:
        print(f'... +{len(hits[token]) - 15} more')
