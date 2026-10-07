import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import "." as Ui

// The one tooltip (FINAL-VISUAL-SPEC.md 5.12): raised surface, 1 px control
// line, 6 px notch, 13 px text, at most 320 px wide, a static drop shadow.
// An optional keycap shows the shortcut ("Gameplay  [Ctrl+2]"). It prefers
// the space below its owner and flips above when that runs off the window,
// so it never sits over the pointer. Shown after 500 ms of hover; fades in
// over 120 ms and out over 80 ms.
ToolTip {
    id: root
    property var tokens: null
    // Widest a tooltip grows before its words wrap.
    property int maxWidth: tokens ? tokens.tooltipMaxWidth : 320
    // Keyboard shortcut drawn as a keycap after the words ("F5", "Ctrl+2").
    property string shortcut: ""
    // Below the owner unless that would leave the window (decided on open).
    property bool placeBelow: true

    delay: tokens ? tokens.tipDelay : 500
    // Material insets popups by its elevation shadow (-32 px); the frame
    // here is drawn exactly at the popup's edges.
    topInset: 0
    bottomInset: 0
    leftInset: 0
    rightInset: 0
    topPadding: 8
    bottomPadding: 8
    leftPadding: 12
    rightPadding: 12
    margins: 8
    font.pixelSize: tokens ? tokens.fontHint : 13
    font.hintingPreference: tokens ? tokens.textHinting : Font.PreferFullHinting
    width: Math.min(root.maxWidth, contentRow.fullWidth + leftPadding + rightPadding)
    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: root.placeBelow ? (parent ? parent.height + 6 : 0) : -implicitHeight - 6

    function fitsBelow() {
        if (!parent || !parent.Window || !parent.Window.window)
            return true
        var bottom = parent.mapToItem(null, 0, parent.height).y + root.implicitHeight + 14
        return bottom <= parent.Window.window.height
    }
    onAboutToShow: root.placeBelow = root.fitsBelow()

    contentItem: Item {
        id: contentRow
        readonly property real fullWidth: label.implicitWidth + (keycap.visible ? keycap.width + 8 : 0)
        implicitWidth: fullWidth
        implicitHeight: Math.max(label.implicitHeight, keycap.visible ? keycap.height : 0)

        Text {
            id: label
            width: Math.min(implicitWidth, contentRow.width - (keycap.visible ? keycap.width + 8 : 0))
            anchors.verticalCenter: parent.verticalCenter
            text: root.text
            textFormat: Text.PlainText
            font: root.font
            color: root.tokens ? root.tokens.textPrimary : "#edf3f5"
            wrapMode: Text.Wrap
            lineHeight: 18
            lineHeightMode: Text.FixedHeight
        }

        Rectangle {
            id: keycap
            visible: root.shortcut.length > 0
            x: label.width + 8
            anchors.verticalCenter: parent.verticalCenter
            width: keyText.implicitWidth + 12
            height: 20
            radius: root.tokens ? root.tokens.radiusSmall : 2
            color: "transparent"
            border.width: root.tokens ? root.tokens.hairlineW : 1
            border.color: Qt.rgba(1, 1, 1, 0.30)

            Text {
                id: keyText
                anchors.centerIn: parent
                text: root.shortcut
                textFormat: Text.PlainText
                color: root.tokens ? root.tokens.textSecondary : "#a9b7c0"
                font.family: root.tokens ? root.tokens.typeSmallSemibold : "Segoe UI Variable Small Semibold"
                font.pixelSize: root.tokens ? root.tokens.fontLabel : 13
                font.weight: Font.DemiBold
                font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
            }
        }
    }

    background: Item {
        RectangularShadow {
            anchors.fill: parent
            offset.y: 16
            blur: 32
            color: root.tokens ? root.tokens.shadow : Qt.rgba(0, 0, 0, 0.55)
        }
        Ui.NotchFrame {
            anchors.fill: parent
            tokens: root.tokens
            notch: root.tokens ? root.tokens.notchSmall : 6
            fillColor: root.tokens ? root.tokens.surfaceRaised : "#0d131a"
            strokeColor: root.tokens ? root.tokens.controlLine : Qt.rgba(0.745, 0.902, 0.941, 0.22)
        }
    }

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: root.tokens ? root.tokens.animTipIn : 120; easing.type: Easing.OutCubic }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1.0; to: 0.0; duration: root.tokens ? root.tokens.animTipOut : 80; easing.type: Easing.InCubic }
    }
}
