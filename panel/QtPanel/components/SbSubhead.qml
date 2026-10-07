import QtQuick

// A group label inside a card (FINAL-VISUAL-SPEC.md 5.10): the 13 px
// uppercase overline ("MORE NUMBERS") with a hairline filling to the right.
// 32 px tall with 8 px above the words. The card header is the only other
// title style on a page.
Item {
    id: root
    property var tokens: null
    property string text: ""

    implicitHeight: 32
    implicitWidth: label.implicitWidth

    Text {
        id: label
        y: 8 + Math.round((24 - height) / 2)
        text: root.text
        textFormat: Text.PlainText
        color: root.tokens ? root.tokens.textMuted : "#7b8994"
        font.family: root.tokens ? root.tokens.typeSmallSemibold : "Segoe UI Variable Small Semibold"
        font.pixelSize: root.tokens ? root.tokens.fontLabel : 13
        font.weight: Font.DemiBold
        font.capitalization: Font.AllUppercase
        font.letterSpacing: 1.3
        font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
    }

    Rectangle {
        x: label.width + 12
        y: label.y + Math.round(label.height / 2)
        width: Math.max(0, root.width - x)
        height: root.tokens ? root.tokens.hairlineW : 1
        color: root.tokens ? root.tokens.hairline : Qt.rgba(0.745, 0.902, 0.941, 0.10)
    }
}
