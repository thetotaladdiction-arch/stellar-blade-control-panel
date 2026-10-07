import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import "." as Ui

// The slider control (FINAL-VISUAL-SPEC.md 5.7): the game's segmented HP
// bar. An 11 px track of 6 px cells with 2 px gaps (empty cells white 14 %,
// filled cells accent, an optional experimental range in amber 36 %), a
// 1 x 21 px "normal" tick at the default value, and a 16 px accent diamond
// thumb with a dark ring and a static glow. The hit area is 32 px tall and
// the full width. SbSliderField adds the label / range / value header.
//
// Input: dragging snaps live to the existing stepSize with no animation;
// arrows use that step (keyStep override), Page Up / Down use pageStep, and Home / End jump to the
// ends. Keyboard steps and value changes from code ("Back to normal")
// animate the thumb and fill over 180 ms. Keyboard steps emit moved(), as a
// drag does.
Slider {
    id: root
    property var tokens: null
    property color accentColor: tokens ? tokens.accent : "#56e0d3"
    // The game's default ("normal") value; NaN hides the tick.
    property real normalValue: NaN
    // Values above this are experimental (amber); NaN = no such range.
    property real experimentalFrom: NaN
    property real keyStep: root.stepSize > 0 ? root.stepSize : 5
    property real pageStep: Math.max(25, root.keyStep * 5)

    readonly property bool experimental: !isNaN(root.experimentalFrom) && root.value > root.experimentalFrom
    readonly property real span: Math.max(1e-9, root.to - root.from)
    function xFor(v) {
        return root.leftPadding + Math.max(0, Math.min(1, (v - root.from) / root.span)) * root.availableWidth
    }
    // Where the thumb is drawn (0..1). It follows a drag at once and eases
    // after a keyboard step or a change from code; a resize never animates.
    property real shownPosition: root.visualPosition
    Behavior on shownPosition {
        enabled: !root.pressed && (root.tokens ? root.tokens.animSlider > 0 : true)
        NumberAnimation { duration: root.tokens ? root.tokens.animSlider : 180; easing.type: Easing.OutCubic }
    }
    readonly property real thumbX: root.tokens
                                   ? root.tokens.snap(root.leftPadding + root.shownPosition * root.availableWidth)
                                   : Math.round(root.leftPadding + root.shownPosition * root.availableWidth)

    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    snapMode: Slider.SnapAlways
    implicitHeight: 32
    implicitWidth: 200
    leftPadding: 0
    topPadding: 0
    bottomPadding: 0
    // The track spans the full width: the fill's cells start at the left
    // edge and the empty track's cells end at the right edge. The two cell
    // grids meet under the thumb, which is always drawn.
    rightPadding: 0
    // Disabled (the game mod is not available): grey fill and thumb.
    readonly property color fillColor: root.enabled ? root.accentColor
                                                    : (root.tokens ? root.tokens.textDisabled : "#56626b")

    function step(delta) {
        var next = Math.max(root.from, Math.min(root.to, root.value + delta))
        // Snap user keyboard input only. Loading a saved value never rewrites it.
        if (root.stepSize > 0 && next !== root.from && next !== root.to) {
            next = root.from + Math.round((next - root.from) / root.stepSize) * root.stepSize
            next = Math.max(root.from, Math.min(root.to, next))
        }
        if (next !== root.value) {
            root.value = next
            root.moved()
        }
    }
    Keys.onPressed: (event) => {
        var sign = root.from <= root.to ? 1 : -1
        if (event.key === Qt.Key_Left || event.key === Qt.Key_Down) root.step(-root.keyStep * sign)
        else if (event.key === Qt.Key_Right || event.key === Qt.Key_Up) root.step(root.keyStep * sign)
        else if (event.key === Qt.Key_PageDown) root.step(-root.pageStep * sign)
        else if (event.key === Qt.Key_PageUp) root.step(root.pageStep * sign)
        else if (event.key === Qt.Key_Home) root.step(root.from - root.value)
        else if (event.key === Qt.Key_End) root.step(root.to - root.value)
        else return
        event.accepted = true
    }

    // Pointer while hovering, grab cursor while dragging.
    HoverHandler {
        cursorShape: !root.enabled ? Qt.ArrowCursor : root.pressed ? Qt.ClosedHandCursor : Qt.PointingHandCursor
    }

    background: Item {
        x: root.leftPadding
        y: 0
        width: root.availableWidth
        height: root.height
        opacity: root.enabled ? 1.0 : 0.45

        readonly property real trackY: Math.round((height - 11) / 2)

        // The empty cells right of the thumb, ending on the right edge.
        Item {
            x: Math.max(0, root.thumbX - root.leftPadding)
            y: parent.trackY
            width: Math.max(0, parent.width - x)
            height: 11
            clip: true
            Ui.SegmentTrack {
                x: -parent.x
                width: parent.parent.width
                height: 11
                alignRight: true
                color: Qt.rgba(1, 1, 1, 0.14)
            }
        }

        // Experimental range right of the thumb, on the same cells.
        Item {
            visible: !isNaN(root.experimentalFrom)
            x: Math.max(root.xFor(root.experimentalFrom), root.thumbX) - root.leftPadding
            y: parent.trackY
            width: Math.max(0, parent.width - x)
            height: 11
            clip: true
            Ui.SegmentTrack {
                x: -parent.x
                width: parent.parent.width
                height: 11
                alignRight: true
                color: root.tokens ? Qt.rgba(root.tokens.statusWarn.r, root.tokens.statusWarn.g,
                                             root.tokens.statusWarn.b, 0.36)
                                   : Qt.rgba(1, 0.71, 0.37, 0.36)
            }
        }

        // The fill: cells from the left edge, clipped at the thumb.
        Item {
            y: parent.trackY
            width: Math.max(0, root.thumbX - root.leftPadding)
            height: 11
            clip: true
            Ui.SegmentTrack {
                width: root.availableWidth
                height: 11
                color: root.fillColor
            }
        }

        // The "normal" tick: 1 x 21 px, 5 px above and below the track.
        Rectangle {
            visible: !isNaN(root.normalValue)
            x: root.tokens ? root.tokens.snap(root.xFor(root.normalValue) - root.leftPadding)
                           : Math.round(root.xFor(root.normalValue) - root.leftPadding)
            y: parent.trackY - 5
            width: root.tokens ? root.tokens.hairlineW : 1
            height: 21
            color: root.tokens ? Qt.rgba(root.tokens.textPrimary.r, root.tokens.textPrimary.g,
                                         root.tokens.textPrimary.b, 0.60)
                               : Qt.rgba(0.93, 0.95, 0.96, 0.60)
        }
    }

    // A zero-width handle, so the pointer maps onto the full track width;
    // the diamond is drawn centred on it.
    handle: Item {
        x: root.thumbX
        y: 0
        width: 0
        height: root.height

        // A 16 px accent diamond (11.5 px square turned 45 degrees) inside a
        // 2 px dark ring, with a static accent glow behind it.
        Item {
            id: diamond
            x: -12
            y: Math.round((root.height - 24) / 2)
            width: 24
            height: 24

            RectangularShadow {
                visible: root.enabled
                anchors.centerIn: parent
                width: 11.5
                height: 11.5
                rotation: 45
                blur: 12
                color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.55)
            }
            // Keyboard focus: a 2 px accent ring around the thumb.
            Rectangle {
                anchors.centerIn: parent
                width: 20.5
                height: 20.5
                rotation: 45
                antialiasing: true
                color: "transparent"
                border.width: 2
                border.color: root.accentColor
                opacity: root.visualFocus ? 1.0 : 0.0
            }
            Rectangle {
                anchors.centerIn: parent
                width: 16.5
                height: 16.5
                rotation: 45
                antialiasing: true
                color: root.tokens ? root.tokens.thumbRing : "#081016"
            }
            Rectangle {
                anchors.centerIn: parent
                width: 11.5
                height: 11.5
                rotation: 45
                antialiasing: true
                color: root.pressed ? Qt.lighter(root.fillColor, 1.12) : root.fillColor
            }
        }
    }
}
