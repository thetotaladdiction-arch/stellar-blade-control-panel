import QtQuick
import QtQuick.Layouts
import "." as Ui

// A short tip inside a card: the toast's anatomy at card scale (FINAL-VISUAL-
// SPEC.md 5.13). A notched box on the card's solid surface, a 3 px bar in the
// info colour on its left edge, a 16 px info icon and the words (14 px
// textSecondary, wrapped). Hover shows the full description. Nothing moves.
Item {
    id: root
    property var tokens: null
    property string summary: ""
    property string detail: ""

    readonly property int padX: tokens ? tokens.spaceSm : 12
    readonly property int padY: tokens ? tokens.spaceXs : 8
    readonly property int iconBox: tokens ? tokens.iconSmall : 16

    Layout.fillWidth: true
    implicitHeight: Math.max(tokens ? tokens.rowCompact : 40, summaryText.implicitHeight + padY * 2)

    // Hovering reveals the full description, so signal it with the pointer.
    HoverHandler { id: hover; cursorShape: root.detail.length > 0 ? Qt.PointingHandCursor : Qt.ArrowCursor }

    Ui.NotchFrame {
        anchors.fill: parent
        tokens: root.tokens
        notch: root.tokens ? root.tokens.notchSmall : 6
        // The card's own solid surface, so the words stay readable anywhere.
        fillColor: root.tokens ? Qt.rgba(root.tokens.surfaceCard.r, root.tokens.surfaceCard.g,
                                         root.tokens.surfaceCard.b, root.tokens.surfaceCardOpacity)
                               : Qt.rgba(0.039, 0.059, 0.082, 0.94)
        strokeColor: hover.hovered && root.detail.length > 0
                     ? (root.tokens ? root.tokens.controlLineHover : Qt.rgba(0.745, 0.902, 0.941, 0.34))
                     : (root.tokens ? root.tokens.controlLine : Qt.rgba(0.745, 0.902, 0.941, 0.22))
    }

    Rectangle {
        x: 0
        y: 0
        width: 3
        height: parent.height
        color: root.tokens ? root.tokens.statusInfo : "#56e0d3"
    }

    Ui.SbIcon {
        id: noteIcon
        x: 3 + root.padX
        // Centred on the first line of the words.
        y: Math.round(summaryText.y + (lineMetrics.height - height) / 2)
        tokens: root.tokens
        name: "info"
        size: root.iconBox
        color: root.tokens ? root.tokens.textMuted : "#7b8994"
    }

    Text {
        id: summaryText
        anchors.left: noteIcon.right
        anchors.leftMargin: root.tokens ? root.tokens.spaceXs : 8
        anchors.right: parent.right
        anchors.rightMargin: root.padX
        anchors.verticalCenter: parent.verticalCenter
        text: root.summary
        textFormat: Text.PlainText
        color: root.tokens ? root.tokens.textSecondary : "#a9b7c0"
        font.pixelSize: root.tokens ? root.tokens.fontCaption : 14
        font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
        wrapMode: Text.WordWrap
    }

    FontMetrics { id: lineMetrics; font: summaryText.font }

    Ui.SbToolTip {
        tokens: root.tokens
        visible: hover.hovered && root.detail.length > 0
        text: root.detail
    }
}
