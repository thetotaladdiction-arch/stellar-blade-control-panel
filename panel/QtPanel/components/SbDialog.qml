pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import "." as Ui

// The one dialog (FINAL-VISUAL-SPEC.md 5.14). A plain scrim over the whole
// window (no blur); a 480 px raised panel with a 12 px notch, 24 px padding
// and a large static shadow; an 18 px title with an optional 20 px status
// icon; a 15 / 22 px body in textSecondary; a right-aligned footer with
// Cancel and the action. A destructive action uses the solid red button,
// and then Enter means Cancel (the safe default). Esc always cancels. Focus
// stays inside while open and returns to the opener when it closes.
// Opens over 160 ms (opacity, and a 0.98 -> 1 scale on the panel only).
Popup {
    id: root
    property var tokens: null
    property string title: ""
    property string body: ""
    // Status icon before the title ("power", "warning"); empty = none.
    property string iconName: ""
    property string iconKind: "error"
    property string acceptText: "OK"
    property string cancelText: "Cancel"
    property bool destructive: false

    signal accepted()
    signal rejected()

    function accept() { root.accepted(); root.close() }
    function reject() { root.rejected(); root.close() }

    parent: Overlay.overlay
    modal: true
    focus: true
    dim: true
    closePolicy: Popup.NoAutoClose
    anchors.centerIn: parent
    width: Math.min(root.tokens ? root.tokens.dialogWidth : 480, parent ? parent.width - 32 : 480)
    padding: 24
    // Material insets popups by its elevation shadow (-32 px); the frame
    // here is drawn exactly at the popup's edges.
    topInset: 0
    bottomInset: 0
    leftInset: 0
    rightInset: 0
    transformOrigin: Popup.Center

    Overlay.modal: Rectangle {
        color: root.tokens ? root.tokens.scrim : Qt.rgba(0, 0, 0, 0.55)
        Behavior on opacity { NumberAnimation { duration: root.tokens ? root.tokens.animDialog : 160 } }
    }

    onOpened: (root.destructive ? cancelButton : acceptButton).forceActiveFocus()

    background: Item {
        RectangularShadow {
            anchors.fill: parent
            offset.y: 24
            blur: 48
            color: root.tokens ? root.tokens.shadowDialog : Qt.rgba(0, 0, 0, 0.6)
        }
        Ui.NotchFrame {
            anchors.fill: parent
            tokens: root.tokens
            notch: root.tokens ? root.tokens.notchSurface : 12
            fillColor: root.tokens ? root.tokens.surfaceRaised : "#0d131a"
            strokeColor: root.tokens ? root.tokens.controlLine : Qt.rgba(0.745, 0.902, 0.941, 0.22)
        }
    }

    contentItem: FocusScope {
        implicitHeight: column.implicitHeight
        Keys.onEscapePressed: root.reject()
        Keys.onReturnPressed: root.destructive ? root.reject() : root.accept()
        Keys.onEnterPressed: root.destructive ? root.reject() : root.accept()

        Column {
            id: column
            width: parent.width
            spacing: 0

            Row {
                spacing: 12
                height: 24
                Ui.SbIcon {
                    visible: root.iconName.length > 0
                    anchors.verticalCenter: parent.verticalCenter
                    tokens: root.tokens
                    name: root.iconName
                    size: 20
                    color: !root.tokens ? "#ff7a72"
                           : root.iconKind === "warn" ? root.tokens.statusWarn
                           : root.iconKind === "ok" ? root.tokens.statusOk
                           : root.tokens.statusError
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.title
                    textFormat: Text.PlainText
                    color: root.tokens ? root.tokens.textPrimary : "#edf3f5"
                    font.pixelSize: root.tokens ? root.tokens.fontHeading : 18
                    font.family: root.tokens ? root.tokens.typeDisplaySemibold : "Bahnschrift SemiBold"
                    font.weight: Font.DemiBold
                }
            }

            Item { width: 1; height: 12 }

            Text {
                width: parent.width
                text: root.body
                textFormat: Text.PlainText
                color: root.tokens ? root.tokens.textSecondary : "#a9b7c0"
                font.pixelSize: root.tokens ? root.tokens.fontBody : 15
                lineHeight: 22
                lineHeightMode: Text.FixedHeight
                wrapMode: Text.Wrap
            }

            Item { width: 1; height: 24 }

            Row {
                anchors.right: parent.right
                spacing: 8
                Ui.SbButton {
                    id: cancelButton
                    tokens: root.tokens
                    text: root.cancelText
                    onClicked: root.reject()
                }
                Ui.SbButton {
                    id: acceptButton
                    tokens: root.tokens
                    text: root.acceptText
                    variant: root.destructive ? "dangerPrimary" : "primary"
                    onClicked: root.accept()
                }
            }
        }
    }

    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: root.tokens ? root.tokens.animDialog : 160; easing.type: Easing.OutCubic }
            NumberAnimation {
                property: "scale"
                from: root.tokens && root.tokens.reduceMotion ? 1.0 : 0.98
                to: 1.0
                duration: root.tokens ? root.tokens.animDialog : 160
                easing.type: Easing.OutCubic
            }
        }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1.0; to: 0.0; duration: root.tokens ? root.tokens.animMenuClose : 100; easing.type: Easing.InCubic }
    }
}
