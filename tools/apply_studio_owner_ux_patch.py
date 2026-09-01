from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0:
        if new in text:
            return text
        raise SystemExit(f"missing patch anchor: {label}")
    if count != 1:
        raise SystemExit(f"ambiguous patch anchor {label}: {count}")
    return text.replace(old, new, 1)


def patch_app() -> None:
    path = ROOT / "audiobook-studio/native/AudiobookStudioApp.swift"
    text = path.read_text(encoding="utf-8")

    old_book = '''                        Section("Книга") {
                            LabeledContent("Название", value: book.title)
                            LabeledContent("Автор", value: book.author)
                            LabeledContent("Source filename", value: book.sourceFilename ?? "Недоступно")
                            LabeledContent("Source SHA-256", value: book.sourceSHA256 ?? "Недоступно")
                            LabeledContent("Source integrity", value: book.sourceIntegrity ?? "Недоступно")
                            LabeledContent("TTS working copy", value: book.ttsWorkingCopyStatus == "CREATED" ? "Создана" : "Недоступно")
                            LabeledContent("Backend", value: book.selectedBackend ?? "Не выбран")
                            LabeledContent("Voice profile", value: book.selectedProfileID ?? "Не выбран")
                        }
'''
    new_book = '''                        Section("Книга") {
                            Text(book.title).font(.title2.weight(.semibold))
                            Text(book.author).foregroundStyle(.secondary)
                            HStack {
                                Label(
                                    book.sourceIntegrity == "OK" ? "Исходник защищён" : "Нужно проверить исходник",
                                    systemImage: book.sourceIntegrity == "OK" ? "checkmark.shield.fill" : "exclamationmark.shield.fill"
                                )
                                .foregroundStyle(book.sourceIntegrity == "OK" ? Color.green : Color.red)
                                Spacer()
                                Text(bookPreparationSidebarLabel(book))
                                    .foregroundStyle(book.preparationStatus == "STALE" ? Color.orange : Color.secondary)
                            }
                            DisclosureGroup("Технические сведения") {
                                LabeledContent("Source filename", value: book.sourceFilename ?? "Недоступно")
                                LabeledContent("Source SHA-256", value: book.sourceSHA256 ?? "Недоступно")
                                LabeledContent("TTS working copy", value: book.ttsWorkingCopyStatus == "CREATED" ? "Создана" : "Недоступно")
                                LabeledContent("Backend", value: book.selectedBackend ?? "Не выбран")
                                LabeledContent("Voice profile", value: book.selectedProfileID ?? "Не выбран")
                            }
                            .font(.caption)
                        }
'''
    text = replace_once(text, old_book, new_book, "book-summary")
    text = replace_once(
        text,
        "                        ContentQualitySettingsPanel(selectedBookID: book.id)\n",
        "                        OwnerProductionFlowPanel(model: model, selectedBookID: book.id)\n",
        "owner-flow-mount",
    )
    text = text.replace('Section("Подготовка озвучки")', 'Section("4. Диктор")')
    text = text.replace('Section("Что озвучить")', 'Section("5. Глава для записи")')
    text = text.replace('Section("Проверка готового аудио")', 'Section("6. Прослушивание и приёмка")')

    old_costs = '''                    if model.engine == .qwen {
                        Section("Расходы и лимиты") {
                            Label("Локальный движок · расходы API отсутствуют", systemImage: "laptopcomputer")
                                .foregroundStyle(.secondary)
                        }
                    } else if let billing = model.selectedBilling {
                        Section("Расходы и лимиты") {
                            BillingValueLine(
                                title: "Израсходовано",
                                value: formattedMoney(billing.spent, currency: billing.currency, source: billing.spentSource),
                                detail: provenanceLabel(billing.spentSource)
                            )
                            BillingValueLine(
                                title: "Остаток",
                                value: formattedMoney(billing.remaining, currency: billing.currency, source: billing.remainingSource),
                                detail: billingAvailabilityReason(billing) ?? provenanceLabel(billing.remainingSource)
                            )
                            BillingValueLine(
                                title: "Текущая задача",
                                value: formattedMoney(billing.currentJobEstimate, currency: billing.currency, source: billing.currentJobEstimateSource),
                                detail: billing.provider == "openai" && billing.currentJobEstimate == nil
                                    ? "Точная стоимость будущего аудио заранее неизвестна"
                                    : provenanceLabel(billing.currentJobEstimateSource)
                            )
                            BillingValueLine(
                                title: "После запуска",
                                value: formattedMoney(billing.projectedRemaining, currency: billing.currency, source: billing.projectedRemainingSource),
                                detail: provenanceLabel(billing.projectedRemainingSource)
                            )
                            BillingValueLine(
                                title: "Лимит задачи",
                                value: formattedMoney(billing.hardLimit, currency: billing.currency, source: "local_actual"),
                                detail: "Локальный защитный лимит"
                            )
                            HStack {
                                Text(freshnessLabel(billing))
                                    .font(.caption)
                                    .foregroundStyle(billing.freshness == "stale" ? .orange : .secondary)
                                Spacer()
                                Button("Обновить") { model.refreshBilling(model.engine) }
                            }
                            ForEach(billing.warnings.filter { $0 != "remaining_unavailable" }, id: \.self) { warning in
                                Label(billingWarningLabel(warning), systemImage: "exclamationmark.triangle")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
'''
    text = replace_once(text, old_costs, "", "remove-main-costs")

    cloud_anchor = '''                Section("Cloud Billing") {
                    LabeledContent("Yandex", value: billingSettingsStatus(model.cloudBilling?.providers.yandex))
                    LabeledContent("OpenAI", value: billingSettingsStatus(model.cloudBilling?.providers.openai))
                    HStack {
                        Button("Обновить Yandex") { model.refreshBilling(.yandex) }
                        Button("Обновить OpenAI") { model.refreshBilling(.openai) }
                    }
                    if !model.billingRefreshText.isEmpty {
                        Text(model.billingRefreshText).font(.caption).foregroundStyle(.secondary)
                    }
                }
'''
    moved_costs = cloud_anchor + '''                Section("Расходы и лимиты") {
                    if model.engine == .qwen {
                        Label("Локальный движок · расходы API отсутствуют", systemImage: "laptopcomputer")
                            .foregroundStyle(.secondary)
                    } else if let billing = model.selectedBilling {
                        BillingValueLine(
                            title: "Израсходовано",
                            value: formattedMoney(billing.spent, currency: billing.currency, source: billing.spentSource),
                            detail: provenanceLabel(billing.spentSource)
                        )
                        BillingValueLine(
                            title: "Остаток",
                            value: formattedMoney(billing.remaining, currency: billing.currency, source: billing.remainingSource),
                            detail: billingAvailabilityReason(billing) ?? provenanceLabel(billing.remainingSource)
                        )
                        BillingValueLine(
                            title: "Текущая задача",
                            value: formattedMoney(billing.currentJobEstimate, currency: billing.currency, source: billing.currentJobEstimateSource),
                            detail: billing.provider == "openai" && billing.currentJobEstimate == nil
                                ? "Точная стоимость будущего аудио заранее неизвестна"
                                : provenanceLabel(billing.currentJobEstimateSource)
                        )
                        BillingValueLine(
                            title: "После запуска",
                            value: formattedMoney(billing.projectedRemaining, currency: billing.currency, source: billing.projectedRemainingSource),
                            detail: provenanceLabel(billing.projectedRemainingSource)
                        )
                        BillingValueLine(
                            title: "Лимит задачи",
                            value: formattedMoney(billing.hardLimit, currency: billing.currency, source: "local_actual"),
                            detail: "Локальный защитный лимит"
                        )
                        Button("Обновить данные") { model.refreshBilling(model.engine) }
                    }
                    Text("Расходы вынесены из рабочего экрана записи и находятся только в Настройках.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                ContentQualitySettingsPanel(selectedBookID: model.selectedBookID)
'''
    text = replace_once(text, cloud_anchor, moved_costs, "move-costs-to-settings")
    path.write_text(text, encoding="utf-8")


def patch_opening_credit() -> None:
    path = ROOT / "audiobook-studio/dilon_identity.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'OPENING_CREDIT_TEXT = "Елена Дилон. Хватит себя обесценивать. Читает Dilon Voices."',
        'OPENING_CREDIT_TEXT = "Елена Ди́лон. Хватит себя обесценивать. Читает Dilon Voices."',
        "opening-credit-stress",
    )
    path.write_text(text, encoding="utf-8")


def patch_chapter_assembly() -> None:
    path = ROOT / "audiobook-studio/chapter_assembly.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from book_library import BookLibraryError, normalize_slug\n",
        "from book_library import BookLibraryError, normalize_slug\nfrom book_sound_design import chapter_cue_for_book\n",
        "cue-import",
    )
    old_identity = '''    def _identity(self, payload: Mapping[str, Any], ffmpeg: FFmpegResolution) -> str:
        input_rates = self._input_rates(payload)
        conversion_required = any(rate != TARGET_SAMPLE_RATE_HZ for rate in input_rates)
        contract = {
'''
    new_identity = '''    def _identity(self, payload: Mapping[str, Any], ffmpeg: FFmpegResolution) -> str:
        input_rates = self._input_rates(payload)
        conversion_required = any(rate != TARGET_SAMPLE_RATE_HZ for rate in input_rates)
        chapter_cue = chapter_cue_for_book(self.workspace_root, str(payload["book_slug"]))
        contract = {
            "chapter_cue": chapter_cue,
'''
    text = replace_once(text, old_identity, new_identity, "cue-identity")

    text = replace_once(
        text,
        '''        payload, sources, manifests = self._validate_input(prepared["input"])
        assembly_identity = prepared["assembly_identity"]
''',
        '''        payload, sources, manifests = self._validate_input(prepared["input"])
        chapter_cue = chapter_cue_for_book(self.workspace_root, str(payload["book_slug"]))
        assembly_identity = prepared["assembly_identity"]
''',
        "cue-load",
    )

    segment_anchor = '''                    normalization.append(facts)
                    normalized_paths.append(normalized)
                output_frames, input_frames = self._concatenate_pcm(normalized_paths, temporary_wav)
                concat = {
                    "version": "pcm16_mono_48000_ordered_frames_v1",
                    "ordered_input_count": len(normalized_paths),
                    "ordered_input_frames": input_frames,
                    "output_frames": output_frames,
                    "pause_contract": payload["pause_contract"],
                    "added_pause_frames": 0,
                }
'''
    segment_new = '''                    normalization.append(facts)
                    normalized_paths.append(normalized)
                if chapter_cue is not None:
                    cue_source = _require_real_path(
                        Path(chapter_cue["path"]), root=self.workspace_root, label="Звук перед главой"
                    )
                    if sha256_file(cue_source) != chapter_cue["sha256"]:
                        raise ChapterAssemblyError("chapter_cue_sha_mismatch", "Звук перед главой изменился.")
                    cue_normalized = temporary / "normalized-chapter-cue.wav"
                    cue_facts = self._normalize_source(
                        cue_source,
                        cue_normalized,
                        sample_rate_hz=int(chapter_cue["sample_rate_hz"]),
                        ffmpeg=ffmpeg,
                    )
                    cue_facts.update({"position": 0, "segment_id": "__chapter_cue__", "role": "chapter_cue"})
                    normalization.insert(0, cue_facts)
                    normalized_paths.insert(0, cue_normalized)
                output_frames, input_frames = self._concatenate_pcm(normalized_paths, temporary_wav)
                concat = {
                    "version": "pcm16_mono_48000_ordered_frames_v1",
                    "ordered_input_count": len(normalized_paths),
                    "ordered_input_frames": input_frames,
                    "output_frames": output_frames,
                    "pause_contract": "chapter_cue_then_speech_v1" if chapter_cue is not None else payload["pause_contract"],
                    "added_pause_frames": 0,
                }
'''
    text = replace_once(text, segment_anchor, segment_new, "cue-segments")

    old_else = '''            else:
                facts = self._normalize_source(
                    sources[0], temporary_wav,
                    sample_rate_hz=int(payload["wav"]["sample_rate_hz"]),
                    ffmpeg=ffmpeg,
                )
                facts.update({"position": 1, "segment_id": payload["segment_id"]})
                normalization.append(facts)
                with wave.open(str(temporary_wav), "rb") as result_wave:
                    output_frames = result_wave.getnframes()
                concat = {
                    "version": "source_is_joined_chapter_v1",
                    "ordered_input_count": 1,
                    "ordered_input_frames": [output_frames],
                    "output_frames": output_frames,
                    "pause_contract": "source_is_joined_chapter_v1",
                    "added_pause_frames": 0,
                }
'''
    new_else = '''            else:
                speech_target = temporary / "normalized-speech.wav" if chapter_cue is not None else temporary_wav
                facts = self._normalize_source(
                    sources[0], speech_target,
                    sample_rate_hz=int(payload["wav"]["sample_rate_hz"]),
                    ffmpeg=ffmpeg,
                )
                facts.update({"position": 1, "segment_id": payload["segment_id"]})
                normalization.append(facts)
                if chapter_cue is not None:
                    cue_source = _require_real_path(
                        Path(chapter_cue["path"]), root=self.workspace_root, label="Звук перед главой"
                    )
                    if sha256_file(cue_source) != chapter_cue["sha256"]:
                        raise ChapterAssemblyError("chapter_cue_sha_mismatch", "Звук перед главой изменился.")
                    cue_normalized = temporary / "normalized-chapter-cue.wav"
                    cue_facts = self._normalize_source(
                        cue_source,
                        cue_normalized,
                        sample_rate_hz=int(chapter_cue["sample_rate_hz"]),
                        ffmpeg=ffmpeg,
                    )
                    cue_facts.update({"position": 0, "segment_id": "__chapter_cue__", "role": "chapter_cue"})
                    normalization.insert(0, cue_facts)
                    normalized_paths.extend([cue_normalized, speech_target])
                    output_frames, input_frames = self._concatenate_pcm(normalized_paths, temporary_wav)
                    concat = {
                        "version": "pcm16_mono_48000_ordered_frames_v1",
                        "ordered_input_count": 2,
                        "ordered_input_frames": input_frames,
                        "output_frames": output_frames,
                        "pause_contract": "chapter_cue_then_speech_v1",
                        "added_pause_frames": 0,
                    }
                else:
                    with wave.open(str(temporary_wav), "rb") as result_wave:
                        output_frames = result_wave.getnframes()
                    concat = {
                        "version": "source_is_joined_chapter_v1",
                        "ordered_input_count": 1,
                        "ordered_input_frames": [output_frames],
                        "output_frames": output_frames,
                        "pause_contract": "source_is_joined_chapter_v1",
                        "added_pause_frames": 0,
                    }
'''
    text = replace_once(text, old_else, new_else, "cue-joined-chapter")

    text = replace_once(
        text,
        '''                "input": payload,
                "normalization": {
''',
        '''                "input": payload,
                "chapter_cue": chapter_cue,
                "normalization": {
''',
        "cue-manifest",
    )

    final_revalidate = '''            if revalidate is not None:
                final_payload, _, _ = self._validate_input(revalidate())
                if _canonical_json(final_payload) != _canonical_json(payload):
                    raise ChapterAssemblyError(
                        "assembly_input_became_stale",
                        "Набор сегментов или QA-состояние изменились перед публикацией.",
                    )
            try:
'''
    final_new = '''            if revalidate is not None:
                final_payload, _, _ = self._validate_input(revalidate())
                if _canonical_json(final_payload) != _canonical_json(payload):
                    raise ChapterAssemblyError(
                        "assembly_input_became_stale",
                        "Набор сегментов или QA-состояние изменились перед публикацией.",
                    )
            if chapter_cue_for_book(self.workspace_root, str(payload["book_slug"])) != chapter_cue:
                raise ChapterAssemblyError(
                    "chapter_cue_changed_during_assembly",
                    "Выбор звука перед главой изменился во время сборки.",
                )
            try:
'''
    text = replace_once(text, final_revalidate, final_new, "cue-final-revalidate")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_app()
    patch_opening_credit()
    patch_chapter_assembly()


if __name__ == "__main__":
    main()
