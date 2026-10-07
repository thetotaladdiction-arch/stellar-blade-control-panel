pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "../DesignSystem/Status.js" as Status
import "../components" as Ui
import "SupportLink.js" as SupportLink

// Support (IA-SPEC 2.5, FINAL-VISUAL-SPEC 4.5): one column, most-used first.
//  1. Fix problems: health chip; Health Check, Reconnect Game Mods and
//     One-Click Repair; old UE4SS files in Binaries\Win64 when there are any.
//  2. Save history: the automatic save copies, Restore (game closed),
//     Undo restore, Open folder, Back up now.
//  3. Get help: Copy Version Info, Open Reports, Create Bug Report (one zip,
//     File Explorer opens with it selected), and the quiet update line.
//  4. Activity log, 5. Technical details, 6. What's new: collapsed cards.
// Safe Reset, Force Quit (now in the top bar's Game menu), the "Game stuck"
// row and the Game performance tiles are gone.
Ui.PageScroll {
    id: root
    property var appBackend
    property var windowRoot
    pageId: "support"

    readonly property var telemetryValues: root.appBackend ? root.appBackend.gameTelemetry.values : ({})
    readonly property var oldUe4ssFiles: root.appBackend && root.appBackend.oldUe4ssFiles
                                         ? root.appBackend.oldUe4ssFiles : []
    readonly property var monthNames: ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    // Diagnostics only: why the hardware may be running below full clocks.
    function hardwareLimitsText() {
        return root.appBackend.gameTelemetry.hardwareLimitsSummary
    }

    // "UE4SS.dll, UE4SS-settings.ini and xinput1_3.dll"
    function namesText(names) {
        if (names.length <= 1)
            return names.join("")
        return names.slice(0, names.length - 1).join(", ") + " and " + names[names.length - 1]
    }

    // One cell of the three-button grid (ButtonRow), so buttons that sit on
    // their own at the right line up with the rows above them.
    function gridCell(rowWidth) {
        var gap = root.tokens ? root.tokens.spaceXs : 8
        return rowWidth >= 600 ? (rowWidth - 2 * gap) / 3 : (rowWidth - gap) / 2
    }

    // "4 kept · last Sep 28, 12:23" under Save history's list.
    readonly property string saveBackupsLine: {
        var b = root.appBackend
        if (!b)
            return ""
        if (b.saveSnapshotBusy)
            return "Checking your saves…"
        var kept = String(b.saveSnapshotSummary || "")
        var line = kept.length === 0 || kept === "None yet" ? "No copies yet"
                                                            : kept.replace(", last ", " · last ")
        return b.saveSnapshotNote.length > 0 ? b.saveSnapshotNote + " " + line : line
    }

    readonly property string logText: root.appBackend ? String(root.appBackend.issueLog || "") : ""
    // The log is newest first, so its first line is the last entry.
    readonly property string lastLogEntry: {
        if (root.logText.length === 0)
            return "No entries yet"
        // plain_issue_line shows each line as "[Sep 29, 7:51 PM] ..."
        var m = /^\[([A-Z][a-z]{2}) (\d{1,2}), (\d{1,2}:\d{2} [AP]M)\]/.exec(root.logText)
        if (!m)
            return ""
        var now = new Date()
        var today = m[1] === root.monthNames[now.getMonth()] && Number(m[2]) === now.getDate()
        return "Last entry " + (today ? "" : m[1] + " " + m[2] + ", ") + m[3]
    }

    function refreshOldUe4ss() {
        if (root.appBackend && root.appBackend.refreshOldUe4ssFiles)
            root.appBackend.refreshOldUe4ssFiles()
    }
    Component.onCompleted: root.refreshOldUe4ss()
    onActiveChanged: if (root.active) root.refreshOldUe4ss()

    // Technical details row: label on the left, the whole value on the right
    // (wrapped, never cut), and an optional 13 px note under it.
    component DetailRow: ColumnLayout {
        id: detail
        property string label: ""
        property string value: ""
        property string hint: ""
        property bool showSeparator: true

        Layout.fillWidth: true
        Layout.minimumWidth: 0
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 10
            Layout.bottomMargin: 10
            spacing: root.tokens.spaceMd

            Text {
                Layout.preferredWidth: 168
                Layout.alignment: Qt.AlignTop
                text: detail.label
                textFormat: Text.PlainText
                color: root.tokens.textPrimary
                font.pixelSize: root.tokens.fontBody
                font.hintingPreference: root.tokens.textHinting
                elide: Text.ElideRight
                maximumLineCount: 1
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: 1
                spacing: root.tokens.spaceXxs

                Text {
                    Layout.fillWidth: true
                    text: detail.value
                    textFormat: Text.PlainText
                    color: root.tokens.textSecondary
                    font.pixelSize: root.tokens.fontCaption
                    font.hintingPreference: root.tokens.textHinting
                    font.features: { "tnum": 1 }
                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                }
                Text {
                    Layout.fillWidth: true
                    visible: detail.hint.length > 0
                    text: detail.hint
                    textFormat: Text.PlainText
                    color: root.tokens.textMuted
                    font.pixelSize: root.tokens.fontHint
                    font.hintingPreference: root.tokens.textHinting
                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: root.tokens.hairlineW
            visible: detail.showSeparator
            color: root.tokens.hairline
        }
    }

    // The fixed-height box the log and the notes scroll in.
    component TextBox: Item {
        id: box
        property string text: ""
        property int textFormat: Text.PlainText
        property int inset: 10
        property real lineHeight: 1.0
        property string emptyText: ""

        Layout.fillWidth: true
        clip: true

        Ui.NotchFrame {
            anchors.fill: parent
            tokens: root.tokens
            notch: root.tokens.notchSmall
            fillColor: root.tokens.logBg
            strokeColor: root.tokens.hairline
        }
        Ui.EmptyState {
            anchors.centerIn: parent
            width: parent.width - 24
            visible: box.text.length === 0 && box.emptyText.length > 0
            tokens: root.tokens
            message: box.emptyText
        }
        Ui.LogScrollBox {
            anchors.fill: parent
            visible: box.text.length > 0
            tokens: root.tokens
            inset: box.inset
            text: box.text
            textFormat: box.textFormat
            lineHeight: box.lineHeight
        }
    }

    // 1. Fix problems
    Ui.SbCard {
        objectName: "supportFixProblems"
        appBackend: root.appBackend
        tokens: root.tokens
        icon: "support"
        title: "Fix problems"
        subtitle: root.appBackend.backendBusy
                  ? "Working… this can take a few seconds."
                  : "Check the panel and game mods, and fix what can be repaired."
        helpTip: "Health Check only looks for problems. One-Click Repair fixes what it can and reports anything still unresolved. "
                 + "Reconnect Game Mods refreshes the link between the panel and the game mods."
        status: root.appBackend.backendBusy ? "Working" : Status.healthLabel(root.appBackend.healthLevel)
        statusKind: root.appBackend.backendBusy ? "warn" : Status.healthKind(root.appBackend.healthLevel)
        bodySpacing: root.tokens.spaceSm

        Ui.ButtonRow {
            tokens: root.tokens
            Ui.SbButton {
                tokens: root.tokens
                text: "Health Check"
                enabled: !root.appBackend.backendBusy
                onClicked: root.appBackend.runHealthCheck()
            }
            Ui.SbButton {
                tokens: root.tokens
                text: "Reconnect Game Mods"
                enabled: !root.appBackend.backendBusy
                onClicked: root.appBackend.resetPanelLink()
            }
            Ui.SbButton {
                objectName: "supportOneClickRepair"
                tokens: root.tokens
                text: "One-Click Repair"
                variant: "primary"
                enabled: !root.appBackend.backendBusy
                onClicked: repairDialog.open()
            }
        }

        // One-Click Repair asks first (spec 5.14). It changes files, so Enter
        // and Esc both mean Cancel.
        Ui.SbDialog {
            id: repairDialog
            objectName: "supportRepairDialog"
            tokens: root.tokens
            title: "Run One-Click Repair?"
            body: "It checks the panel and game mods, finds your saves, and fixes what it can. "
                  + "Close Stellar Blade first for the most complete repair."
            iconName: "support"
            iconKind: "warn"
            acceptText: "Repair"
            onAccepted: root.appBackend.runOneClickRepair()
        }

        // Files an older UE4SS left straight in Binaries\Win64. Below the
        // buttons, so the buttons never move when it shows.
        Item {
            objectName: "supportOldUe4ss"
            visible: root.oldUe4ssFiles.length > 0
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            implicitHeight: noticeRow.implicitHeight + 2 * root.tokens.spaceSm

            Ui.NotchFrame {
                anchors.fill: parent
                tokens: root.tokens
                notch: root.tokens.notchControl
                fillColor: root.tokens.alpha(root.tokens.statusWarn, 0.08)
                strokeColor: root.tokens.alpha(root.tokens.statusWarn, 0.35)
            }

            RowLayout {
                id: noticeRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: root.tokens.spaceSm
                anchors.rightMargin: root.tokens.spaceSm
                spacing: root.tokens.spaceSm

                Ui.SbIcon {
                    Layout.alignment: Qt.AlignTop
                    tokens: root.tokens
                    name: "warning"
                    size: root.tokens.iconSize
                    color: root.tokens.statusWarn
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: root.tokens.spaceXxs

                    Text {
                        Layout.fillWidth: true
                        text: "Old mod loader files found"
                        textFormat: Text.PlainText
                        color: root.tokens.statusWarnInk
                        font.pixelSize: root.tokens.fontBody
                        font.family: root.tokens.typeSemibold
                        font.weight: Font.DemiBold
                        font.hintingPreference: root.tokens.textHinting
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        objectName: "supportOldUe4ssFiles"
                        Layout.fillWidth: true
                        text: root.namesText(root.oldUe4ssFiles) + " in SB\\Binaries\\Win64 "
                              + (root.oldUe4ssFiles.length > 1 ? "are" : "is")
                              + " from an older mod loader install and can stop the game mods from working."
                              + (root.appBackend.gameRunning ? " Close the game to move them." : "")
                        textFormat: Text.PlainText
                        color: root.tokens.textSecondary
                        font.pixelSize: root.tokens.fontHint
                        font.hintingPreference: root.tokens.textHinting
                        wrapMode: Text.WordWrap
                    }
                }

                Ui.SbButton {
                    id: moveOldButton
                    objectName: "supportMoveOldUe4ss"
                    Layout.alignment: Qt.AlignVCenter
                    tokens: root.tokens
                    text: "Move old files to a backup folder"
                    // Windows keeps the files locked while the game runs.
                    enabled: !root.appBackend.gameRunning
                    onClicked: root.appBackend.moveOldUe4ssFiles()
                    Ui.SbToolTip {
                        tokens: root.tokens
                        visible: moveOldButton.hovered
                        text: "Moves them into a new dated folder next to them. Nothing is deleted."
                    }
                }
            }
        }
    }

    // 2. Save history: a checked copy of the save folder when the panel
    // opens, when the game starts and each time the game saves (older ones
    // thinned out by age counted in time the game saved,
    // services/save_snapshots.retained), and Restore. Near the end of the game a story choice decides
    // the ending and the game saves over it; picking a copy from before it
    // is the way back. Restore works only while the game is closed and
    // first copies the save as it is now ("Before restore"), so Undo
    // restore can put that back.
    Ui.SbCard {
        id: saveCard
        objectName: "supportSaveHistory"
        appBackend: root.appBackend
        tokens: root.tokens
        icon: "save"
        title: "Save history"
        subtitle: "Made a choice you regret? Close the game, pick a time from before it, press Restore."
        helpTip: "Restore keeps your current graphics settings. A checked copy of your saves is made when the panel opens, when the game starts and "
                 + "each time the game saves. Every copy from the last 15 minutes is kept, then one per "
                 + "10 minutes for 3 hours of play, one per hour for 2 days of play and one per day for the "
                 + "last 30 days you played (time away from the game does not count). Restore "
                 + "first copies your save as it is now (\"Before restore\", always kept), so you can undo "
                 + "it. If Steam then asks about a cloud conflict, pick the save on this PC (Local)."
        status: root.appBackend.saveRestoreBusy ? "Working"
                : root.appBackend.saveSnapshotNote.length > 0 ? "Last backup failed" : ""
        statusKind: "warn"
        bodySpacing: root.tokens.spaceSm

        readonly property var rows: root.appBackend && root.appBackend.saveHistory
                                    ? root.appBackend.saveHistory : []
        readonly property bool canRestore: !root.appBackend.gameRunning && !root.appBackend.saveRestoreBusy
        // The row the dialog asks about ("" = Undo restore).
        property string pendingName: ""
        property string pendingWhen: ""

        function askRestore(name, when) {
            saveCard.pendingName = name
            saveCard.pendingWhen = when
            restoreDialog.open()
        }

        // The copies, newest first: time, why it was made, Restore.
        Item {
            objectName: "supportSaveHistoryList"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredHeight: saveCard.rows.length === 0 ? 72
                                    : Math.min(5, saveCard.rows.length) * 44 + 12
            clip: true

            Ui.NotchFrame {
                anchors.fill: parent
                tokens: root.tokens
                notch: root.tokens.notchSmall
                fillColor: root.tokens.logBg
                strokeColor: root.tokens.hairline
            }
            Ui.EmptyState {
                anchors.centerIn: parent
                width: parent.width - 24
                visible: saveCard.rows.length === 0
                tokens: root.tokens
                message: "No copies yet. One is made when the panel opens and each time the game saves."
            }
            Ui.FixedScrollBox {
                anchors.fill: parent
                visible: saveCard.rows.length > 0
                tokens: root.tokens
                inset: 6

                Repeater {
                    model: saveCard.rows

                    delegate: Item {
                        id: row
                        required property var modelData
                        required property int index
                        objectName: "supportSaveHistoryRow"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: 44

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: root.tokens.hairlineW
                            visible: row.index < saveCard.rows.length - 1
                            color: root.tokens.hairline
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 4
                            spacing: root.tokens.spaceSm

                            Text {
                                Layout.preferredWidth: 150
                                text: String(row.modelData.when || "")
                                textFormat: Text.PlainText
                                color: root.tokens.textPrimary
                                font.pixelSize: root.tokens.fontBody
                                font.features: { "tnum": 1 }
                                font.hintingPreference: root.tokens.textHinting
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: String(row.modelData.label || "")
                                textFormat: Text.PlainText
                                color: root.tokens.textSecondary
                                font.pixelSize: root.tokens.fontCaption
                                font.hintingPreference: root.tokens.textHinting
                                elide: Text.ElideRight
                            }
                            Ui.SbButton {
                                objectName: "supportSaveRestore"
                                tokens: root.tokens
                                compact: true
                                text: "Restore"
                                enabled: saveCard.canRestore
                                Accessible.name: "Restore the save from " + String(row.modelData.when || "")
                                onClicked: saveCard.askRestore(String(row.modelData.name || ""),
                                                               String(row.modelData.when || ""))
                            }
                        }
                    }
                }
            }
        }

        // What is true now: the game must be closed to restore, a restore
        // is running, or how the last one went.
        Text {
            objectName: "supportSaveRestoreNote"
            Layout.fillWidth: true
            visible: text.length > 0
            text: root.appBackend.saveRestoreBusy ? "Restoring…"
                  : root.appBackend.saveRestoreNote.length > 0 ? root.appBackend.saveRestoreNote
                  : root.appBackend.gameRunning && saveCard.rows.length > 0 ? "Close the game to restore."
                  : ""
            textFormat: Text.PlainText
            color: root.appBackend.saveRestoreNote.indexOf("Restored") === 0
                   || root.appBackend.saveRestoreNote.indexOf("Undone") === 0
                   ? root.tokens.statusOkInk : root.tokens.textSecondary
            font.pixelSize: root.tokens.fontCaption
            font.hintingPreference: root.tokens.textHinting
            wrapMode: Text.WordWrap
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            spacing: root.tokens.spaceXs

            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: root.saveBackupsLine
                textFormat: Text.PlainText
                color: root.tokens.textMuted
                font.pixelSize: root.tokens.fontHint
                font.hintingPreference: root.tokens.textHinting
                wrapMode: Text.WordWrap
            }
            Ui.SbButton {
                objectName: "supportSaveUndo"
                visible: root.appBackend.saveUndoAvailable
                Layout.preferredHeight: root.tokens.btnHeight
                tokens: root.tokens
                text: "Undo restore"
                enabled: saveCard.canRestore
                onClicked: saveCard.askRestore("", "")
            }
            Ui.SbButton {
                Layout.preferredWidth: root.gridCell(saveCard.width - 2 * saveCard.padX)
                Layout.preferredHeight: root.tokens.btnHeight
                tokens: root.tokens
                text: "Open folder"
                onClicked: root.appBackend.openSaveSnapshotsFolder()
            }
            Ui.SbButton {
                Layout.preferredWidth: root.gridCell(saveCard.width - 2 * saveCard.padX)
                Layout.preferredHeight: root.tokens.btnHeight
                tokens: root.tokens
                text: "Back up now"
                variant: "primary"
                enabled: !root.appBackend.saveBusy && !root.appBackend.saveRestoreBusy
                onClicked: root.appBackend.backupSaves()
            }
        }

        // One plain sentence before anything is changed. Enter and Esc
        // both mean Cancel.
        Ui.SbDialog {
            id: restoreDialog
            objectName: "supportRestoreDialog"
            tokens: root.tokens
            title: saveCard.pendingName.length > 0
                   ? "Restore the save from " + saveCard.pendingWhen + "?"
                   : "Undo the restore?"
            body: (saveCard.pendingName.length > 0
                   ? "Your save as it is now is kept first (\"Before restore\"), so you can undo this."
                   : "Your save goes back to how it was just before the restore.")
                  + " If Steam then asks about a cloud conflict, pick the save on this PC (Local)."
            iconName: "save"
            iconKind: "warn"
            acceptText: saveCard.pendingName.length > 0 ? "Restore" : "Undo restore"
            onAccepted: {
                if (saveCard.pendingName.length > 0)
                    root.appBackend.restoreSaveSnapshot(saveCard.pendingName)
                else
                    root.appBackend.undoSaveRestore()
            }
        }
    }

    // 3. Get help, in the order you use it.
    Ui.SbCard {
        objectName: "supportGetHelp"
        appBackend: root.appBackend
        tokens: root.tokens
        icon: "report"
        title: "Get help"
        subtitle: "Create a bug report, then send it to the mod author."
        helpTip: "The bug report is one zip with the panel's and game mods' logs, versions and settings. "
                 + "Your Windows user name is taken out, and your save files are never included."
        bodySpacing: root.tokens.spaceSm

        Ui.ButtonRow {
            tokens: root.tokens
            Ui.SbButton {
                tokens: root.tokens
                text: "Copy Version Info"
                onClicked: root.appBackend.copyVersionDetails()
            }
            Ui.SbButton {
                tokens: root.tokens
                text: "Open Reports"
                onClicked: root.appBackend.openReportsFolder()
            }
            Ui.SbButton {
                objectName: "supportCreateBugReport"
                tokens: root.tokens
                text: root.appBackend.supportBusy ? "Working…" : "Create Bug Report"
                variant: "primary"
                enabled: !root.appBackend.supportBusy
                onClicked: root.appBackend.createBugReport()
            }
        }

        // After a report: the one thing to do with it (File Explorer is
        // already open with the file selected).
        Ui.FriendlyNote {
            objectName: "supportBugReportSaved"
            visible: String(root.appBackend.lastBugReport || "").length > 0
            tokens: root.tokens
            summary: "Send this file to the mod author with a short description of what happened."
            detail: "Saved as " + root.appBackend.lastBugReport + " in the Reports folder."
        }

        Ui.UpdateNotice {
            objectName: "supportUpdateNotice"
            tokens: root.tokens
            appBackend: root.appBackend
        }

        // Hidden until SupportLink.SHOW_SUPPORT_LINK is true.
        Text {
            objectName: "supportAuthorLink"
            visible: SupportLink.SHOW_SUPPORT_LINK
            Layout.alignment: Qt.AlignRight
            text: "Support the author"
            textFormat: Text.PlainText
            color: linkHover.hovered || activeFocus ? root.tokens.accent : root.tokens.textMuted
            font.pixelSize: root.tokens.fontHint
            font.hintingPreference: root.tokens.textHinting
            font.underline: true
            activeFocusOnTab: visible
            Accessible.role: Accessible.Link
            Accessible.name: text
            Keys.onReturnPressed: Qt.openUrlExternally(SupportLink.SUPPORT_URL)
            Keys.onSpacePressed: Qt.openUrlExternally(SupportLink.SUPPORT_URL)

            HoverHandler { id: linkHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: Qt.openUrlExternally(SupportLink.SUPPORT_URL) }
        }
    }

    // 4. Activity log: newest first, so the box opens at the newest line
    // (Backend._read_issue_tail).
    Ui.CollapsibleSection {
        objectName: "supportActivityLog"
        appBackend: root.appBackend
        tokens: root.tokens
        icon: "log"
        title: "Activity log"
        subtitle: "Panel and game mod messages, newest first."
        summary: root.lastLogEntry
        expanded: false

        TextBox {
            Layout.preferredHeight: 240
            text: root.logText
            emptyText: "No activity yet. Panel actions and mod messages will appear here."
        }
    }

    // 5. Technical details: developer detail lives only here.
    Ui.CollapsibleSection {
        id: detailsCard
        objectName: "supportTechnicalDetails"
        appBackend: root.appBackend
        tokens: root.tokens
        icon: "chip"
        title: "Technical details"
        subtitle: "For support reports and advanced checks."
        // Plain words in the folded summary; the exact graphics API is in
        // the "Panel graphics" row inside.
        summary: {
            var mode = root.appBackend.panelRendererMode
            if (mode === "checking") return "Checking graphics"
            if (mode === "hardware") return "Graphics card in use"
            if (mode === "software_override") return "Software graphics selected"
            if (mode === "safe_mode") return "Graphics compatibility mode"
            return "Software graphics"
        }
        onExpandedChanged: if (expanded) root.appBackend.refreshExternalFramePolicy()
        expanded: false
        bodySpacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.bottomMargin: root.tokens.spaceXxs
            spacing: root.tokens.spaceXs

            Item { Layout.fillWidth: true }
            Ui.SbButton {
                Layout.preferredWidth: root.gridCell(detailsCard.width - 2 * detailsCard.padX)
                Layout.preferredHeight: root.tokens.btnHeight
                tokens: root.tokens
                text: "Test the Panel"
                enabled: !root.appBackend.backendBusy
                onClicked: root.appBackend.runPanelSelfTest()
            }
        }

        DetailRow {
            label: "Panel graphics"
            value: root.appBackend.panelRendererSummary
        }
        DetailRow {
            label: "Overlay detection"
            value: root.appBackend.panelGraphicsIsolationSummary
        }
        DetailRow {
            label: "Panel redraws"
            // 2.5.503: frames follow the monitor while something moves and
            // stop while nothing changes. The row itself changes once a second,
            // so it reads the counter only while the card is open: folded, it
            // never redraws the page at rest (2.5.504 pace probe: 1 frame/s).
            value: !detailsCard.expanded ? ""
                   : !root.appBackend.performance.frameSampleFresh ? "Measuring…"
                   : root.appBackend.performance.fps < 0.5 ? "None while nothing moves"
                   : root.appBackend.performance.fps.toFixed(0) + " per second, only when something changes"
        }
        DetailRow {
            label: "Item filtering time"
            value: root.appBackend.performance.catalogFilterMs > 0
                   ? root.appBackend.performance.catalogFilterMs.toFixed(2) + " ms" : "No search yet"
        }
        DetailRow {
            label: "Last task"
            // "No completed job", or the job and how long it took.
            value: root.appBackend.performance.backendJobMs > 0
                   ? root.appBackend.performance.backendJobName + " · "
                     + root.appBackend.performance.backendJobMs.toFixed(0) + " ms"
                   : root.appBackend.performance.backendJobName
        }
        DetailRow {
            label: "Hardware limits"
            value: root.hardwareLimitsText()
        }
        DetailRow {
            label: "Numbers from"
            value: root.appBackend.gameTelemetry.sourceSummary
        }
        DetailRow {
            label: "Frame rate caps"
            value: root.appBackend.externalFramePolicySummary
        }
        // Instant Boss Restart's game mod: version, state, phase, restarts
        // and the last result, as its status file says (the cards show words).
        DetailRow {
            objectName: "supportBossRestart"
            label: "Instant Boss Restart"
            value: root.appBackend.bossDiagnostics
        }

        // The activity log's lines with their level, area and technical
        // detail (reason codes, file names): the Activity log card shows
        // plain words only. Read only while this card is open.
        Text {
            Layout.fillWidth: true
            Layout.topMargin: 10
            Layout.bottomMargin: root.tokens.spaceXs
            text: "Technical log"
            textFormat: Text.PlainText
            color: root.tokens.textPrimary
            font.pixelSize: root.tokens.fontBody
            font.hintingPreference: root.tokens.textHinting
        }
        TextBox {
            objectName: "supportTechnicalLog"
            Layout.preferredHeight: 200
            Layout.bottomMargin: root.tokens.spaceXxs
            text: detailsCard.expanded ? String(root.appBackend.technicalLog || "") : ""
            emptyText: "No entries yet."
        }
    }

    // 6. What's new (was Patch notes).
    Ui.CollapsibleSection {
        objectName: "supportWhatsNew"
        appBackend: root.appBackend
        tokens: root.tokens
        icon: "appearance"
        title: "What's new"
        subtitle: root.appBackend ? "Version " + root.appBackend.version : ""
        summary: root.appBackend ? "Version " + root.appBackend.version : ""
        expanded: false

        // Headings and one list item per change, wrapped to the box's width
        // (Backend._friendly_patch_notes).
        TextBox {
            Layout.preferredHeight: 300
            inset: 12
            lineHeight: 1.25
            textFormat: Text.StyledText
            text: root.appBackend.patchNotes
        }
    }
}
