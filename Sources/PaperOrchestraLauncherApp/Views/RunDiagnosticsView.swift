import AppKit
import SwiftUI

import PaperOrchestraLauncherCore

struct RunDiagnosticsView: View {
    let diagnostics: LauncherRunDiagnosticsSnapshot
    let openPath: (String) -> Void
    let revealPath: (String) -> Void
    let copyDiagnostics: (LauncherRunDiagnosticsSnapshot) -> Void
    @State private var selectedLogKind: LauncherLogKind = .stderr

    var body: some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.medium) {
                HStack(alignment: .firstTextBaseline) {
                    Label("Run Diagnostics", systemImage: diagnostics.isStale ? "exclamationmark.triangle.fill" : "waveform.path.ecg")
                        .font(LauncherTypography.cardTitle)
                    Spacer()
                    LauncherStatusBadge(status: diagnostics.workerState)
                }

                if diagnostics.isStale {
                    NativeSurface {
                        HStack(alignment: .top, spacing: LauncherDesignTokens.Spacing.small) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundStyle(LauncherSemanticColors.warning)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Worker process stopped before completion")
                                    .font(LauncherTypography.body.weight(.semibold))
                                Text(diagnostics.attentionMessage ?? "Inspect the worker logs before retrying.")
                                    .font(LauncherTypography.detail)
                                    .foregroundStyle(.secondary)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }

                NativeSurface {
                    VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                        diagnosticRow(label: "Worker", value: diagnostics.workerState.replacingOccurrences(of: "_", with: " ").capitalized)
                        diagnosticRow(label: "PID", value: diagnostics.pid ?? "Not recorded")
                        diagnosticRow(label: "Started", value: diagnostics.startedAt ?? "Not recorded")
                        diagnosticRow(label: "Last event", value: lastEventLabel)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                    pathRow(label: "stdout", path: diagnostics.stdoutLogPath)
                    pathRow(label: "stderr", path: diagnostics.stderrLogPath)
                    pathRow(label: "events", path: diagnostics.eventsLogPath)
                }

                if diagnostics.stderrHasContent {
                    NativeSurface {
                        Label("stderr contains output. Review it before retrying or trusting this run.", systemImage: "exclamationmark.triangle.fill")
                            .font(LauncherTypography.detail)
                            .foregroundStyle(LauncherSemanticColors.warning)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                logViewer

                ViewThatFits(in: .horizontal) {
                    HStack(spacing: LauncherDesignTokens.Spacing.small) {
                        actionButtons
                    }
                    VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                        actionButtons
                    }
                }
            }
        }
        .onAppear(perform: normalizeSelectedLogKind)
        .onChange(of: diagnostics.logs) { _, _ in
            normalizeSelectedLogKind()
        }
    }

    @ViewBuilder
    private var actionButtons: some View {
        Button("View stdout", systemImage: "doc.text") {
            selectedLogKind = .stdout
        }
        .disabled(diagnostics.stdoutLogPath == nil)

        Button("View stderr", systemImage: "exclamationmark.bubble") {
            selectedLogKind = .stderr
        }
        .disabled(diagnostics.stderrLogPath == nil)

        Button("Reveal Run", systemImage: "folder") {
            revealPath(diagnostics.runFolderPath)
        }

        Button("Copy", systemImage: "doc.on.doc") {
            copyDiagnostics(diagnostics)
        }
    }

    private var logViewer: some View {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
            Picker("Log", selection: $selectedLogKind) {
                ForEach(availableLogKinds) { kind in
                    Text(kind.displayName).tag(kind)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()

            NativeSurface {
                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(selectedLogKind.displayName)
                            .font(LauncherTypography.detail.weight(.semibold))
                        Spacer()
                        if let log = selectedLog {
                            Text(logStatus(log))
                                .font(LauncherTypography.fineDetail)
                                .foregroundStyle(.secondary)
                        }
                    }

                    if let log = selectedLog {
                        if let error = log.errorMessage {
                            LauncherEmptyState(title: "Log unavailable", message: error, systemImage: "doc.badge.exclamationmark")
                        } else if log.hasContent {
                            ScrollView {
                                Text(log.text)
                                    .font(.system(.caption, design: .monospaced))
                                    .textSelection(.enabled)
                                    .frame(maxWidth: .infinity, alignment: .topLeading)
                            }
                            .frame(minHeight: 140, maxHeight: 240)
                        } else {
                            LauncherEmptyState(title: "Log is empty", message: "No \(selectedLogKind.displayName) output has been recorded yet.", systemImage: "doc.text")
                        }
                    } else {
                        LauncherEmptyState(title: "Log not recorded", message: "This run has no \(selectedLogKind.displayName) path.", systemImage: "doc.text")
                    }

                    HStack(spacing: LauncherDesignTokens.Spacing.small) {
                        Button("Open Externally", systemImage: "arrow.up.forward.app") {
                            if let path = selectedLog?.path {
                                openPath(path)
                            }
                        }
                        .disabled(selectedLog == nil)

                        Button("Copy Log", systemImage: "doc.on.doc") {
                            if let text = selectedLog?.text {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(text, forType: .string)
                            }
                        }
                        .disabled(selectedLog?.hasContent != true)
                    }
                    .buttonStyle(LauncherSecondaryButtonStyle())
                    .controlSize(.small)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var availableLogKinds: [LauncherLogKind] {
        let available = LauncherLogKind.allCases.filter { diagnostics.log(for: $0) != nil }
        return available.isEmpty ? LauncherLogKind.allCases : available
    }

    private var selectedLog: LauncherLogSnapshot? {
        diagnostics.log(for: selectedLogKind)
    }

    private func normalizeSelectedLogKind() {
        guard diagnostics.log(for: selectedLogKind) == nil else { return }
        selectedLogKind = availableLogKinds.first ?? .events
    }

    private var lastEventLabel: String {
        guard let type = diagnostics.lastEventType, !type.isEmpty else {
            return "No events recorded"
        }
        if let at = diagnostics.lastEventAt, !at.isEmpty {
            return "\(type) at \(at)"
        }
        return type
    }

    private func diagnosticRow(label: String, value: String) -> some View {
        HStack(alignment: .top) {
            Text(label)
                .font(LauncherTypography.fineDetail)
                .foregroundStyle(.secondary)
                .frame(width: 68, alignment: .leading)
            Text(value)
                .font(LauncherTypography.detail)
                .textSelection(.enabled)
            Spacer(minLength: 0)
        }
    }

    private func logStatus(_ log: LauncherLogSnapshot) -> String {
        if log.isTruncated {
            return "\(log.lineCount) tailed lines"
        }
        return "\(log.lineCount) lines"
    }

    @ViewBuilder
    private func pathRow(label: String, path: String?) -> some View {
        if let path, !path.isEmpty {
            Button {
                openPath(path)
            } label: {
                NativeSurface {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(label)
                            .font(LauncherTypography.detail.weight(.semibold))
                        Text(path)
                            .font(LauncherTypography.fineDetail)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .textSelection(.enabled)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .buttonStyle(.plain)
        }
    }
}
