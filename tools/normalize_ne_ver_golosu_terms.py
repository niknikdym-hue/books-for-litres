from pathlib import Path
import re

ROOT = Path("ne-ver-golosu")
MANUSCRIPT = ROOT / "manuscript"

REPLACEMENTS = {
    "02-FACE.md": [
        ("deepfake-технологией", "технологией дипфейков"),
        ("случайные human-in-the-loop cues — NIST упоминает подобные меры как дополнительный слой", "случайные проверочные действия с участием человека — NIST упоминает подобные меры как дополнительный слой"),
        ("не сводить проблему к deepfake detection", "не сводить проблему к выявлению дипфейков"),
        ("Так называемые cheapfakes или shallowfakes напоминают неприятную вещь", "Так называемые простые подделки — манипуляции с настоящим контентом без сложного синтеза — напоминают неприятную вещь"),
        ("«Это действительно CFO?»", "«Это действительно финансовый директор?»"),
        ("«как выполнить распоряжение CFO?»", "«как выполнить распоряжение финансового директора?»"),
    ],
    "03-MESSAGES.md": [
        ("так называемые knowledge-based вопросы — сведения вроде девичьей фамилии матери или фактов из кредитной истории", "так называемые контрольные вопросы, основанные на знании биографических сведений, — например, о девичьей фамилии матери или фактах из кредитной истории"),
    ],
    "11A-WHO-IS-REAL.md": [
        ("в актуальном семействе Digital Identity Guidelines разделяет", "в актуальном семействе рекомендаций по цифровой идентичности (Digital Identity Guidelines) разделяет"),
        ("Это область **identity proofing**: установление заявленной идентичности и проверка доказательств, на которых она основана.", "Это область **установления личности (identity proofing)**: проверки заявленной идентичности и доказательств, на которых она основана."),
        ("стандарт отдельно учитывает forged media и digital injection — поддельные или внедрённые медиапотоки.", "стандарт отдельно учитывает поддельные медиа и атаки с внедрением цифрового медиапотока."),
        ("серьёзный remote identity proofing складывается", "серьёзное удалённое установление личности складывается"),
        ("Это **authentication**.", "Это **аутентификация (authentication)**."),
        ("Пароль, аппаратный ключ, passkey, одноразовый код", "Пароль, аппаратный ключ, ключ доступа (passkey), одноразовый код"),
        ("остаётся **authorization** — полномочия.", "остаётся **авторизация (authorization)** — проверка полномочий."),
        ("authorization — широкий базовый security concept, а не ещё один «уровень AAL»", "авторизация — базовое понятие информационной безопасности, а не ещё один «уровень надёжности аутентификации»"),
        ("понятие — **authentication intent**.", "понятие — **подтверждение намерения аутентифицироваться (authentication intent)**."),
        ("обычные OTP-механизмы и phishing-resistant authentication.", "обычные механизмы одноразовых паролей (OTP) и устойчивую к фишингу аутентификацию."),
        ("Именно поэтому passkeys и другие криптографические механизмы", "Именно поэтому ключи доступа и другие криптографические механизмы"),
        ("Liveness-механизмы — повысить уверенность", "Механизмы проверки живого присутствия (liveness) — повысить уверенность"),
        ("между **identity attack** и **decision attack**.", "между **атакой на личность** и **атакой на решение**."),
        ("Deepfake способен участвовать", "Дипфейк способен участвовать"),
        ("## Liveness — не экзамен, который нужно проводить родственнику", "## Проверка живого присутствия — не экзамен, который нужно проводить родственнику"),
        ("Профессиональные требования к remote proofing иногда включают случайные human-in-the-loop действия", "Профессиональные требования к удалённому установлению личности иногда включают случайные проверочные действия с участием человека"),
        ("обнаружить forged media в attended-сценарии", "обнаружить поддельные медиа в процедуре с участием оператора"),
        ("лабораторию liveness detection", "лабораторию проверки живого присутствия"),
    ],
    "12-DETECTORS-PROVENANCE.md": [
        ("«synthetic»", "«синтетический материал»"),
        ("идея: **provenance**, происхождение цифрового материала.", "идея: **происхождение цифрового материала (provenance)**."),
        ("Coalition for Content Provenance and Authenticity — C2PA — развивает", "Коалиция по происхождению и подлинности контента (Coalition for Content Provenance and Authenticity, C2PA) развивает"),
        ("В упрощённом виде Content Credential содержит", "В упрощённом виде запись Content Credentials содержит"),
        ("Provenance может сказать", "Система происхождения может показать"),
        ("что нужно понимать о provenance", "что нужно понимать о происхождении цифрового материала"),
        ("специалистом по forensic-анализу изображения", "специалистом по экспертному анализу изображения"),
    ],
    "13-DIGITAL-DOUBLE.md": [
        ("один deepfake способен", "один дипфейк способен"),
    ],
    "13A-PUBLIC-EVIDENCE.md": [
        ("технология provenance так важна", "технология подтверждения происхождения так важна"),
        ("C2PA описывает provenance как историю цифрового актива", "C2PA описывает происхождение цифрового материала как историю цифрового актива"),
        ("Content Credentials позволяют хранить криптографически проверяемые assertions — утверждения о создании, обработке, устройстве, действиях и других элементах истории материала.", "Content Credentials позволяют хранить криптографически проверяемые утверждения о создании, обработке, устройстве, действиях и других элементах истории материала."),
        ("объявить provenance data «хорошими» или «плохими»", "объявить данные о происхождении «хорошими» или «плохими»"),
        ("что соответствующие assertions действительно связаны", "что соответствующие утверждения действительно связаны"),
        ("**Authenticity не равна truth.**", "**Подлинность не равна истинности.**"),
        ("Это не слабость provenance.", "Это не слабость технологии подтверждения происхождения."),
        ("внешнее хранилище provenance", "внешнее хранилище данных о происхождении"),
        ("не требует forensic-лаборатории", "не требует экспертной лаборатории"),
        ("Исследования real-world deepfake detection в последние годы", "Исследования выявления дипфейков в реальных условиях в последние годы"),
        ("слово «deepfake detector»", "выражение «детектор дипфейков»"),
        ("«видео CEO»", "«видео генерального директора»"),
    ],
    "14-LIARS-DIVIDEND.md": [
        ("**liar's dividend — дивидендом лжеца**", "**дивидендом лжеца (liar's dividend)**"),
        ("всей темы deepfake", "всей темы дипфейков"),
        ("что это misinformation или deepfake", "что это дезинформация или дипфейк"),
        ("Ложные заявления о misinformation", "Ложные заявления о «дезинформации»"),
        ("заявления «это deepfake»", "заявления «это дипфейк»"),
        ("слово «deepfake» не является техническим заключением", "слово «дипфейк» не является техническим заключением"),
        ("значение provenance шире", "значение проверяемого происхождения шире"),
        ("заявление «это deepfake» против видеоматериала", "заявление «это дипфейк» против видеоматериала"),
        ("Самый опасный deepfake будущего", "Самый опасный дипфейк будущего"),
    ],
    "16-APPENDICES.md": [
        ("автоматический deepfake detector", "автоматический детектор дипфейков"),
        ("**BEC (Business Email Compromise)** — класс делового мошенничества", "**Компрометация деловой электронной почты (BEC, Business Email Compromise)** — класс делового мошенничества"),
        ("**Provenance / происхождение контента**", "**Происхождение контента (provenance)**"),
        ("**Digital injection attack** — внедрение изменённого или искусственно созданного цифрового медиапотока", "**Атака с внедрением цифрового медиапотока (digital injection attack)** — внедрение изменённого или искусственно созданного цифрового медиапотока"),
        ("**False positive** — система ошибочно считает настоящий материал поддельным.", "**Ложноположительный результат (false positive)** — система ошибочно считает настоящий материал поддельным."),
        ("**False negative** — система ошибочно пропускает поддельный материал как настоящий.", "**Ложноотрицательный результат (false negative)** — система ошибочно пропускает поддельный материал как настоящий."),
        ("**Liar's dividend / дивиденд лжеца**", "**Дивиденд лжеца (liar's dividend)**"),
        ("**NIST** — Digital Identity Guidelines и материалы о рисках synthetic content.", "**NIST** — рекомендации по цифровой идентичности (Digital Identity Guidelines) и материалы о рисках синтетического контента."),
        ("**FTC Consumer Advice** — потребительские рекомендации, включая family emergency scams и voice cloning.", "**FTC Consumer Advice** — потребительские рекомендации, включая мошеннические сценарии с семейной чрезвычайной ситуацией и клонированием голоса."),
        ("статистики именно AI/deepfake incidents", "статистики именно инцидентов с ИИ и дипфейками"),
    ],
}

changed = []
not_found = []

for filename, pairs in REPLACEMENTS.items():
    path = MANUSCRIPT / filename
    text = path.read_text(encoding="utf-8")
    original = text
    for old, new in pairs:
        if old not in text:
            not_found.append(f"{filename}: {old}")
            continue
        text = text.replace(old, new)
    # Remaining bare English spelling of deepfake in narrative is not useful.
    text = re.sub(r"\bDeepfake\b", "Дипфейк", text)
    text = re.sub(r"\bdeepfake\b", "дипфейк", text)
    if text != original:
        path.write_text(text, encoding="utf-8")
        changed.append(filename)

style_path = ROOT / "04-STYLE-FACTCHECK-SAFETY.md"
style = style_path.read_text(encoding="utf-8")
marker = "## Терминология и англоязычные термины"
if marker not in style:
    style += """

## Терминология и англоязычные термины

- Основной текст пишется на русском языке; англоязычный термин не используется там, где есть точный и естественный русский эквивалент.
- Если английский термин нужен для точности, поиска первоисточника или связи с профессиональной терминологией, при первом упоминании даётся русский термин, затем оригинал в скобках. Дальше используется русский вариант.
- Официальные названия стандартов, организаций, спецификаций и продуктов (например, NIST, C2PA, Content Credentials) сохраняются в официальной форме; при необходимости перед ними даётся русское пояснение.
- Не использовать в русском повествовании гибриды вроде `deepfake detection`, `forensic-анализ`, `knowledge-based вопросы`, `human-in-the-loop cues`, если смысл можно передать нормальным русским языком.
- В словаре русский термин ставится первым; английский эквивалент в скобках допускается как справочный.
"""
    style_path.write_text(style, encoding="utf-8")
    changed.append(str(style_path.relative_to(ROOT)))

# Audit remaining Latin-script vocabulary in narrative files. Sources are excluded;
# official names/acronyms are expected and reviewed separately.
allowed = {
    "NIST", "SP", "C2PA", "Content", "Credentials", "Credential", "PDF", "WhatsApp",
    "FBI", "IC3", "INTERPOL", "Europol", "FTC", "Consumer", "Advice", "BEC",
    "Business", "Email", "Compromise", "Digital", "Identity", "Guidelines",
    "Coalition", "for", "Provenance", "and", "Authenticity", "passkey", "provenance",
    "authentication", "authorization", "intent", "liveness", "OTP", "liar", "s",
    "dividend", "digital", "injection", "attack", "false", "positive", "negative",
}

unknown = {}
for path in sorted(MANUSCRIPT.glob("*.md")):
    if path.name == "17-SOURCES.md":
        continue
    text = path.read_text(encoding="utf-8")
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    extras = sorted({w for w in words if w not in allowed and not re.fullmatch(r"[A-Z]{2,8}", w)})
    if extras:
        unknown[path.name] = extras

print("Changed:", ", ".join(changed) or "none")
if not_found:
    print("Expected strings not found:")
    for item in not_found:
        print(" -", item)
if unknown:
    print("Remaining Latin-script terms requiring editorial review:")
    for name, words in unknown.items():
        print(f" - {name}: {', '.join(words)}")
else:
    print("No unreviewed Latin-script terms remain outside sources.")
