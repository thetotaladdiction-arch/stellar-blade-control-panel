import QtQuick
import "." as Ui

// One sidebar entry (FINAL-VISUAL-SPEC.md 3.3): 44 px, 14 px left padding,
// a 20 px icon, 12 px gap, the name in 15 px Bahnschrift. At rest the name
// is textSecondary and the icon textMuted; hover adds a white 4 % fill and
// turns the name textPrimary; the selected item's icon is accent and its
// name textPrimary (SidebarNav draws the one shared selection indicator).
// In the icon rail (`compact`) only the icon shows, centred, and a tooltip
// gives the name and its shortcut keycap; in the full sidebar the keycap
// shows inside the entry on hover. Tab reaches it; Enter or Space
// opens the page.
Item {
    id: root
    property var tokens: null
    property string page: ""
    property string title: ""
    property string icon: ""
    property string shortcut: ""
    property bool selected: false
    property bool compact: false
    signal triggered()

    implicitHeight: tokens ? tokens.navItemHeight : 44
    height: implicitHeight
    activeFocusOnTab: true

    Accessible.role: Accessible.PageTab
    Accessible.name: root.title
    Accessible.selected: root.selected
    Keys.onReturnPressed: root.triggered()
    Keys.onEnterPressed: root.triggered()
    Keys.onSpacePressed: root.triggered()

    Rectangle {
        anchors.fill: parent
        color: navMouse.pressed ? Qt.rgba(1, 1, 1, 0.08)
               : navMouse.containsMouse && !root.selected ? Qt.rgba(1, 1, 1, 0.04)
               : "transparent"
        border.width: root.activeFocus ? 2 : 0
        border.color: root.tokens ? root.tokens.accent : "#56e0d3"
        Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animHover : 120; easing.type: Easing.OutCubic } }
    }

    Ui.NavGlyph {
        id: glyph
        x: root.compact ? Math.round((root.width - width) / 2) : 14
        y: Math.round((root.height - height) / 2)
        page: root.icon
        selected: root.selected
        hovered: navMouse.containsMouse
        tokens: root.tokens
    }

    Text {
        x: glyph.x + glyph.width + 12
        width: Math.max(0, root.width - x - 24)
        anchors.verticalCenter: parent.verticalCenter
        visible: !root.compact
        text: root.title
        textFormat: Text.PlainText
        color: root.selected || navMouse.containsMouse ? (root.tokens ? root.tokens.textPrimary : "#edf3f5")
                                                       : (root.tokens ? root.tokens.textSecondary : "#a9b7c0")
        font.pixelSize: root.tokens ? root.tokens.fontBody : 15
        font.family: root.tokens ? root.tokens.typeDisplay : "Bahnschrift"
        font.letterSpacing: 0.3
        font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
        elide: Text.ElideRight
        Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animHover : 120; easing.type: Easing.OutCubic } }
    }

    MouseArea {
        id: navMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.triggered()
    }

    // The full sidebar already shows the name: its shortcut appears as a
    // keycap inside the entry, so nothing covers the page (build 4d live
    // test: the "Gameplay Ctrl+2" tooltip beside the sidebar covered the
    // God Mode card's first line). 4 px from the right edge, 6 px wider
    // than its words: clear of the widest name (Items & Money ends at about
    // 147 of the 200 px entry, the "Ctrl+3" keycap starts at about 155).
    // Not on the page you are on: its diamond sits there.
    Rectangle {
        id: keycap
        objectName: "navShortcutKeycap"
        visible: !root.compact && !root.selected && root.shortcut.length > 0
                 && (navMouse.containsMouse || root.activeFocus)
        anchors.right: parent.right
        anchors.rightMargin: 4
        anchors.verticalCenter: parent.verticalCenter
        width: keyText.implicitWidth + 6
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
            font.pixelSize: root.tokens ? root.tokens.fontLabel : 13
            font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
        }
    }

    // The icon rail hides the names, so there the tooltip carries the name
    // and its shortcut, beside the rail.
    Ui.SbToolTip {
        objectName: "navRailTooltip"
        tokens: root.tokens
        visible: root.compact && navMouse.containsMouse
        x: root.width + 12
        y: Math.round((root.height - height) / 2)
        text: root.title
        shortcut: root.shortcut
    }
}
