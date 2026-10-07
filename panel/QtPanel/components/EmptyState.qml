import QtQuick
import QtQuick.Controls.Material
import QtQuick.Layouts
import "." as Ui

Item {
    id: root
    property var tokens: null
    property string message: ""
    property string actionText: ""
    property bool actionEnabled: true
    signal actionClicked()

    Layout.fillWidth: true
    implicitHeight: message.length > 0 ? inner.implicitHeight + 32 : 0

    Rectangle {
        id: inner
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        implicitHeight: col.implicitHeight + 2 * (tokens ? tokens.spaceMd : 16)
        // It always sits inside a box of its own (the catalog list, the
        // activity log), so it draws no second box: just the words and the
        // one action, centred.
        color: "transparent"
        border.width: 0

        ColumnLayout {
            id: col
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: tokens ? tokens.spaceMd : 16
            spacing: tokens ? tokens.spaceSm : 12

            Text {
                Layout.fillWidth: true
                text: root.message
                textFormat: Text.PlainText
                color: tokens ? tokens.textSecondary : Material.foreground
                font.pixelSize: tokens ? tokens.fontBody : 15
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }

            Ui.SbButton {
                Layout.alignment: Qt.AlignHCenter
                visible: root.actionText.length > 0
                enabled: root.actionEnabled
                tokens: root.tokens
                text: root.actionText
                onClicked: root.actionClicked()
            }
        }
    }
}
