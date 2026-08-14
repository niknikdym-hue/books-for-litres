# Примечание об источниках

Фактологический срез этой книги сделан на **14 августа 2026 года**. Технологии синтетического контента, стандарты и законодательство меняются; для быстро меняющихся утверждений в тексте сознательно избегаются универсальные численные обещания и рейтинги конкретных сервисов.

Ниже перечислены основные источники, на которых основаны проверяемые факты, реальные кейсы и технические/правовые границы книги.

## К прологу и главе 1

**Federal Trade Commission (FTC).** *Scammers Use Fake Emergencies To Steal Your Money.* Официальная потребительская памятка о family-emergency scams, включая использование AI voice cloning, срочность, секретность и рекомендацию независимо связаться с близким по известному номеру.
https://consumer.ftc.gov/articles/scammers-use-fake-emergencies-steal-your-money

**FTC.** *Scammers use AI to enhance their family emergency schemes*, 20 марта 2023 года.
https://consumer.ftc.gov/consumer-alerts/2023/03/scammers-use-ai-enhance-their-family-emergency-schemes

**FTC.** Материалы Voice Cloning Challenge и публикации о предотвращении вреда от AI-enabled voice cloning. Использованы для общей рамки возможностей и законных/вредоносных применений; конкретные быстро устаревающие показатели не переносились в текст как универсальные свойства отрасли.
https://www.ftc.gov/news-events/news/press-releases/2023/11/ftc-announces-exploratory-challenge-prevent-harms-ai-enabled-voice-cloning

**Банк России.** *Мошенники обманывают людей с помощью дипфейков*, 15 августа 2024 года.
https://www.cbr.ru/information_security/pmp/15082024/

## К главе 2

**Government of the Hong Kong Special Administrative Region.** *LCQ9: Combating frauds involving deepfake*, 26 июня 2024 года.
https://www.info.gov.hk/gia/general/202406/26/P2024062600192p.htm

Это первичный источник для двух корпоративных кейсов 2024 года. В книге сохранено важное уточнение официального сообщения: январская видеоконференция описана полицией как **предварительно записанная**, без реального взаимодействия с изображёнными участниками. Медийная версия о полностью интерактивной «живой комнате дипфейков» не используется как установленный факт.

**NIST.** *SP 800-63A-4, Digital Identity Guidelines: Identity Proofing and Enrollment*, финальная версия, июль 2025 года. Раздел Digital Injection Prevention and Forged Media Detection.
https://pages.nist.gov/800-63-4/sp800-63a.html

## К главам 3 и 7

**Federal Bureau of Investigation (FBI).** *Senior U.S. Officials Impersonated in Malicious Messaging Campaign*, 15 мая 2025 года, и обновление от 19 декабря 2025 года. Официально описаны кампании с текстовыми сообщениями и AI-generated voice, сменой платформ и рекомендацией независимо подтверждать контактные данные.
https://www.fbi.gov/investigate/cyber/alerts/2025/senior-us-officials-impersonated-in-malicious-messaging-campaign
https://www.fbi.gov/investigate/cyber/alerts/2025/senior-us-officials-continue-to-be-impersonated-in-malicious-messaging-campaign

**NIST.** *Digital Identity Guidelines, SP 800-63-4* и связанные разделы об аутентификаторах/identity proofing. Использованы для ограничения роли knowledge-based вопросов как современной аутентификации.
https://pages.nist.gov/800-63-4/

## К главам 4 и 12

**NIST.** *AI 100-4: Reducing Risks Posed by Synthetic Content: An Overview of Technical Approaches to Digital Content Transparency*, опубликован 20 ноября 2024 года, обновлённая страница доступна в 2026 году.
https://www.nist.gov/publications/reducing-risks-posed-synthetic-content-overview-technical-approaches-digital-content

**NIST.** *SP 800-63A-4.* Использованы положения о forged-media detection, необходимости измерять false positive/false negative, защищённых каналах и многослойном контроле.
https://pages.nist.gov/800-63-4/sp800-63a.html

**Coalition for Content Provenance and Authenticity (C2PA).** *Content Credentials: C2PA Technical Specification 2.4*, апрель 2026 года.
https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html

Спецификация использована для понятий provenance, assertions, claim signature, manifest и Content Credentials. В книге отдельно подчёркнуто: криптографически проверяемая история происхождения не равна доказательству истинности всех слов или событий внутри материала.

## К главам 5 и 6

**Банк России.** Интервью заместителя Председателя Банка России Германа Зубарева, 6 февраля 2026 года. Использована позиция регулятора о deepfake fraud как одной из ключевых угроз 2026 года и различие между дипфейком как средством входа в доверие и последующим действием жертвы.
https://www.cbr.ru/press/event/?id=28288

**Банк России.** Материалы о психологических приёмах финансовых мошенников: страх, давление и требование срочного решения.
https://www.cbr.ru/Reception/TopicalMessage/Page/3406

**INTERPOL.** *INTERPOL-UNODC global summit ends with call to action against fraud surge*, 17 марта 2026 года. Использована международная оценка роли generative AI, включая deepfake video/images/audio и chatbots, в облегчении имперсонации доверенных лиц.
https://www.interpol.int/en/News-and-Events/News/2026/INTERPOL-UNODC-global-summit-ends-with-call-to-action-against-fraud-surge

## К главам 8–11

**FTC.** Family emergency guidance — для принципа независимого обратного звонка по известному контакту.

**FBI.** *Business Email Compromise.* Официальная памятка: самостоятельно находить номер компании, отдельно подтверждать платёжные запросы и изменения банковских данных, использовать многофакторную защиту.
https://www.fbi.gov/how-we-can-help-you/scams-and-safety/common-frauds-and-scams/business-email-compromise

**FBI / IC3.** *Business Email Compromise: Virtual Meeting Platforms*, 2022. Использовано как подтверждение того, что бизнес-имперсонация может сочетать компрометированную переписку, virtual meeting, статическое изображение/deepfake audio и последующую коммуникацию; конкретные тактики изготовления в книге не описываются.

**NIST SP 800-63-4.** Общий risk-based принцип assurance использован как интеллектуальная опора главы 9. Бытовая трёхзонная модель книги является авторской и не выдаётся за официальный стандарт NIST.

## К главе 13: право России

Правовые положения актуализированы на дату фактологического среза. Книга не является индивидуальной юридической консультацией и не обещает одинаковой квалификации для всех deepfake-кейсов.

**Гражданский кодекс РФ, ст. 152.** Защита чести, достоинства и деловой репутации.
https://www.consultant.ru/document/cons_doc_LAW_5142/1de6cd3cbb386056a2ecd2c64ff087b13c8de585/

**ГК РФ, ст. 152.1.** Охрана изображения гражданина.
https://www.consultant.ru/document/cons_doc_LAW_5142/14c6c3902cffa17ab26d330b2fd4fae28e5cd059/

**ГК РФ, ст. 152.2.** Охрана частной жизни гражданина.
https://www.consultant.ru/document/cons_doc_LAW_5142/9c307a0f2164645c15ca4e3146ff5f6e56060b23/

**Федеральный закон от 27.07.2006 №152-ФЗ «О персональных данных»**, редакция от 26.07.2026 на дату проверки. В частности, ст. 7, 9, 11.
https://www.consultant.ru/document/cons_doc_LAW_61801/

Критическое ограничение: ст. 11 связывает понятие биометрических персональных данных с физиологическими/биологическими особенностями, на основании которых можно установить личность и которые используются оператором для установления личности. Поэтому книга не называет любую фотографию или любую запись голоса биометрическими персональными данными автоматически.

## К главе 14

**Robert Chesney, Danielle Keats Citron.** *Deep Fakes: A Looming Challenge for Privacy, Democracy, and National Security*, California Law Review, 2019. Источник концепции liar's dividend.

**Kaylyn Jackson Schiff, Daniel S. Schiff, Natália S. Bueno.** *The Liar’s Dividend: Can Politicians Claim Misinformation to Evade Accountability?* American Political Science Review, online publication 20 февраля 2024 года; Volume 119, Issue 1, 2025, pp. 71–90.
https://www.cambridge.org/core/journals/american-political-science-review/article/liars-dividend-can-politicians-claim-misinformation-to-evade-accountability/687FEE54DBD7ED0C96D72B26606AA073

Исследование включало пять preregistered survey experiments с более чем 15 000 взрослыми американцами. В книге сохранено важное ограничение результата: эффект ложных заявлений о misinformation был устойчивее для текстовых историй; утверждения о deepfake против видеодоказательств в большинстве тестов не давали такого же устойчивого эффекта.

## Принцип чтения цифр

В книге намеренно не используется общая статистика мошенничества как «статистика дипфейков». Там, где упоминается сумма конкретного инцидента, она привязана к первичному официальному сообщению. Там, где приводится исследовательская выборка, обозначены предмет и география исследования.

## Обновление

Читателю, которому нужны рекомендации после даты фактологического среза, следует проверять актуальные материалы Банка России, NIST, FTC, FBI/IC3, INTERPOL/Europol, C2PA и действующие редакции российского законодательства.
