import QtQuick
import QtQuick.Effects
import "." as Ui

// The one toast (FINAL-VISUAL-SPEC.md 5.13). main.qml places it at the
// bottom centre of the content column (never over the sidebar), 16 px above
// the window's bottom edge. 320-480 px wide, at least 48 px tall; raised
// surface, 8 px notch, a 3 px bar on the left in the status colour, a 20 px
// status icon, the message, an optional compact action ("Fix") and a close
// button.
//
// One at a time; later messages wait in a queue. A success closes itself
// after 4 s, a warning after 8 s (the game-side "Pick an item first."
// prompts are warnings), an error stays until it is closed. Hovering pauses
// the countdown. In over 200 ms (opacity, y +8 -> 0), out over 160 ms.
//
// "info" (an activity-log INFO line: "Starting Stellar Blade: working on
// it...", "Closing Stellar Blade...") is a note, not a success: the accent
// colour and the info icon, never the green check. It gives way: newer news
// replaces an info toast on screen at once, and info toasts still waiting in
// the queue are dropped (build 4c live test: the signed-out warning waited
// about 4 s behind "working on it...").
Item {
    id: root
    property var tokens: null
    // The message on screen and its kind ("ok", "info", "warn", "error").
    property string message: ""
    property string kind: "ok"
    property string actionText: ""
    property var queue: []
    property bool shown: false
    // Animated rise; y bindings stay intact.
    property real rise: 0

    signal actionTriggered(string message)

    readonly property color tone: !root.tokens ? "#62dca0"
                                  : root.kind === "error" ? root.tokens.statusError
                                  : root.kind === "warn" ? root.tokens.statusWarn
                                  : root.kind === "info" ? root.tokens.statusInfo
                                  : root.tokens.statusOk
    readonly property int holdMs: root.kind === "error" ? 0
                                  : root.kind === "warn" ? 8000
                                  : (root.tokens ? root.tokens.toastSuccessMs : 4000)

    function show(text, kind, action) {
        var entry = { text: String(text || ""), kind: kind || "ok", action: action || "" }
        if (entry.text.length === 0)
            return
        if (root.shown) {
            // The same words again only restart the countdown.
            if (entry.text === root.message && entry.kind === root.kind) {
                holdTimer.restart()
                return
            }
            // Newer news supersedes a progress note, on screen or queued.
            var next = root.queue.filter(function (queued) { return queued.kind !== "info" })
            if (root.kind === "info") {
                root.queue = next
                root.present(entry)
                return
            }
            next.push(entry)
            root.queue = next
            return
        }
        root.present(entry)
    }
    function present(entry) {
        root.message = entry.text
        root.kind = entry.kind
        root.actionText = entry.action
        root.shown = true
        riseAnim.from = root.tokens ? root.tokens.pageRise : 8
        riseAnim.restart()
        if (root.holdMs > 0)
            holdTimer.restart()
        else
            holdTimer.stop()
    }
    function dismiss() {
        holdTimer.stop()
        root.shown = false
    }
    function presentNext() {
        if (root.shown || root.queue.length === 0)
            return
        var next = root.queue.slice()
        var entry = next.shift()
        root.queue = next
        root.present(entry)
    }

    width: Math.max(root.tokens ? root.tokens.toastMinWidth : 320,
                    Math.min(root.tokens ? root.tokens.toastMaxWidth : 480, row.x + row.implicitWidth + 12 + 32 + 8))
    height: Math.max(48, row.implicitHeight + 16)
    visible: opacity > 0
    opacity: root.shown ? 1 : 0
    enabled: root.shown
    transform: Translate { y: root.rise }

    Behavior on opacity {
        NumberAnimation {
            duration: root.shown ? (root.tokens ? root.tokens.animToastIn : 200)
                                 : (root.tokens ? root.tokens.animToastOut : 160)
            easing.type: root.shown ? Easing.OutCubic : Easing.InCubic
            onRunningChanged: if (!running && !root.shown) root.presentNext()
        }
    }
    NumberAnimation {
        id: riseAnim
        target: root
        property: "rise"
        to: 0
        duration: root.tokens ? root.tokens.animToastIn : 200
        easing.type: Easing.OutCubic
    }

    Timer {
        id: holdTimer
        interval: Math.max(1, root.holdMs)
        running: false
        onTriggered: {
            if (toastHover.hovered)
                restart()
            else
                root.dismiss()
        }
    }

    HoverHandler { id: toastHover }

    RectangularShadow {
        anchors.fill: parent
        offset.y: 16
        blur: 32
        color: root.tokens ? root.tokens.shadow : Qt.rgba(0, 0, 0, 0.55)
    }
    Ui.NotchFrame {
        anchors.fill: parent
        tokens: root.tokens
        notch: root.tokens ? root.tokens.notchControl : 8
        fillColor: root.tokens ? root.tokens.surfaceRaised : "#0d131a"
        strokeColor: root.tokens ? root.tokens.controlLine : Qt.rgba(0.745, 0.902, 0.941, 0.22)
    }
    Rectangle {
        width: 3
        height: parent.height
        color: root.tone
    }

    Row {
        id: row
        x: 3 + 16
        anchors.verticalCenter: parent.verticalCenter
        spacing: 12

        Ui.SbIcon {
            anchors.verticalCenter: parent.verticalCenter
            tokens: root.tokens
            name: root.kind === "ok" ? "check" : root.kind === "info" ? "info" : "warning"
            size: 20
            color: root.tone
        }

        Text {
            id: messageText
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, (root.tokens ? root.tokens.toastMaxWidth : 480) - 3 - 16 - 20 - 12
                            - (actionButton.visible ? actionButton.implicitWidth + 12 : 0) - 32 - 12 - 8)
            text: root.message
            textFormat: Text.PlainText
            color: root.tokens ? root.tokens.textPrimary : "#edf3f5"
            font.pixelSize: root.tokens ? root.tokens.fontBody : 15
            wrapMode: Text.Wrap
            maximumLineCount: 3
            elide: Text.ElideRight
        }

        Ui.SbButton {
            id: actionButton
            visible: root.actionText.length > 0
            anchors.verticalCenter: parent.verticalCenter
            tokens: root.tokens
            compact: true
            text: root.actionText
            onClicked: {
                root.actionTriggered(root.message)
                root.dismiss()
            }
        }
    }

    Ui.SbButton {
        anchors.right: parent.right
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        tokens: root.tokens
        iconName: "close"
        Accessible.name: "Close"
        onClicked: root.dismiss()
    }
}
