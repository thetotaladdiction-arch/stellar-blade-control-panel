import QtQuick
import QtQuick.Layouts
import "." as Ui

// A labelled slider (FINAL-VISUAL-SPEC.md 5.7). A 24 px header: the label
// (15 px) with its range written inline (13 px textMuted, "50-300%"), an
// optional amber note ("experimental above 100°"), and the value at the
// right (18 px Bahnschrift SemiBold, tabular figures). 8 px below it, the
// segmented SbSlider. The value turns amber only while it sits in the
// experimental range. The field contains the complete 32 px slider hit area
// below its 24 px header, keeping the gap to the next slider clear.
Item {
    id: root
    property var tokens: null
    property string label: ""
    property string rangeText: ""
    property string experimentalText: ""
    property string valueText: ""
    property alias from: slider.from
    property alias to: slider.to
    property alias value: slider.value
    property alias stepSize: slider.stepSize
    property alias snapMode: slider.snapMode
    property alias live: slider.live
    property alias normalValue: slider.normalValue
    property alias experimentalFrom: slider.experimentalFrom
    property alias keyStep: slider.keyStep
    property alias pageStep: slider.pageStep
    property alias pressed: slider.pressed
    property alias accentColor: slider.accentColor
    readonly property alias slider: slider
    readonly property bool experimental: slider.experimental

    signal moved()

    Layout.fillWidth: true
    implicitWidth: 320
    implicitHeight: 56

    RowLayout {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        height: 24
        spacing: 8

        Text {
            Layout.alignment: Qt.AlignVCenter
            Layout.minimumWidth: 0
            // Whole pixels: a fractional text width was rounded down by the
            // layout and elided the label ("Movement spe...").
            Layout.preferredWidth: Math.ceil(implicitWidth)
            Layout.maximumWidth: Math.ceil(implicitWidth)
            Layout.fillWidth: true
            text: root.label
            textFormat: Text.PlainText
            color: root.enabled ? (root.tokens ? root.tokens.textPrimary : "#edf3f5")
                                : (root.tokens ? root.tokens.textDisabled : "#56626b")
            font.pixelSize: root.tokens ? root.tokens.fontBody : 15
            elide: Text.ElideRight
        }

        Text {
            id: rangeLabel
            Layout.alignment: Qt.AlignVCenter
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            visible: root.rangeText.length > 0 || root.experimentalText.length > 0
            textFormat: Text.StyledText
            text: root.rangeText
                  + (root.experimentalText.length > 0
                     ? (root.rangeText.length > 0 ? " · " : "")
                       + "<font color=\"" + (!root.enabled ? (root.tokens ? root.tokens.textDisabled : "#56626b")
                                             : (root.tokens ? root.tokens.statusWarnInk : "#ffcd92")) + "\">"
                       + root.experimentalText + "</font>"
                     : "")
            color: !root.enabled ? (root.tokens ? root.tokens.textDisabled : "#56626b")
                   : (root.tokens ? root.tokens.textMuted : "#7b8994")
            font.pixelSize: root.tokens ? root.tokens.fontHint : 13
            elide: Text.ElideRight
            maximumLineCount: 1
        }

        Text {
            Layout.alignment: Qt.AlignVCenter
            text: root.valueText
            textFormat: Text.PlainText
            color: !root.enabled ? (root.tokens ? root.tokens.textDisabled : "#56626b")
                   : root.experimental ? (root.tokens ? root.tokens.statusWarn : "#ffb45e")
                   : (root.tokens ? root.tokens.textPrimary : "#edf3f5")
            font.pixelSize: root.tokens ? root.tokens.fontValue : 18
            font.family: root.tokens ? root.tokens.typeDisplaySemibold : "Bahnschrift SemiBold"
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
            font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
            Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animHover : 120 } }
        }
    }

    Ui.SbSlider {
        id: slider
        anchors.left: parent.left
        anchors.right: parent.right
        y: 24
        tokens: root.tokens
        enabled: root.enabled
        onMoved: root.moved()
    }
}
