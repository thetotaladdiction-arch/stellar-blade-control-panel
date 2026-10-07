import QtQuick
import QtQuick.Layouts
import "." as Ui

// The top bar (FINAL-VISUAL-SPEC.md 3.2, IA-SPEC section 1): one glass
// surface, 56 px tall and as wide as the page's column, the same on every
// page. Left: the page name (22 px). Right, 8 px apart: the game chip, the
// one game control, and a 32 px refresh button ("Check the game again", F5).
//
//   Closed                      Game closed (off)    Start game (primary)
//   Starting                    Starting game (warn) none
//   Running, mods connected     Game running (ok)    Game (menu)
//   Running, mods not yet       Game running (ok) + "Waiting for game mods..."
//                                                    Game (menu)
//
// The Game menu: Restart game, Quit game, a separator, then Force quit game
// in red, which asks first (main.qml opens the confirmation dialog on
// forceQuitRequested). Under 640 px of bar width the chip shrinks to its
// diamond and its words (and the waiting note) move into its tooltip.
// The one place that says whether the game is running and the game mods are
// answering; the connection route and its internals stay on Support.
Item {
    id: root
    property var appBackend
    property var tokens: null
    // The page name ("Gameplay"); PageTheme.bannerMeta(page).title.
    property string title: ""

    signal forceQuitRequested()

    readonly property bool gameRunning: !!appBackend && appBackend.gameRunning
    readonly property bool opening: !!appBackend && appBackend.gameLaunchBusy && !root.gameRunning
    // Either connection route counts: the in-game mod or the safe external one.
    readonly property bool connected: !!appBackend
                                      && (appBackend.modConnected || appBackend.connectionTier === "external")
    readonly property bool narrow: root.width < 640
    readonly property string chipText: root.opening ? "Starting game"
                                       : root.gameRunning ? "Game running"
                                       : "Game closed"
    readonly property string chipKind: root.opening ? "warn" : root.gameRunning ? "ok" : "off"
    // Only what the chip does not already say.
    readonly property string waitingText: !root.gameRunning || root.opening || root.connected
                                          ? "" : "Waiting for game mods…"
    // Build 4d: after a Start game that ended on its own ("Steam is waiting
    // for a sign-in") the words stay here once the toast is gone, until the
    // next Start game, the game running, or Steam signing in or closing.
    readonly property string startNote: !!appBackend && !root.gameRunning && !root.opening
                                        ? String(appBackend.gameStartNote || "") : ""
    readonly property string startNoteDetail: !!appBackend ? String(appBackend.gameStartNoteDetail || "") : ""

    implicitHeight: tokens ? tokens.topBarHeight : 56
    Layout.preferredHeight: implicitHeight

    Ui.GlassSurface {
        anchors.fill: parent
        tokens: root.tokens
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: root.tokens ? root.tokens.spaceMd : 16
        anchors.rightMargin: root.tokens ? root.tokens.spaceSm : 12
        spacing: root.tokens ? root.tokens.spaceXs : 8

        Text {
            objectName: "topBarTitle"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.alignment: Qt.AlignVCenter
            text: root.title
            textFormat: Text.PlainText
            color: root.tokens ? root.tokens.textPrimary : "#edf3f5"
            font.pixelSize: root.tokens ? root.tokens.fontTitle : 22
            font.family: root.tokens ? root.tokens.typeDisplaySemibold : "Bahnschrift SemiBold"
            font.weight: Font.DemiBold
            font.letterSpacing: 0.2
            font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
            elide: Text.ElideRight
            maximumLineCount: 1
        }

        Ui.StatusChip {
            id: gameChip
            objectName: "topBarGameChip"
            Layout.alignment: Qt.AlignVCenter
            tokens: root.tokens
            text: root.chipText
            kind: root.chipKind
            markOnly: root.narrow

            HoverHandler { id: chipHover }
            Ui.SbToolTip {
                tokens: root.tokens
                visible: root.narrow && chipHover.hovered
                text: root.chipText + (root.waitingText.length > 0 ? ". " + root.waitingText : "")
                      + (root.startNote.length > 0 ? ". " + root.startNoteDetail : "")
            }
        }

        Text {
            id: startNoteText
            objectName: "topBarStartNote"
            Layout.alignment: Qt.AlignVCenter
            // Keeps its full width; the page name gives way first.
            Layout.minimumWidth: 0
            Layout.preferredWidth: implicitWidth
            visible: text.length > 0 && !root.narrow
            text: root.startNote
            textFormat: Text.PlainText
            color: root.tokens ? root.tokens.statusWarnInk : "#ffcd92"
            font.pixelSize: root.tokens ? root.tokens.fontHint : 13
            elide: Text.ElideRight
            maximumLineCount: 1

            HoverHandler { id: startNoteHover }
            Ui.SbToolTip {
                tokens: root.tokens
                visible: startNoteHover.hovered && root.startNoteDetail.length > 0
                text: root.startNoteDetail
            }
        }

        Text {
            objectName: "topBarWaiting"
            Layout.alignment: Qt.AlignVCenter
            // Keeps its full width; the page name gives way first.
            Layout.minimumWidth: 0
            Layout.preferredWidth: implicitWidth
            visible: text.length > 0 && !root.narrow
            text: !root.gameRunning || root.opening ? "" : root.waitingText
            textFormat: Text.PlainText
            color: root.tokens ? root.tokens.statusWarnInk : "#ffcd92"
            font.pixelSize: root.tokens ? root.tokens.fontHint : 13
            elide: Text.ElideRight
            maximumLineCount: 1
        }

        // Closed: Start game.
        Ui.SbButton {
            objectName: "topBarStartGame"
            visible: !root.gameRunning && !root.opening
            Layout.alignment: Qt.AlignVCenter
            Layout.preferredHeight: root.tokens ? root.tokens.btnHeightCompact : 32
            tokens: root.tokens
            compact: true
            variant: "primary"
            iconName: "play"
            text: "Start game"
            enabled: !!root.appBackend && !root.appBackend.gameLaunchBusy
            onClicked: root.appBackend.openGame()
        }

        // Running: the Game menu.
        Ui.SbButton {
            id: gameButton
            objectName: "topBarGameMenu"
            visible: root.gameRunning
            Layout.alignment: Qt.AlignVCenter
            Layout.preferredHeight: root.tokens ? root.tokens.btnHeightCompact : 32
            tokens: root.tokens
            compact: true
            text: "Game"
            trailingIcon: "chevronDown"
            menuOpen: gameMenu.visible
            Accessible.role: Accessible.ButtonMenu
            onClicked: gameMenu.visible ? gameMenu.close() : gameMenu.openUnder(gameButton)

            Ui.SbMenu {
                id: gameMenu
                objectName: "topBarGameMenuPopup"
                tokens: root.tokens

                Ui.SbMenuItem {
                    tokens: root.tokens
                    iconName: "restart"
                    text: "Restart game"
                    enabled: !!root.appBackend && !root.appBackend.gameLaunchBusy
                    onTriggered: root.appBackend.restartGame()
                }
                Ui.SbMenuItem {
                    tokens: root.tokens
                    iconName: "stop"
                    text: "Quit game"
                    onTriggered: root.appBackend.quitGame()
                }
                Ui.SbMenuSeparator { tokens: root.tokens }
                Ui.SbMenuItem {
                    tokens: root.tokens
                    iconName: "power"
                    text: "Force quit game"
                    danger: true
                    onTriggered: root.forceQuitRequested()
                }
            }
        }

        Ui.SbButton {
            id: refreshButton
            objectName: "topBarRefresh"
            Layout.alignment: Qt.AlignVCenter
            tokens: root.tokens
            iconName: "refresh"
            Accessible.name: "Check the game again"
            onClicked: root.appBackend.refresh()

            Ui.SbToolTip {
                tokens: root.tokens
                visible: refreshButton.hovered
                text: "Check the game again"
                shortcut: "F5"
            }
        }
    }
}
