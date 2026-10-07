import QtQuick
import QtQuick.Layouts
import "." as Ui

// Card header (FINAL-VISUAL-SPEC.md 5.1), the only section header on a
// page. One 24 px line: 20 px icon (accent while the feature is live,
// textMuted otherwise), 12 px gap, 18 px title, then on the right the status
// chip, 8 px, and the (i) help button. Under it, 4 px lower, the card's one
// line: 14 px textSecondary, never more than one line; when it is cut short
// the (i) tooltip carries the whole sentence.
//
// A collapsible card adds a 13 px summary and a chevron at the right end,
// and opens from anywhere on its header (the line included).
ColumnLayout {
    id: root
    property var tokens: null
    property string text: ""
    property string subtitle: ""
    property string helpTip: ""
    // Line icon name (DesignSystem/Icons.js); empty = no icon.
    property string icon: ""
    // Kept for older callers; the header colour no longer follows a page tint.
    property color neonColor: root.tokens ? root.tokens.accent : "#56e0d3"
    property bool showChevron: false
    property bool expanded: false
    // The feature is live: the icon turns accent.
    property bool highlighted: false
    // Status shown in the header (StatusChip), e.g. "Active" / "ok".
    property string status: ""
    property string statusKind: "off"
    // Collapsed cards show this on the right ("Last entry 12:23").
    property string summary: ""

    signal headerTapped()

    readonly property bool lineShown: root.subtitle.length > 0 && (!root.showChevron || root.expanded)
    readonly property string tipWords: {
        var full = root.lineShown && lineText.truncated ? root.subtitle : ""
        if (full.length > 0 && root.helpTip.length > 0)
            return full + "\n\n" + root.helpTip
        return full.length > 0 ? full : root.helpTip
    }

    spacing: root.tokens ? root.tokens.spaceXxs : 4
    Layout.minimumWidth: 0

    Item {
        id: headerRow
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        Layout.preferredHeight: 24
        implicitHeight: 24

        // The whole header opens a collapsible card. It sits under the chip
        // and the (i) so their own hover still works.
        MouseArea {
            id: headerMouse
            anchors.fill: parent
            anchors.margins: -4
            enabled: root.showChevron
            hoverEnabled: true
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: root.headerTapped()
        }

        RowLayout {
            anchors.fill: parent
            spacing: 0

            Ui.SbIcon {
                visible: root.icon.length > 0
                Layout.alignment: Qt.AlignVCenter
                Layout.rightMargin: root.tokens ? root.tokens.spaceSm : 12
                tokens: root.tokens
                name: root.icon
                size: root.tokens ? root.tokens.iconSize : 20
                color: root.highlighted ? (root.tokens ? root.tokens.accent : "#56e0d3")
                                        : (root.tokens ? root.tokens.textMuted : "#7b8994")
            }

            Text {
                id: titleText
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.alignment: Qt.AlignVCenter
                text: root.text
                textFormat: Text.PlainText
                color: root.tokens ? root.tokens.textPrimary : "#edf3f5"
                font.pixelSize: root.tokens ? root.tokens.fontHeading : 18
                font.family: root.tokens ? root.tokens.typeDisplaySemibold : "Bahnschrift SemiBold"
                font.weight: Font.DemiBold
                font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
                elide: Text.ElideRight
                maximumLineCount: 1
            }

            Text {
                visible: root.showChevron && !root.expanded && root.summary.length > 0
                Layout.alignment: Qt.AlignVCenter
                Layout.leftMargin: root.tokens ? root.tokens.spaceXs : 8
                Layout.maximumWidth: Math.max(80, headerRow.width * 0.45)
                text: root.summary
                textFormat: Text.PlainText
                color: root.tokens ? root.tokens.textMuted : "#7b8994"
                font.pixelSize: root.tokens ? root.tokens.fontHint : 13
                elide: Text.ElideRight
                maximumLineCount: 1
            }

            Ui.StatusChip {
                Layout.alignment: Qt.AlignVCenter
                Layout.leftMargin: root.tokens ? root.tokens.spaceXs : 8
                Layout.maximumWidth: 280
                tokens: root.tokens
                text: root.status
                kind: root.statusKind
            }

            Ui.HelpTip {
                visible: root.tipWords.length > 0
                tokens: root.tokens
                tipText: root.tipWords
                Layout.alignment: Qt.AlignVCenter
                Layout.leftMargin: root.tokens ? root.tokens.spaceXs : 8
            }

            Item {
                id: chevronHitTarget
                visible: root.showChevron
                Layout.alignment: Qt.AlignVCenter
                Layout.leftMargin: root.tokens ? root.tokens.spaceXs : 8
                Layout.preferredWidth: 24
                Layout.preferredHeight: 24

                Ui.ChevronIndicator {
                    anchors.fill: parent
                    tokens: root.tokens
                    expanded: root.expanded
                    highlighted: headerMouse.containsMouse || chevronMouse.containsMouse
                                 || subtitleHover.hovered
                    pressed: headerMouse.pressed || chevronMouse.pressed || subtitleTap.pressed
                }

                MouseArea {
                    id: chevronMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.headerTapped()
                }
            }
        }
    }

    Text {
        id: lineText
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        Layout.preferredHeight: 20
        visible: root.lineShown
        text: root.subtitle
        textFormat: Text.PlainText
        color: root.tokens ? root.tokens.textSecondary : "#a9b7c0"
        font.pixelSize: root.tokens ? root.tokens.fontCaption : 14
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        maximumLineCount: 1

        // A collapsible card opens from anywhere on its header, the line
        // under the title included.
        HoverHandler {
            id: subtitleHover
            enabled: root.showChevron
            cursorShape: Qt.PointingHandCursor
        }
        TapHandler {
            id: subtitleTap
            enabled: root.showChevron
            onTapped: root.headerTapped()
        }
    }
}
