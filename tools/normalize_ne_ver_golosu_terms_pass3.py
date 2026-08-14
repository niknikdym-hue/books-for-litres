from pathlib import Path

ROOT = Path("ne-ver-golosu/manuscript")

replacements = {
    "07A-TRUST-CHAIN.md": [
        ("Мы скоро будем говорить о provenance цифрового контента — происхождении файла и истории его изменений.", "Мы скоро будем говорить о происхождении цифрового контента — происхождении файла и истории его изменений."),
        ("Но у доверия есть собственное provenance.", "Но у доверия тоже есть собственная история происхождения."),
    ],
    "13A-PUBLIC-EVIDENCE.md": [
        ("платформам, системам цифровой подписи и provenance.", "платформам, системам цифровой подписи и подтверждения происхождения контента."),
        ("Эта последовательность делает разговор о дипфейк гораздо взрослее.", "Эта последовательность делает разговор о дипфейках гораздо взрослее."),
    ],
    "14-LIARS-DIVIDEND.md": [
        ("Несоответствие provenance?", "Несоответствие данных о происхождении?"),
    ],
}

changed = []
for name, pairs in replacements.items():
    path = ROOT / name
    text = path.read_text(encoding="utf-8")
    before = text
    for old, new in pairs:
        if old not in text:
            raise SystemExit(f"Expected text not found in {name}: {old}")
        text = text.replace(old, new)
    if text != before:
        path.write_text(text, encoding="utf-8")
        changed.append(name)

print("Changed:", ", ".join(changed))
