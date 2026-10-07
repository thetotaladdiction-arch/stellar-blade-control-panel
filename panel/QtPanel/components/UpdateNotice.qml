import QtQuick
import QtQuick.Layouts
import "." as Ui

// The quiet update line (Gameplay and Support > Get help): the FriendlyNote
// box with "Version X is available" and one compact Download button that
// opens the download page in the browser. Hidden while there is nothing
// newer, while the check is off, and it never pops up or downloads anything
// (services/update_check.py).
Item {
    id: root
    property var tokens: null
    property var appBackend: null

    readonly property string version: appBackend ? String(appBackend.updateAvailableVersion || "") : ""
    readonly property bool hasLink: !!appBackend && String(appBackend.updateDownloadUrl || "").length > 0
    readonly property int padX: tokens ? tokens.spaceSm : 12
    readonly property int padY: tokens ? tokens.spaceXs : 8

    visible: !!appBackend && !!appBackend.updateCheckAvailable && root.version.length > 0
    Layout.fillWidth: true
    implicitHeight: visible ? Math.max(tokens ? tokens.rowCompact : 40,
                                       Math.max(line.implicitHeight, download.implicitHeight) + padY * 2)
                            : 0

    Ui.NotchFrame {
        anchors.fill: parent
        tokens: root.tokens
        notch: root.tokens ? root.tokens.notchSmall : 6
        fillColor: root.tokens ? Qt.rgba(root.tokens.surfaceCard.r, root.tokens.surfaceCard.g,
                                         root.tokens.surfaceCard.b, root.tokens.surfaceCardOpacity)
                               : Qt.rgba(0.039, 0.059, 0.082, 0.94)
        strokeColor: root.tokens ? root.tokens.controlLine : Qt.rgba(0.745, 0.902, 0.941, 0.22)
    }

    Rectangle {
        width: 3
        height: parent.height
        color: root.tokens ? root.tokens.statusInfo : "#56e0d3"
    }

    Ui.SbIcon {
        id: noteIcon
        x: 3 + root.padX
        anchors.verticalCenter: parent.verticalCenter
        tokens: root.tokens
        name: "info"
        size: root.tokens ? root.tokens.iconSmall : 16
        color: root.tokens ? root.tokens.textMuted : "#7b8994"
    }

    Text {
        id: line
        objectName: "updateNoticeText"
        anchors.left: noteIcon.right
        anchors.leftMargin: root.tokens ? root.tokens.spaceXs : 8
        anchors.right: download.visible ? download.left : parent.right
        anchors.rightMargin: root.padX
        anchors.verticalCenter: parent.verticalCenter
        text: "Version " + root.version + " is available"
        textFormat: Text.PlainText
        color: root.tokens ? root.tokens.textSecondary : "#a9b7c0"
        font.pixelSize: root.tokens ? root.tokens.fontCaption : 14
        font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
        wrapMode: Text.WordWrap
    }

    Ui.SbButton {
        id: download
        objectName: "updateNoticeDownload"
        anchors.right: parent.right
        anchors.rightMargin: root.padX
        anchors.verticalCenter: parent.verticalCenter
        tokens: root.tokens
        compact: true
        visible: root.hasLink
        text: "Download"
        Accessible.name: "Download version " + root.version
        onClicked: root.appBackend.openUpdateDownload()
    }
}
