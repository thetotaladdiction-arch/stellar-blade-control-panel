import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import "." as Ui

// Navigation (FINAL-VISUAL-SPEC.md 3.3): a 216 px glass surface that runs
// the full height of the window. A 56 px brand block level with the top bar
// (32 px mark, the caps lockup STELLAR BLADE / MOD SUITE, a hairline under
// it); 44 px items 4 px apart, inset 8 px; a divider between the game pages
// and the panel pages; the version pinned 16 px above the bottom.
//
// The selection is ONE shared indicator (accent gradient, a 3 px glowing
// bar at the left edge, a 6 px diamond at the right end) that slides to the
// chosen item over 180 ms, so no item redraws its own bar. The game's status
// lives once, in the top bar. In a narrow window (`compact`, under 980 px)
// the sidebar folds to a 64 px icon rail; tooltips carry the page names and
// their Ctrl shortcuts.
Item {
    id: root
    property string activePage: "gameplay"
    property var tokens: null
    property var appBackend: null
    property bool compact: false
    signal pageSelected(string page)

    readonly property int fullWidth: tokens ? tokens.sidebarWidth : 216
    readonly property int railWidth: tokens ? tokens.sidebarRailWidth : 64
    readonly property int inset: 8
    // The indicator slides only after the first layout, so a saved page
    // does not animate in at start-up.
    property bool settled: false
    Component.onCompleted: Qt.callLater(function() { root.settled = true })

    Layout.preferredWidth: root.compact ? root.railWidth : root.fullWidth
    Layout.fillHeight: true
    implicitWidth: root.compact ? root.railWidth : root.fullWidth

    readonly property Item selectedItem: {
        switch (root.activePage) {
        case "gameplay": return navGameplay
        case "items": return navItems
        case "settings": return navSettings
        case "support": return navSupport
        default: return navGameplay
        }
    }

    // Solid chrome so the navigation reads cleanly over any artwork.
    Ui.GlassSurface {
        anchors.fill: parent
        tokens: root.tokens
    }

    // Brand block: 56 px, level with the top bar.
    RowLayout {
        id: brand
        x: root.compact ? 0 : 16
        y: 0
        width: root.compact ? root.width : root.width - 32
        height: root.tokens ? root.tokens.topBarHeight : 56
        spacing: root.compact ? 0 : (root.tokens ? root.tokens.spaceSm : 12)

        Item { Layout.fillWidth: true; visible: root.compact }

        Ui.BrandImage {
            appBackend: root.appBackend
            tokens: root.tokens
            size: 32
            Layout.alignment: Qt.AlignVCenter
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            visible: !root.compact
            spacing: 0

            Text {
                text: "Stellar Blade"
                textFormat: Text.PlainText
                color: root.tokens ? root.tokens.textPrimary : "#edf3f5"
                font.pixelSize: root.tokens ? root.tokens.fontLabel : 13
                font.family: root.tokens ? root.tokens.typeDisplaySemibold : "Bahnschrift SemiBold"
                font.weight: Font.DemiBold
                font.capitalization: Font.AllUppercase
                font.letterSpacing: 1.8
                font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            Text {
                text: "Mod Suite"
                textFormat: Text.PlainText
                color: root.tokens ? root.tokens.accent : "#56e0d3"
                font.pixelSize: root.tokens ? root.tokens.fontLabel : 13
                font.family: root.tokens ? root.tokens.typeDisplay : "Bahnschrift"
                font.capitalization: Font.AllUppercase
                font.letterSpacing: 3.1
                font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }

        Item { Layout.fillWidth: true; visible: root.compact }
    }

    Rectangle {
        x: root.tokens ? root.tokens.hairlineW : 1
        y: brand.height
        width: root.width - 2 * x
        height: root.tokens ? root.tokens.hairlineW : 1
        color: root.tokens ? root.tokens.hairline : Qt.rgba(0.745, 0.902, 0.941, 0.10)
    }

    // The one selection indicator. It slides between items; nothing else
    // animates in the sidebar.
    Item {
        id: indicator
        x: nav.x
        y: nav.y + (root.selectedItem ? root.selectedItem.y : 0)
        width: nav.width
        height: root.tokens ? root.tokens.navItemHeight : 44
        Behavior on y {
            enabled: root.settled
            NumberAnimation { duration: root.tokens ? root.tokens.animNav : 180; easing.type: Easing.OutCubic }
        }

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: root.tokens ? root.tokens.alpha(root.tokens.accent, 0.16) : Qt.rgba(0.337, 0.878, 0.827, 0.16) }
                GradientStop { position: 0.6; color: root.tokens ? root.tokens.alpha(root.tokens.accent, 0.04) : Qt.rgba(0.337, 0.878, 0.827, 0.04) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }
        // The 3 px bar with its static glow.
        RectangularShadow {
            x: 0
            width: 3
            height: parent.height
            blur: 8
            color: root.tokens ? root.tokens.alpha(root.tokens.accent, 0.55) : Qt.rgba(0.337, 0.878, 0.827, 0.55)
        }
        Rectangle {
            width: 3
            height: parent.height
            color: root.tokens ? root.tokens.accent : "#56e0d3"
        }
        // The 6 px diamond at the right end.
        Rectangle {
            visible: !root.compact
            x: parent.width - 16 - 3
            y: Math.round((parent.height - 6) / 2)
            width: 6
            height: 6
            rotation: 45
            antialiasing: true
            color: root.tokens ? root.tokens.accent : "#56e0d3"
        }
    }

    Column {
        id: nav
        x: root.inset
        y: brand.height + (root.tokens ? root.tokens.spaceSm : 12)
        width: root.width - 2 * root.inset
        spacing: root.tokens ? root.tokens.spaceXxs : 4

        Ui.NavItem {
            id: navGameplay
            objectName: "navGameplay"
            width: nav.width
            tokens: root.tokens
            compact: root.compact
            page: "gameplay"
            title: "Gameplay"
            icon: "gameplay"
            shortcut: "Ctrl+1"
            selected: root.activePage === "gameplay"
            onTriggered: root.pageSelected("gameplay")
        }
        Ui.NavItem {
            id: navItems
            objectName: "navItems"
            width: nav.width
            tokens: root.tokens
            compact: root.compact
            page: "items"
            title: "Items & Money"
            icon: "items"
            shortcut: "Ctrl+2"
            selected: root.activePage === "items"
            onTriggered: root.pageSelected("items")
        }

        // Settings and Support are about the panel, not the game: a 1 px
        // divider with 8 px above and below it.
        Item {
            width: nav.width
            height: 9
            Rectangle {
                x: 8
                y: 4
                width: parent.width - 16
                height: root.tokens ? root.tokens.hairlineW : 1
                color: root.tokens ? root.tokens.hairline : Qt.rgba(0.745, 0.902, 0.941, 0.10)
            }
        }

        Ui.NavItem {
            id: navSettings
            objectName: "navSettings"
            width: nav.width
            tokens: root.tokens
            compact: root.compact
            page: "settings"
            title: "Settings"
            icon: "settings"
            shortcut: "Ctrl+3"
            selected: root.activePage === "settings"
            onTriggered: root.pageSelected("settings")
        }
        Ui.NavItem {
            id: navSupport
            objectName: "navSupport"
            width: nav.width
            tokens: root.tokens
            compact: root.compact
            page: "support"
            title: "Support"
            icon: "support"
            shortcut: "Ctrl+4"
            selected: root.activePage === "support"
            onTriggered: root.pageSelected("support")
        }
    }

    Text {
        x: 16
        y: root.height - 16 - height
        width: root.width - 32
        visible: !root.compact
        text: "Version " + (root.appBackend ? root.appBackend.version : "")
        textFormat: Text.PlainText
        color: root.tokens ? root.tokens.textMuted : "#7b8994"
        font.pixelSize: root.tokens ? root.tokens.fontLabel : 13
        font.family: root.tokens ? root.tokens.typeDisplay : "Bahnschrift"
        elide: Text.ElideRight
    }
}
