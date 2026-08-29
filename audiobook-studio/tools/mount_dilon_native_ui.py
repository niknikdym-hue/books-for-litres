#!/usr/bin/env python3
from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "native" / "AudiobookStudioApp.swift"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one marker, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    source = APP.read_text(encoding="utf-8")
    if "@StateObject private var dilonFlow = DilonNativeFlowController()" in source:
        raise SystemExit("Dilon native UI is already mounted")

    source = replace_once(
        source,
        "struct StudioView: View {\n    @ObservedObject var model: StudioModel\n",
        "@MainActor\nstruct StudioView: View {\n    @ObservedObject var model: StudioModel\n"
        "    @StateObject private var dilonFlow = DilonNativeFlowController()\n",
        "StudioView state",
    )

    source = replace_once(
        source,
        "    @State private var newBookSlug = \"\"\n\n    var body: some View {",
        "    @State private var newBookSlug = \"\"\n\n"
        "    private var dilonSelectionKey: String {\n"
        "        \"\\(model.selectedBookID)\\u{1f}\\(model.selectedJobID)\"\n"
        "    }\n\n"
        "    private func syncDilonSelection() {\n"
        "        guard let book = model.selectedBook, book.kind == \"production\",\n"
        "              let job = model.selectedJob, job.kind == \"chapter\" else {\n"
        "            dilonFlow.selectionDidChange(\n"
        "                bookName: \"\", jobID: \"\", player: model.audioPlayer\n"
        "            )\n"
        "            return\n"
        "        }\n"
        "        dilonFlow.selectionDidChange(\n"
        "            bookName: book.id, jobID: job.id, player: model.audioPlayer\n"
        "        )\n"
        "    }\n\n"
        "    var body: some View {",
        "Dilon selection lifecycle helpers",
    )

    source = replace_once(
        source,
        "                    AudioQAReviewSection(model: model)\n\n                    if model.engine == .qwen {",
        "                    AudioQAReviewSection(model: model)\n\n"
        "                    if let snapshot = dilonFlow.snapshot {\n"
        "                        DilonNativeCard(\n"
        "                            snapshot: snapshot,\n"
        "                            player: model.audioPlayer,\n"
        "                            selectedCandidateID: $dilonFlow.selectedCandidateID,\n"
        "                            onApproveListenedCandidate: { candidate in\n"
        "                                dilonFlow.approveListenedCandidate(\n"
        "                                    candidate, player: model.audioPlayer\n"
        "                                )\n"
        "                            }\n"
        "                        )\n"
        "                        if !dilonFlow.statusText.isEmpty {\n"
        "                            Section(\"Dilon Voices status\") {\n"
        "                                Label(dilonFlow.statusText, systemImage: \"checkmark.shield.fill\")\n"
        "                                    .foregroundStyle(.green)\n"
        "                            }\n"
        "                        }\n"
        "                    } else if model.selectedBook?.kind == \"production\",\n"
        "                              model.selectedJob?.kind == \"chapter\" {\n"
        "                        Section(\"Dilon Voices\") {\n"
        "                            if dilonFlow.isLoading {\n"
        "                                ProgressView(\"Проверяется Dilon identity…\")\n"
        "                            } else if let error = dilonFlow.errorMessage {\n"
        "                                Label(error, systemImage: \"lock.shield\")\n"
        "                                    .foregroundStyle(.secondary)\n"
        "                                Button(\"Обновить Dilon status\") {\n"
        "                                    dilonFlow.refresh(player: model.audioPlayer)\n"
        "                                }\n"
        "                            } else {\n"
        "                                Label(\"Dilon identity пока недоступен\", systemImage: \"lock.fill\")\n"
        "                                    .foregroundStyle(.secondary)\n"
        "                            }\n"
        "                        }\n"
        "                    }\n\n"
        "                    if model.engine == .qwen {",
        "Dilon mounted form section",
    )

    source = replace_once(
        source,
        "            .navigationTitle(model.selectedBook?.title ?? \"Audiobook Studio\")\n            .onChange(of: model.selectedBookID)",
        "            .navigationTitle(model.selectedBook?.title ?? \"Audiobook Studio\")\n"
        "            .task(id: dilonSelectionKey) {\n"
        "                syncDilonSelection()\n"
        "            }\n"
        "            .onChange(of: model.selectedBookID)",
        "Dilon task lifecycle",
    )

    APP.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
