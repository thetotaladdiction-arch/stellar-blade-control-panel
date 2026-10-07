import QtQuick
import "." as Ui

// The fold / select chevron (FINAL-VISUAL-SPEC.md 5.8, 5.11): a 16 px line
// chevron that points down and turns 180 degrees when its fold or popup is
// open. It is textSecondary at rest, textPrimary while its row is hovered
// and accent while pressed or open. No box, no Canvas repaint.
Item {
    id: root

    property var tokens: null
    property color accentColor: tokens ? tokens.accent : "#56e0d3"
    property bool expanded: false
    property bool highlighted: false
    // Held down (a header or the chevron is being clicked).
    property bool pressed: false
    // Degrees from a right-pointing chevron: 90 = down (closed), -90 = up.
    property real collapsedRotation: 90
    property real expandedRotation: -90
    property real iconSize: tokens ? tokens.iconSmall : 16

    readonly property color indicatorColor: root.pressed ? root.accentColor
                                            : root.highlighted ? (root.tokens ? root.tokens.textPrimary : "#edf3f5")
                                            : (root.tokens ? root.tokens.textSecondary : "#a9b7c0")

    implicitWidth: 24
    implicitHeight: 24

    Ui.SbIcon {
        id: turningChevron
        anchors.centerIn: parent
        tokens: root.tokens
        name: "chevronRight"
        size: root.iconSize
        color: root.indicatorColor
        rotation: root.expanded ? root.expandedRotation : root.collapsedRotation

        Behavior on rotation {
            NumberAnimation { duration: root.tokens ? root.tokens.animFold : 200; easing.type: Easing.OutCubic }
        }
    }
}
