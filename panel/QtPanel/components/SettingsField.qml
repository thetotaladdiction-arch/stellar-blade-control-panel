import QtQuick
import QtQuick.Layouts
import "." as Ui

// One settings row (FINAL-VISUAL-SPEC.md 5.2): 48 px (40 px `dense`, for a
// row with no hint). Left: the label (15 px) and an optional one-line hint
// (13 px textMuted, elided; the full words in its tooltip). Right: one
// control whose right edge is flush with the card's content edge, so every
// control on a card ends on the same x. A 1 px hairline goes under the row
// unless `showSeparator` is false (the last row has none).
//
// A switch row is clickable across its whole width (clicking the label
// toggles the switch). A `subRow` is indented 24 px with an L-shaped guide
// line and no divider above it. A disabled row greys its label.
ColumnLayout {
    id: root
    property var tokens: null
    property string label: ""
    property string value: ""
    property string hint: ""
    property color valueColor: tokens ? tokens.textSecondary : "#a9b7c0"
    property bool hasControl: false
    // A switch needs only its own width; wider controls (selects) use the
    // shared field width so they line up down the card.
    property bool compactControl: false
    property bool showSeparator: true
    // A short row (a label and a switch, no hint).
    property bool dense: false
    // Indented under the row it depends on.
    property bool subRow: false
    default property alias control: slot.data

    Layout.fillWidth: true
    spacing: 0

    readonly property int rowH: root.dense || root.hint.length === 0
                                ? (tokens ? tokens.rowCompact : 40)
                                : (tokens ? tokens.rowHeight : 48)
    readonly property var firstControl: slot.children.length > 0 ? slot.children[0] : null
    readonly property int ctrlW: root.compactControl
                                 ? (root.firstControl && root.firstControl.implicitWidth > 0
                                    ? Math.ceil(root.firstControl.implicitWidth) : 44)
                                 : (tokens ? tokens.fieldWidth : 240)
    readonly property bool togglesOnRowClick: root.hasControl && root.firstControl !== null
                                              && root.firstControl.checkable === true
                                              && typeof root.firstControl.click === "function"

    Item {
        id: row
        Layout.fillWidth: true
        Layout.preferredHeight: root.rowH
        implicitHeight: root.rowH

        // Clicking anywhere on a switch row toggles its switch.
        TapHandler {
            enabled: root.togglesOnRowClick && root.enabled && root.firstControl.enabled
            onTapped: root.firstControl.click()
        }
        HoverHandler {
            enabled: root.togglesOnRowClick && root.enabled
            cursorShape: Qt.PointingHandCursor
        }

        // Sub-row guide: a 10 x 24 px "L" in the control line colour.
        Item {
            visible: root.subRow
            x: 6
            y: 0
            width: 10
            height: Math.round(root.rowH / 2)
            Rectangle {
                width: root.tokens ? root.tokens.hairlineW : 1
                height: parent.height
                color: root.tokens ? root.tokens.controlLine : Qt.rgba(0.745, 0.902, 0.941, 0.22)
            }
            Rectangle {
                y: parent.height - height
                width: parent.width
                height: root.tokens ? root.tokens.hairlineW : 1
                color: root.tokens ? root.tokens.controlLine : Qt.rgba(0.745, 0.902, 0.941, 0.22)
            }
        }

        ColumnLayout {
            id: labelCol
            anchors.left: parent.left
            anchors.leftMargin: root.subRow ? 24 : 0
            anchors.right: slot.left
            anchors.rightMargin: root.tokens ? root.tokens.spaceMd : 16
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0

            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: root.label
                textFormat: Text.PlainText
                color: root.enabled ? (root.tokens ? root.tokens.textPrimary : "#edf3f5")
                                    : (root.tokens ? root.tokens.textDisabled : "#56626b")
                font.pixelSize: root.tokens ? root.tokens.fontBody : 15
                elide: Text.ElideRight
                maximumLineCount: 1
            }

            Text {
                id: hintText
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                visible: root.hint.length > 0 && !root.dense
                text: root.hint
                textFormat: Text.PlainText
                color: root.enabled ? (root.tokens ? root.tokens.textMuted : "#7b8994")
                                    : (root.tokens ? root.tokens.textDisabled : "#56626b")
                font.pixelSize: root.tokens ? root.tokens.fontHint : 13
                elide: Text.ElideRight
                maximumLineCount: 1

                HoverHandler { id: hintHover; enabled: hintText.truncated }
            }
        }

        Item {
            id: slot
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: root.ctrlW
            height: Math.max(24, root.firstControl && root.firstControl.implicitHeight > 0
                                 ? root.firstControl.implicitHeight : 0)
        }

        // A plain value instead of a control ("On", a version number).
        Text {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: root.ctrlW
            visible: !root.hasControl && root.value.length > 0
            text: root.value
            textFormat: Text.PlainText
            color: root.valueColor
            font.pixelSize: root.tokens ? root.tokens.fontBody : 15
            horizontalAlignment: Text.AlignRight
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        Ui.SbToolTip {
            tokens: root.tokens
            visible: hintHover.hovered
            text: root.hint
        }
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: root.tokens ? root.tokens.hairlineW : 1
        visible: root.showSeparator
        color: root.tokens ? root.tokens.hairline : Qt.rgba(0.745, 0.902, 0.941, 0.10)
    }
}
