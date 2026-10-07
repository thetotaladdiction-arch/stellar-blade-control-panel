import QtQuick
import QtQuick.Layouts
import "." as Ui

Item {
    id: root
    property var tokens: null
    property alias text: bodyText.text
    property alias font: bodyText.font
    property alias textFormat: bodyText.textFormat
    property alias wrapMode: bodyText.wrapMode
    property alias lineHeight: bodyText.lineHeight
    property int inset: 10

    clip: true

    Ui.FixedScrollBox {
        anchors.fill: parent
        tokens: root.tokens
        inset: root.inset

        Text {
            id: bodyText
            width: parent.width
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: parent.width
            // Preserve normal word wrapping, but still break long paths,
            // identifiers, and divider lines before they reach the scroll rail.
            wrapMode: Text.WrapAtWordBoundaryOrAnywhere
            textFormat: Text.PlainText
            color: root.tokens ? root.tokens.textSecondary : "#a9b7c0"
            // The log and the notes read in the body face at 13 px with
            // even-width digits, so times line up (FINAL-VISUAL-SPEC 4.5).
            font.family: root.tokens ? root.tokens.typeFamily : "Segoe UI Variable Text"
            font.pixelSize: root.tokens ? root.tokens.fontHint : 13
            font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
            font.features: { "tnum": 1 }
        }
    }
}
