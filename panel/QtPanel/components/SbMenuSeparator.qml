import QtQuick
import QtQuick.Controls

// A menu separator (FINAL-VISUAL-SPEC.md 5.6): a 1 px hairline with 4 px
// above and below.
MenuSeparator {
    id: root
    property var tokens: null
    padding: 0
    topPadding: 4
    bottomPadding: 4
    contentItem: Rectangle {
        implicitWidth: root.tokens ? root.tokens.menuWidth : 216
        implicitHeight: root.tokens ? root.tokens.hairlineW : 1
        color: root.tokens ? root.tokens.hairline : Qt.rgba(0.745, 0.902, 0.941, 0.10)
    }
}
