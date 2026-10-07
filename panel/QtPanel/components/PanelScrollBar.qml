import QtQuick
import QtQuick.Controls

// Panel scrollbar.
//
// The app runs the Material style, whose ScrollBar grows the thumb thickness on
// hover and drives the contentItem's geometry itself. Setting `width` directly
// on the contentItem does not hold - Material stretches it - which is why the
// bar looked like it swelled and filled in on hover.
//
// So the contentItem is a transparent Item that Material may size however it
// likes, and the visible thumb is a fixed-width child centered inside it. The
// painted bar stays a constant 10px line inside an 18px grab lane. Hover and
// press only change brightness, never size.
//
// Material also fades its own contentItem through a state/transition pair
// that writes `contentItem.opacity`. With a custom contentItem that meant the
// thumb vanished 2.5 s after every scroll and, because the style's
// "size < 1" check never reached our thumb, a list that fitted still showed a
// full-height bar. Those states are cleared here and the thumb decides for
// itself: shown whenever there is something to scroll, hidden otherwise.
ScrollBar {
    id: bar
    property var tokens: null

    readonly property color accentColor: tokens ? tokens.accent : "#56e0d3"
    readonly property int hoverMs: tokens ? tokens.animHover : 200
    readonly property int easeKind: tokens ? tokens.easeSoft : Easing.OutCubic
    readonly property int grabWidth: 18
    property int thumbWidth: 10
    // Thumb opacity while nothing scrolls, hovers or drags. The page bar in
    // the 16 px gap beside the sidebar uses 0: it shows only while in use.
    property real restOpacity: 0.28
    readonly property bool scrollable: bar.policy === ScrollBar.AlwaysOn
                                       || (bar.policy === ScrollBar.AsNeeded && bar.size < 0.999)

    implicitWidth: grabWidth
    implicitHeight: grabWidth
    minimumSize: 0.16
    policy: ScrollBar.AsNeeded
    hoverEnabled: true
    interactive: true
    padding: 3

    states: []
    transitions: []

    // A list that fits keeps its (empty) grab lane; a pointing hand there
    // would promise a control that is not drawn and does nothing.
    HoverHandler {
        enabled: bar.scrollable
        cursorShape: Qt.PointingHandCursor
    }

    contentItem: Item {
        implicitWidth: bar.grabWidth - bar.leftPadding - bar.rightPadding
        opacity: 1.0

        Rectangle {
            id: thumb
            objectName: "panelScrollThumb"
            width: bar.thumbWidth
            height: parent.height
            anchors.horizontalCenter: parent.horizontalCenter
            // No rounded ends: only chips and switches are rounded (2 px).
            radius: bar.tokens ? bar.tokens.radiusSmall : 2
            color: bar.accentColor
            visible: bar.scrollable
            // Quiet at rest (a page that barely scrolls showed a bright
            // full-height stripe beside the sidebar); it brightens as soon
            // as you scroll, hover or drag.
            opacity: bar.pressed ? 0.95 : bar.hovered ? 0.75 : bar.active ? 0.6 : bar.restOpacity
            Behavior on opacity { NumberAnimation { duration: bar.hoverMs; easing.type: bar.easeKind } }
        }
    }

    // No track fill. Lighting up the whole track on hover was part of what read
    // as a "full covered bar"; the thumb alone is enough to show position.
    background: Item {
        implicitWidth: bar.grabWidth
        opacity: 1.0
    }
}
