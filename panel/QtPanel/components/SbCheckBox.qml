import QtQuick
import QtQuick.Controls
import "." as Ui

// The one checkbox (FINAL-VISUAL-SPEC.md 5.8): a 16 px square with a 1 px
// outline at 34 %; checked, an accent fill with a 2 px accent-ink check.
// The 15 px label is textPrimary when checked and textSecondary when not.
// Rows are 32 px; the whole row is the hit area. Keyboard focus draws a
// 2 px accent ring around the box.
CheckBox {
    id: root
    property var tokens: null

    hoverEnabled: true
    implicitHeight: 32
    padding: 0
    spacing: 12
    font.pixelSize: tokens ? tokens.fontBody : 15
    font.hintingPreference: tokens ? tokens.textHinting : Font.PreferFullHinting
    opacity: root.enabled ? 1.0 : 0.4

    HoverHandler { cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }

    indicator: Item {
        implicitWidth: 16
        implicitHeight: 16
        x: root.leftPadding
        y: Math.round((root.height - height) / 2)

        Rectangle {
            anchors.fill: parent
            radius: 1
            color: root.checked ? (root.tokens ? root.tokens.accent : "#56e0d3")
                                : Qt.rgba(1, 1, 1, root.hovered ? 0.06 : 0.02)
            border.width: root.checked ? 0 : (root.tokens ? root.tokens.hairlineW : 1)
            border.color: Qt.rgba(0.745, 0.902, 0.941, root.hovered ? 0.50 : 0.34)
            Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animHover : 120; easing.type: Easing.OutCubic } }
        }
        Ui.SbIcon {
            anchors.centerIn: parent
            visible: root.checked
            tokens: root.tokens
            name: "check"
            size: 14
            stroke: 2 * 24 / 14
            color: root.tokens ? root.tokens.accentInk : "#03201d"
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: -4
            radius: 2
            color: "transparent"
            border.width: 2
            border.color: root.tokens ? root.tokens.accent : "#56e0d3"
            visible: root.visualFocus
        }
    }

    contentItem: Text {
        leftPadding: root.indicator.width + root.spacing
        text: root.text
        textFormat: Text.PlainText
        font: root.font
        color: root.checked ? (root.tokens ? root.tokens.textPrimary : "#edf3f5")
                            : (root.tokens ? root.tokens.textSecondary : "#a9b7c0")
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
