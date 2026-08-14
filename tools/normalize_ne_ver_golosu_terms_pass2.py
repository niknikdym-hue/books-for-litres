from pathlib import Path
import re

ROOT = Path("ne-ver-golosu")
MANUSCRIPT = ROOT / "manuscript"

REPLACEMENTS = {
    "05-DECISION.md": [
        ("включая deepfake-видео, изображения, аудио и чат-боты", "включая дипфейки в видео и аудио, синтетические изображения и чат-боты"),
        ("сочетания текстовых сообщений, AI-generated voice и перехода на новые платформы", "сочетания текстовых сообщений, синтетического голоса и перехода на новые платформы"),
    ],
    "07-KNOWLEDGE.md": [
        ("профессиональные стандарты цифровой идентичности давно относятся к knowledge-based проверкам скептически", "профессиональные стандарты цифровой идентичности давно относятся скептически к проверкам, основанным на знании биографических сведений"),
    ],
    "09-RISK.md": [
        ("В профессиональной цифровой идентичности используется понятие assurance — степень уверенности, необходимая для конкретной операции.", "В профессиональной цифровой идентичности используется понятие уровня уверенности — степени уверенности, необходимой для конкретной операции."),
    ],
    "10-FAMILY.md": [
        ("Разговор о deepfake fraud часто строится", "Разговор о мошенничестве с дипфейками часто строится"),
    ],
    "11-BUSINESS.md": [
        ("Это разница между поиском виноватого и post-incident review.", "Это разница между поиском виноватого и разбором инцидента."),
        ("### BEC старше генеративного ИИ\n\nBusiness Email Compromise — мошенничество с компрометацией или имитацией деловой переписки — не появилось вместе с нейросетями.", "### Компрометация деловой переписки старше генеративного ИИ\n\nКомпрометация деловой электронной почты (Business Email Compromise, BEC) — мошенничество с компрометацией или имитацией деловой переписки — не появилась вместе с нейросетями."),
        ("правило «платёж выше X подтверждают два человека»", "правило «платёж выше установленного лимита подтверждают два человека»"),
        ("### HR: «директор попросил прислать документы»", "### Кадровая служба: «директор попросил прислать документы»"),
        ("HR хранит персональные данные сотрудников.", "Кадровая служба хранит персональные данные сотрудников."),
        ("IT — права доступа.", "ИТ — права доступа."),
        ("Настоящий HR не должен просить код MFA.", "Настоящий сотрудник кадровой службы не должен просить код многофакторной аутентификации."),
        ("Голос, видео, email или мессенджер", "Голос, видео, электронная почта или мессенджер"),
        ("CEO, собственник, финансовый директор и любой другой руководитель", "Генеральный директор, собственник, финансовый директор и любой другой руководитель"),
    ],
    "15-CONCLUSION.md": [
        ("набор секретных признаков deepfake", "набор секретных признаков дипфейка"),
    ],
}

changed = []
missing = []
for filename, pairs in REPLACEMENTS.items():
    path = MANUSCRIPT / filename
    text = path.read_text(encoding="utf-8")
    original = text
    for old, new in pairs:
        if old not in text:
            missing.append(f"{filename}: {old}")
        else:
            text = text.replace(old, new)
    if text != original:
        path.write_text(text, encoding="utf-8")
        changed.append(filename)

# A focused audit: Latin-script prose that is neither an official name/product/standard
# nor an English equivalent deliberately retained once in parentheses/glossary.
allowed_exact = {
    "WhatsApp", "PDF", "NIST", "C2PA", "Content", "Credentials", "Credential",
    "FBI", "IC3", "INTERPOL", "UNODC", "FTC", "Consumer", "Advice", "Europol",
    "BEC", "Business", "Email", "Compromise", "Digital", "Identity", "Guidelines",
    "Coalition", "for", "Provenance", "and", "Authenticity", "identity", "proofing",
    "authentication", "authorization", "intent", "passkey", "liveness", "OTP",
    "digital", "injection", "attack", "false", "positive", "negative", "liar's",
    "dividend", "Kaylyn", "Jackson", "Schiff", "Daniel", "Natália", "Bueno",
}

unknown = {}
for path in sorted(MANUSCRIPT.glob("*.md")):
    if path.name == "17-SOURCES.md":
        continue
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'-]*", path.read_text(encoding="utf-8"))
    extras = sorted({
        w for w in words
        if w not in allowed_exact
        and not re.fullmatch(r"[A-Z]{1,8}", w)
        and not re.fullmatch(r"[A-Z]-", w)
    })
    if extras:
        unknown[path.name] = extras

print("Changed:", ", ".join(changed) or "none")
if missing:
    print("Expected strings not found:")
    for item in missing:
        print(" -", item)
if unknown:
    print("Remaining Latin-script terms requiring editorial review:")
    for name, words in unknown.items():
        print(f" - {name}: {', '.join(words)}")
else:
    print("No unreviewed Latin-script terms remain outside sources.")
