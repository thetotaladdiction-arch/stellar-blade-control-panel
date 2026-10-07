import QtQuick
import QtQuick.Layouts
import "." as Ui

// The fold (FINAL-VISUAL-SPEC.md 5.11): a 48 px row with a label, a one-line
// summary hint, a count ("8 on", 15 px Bahnschrift SemiBold) and a 16 px
// chevron. One click opens it: the chevron turns 180 degrees and the content
// below grows over 200 ms with a clip. One level only; put the content in as
// children. The whole row is the hit area; Tab reaches it and Space or Enter
// toggles it. Nothing moves at rest.
ColumnLayout {
    id: root
    property var tokens: null
    property string text: ""
    // What is inside, in a few words (13 px textMuted, one line, elided).
    property string hint: ""
    // Short count at the right ("8 on").
    property string count: ""
    property bool expanded: false
    signal toggled()

    default property alias content: body.data

    Layout.fillWidth: true
    spacing: 0

    activeFocusOnTab: true
    Keys.onSpacePressed: root.toggled()
    Keys.onReturnPressed: root.toggled()
    Keys.onEnterPressed: root.toggled()
    Accessible.role: Accessible.Button
    Accessible.name: root.count.length > 0 ? root.text + ", " + root.count : root.text
    Accessible.description: root.hint
    Accessible.checkable: true
    Accessible.checked: root.expanded

    // 0 = closed, 1 = open. Only a toggle changes it, so a window resize
    // re-flows the open content at once instead of animating.
    property real openAmount: root.expanded ? 1.0 : 0.0
    Behavior on openAmount {
        NumberAnimation { duration: root.tokens ? root.tokens.animFold : 200; easing.type: Easing.OutCubic }
    }

    Item {
        id: header
        Layout.fillWidth: true
        readonly property int rowH: root.hint.length > 0 ? (root.tokens ? root.tokens.rowHeight : 48)
                                                          : (root.tokens ? root.tokens.rowCompact : 40)
        Layout.preferredHeight: rowH
        implicitHeight: rowH

        // Hover and press feedback, reaching 8 px into the card padding.
        Rectangle {
            anchors.fill: parent
            anchors.leftMargin: -8
            anchors.rightMargin: -8
            color: Qt.rgba(1, 1, 1, tap.pressed ? 0.10 : (hover.hovered ? 0.04 : 0.0))
            border.width: root.activeFocus ? 2 : 0
            border.color: root.tokens ? root.tokens.accent : "#56e0d3"
            Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animHover : 120 } }
        }

        ColumnLayout {
            anchors.left: parent.left
            anchors.right: tail.left
            anchors.rightMargin: root.tokens ? root.tokens.spaceMd : 16
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0

            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: root.text
                textFormat: Text.PlainText
                color: root.tokens ? root.tokens.textPrimary : "#edf3f5"
                font.pixelSize: root.tokens ? root.tokens.fontBody : 15
                font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
                elide: Text.ElideRight
                maximumLineCount: 1
            }

            Text {
                id: hintText
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                visible: root.hint.length > 0
                text: root.hint
                textFormat: Text.PlainText
                color: root.tokens ? root.tokens.textMuted : "#7b8994"
                font.pixelSize: root.tokens ? root.tokens.fontHint : 13
                font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
                elide: Text.ElideRight
                maximumLineCount: 1
            }
        }

        // The count and the chevron. The chevron box is 16 px wide, so its
        // right edge is the card's content edge, the same x every other
        // control ends on.
        Row {
            id: tail
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: root.tokens ? root.tokens.spaceXs : 8

            Text {
                id: countText
                anchors.verticalCenter: parent.verticalCenter
                visible: root.count.length > 0
                text: root.count
                textFormat: Text.PlainText
                color: root.tokens ? root.tokens.textSecondary : "#a9b7c0"
                font.family: root.tokens ? root.tokens.typeDisplaySemibold : "Bahnschrift SemiBold"
                font.pixelSize: root.tokens ? root.tokens.fontBody : 15
                font.features: { "tnum": 1 }
                font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
            }

            Ui.ChevronIndicator {
                id: chevron
                anchors.verticalCenter: parent.verticalCenter
                width: root.tokens ? root.tokens.iconSmall : 16
                height: 24
                tokens: root.tokens
                expanded: root.expanded
                highlighted: hover.hovered
                pressed: tap.pressed
            }
        }

        HoverHandler {
            id: hover
            cursorShape: Qt.PointingHandCursor
        }
        TapHandler {
            id: tap
            onTapped: root.toggled()
        }

        Ui.SbToolTip {
            tokens: root.tokens
            visible: hover.hovered && hintText.truncated
            text: root.hint
        }
    }

    // The folded content. Hidden (and out of the Tab order) while closed;
    // clipped only while it grows or shrinks.
    Item {
        id: bodyClip
        Layout.fillWidth: true
        Layout.preferredHeight: Math.round(body.implicitHeight * root.openAmount)
        implicitHeight: Layout.preferredHeight
        visible: root.openAmount > 0
        clip: root.openAmount < 1

        ColumnLayout {
            id: body
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            spacing: 0
        }
    }
}
