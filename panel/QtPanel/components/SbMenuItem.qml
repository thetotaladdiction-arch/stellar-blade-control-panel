import QtQuick
import QtQuick.Controls
import "." as Ui

// One menu row (FINAL-VISUAL-SPEC.md 3.2, 5.6): 40 px, 16 px padding, a
// 16 px icon, 15 px words. Hover or keyboard highlight: accent 10 % fill
// with a 2 px accent bar inset on the left. A `danger` row (Force quit game)
// uses the red ink. A checkable row shows a 16 px accent check when chosen.
MenuItem {
    id: root
    property var tokens: null
    property string iconName: ""
    property bool danger: false

    readonly property color ink: !root.enabled ? (root.tokens ? root.tokens.textDisabled : "#56626b")
                                 : root.danger ? (root.tokens ? root.tokens.statusErrorInk : "#ffa39d")
                                 : (root.tokens ? root.tokens.textPrimary : "#edf3f5")

    implicitWidth: root.tokens ? root.tokens.menuWidth : 216
    implicitHeight: root.tokens ? root.tokens.menuItemHeight : 40
    padding: 0
    leftPadding: 16
    rightPadding: 16
    spacing: 12
    hoverEnabled: true
    font.pixelSize: root.tokens ? root.tokens.fontBody : 15
    font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting

    HoverHandler { cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }

    arrow: null
    indicator: null

    contentItem: Item {
        implicitHeight: root.implicitHeight
        Ui.SbIcon {
            id: icon
            visible: root.iconName.length > 0
            anchors.verticalCenter: parent.verticalCenter
            tokens: root.tokens
            name: root.iconName
            size: 16
            color: root.danger ? root.ink
                   : root.highlighted ? (root.tokens ? root.tokens.accent : "#56e0d3")
                   : (root.tokens ? root.tokens.textMuted : "#7b8994")
        }
        Text {
            anchors.left: icon.visible ? icon.right : parent.left
            anchors.leftMargin: icon.visible ? root.spacing : 0
            anchors.right: check.visible ? check.left : parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: root.text
            textFormat: Text.PlainText
            font: root.font
            color: root.ink
            elide: Text.ElideRight
        }
        Ui.SbIcon {
            id: check
            visible: root.checkable && root.checked
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            tokens: root.tokens
            name: "check"
            size: 16
            color: root.tokens ? root.tokens.accent : "#56e0d3"
        }
    }

    background: Item {
        implicitWidth: root.implicitWidth
        implicitHeight: root.implicitHeight
        Rectangle {
            anchors.fill: parent
            color: root.highlighted || root.down
                   ? (root.tokens ? Qt.rgba(root.tokens.accent.r, root.tokens.accent.g, root.tokens.accent.b,
                                            root.down ? 0.16 : 0.10)
                                  : Qt.rgba(0.337, 0.878, 0.827, 0.10))
                   : "transparent"
            Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animHover : 120; easing.type: Easing.OutCubic } }
        }
        Rectangle {
            visible: root.highlighted
            width: 2
            height: parent.height
            color: root.tokens ? root.tokens.accent : "#56e0d3"
        }
    }
}
