import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var tokens: null
    property int inset: 0

    // Attached ScrollBars overlay a Flickable instead of taking layout space.
    // Reserve a gutter only when the rail is visible so wrapped text and other
    // content never render beneath the thumb at narrow/docked window widths.
    readonly property bool needsVerticalScroll: flick.contentHeight > flick.height + 2
    readonly property real scrollBarGutter: needsVerticalScroll
                                                   ? scrollBar.implicitWidth + 4
                                                   : 0

    default property alias content: contentCol.data

    clip: true

    Flickable {
        id: flick
        anchors.fill: parent
        anchors.margins: root.inset
        boundsBehavior: Flickable.StopAtBounds
        maximumFlickVelocity: 0
        flickDeceleration: 100000
        clip: true
        interactive: false
        contentWidth: width
        contentHeight: contentCol.implicitHeight

        ColumnLayout {
            id: contentCol
            width: Math.max(0, flick.width - root.scrollBarGutter)
            spacing: 0
        }

        ScrollBar.vertical: PanelScrollBar {
            id: scrollBar
            tokens: root.tokens
            policy: root.needsVerticalScroll ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
        }
    }

    WheelScroller {
        view: flick
        tokens: root.tokens
        wheelStep: 90
    }
}
