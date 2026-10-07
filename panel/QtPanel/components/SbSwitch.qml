import QtQuick
import QtQuick.Controls
import QtQuick.Effects

// The one on/off control (FINAL-VISUAL-SPEC.md 5.4): 44 x 24, 2 px radius,
// a 16 px knob with 20 px of travel.
//   Off  1 px outline at 32 %, white 3.5 % fill, grey knob at x = 3
//   On   accent outline, accent 18 % fill, accent knob at x = 23 with a
//        static glow
// Keyboard focus: a 2 px accent ring 2 px outside. Disabled: 40 % opacity
// (the switch holds no text). Space toggles it; a settings row makes its
// whole width the hit area. The knob travels over 140 ms (none with
// Windows animation effects off) and stretches while pressed, so a press
// shows before the switch flips on release.
Switch {
    id: root
    property var tokens: null
    property color accentColor: tokens ? tokens.accent : "#56e0d3"

    hoverEnabled: true
    implicitWidth: tokens ? tokens.switchWidth : 44
    implicitHeight: tokens ? tokens.switchHeight : 24
    padding: 0
    spacing: 0
    opacity: root.enabled ? 1.0 : 0.4

    HoverHandler { cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }

    indicator: Item {
        id: track
        implicitWidth: root.tokens ? root.tokens.switchWidth : 44
        implicitHeight: root.tokens ? root.tokens.switchHeight : 24
        width: implicitWidth
        height: implicitHeight
        x: root.leftPadding
        y: root.topPadding + Math.round((root.availableHeight - height) / 2)

        Rectangle {
            anchors.fill: parent
            radius: root.tokens ? root.tokens.radiusSmall : 2
            color: root.checked
                   ? Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b,
                             root.down ? 0.30 : root.hovered ? 0.24 : 0.18)
                   : Qt.rgba(1, 1, 1, root.down ? 0.09 : root.hovered ? 0.06 : 0.035)
            border.width: root.tokens ? root.tokens.hairlineW : 1
            border.color: root.checked ? root.accentColor
                          : Qt.rgba(0.745, 0.902, 0.941, root.hovered ? 0.46 : 0.32)
            Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animSwitch : 140; easing.type: Easing.OutCubic } }
            Behavior on border.color { ColorAnimation { duration: root.tokens ? root.tokens.animSwitch : 140; easing.type: Easing.OutCubic } }
        }

        // Keyboard focus ring (Tab only), 2 px wide, 2 px outside.
        Rectangle {
            anchors.fill: parent
            anchors.margins: -4
            radius: 4
            color: "transparent"
            border.width: 2
            border.color: root.accentColor
            visible: root.visualFocus
        }

        // Static glow behind the lit knob (no animation, no layer).
        RectangularShadow {
            visible: root.checked && root.enabled
            x: knob.x
            y: knob.y
            width: knob.width
            height: knob.height
            blur: 8
            color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.55)
        }

        Rectangle {
            id: knob
            readonly property int size: root.tokens ? root.tokens.switchKnob : 16
            x: root.checked ? track.width - width - 4 : 4
            y: Math.round((track.height - height) / 2)
            width: root.down && root.enabled ? size + 4 : size
            height: size
            radius: 1
            color: root.checked ? root.accentColor : (root.tokens ? root.tokens.knobOff : "#7d8a94")
            Behavior on x {
                NumberAnimation { duration: root.tokens ? root.tokens.animSwitch : 140; easing.type: Easing.OutCubic }
            }
            Behavior on width {
                NumberAnimation { duration: root.tokens ? root.tokens.animPress : 90; easing.type: Easing.OutCubic }
            }
            Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animSwitch : 140; easing.type: Easing.OutCubic } }
        }
    }

    contentItem: Item {}
}
