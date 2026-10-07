import QtQuick
import "." as Ui

// The (i) help button on a card header (FINAL-VISUAL-SPEC.md 5.1): a 24 px
// box with a 16 px line icon that is ALWAYS textMuted (its colour never
// changes with the card's state). Hover or keyboard focus shows the card's
// full words in the shared tooltip. Nothing here scales, so the icon stays
// sharp.
Item {
    id: root
    property var tokens: null
    property string tipText: ""
    // Kept for callers that still pass it; the icon no longer follows it.
    property color tipAccent: tokens ? tokens.accent : "#56e0d3"

    readonly property int box: tokens ? tokens.helpSize : 24
    implicitWidth: box
    implicitHeight: box
    width: box
    height: box
    activeFocusOnTab: root.tipText.length > 0
    Accessible.role: Accessible.Button
    Accessible.name: "More about this"
    Accessible.description: root.tipText

    HoverHandler {
        id: iconHover
        // The (i) reveals a tooltip on hover, so it shows the pointer.
        cursorShape: Qt.PointingHandCursor
    }

    // A quiet hover wash so the target reads as interactive.
    Rectangle {
        id: iconChip
        anchors.fill: parent
        radius: root.tokens ? root.tokens.radiusSmall : 2
        color: iconHover.hovered ? Qt.rgba(1, 1, 1, 0.06) : "transparent"
        border.width: root.activeFocus ? 2 : 0
        border.color: root.tokens ? root.tokens.accent : "#56e0d3"
        Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animHover : 120 } }
    }

    Ui.SbIcon {
        id: infoGlyph
        x: (root.width - width) / 2
        y: (root.height - height) / 2
        tokens: root.tokens
        name: "info"
        size: root.tokens ? root.tokens.iconSmall : 16
        color: root.tokens ? root.tokens.textMuted : "#7b8994"
    }

    Ui.SbToolTip {
        tokens: root.tokens
        visible: (iconHover.hovered || root.activeFocus) && root.tipText.length > 0
        text: root.tipText
    }
}
