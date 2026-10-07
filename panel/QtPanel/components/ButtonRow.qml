import QtQuick
import QtQuick.Layouts

// Equal-width buttons on one grid (FINAL-VISUAL-SPEC.md 5.5): 3 per row when
// the card is at least 600 px wide, otherwise 2 (or `maxColumns` when set),
// 8 px apart. A lone last button spans the remaining columns so rows always
// end flush. Put the one primary button last, at the right end.
GridLayout {
    id: root
    property var tokens: null
    property int maxColumns: width >= 600 ? 3 : 2

    Layout.fillWidth: true
    Layout.minimumWidth: 0
    columnSpacing: tokens ? tokens.spaceXs : 8
    rowSpacing: tokens ? tokens.spaceXs : 8
    columns: Math.max(1, Math.min(buttonCount(), maxColumns))
    default property alias buttons: root.data

    function buttonCount() {
        var n = 0
        for (var i = 0; i < root.children.length; i++) {
            if (root.children[i] && root.children[i].Layout)
                n++
        }
        return n
    }

    Component.onCompleted: wireChildren()
    onChildrenChanged: Qt.callLater(wireChildren)
    onWidthChanged: Qt.callLater(wireChildren)
    onMaxColumnsChanged: Qt.callLater(wireChildren)

    function wireChildren() {
        var h = tokens ? tokens.btnHeight : 40
        var count = buttonCount()
        var cols = Math.max(1, Math.min(count, root.maxColumns))
        root.columns = cols
        var remainder = count % cols
        for (var i = 0; i < root.children.length; i++) {
            var c = root.children[i]
            if (!c || !c.Layout)
                continue
            c.Layout.fillWidth = true
            c.Layout.preferredWidth = 1
            c.Layout.preferredHeight = h
            c.Layout.minimumWidth = 0
            c.Layout.alignment = Qt.AlignVCenter
            c.Layout.columnSpan = 1
            if (remainder !== 0 && i === root.children.length - 1)
                c.Layout.columnSpan = cols - remainder + 1
        }
    }
}
