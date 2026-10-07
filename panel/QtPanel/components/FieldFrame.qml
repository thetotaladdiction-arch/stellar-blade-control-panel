import QtQuick
import "." as Ui

// The box behind every field (FINAL-VISUAL-SPEC.md 5.8): select, text and
// number fields share it. 6 px notch, 1 px control line, white 3.5 % fill.
// Hover lifts the outline to 34 %; focus or an open popup draws the accent
// outline plus a 1 px inner accent line at 35 %; an error draws the red
// outline at 70 %; disabled is flatter (surfaceDisabled) with a hairline.
Item {
    id: root
    property var tokens: null
    property bool hovered: false
    property bool focused: false
    property bool error: false
    property real notch: tokens ? tokens.notchSmall : 6

    readonly property real line: tokens ? tokens.hairlineW : 1

    Ui.NotchFrame {
        anchors.fill: parent
        tokens: root.tokens
        notch: root.notch
        fillColor: !root.tokens ? Qt.rgba(1, 1, 1, 0.035)
                   : !root.enabled ? root.tokens.surfaceDisabled
                   : Qt.rgba(1, 1, 1, root.hovered && !root.focused ? 0.05 : 0.035)
        strokeColor: !root.tokens ? Qt.rgba(0.745, 0.902, 0.941, 0.22)
                     : !root.enabled ? root.tokens.hairline
                     : root.error ? Qt.rgba(root.tokens.statusError.r, root.tokens.statusError.g,
                                            root.tokens.statusError.b, 0.70)
                     : root.focused ? root.tokens.accent
                     : root.hovered ? root.tokens.controlLineHover
                     : root.tokens.controlLine
        Behavior on strokeColor { ColorAnimation { duration: root.tokens ? root.tokens.animHover : 120; easing.type: Easing.OutCubic } }
    }

    // The inner focus line, one line-width inside the outline.
    Ui.NotchFrame {
        visible: root.focused && root.enabled && !root.error
        anchors.fill: parent
        anchors.margins: root.line
        tokens: root.tokens
        notch: Math.max(0, root.notch - root.line * 0.41421356)
        strokeColor: root.tokens ? Qt.rgba(root.tokens.accent.r, root.tokens.accent.g, root.tokens.accent.b, 0.35)
                                 : Qt.rgba(0.337, 0.878, 0.827, 0.35)
    }
}
