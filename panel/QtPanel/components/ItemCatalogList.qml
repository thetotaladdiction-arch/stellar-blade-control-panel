pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "." as Ui

// The Items & Money catalog viewport: the list, its scrollbar, wheel handling
// and the empty state. It lives in its own component so the exact production
// delegate can be driven by the offscreen Qt runtime tests
// (tests/test_items_qml_runtime.py) - scrolled by wheel and by dragging the
// scrollbar, filtered, cleared, resized and refreshed.
//
// Each row (FINAL-VISUAL-SPEC.md 5.9): 44 px, the item's game name on the
// left and its category in a quiet 13 px column on the right. No chip: an
// item that can be added needs no word. One the Items & Money game mod says
// can't be added now (Owned, At limit, Needs DLC, Not available) greys its
// name and shows that word in the warning ink instead of the category. A
// hairline separates the rows. Hover is white 4 %; the chosen row is accent
// 10 % with a 3 px accent bar at its left edge. A search-only row (never
// addable) puts its plain reason under its name in the warning ink.
//
// Rules that keep every row readable:
//  * Delegates are not recycled (reuseItems: false). With a few hundred
//    light rows recycling saves nothing, and pooled rows would stay parked
//    inside the list where they cannot be told apart from real ones.
//  * Wheel scrolling respects the list's real extent (WheelScroller): after
//    a search the rows no longer start at y = 0, and a wheel clamped to 0
//    scrolled into empty space - the "blank catalog" bug.
//  * Names, captions and reasons render as plain text, never as
//    auto-detected rich text.
//  * Nothing is cut off: a long name wraps to a second line and a reason
//    wraps under it; the row grows to fit. Only below the supported width
//    does a name shorten, and then its tooltip shows it whole.
//  * The category column keeps its own width; the name gives way.
//  * A new search or category always starts at the first result
//    (showFirstItem), so no row is left half-scrolled under the top edge.
//  * Search-only rows (items that can't be added, shown only while a search
//    finds them) come after every listed result, under one quiet heading,
//    and can't be chosen.
Rectangle {
    id: root

    property var tokens: null
    property var model: null
    property string selectedAlias: ""
    // Every category name, so the category column is as wide as the widest
    // one and the categories line up down the list.
    property var categories: []
    // True while a search or category narrows the list; the empty state then
    // offers to clear it.
    property bool filtered: false
    // Index of the first search-only row (the listed results come first);
    // -1 when there is none.
    property int firstSearchOnlyIndex: -1

    signal itemSelected(string alias, string name)
    signal clearFilterRequested()

    readonly property int rowHeight: tokens ? tokens.catalogRowHeight : 44
    // Rows abut; the hairline at each row's foot separates them.
    readonly property int rowSpacing: 0
    // 12 px at the sides; at least 10 px above and below: a one-line row is
    // exactly 44 px.
    readonly property int rowPad: 12
    readonly property int rowPadY: 10
    // The row stops short of the scrollbar's grab lane (18 px + 4 px gap), so
    // the category never sits under the thumb.
    readonly property int scrollLane: 22
    readonly property int count: catalogList.count

    // The words a row shows instead of its category when it can't be added.
    readonly property var verdictWords: ["Owned", "At limit", "Needs DLC", "Not available"]
    // The category column: the widest category name or verdict word (plus a
    // pixel so the measured and laid-out widths never disagree about a
    // cut-off).
    readonly property real categoryColumn: {
        var widest = 0
        var names = (root.categories || []).concat(root.verdictWords)
        // Read the metrics' height so a font change re-measures.
        var unused = captionMetrics.height
        for (var i = 0; i < names.length; ++i)
            widest = Math.max(widest, captionMetrics.advanceWidth(String(names[i])))
        return Math.ceil(widest) + 2
    }

    FontMetrics {
        id: captionMetrics
        font.pixelSize: root.tokens ? root.tokens.fontLabel : 13
        font.family: root.tokens ? root.tokens.typeFamily : "Segoe UI Variable Text"
    }

    function showFirstItem(): void {
        wheel.stop()
        catalogList.positionViewAtBeginning()
    }

    // A catalog reload (a toggle adds or removes a group) resets the model,
    // and a reset ListView jumps back to the first row. Keep the row the
    // player was looking at, at the same offset, instead; a shorter list
    // lands at its end.
    property int reloadIndex: -1
    property real reloadOffset: 0

    // The row at the top edge of the viewport, or -1 for an empty list. The
    // edge can sit in a gap between two rows (when rows are spaced), where
    // indexAt() finds nothing; the row below the gap is the one on screen
    // then. (Missing it sent every reload taken at such an offset back to
    // the first row.)
    function topRowIndex(): int {
        const y = catalogList.contentY
        const index = catalogList.indexAt(1, y + 1)
        return index >= 0 ? index : catalogList.indexAt(1, y + root.rowSpacing + 1)
    }

    Connections {
        target: root.model
        ignoreUnknownSignals: true
        function onModelAboutToBeReset() {
            wheel.stop()
            const index = root.topRowIndex()
            const row = index >= 0 ? catalogList.itemAtIndex(index) : null
            root.reloadIndex = row ? index : -1
            root.reloadOffset = row ? catalogList.contentY - row.y : 0
        }
        function onModelReset() {
            const index = root.reloadIndex
            const offset = root.reloadOffset
            root.reloadIndex = -1
            if (index < 0 || (index === 0 && offset <= 0))
                return
            Qt.callLater(function() {
                if (catalogList.count === 0)
                    return
                const target = Math.min(index, catalogList.count - 1)
                catalogList.positionViewAtIndex(target, ListView.Beginning)
                if (target === index)
                    catalogList.contentY = wheel.clampY(catalogList.contentY + offset)
            })
        }
    }

    Layout.fillWidth: true
    Layout.preferredHeight: 5 * rowHeight
    // A quiet well under the rows, so the scrolling area reads as one.
    color: tokens ? tokens.white(0.025) : Qt.rgba(1, 1, 1, 0.025)
    clip: true

    ListView {
        id: catalogList
        objectName: "itemsCatalogList"
        anchors.fill: parent
        model: root.model
        clip: true
        spacing: root.rowSpacing
        reuseItems: false
        cacheBuffer: 640
        boundsBehavior: Flickable.StopAtBounds
        boundsMovement: Flickable.StopAtBounds

        delegate: Item {
            id: itemRow
            objectName: "itemsCatalogRow"
            required property int index
            required property string alias
            required property string name
            required property string category
            required property bool listed
            required property string chipText
            required property string chipKind
            required property string reason
            readonly property bool selected: itemRow.listed && root.selectedAlias.length > 0
                                             && root.selectedAlias === itemRow.alias
            // The first search-only result carries the heading above it.
            readonly property bool headed: !itemRow.listed && itemRow.index === root.firstSearchOnlyIndex
            // A search-only row says why it can't be added, under its name.
            readonly property bool reasonBelow: !itemRow.listed && itemRow.reason.length > 0
            // A listed item the game mod says can't be added now: its word
            // (Owned, At limit, Needs DLC, Not available) replaces the
            // category. "Ready" (kind ok) needs no word.
            readonly property bool blocked: itemRow.listed && itemRow.chipText.length > 0
                                            && itemRow.chipKind !== "ok"
            readonly property real headingHeight: itemRow.headed ? heading.implicitHeight : 0

            width: Math.max(0, catalogList.width - root.scrollLane)
            // An even height keeps every row on whole device pixels at 100 %
            // and 150 %, so text never lands between two pixels as rows of
            // different heights stack up.
            height: 2 * Math.ceil((Math.max(root.rowHeight, cells.implicitHeight + root.rowPadY * 2)
                                   + itemRow.headingHeight) / 2)

            Ui.SbSubhead {
                id: heading
                objectName: "itemsCatalogSearchOnlyHeading"
                visible: itemRow.headed
                x: root.rowPad
                y: 0
                width: parent.width - root.rowPad * 2
                tokens: root.tokens
                text: "Found by search, but can't be added"
            }

            Rectangle {
                id: surface
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: parent.height - itemRow.headingHeight
                color: !root.tokens ? "transparent"
                       : itemRow.selected ? root.tokens.alpha(root.tokens.accent, 0.10)
                       : itemRow.listed && itemHover.hovered ? root.tokens.white(0.04)
                       : "transparent"
                Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animHover : 120 } }

                // The chosen row's 3 px accent bar.
                Rectangle {
                    visible: itemRow.selected
                    width: 3
                    height: parent.height
                    color: root.tokens ? root.tokens.accent : "#56e0d3"
                }

                // The hairline between rows.
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: root.tokens ? root.tokens.hairlineW : 1
                    color: root.tokens ? root.tokens.hairline : Qt.rgba(0.745, 0.902, 0.941, 0.10)
                }

                GridLayout {
                    id: cells
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: root.rowPad
                    anchors.rightMargin: root.rowPad
                    columns: 2
                    columnSpacing: 12
                    rowSpacing: 2

                    Text {
                        id: nameText
                        objectName: "itemsCatalogName"
                        Layout.row: 0
                        Layout.column: 0
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        // Name and category share a baseline.
                        Layout.alignment: Qt.AlignBaseline
                        text: itemRow.name
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        color: !root.tokens ? "#edf3f5"
                               : itemRow.listed && !itemRow.blocked ? root.tokens.textPrimary
                               : root.tokens.textSecondary
                        font.pixelSize: root.tokens ? root.tokens.fontBody : 15
                        font.family: itemRow.selected
                                     ? (root.tokens ? root.tokens.typeSemibold : "Segoe UI Variable Text Semibold")
                                     : (root.tokens ? root.tokens.typeFamily : "Segoe UI Variable Text")
                        font.weight: itemRow.selected ? Font.DemiBold : Font.Normal
                        font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
                    }

                    // A listed row names its category in the column (or, when
                    // it can't be added now, the game mod's word); a
                    // search-only row says why it can't be added, under its
                    // name and across the category column.
                    Text {
                        id: captionText
                        objectName: "itemsCatalogCategory"
                        Layout.row: itemRow.reasonBelow ? 1 : 0
                        Layout.column: itemRow.reasonBelow ? 0 : 1
                        Layout.columnSpan: itemRow.reasonBelow ? 2 : 1
                        Layout.fillWidth: itemRow.reasonBelow
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: itemRow.reasonBelow ? -1 : root.categoryColumn
                        Layout.alignment: itemRow.reasonBelow ? Qt.AlignTop | Qt.AlignLeft : Qt.AlignBaseline
                        text: itemRow.reasonBelow ? itemRow.reason
                              : itemRow.blocked ? itemRow.chipText : itemRow.category
                        textFormat: Text.PlainText
                        wrapMode: itemRow.reasonBelow ? Text.Wrap : Text.NoWrap
                        maximumLineCount: itemRow.reasonBelow ? 3 : 1
                        elide: Text.ElideRight
                        color: !root.tokens ? "#7b8994"
                               : itemRow.reasonBelow || itemRow.blocked ? root.tokens.statusWarnInk
                               : root.tokens.textMuted
                        font.pixelSize: root.tokens ? root.tokens.fontLabel : 13
                        font.family: root.tokens ? root.tokens.typeFamily : "Segoe UI Variable Text"
                        font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
                    }
                }

                HoverHandler {
                    id: itemHover
                    enabled: itemRow.listed
                    cursorShape: Qt.PointingHandCursor
                }
                TapHandler {
                    enabled: itemRow.listed
                    onTapped: root.itemSelected(itemRow.alias, itemRow.name)
                }
                // Search-only rows still explain themselves on hover.
                HoverHandler {
                    id: reasonHover
                    enabled: !itemRow.listed
                }

                Ui.SbToolTip {
                    tokens: root.tokens
                    visible: (itemHover.hovered || reasonHover.hovered)
                             && (nameText.truncated || captionText.truncated)
                    text: itemRow.reasonBelow ? itemRow.name + " · " + itemRow.reason
                          : itemRow.name + " · " + captionText.text
                }
            }
        }

        ScrollBar.vertical: Ui.PanelScrollBar {
            objectName: "itemsCatalogScrollBar"
            tokens: root.tokens
            policy: ScrollBar.AsNeeded
        }

        Ui.WheelScroller {
            id: wheel
            objectName: "itemsCatalogWheelScroller"
            view: catalogList
            tokens: root.tokens
        }
    }

    // The well's top and bottom edges, drawn over the rows.
    Rectangle {
        z: 2
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: root.tokens ? root.tokens.hairlineW : 1
        color: root.tokens ? root.tokens.controlLine : Qt.rgba(0.745, 0.902, 0.941, 0.22)
    }
    Rectangle {
        z: 2
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: root.tokens ? root.tokens.hairlineW : 1
        color: root.tokens ? root.tokens.controlLine : Qt.rgba(0.745, 0.902, 0.941, 0.22)
    }

    Ui.EmptyState {
        objectName: "itemsCatalogEmpty"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.margins: 12
        visible: catalogList.count === 0
        tokens: root.tokens
        message: !root.filtered && catalogList.count === 0
                 ? "The item list is missing. Run One-Click Repair on Support."
                 : "No items match. Try another search or category."
        actionText: root.filtered ? "Show all items" : ""
        onActionClicked: root.clearFilterRequested()
    }
}
