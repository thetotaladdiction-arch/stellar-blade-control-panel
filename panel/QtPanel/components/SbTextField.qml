import QtQuick
import QtQuick.Controls
import "." as Ui

// The one text field (FINAL-VISUAL-SPEC.md 5.8): the shared FieldFrame
// (40 px, 6 px notch, control line), 15 px text, an optional 16 px leading
// icon, and a clear (x) button at the right while there is text.
//
// There is no floating label. The Material style floats `placeholderText`
// up onto the field's top edge once text is typed, where the border clipped
// it ("earch items"). This field never sets placeholderText: its own hint
// sits inside the field and simply disappears while there is text, so no
// state (empty, focused, typing, filled, disabled) can clip it.
//
// An error draws the red outline and one 13 px line 4 px under the field
// (`errorText`); the owner leaves room for it.
TextField {
    id: root
    property var tokens: null
    // Shown only while the field is empty.
    property string hint: ""
    // Optional clear button (one click or Esc empties the field).
    property bool clearable: false
    // Optional leading icon (DesignSystem/Icons.js), e.g. "search".
    property string iconName: ""
    // A problem with what was typed; empty = none.
    property string errorText: ""
    property bool compact: false
    // Names for automation and tests (e.g. "itemsSearchPlaceholder").
    property string hintObjectName: "fieldHint"
    property string clearObjectName: "fieldClear"

    implicitHeight: root.compact ? (root.tokens ? root.tokens.btnHeightCompact : 32) : (root.tokens ? root.tokens.fieldHeight : 40)
    implicitWidth: root.tokens ? root.tokens.fieldWidth : 240
    color: root.enabled ? (root.tokens ? root.tokens.textPrimary : "#edf3f5")
                        : (root.tokens ? root.tokens.textDisabled : "#56626b")
    selectionColor: root.tokens ? Qt.rgba(root.tokens.accent.r, root.tokens.accent.g, root.tokens.accent.b, 0.35) : "#43b3aa"
    selectedTextColor: root.tokens ? root.tokens.textPrimary : "#edf3f5"
    font.pixelSize: root.tokens ? root.tokens.fontBody : 15
    font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
    leftPadding: root.iconName.length > 0 ? 12 + 16 + 8 : 12
    rightPadding: clearButton.visible ? clearButton.width + 8 : 12
    topPadding: 0
    bottomPadding: 0
    topInset: 0
    bottomInset: 0
    verticalAlignment: TextInput.AlignVCenter
    selectByMouse: true
    hoverEnabled: true
    Accessible.name: root.hint

    Keys.onEscapePressed: (event) => {
        if (root.clearable && root.length > 0) {
            root.clear()
            event.accepted = true
        } else {
            event.accepted = false
        }
    }

    background: Ui.FieldFrame {
        tokens: root.tokens
        enabled: root.enabled
        hovered: root.hovered
        focused: root.activeFocus
        error: root.errorText.length > 0
    }

    Ui.SbIcon {
        visible: root.iconName.length > 0
        x: 12
        y: Math.round((root.height - height) / 2)
        tokens: root.tokens
        name: root.iconName
        size: 16
        color: root.tokens ? (root.enabled ? root.tokens.textMuted : root.tokens.textDisabled) : "#7b8994"
    }

    Text {
        objectName: root.hintObjectName
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: root.leftPadding
        anchors.rightMargin: root.rightPadding
        anchors.verticalCenter: parent.verticalCenter
        visible: root.length === 0 && root.preeditText.length === 0
        text: root.hint
        textFormat: Text.PlainText
        color: !root.enabled ? (root.tokens ? root.tokens.textDisabled : "#56626b")
                             : (root.tokens ? root.tokens.textMuted : "#7b8994")
        font: root.font
        elide: Text.ElideRight
    }

    Item {
        id: clearButton
        objectName: root.clearObjectName
        visible: root.clearable && root.length > 0 && root.enabled
        width: 28
        height: 28
        anchors.right: parent.right
        anchors.rightMargin: 6
        anchors.verticalCenter: parent.verticalCenter
        Accessible.role: Accessible.Button
        Accessible.name: "Clear"

        Rectangle {
            anchors.fill: parent
            radius: root.tokens ? root.tokens.radiusSmall : 2
            color: clearHover.hovered ? Qt.rgba(1, 1, 1, 0.08) : "transparent"
            Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animHover : 120 } }
        }
        Ui.SbIcon {
            anchors.centerIn: parent
            tokens: root.tokens
            name: "close"
            size: 16
            color: clearHover.hovered ? (root.tokens ? root.tokens.textPrimary : "#edf3f5")
                                      : (root.tokens ? root.tokens.textSecondary : "#a9b7c0")
        }

        HoverHandler {
            id: clearHover
            cursorShape: Qt.PointingHandCursor
        }
        TapHandler {
            onTapped: {
                root.clear()
                root.forceActiveFocus()
            }
        }
    }

    Text {
        visible: root.errorText.length > 0
        x: 0
        y: root.height + 4
        width: root.width
        text: root.errorText
        textFormat: Text.PlainText
        color: root.tokens ? root.tokens.statusErrorInk : "#ffa39d"
        font.pixelSize: root.tokens ? root.tokens.fontHint : 13
        elide: Text.ElideRight
    }
}
