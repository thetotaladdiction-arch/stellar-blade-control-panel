import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "../DesignSystem/PageTheme.js" as PageTheme

Item {
    id: root
    // Pages set this one property (they must not declare their own
    // `tokens`: a shadowing property left this one null, so four pages fell
    // back to a 14 px card gap and 32 px padding while Items used 16 / 48).
    property var tokens: null
    property bool active: true
    property real slideY: 0
    property string pageId: "gameplay"

    readonly property color pageNeon: PageTheme.pageNeonColor(pageId, tokens)
    // Cards fill the column exactly (FINAL-VISUAL-SPEC.md 3.1): the card's
    // left edge and content edge line up with the top bar's title, and the
    // scroll rail lives in the divider beside the sidebar, not in the column.
    readonly property int scrollGutter: 0
    // The 18 px grab lane is centred in the 16 px gap between the sidebar
    // and the column, so the 10 px thumb touches neither.
    readonly property int navigationRailGap: Math.round(((tokens ? tokens.gap : 16) - 18) / 2)
    // Room under the last card when the page scrolls to its end.
    property int bottomPadding: 0
    // Height of the cards themselves (main.qml bottom-aligns the Dashboard).
    readonly property real contentImplicitHeight: contentColumn.implicitHeight

    default property alias content: contentColumn.data

    clip: false
    // The page-change rise lands on whole device pixels at every step.
    transform: Translate { y: root.tokens ? root.tokens.snap(root.slideY) : Math.round(root.slideY) }

    readonly property bool needsScroll: flick.contentHeight > flick.height + 2

    // The glass under every card samples the art in window coordinates, so
    // anything that moves the cards in the window tells it (Tokens.bumpGlass).
    function bumpGlass() {
        if (root.tokens && root.visible)
            root.tokens.bumpGlass()
    }
    onSlideYChanged: bumpGlass()
    onVisibleChanged: bumpGlass()

    Flickable {
        id: flick
        objectName: "pageScrollFlick"
        anchors.fill: parent
        boundsBehavior: Flickable.StopAtBounds
        // Lower deceleration lets a flick coast instead of stopping abruptly.
        flickDeceleration: 1600
        maximumFlickVelocity: 2800
        clip: true
        interactive: root.needsScroll
        contentWidth: width
        contentHeight: contentColumn.implicitHeight + root.bottomPadding
        pixelAligned: true

        onContentHeightChanged: {
            if (!root.needsScroll && contentY > 0)
                contentY = 0
            root.bumpGlass()
        }
        onContentYChanged: root.bumpGlass()
        onWidthChanged: root.bumpGlass()

        ColumnLayout {
            id: contentColumn
            objectName: "pageScrollContent"
            // The width never depends on whether the page scrolls (the rail is
            // outside the column), so opening a card never reflows the page.
            width: Math.max(0, flick.width - root.scrollGutter)
            // 16 px between cards, down and across.
            spacing: root.tokens ? root.tokens.gap : 16
        }

        // MUST stay inside the Flickable. As a sibling it never saw a wheel
        // event: an interactive Flickable is the item under the cursor, so it
        // handled and accepted the wheel itself and the handler was starved.
        // (FixedScrollBox gets away with a sibling only because its Flickable
        // is interactive: false, which does not consume wheel events.)
        WheelScroller {
            view: flick
            tokens: root.tokens
        }
    }

    PanelScrollBar {
        id: scrollBar
        objectName: "pageScrollBar"
        // Feature artwork is authored on the right. Keep the page rail in the
        // navigation/content divider instead of drawing a bright line over
        // the character. The bar is linked by hand because an attached
        // ScrollBar owns its edge geometry even after a parent override.
        parent: root
        anchors.top: root.top
        anchors.bottom: root.bottom
        anchors.right: root.left
        anchors.rightMargin: root.navigationRailGap
        z: 2
        tokens: root.tokens
        // A 4 px line in the 16 px gap, shown only while the page scrolls or
        // the pointer is on it (2.5.504 review: a 10 px bar always showed,
        // 3 px from the sidebar).
        thumbWidth: 4
        restOpacity: 0.0
        orientation: Qt.Vertical
        policy: root.needsScroll ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
        size: root.needsScroll ? Math.min(1.0, flick.visibleArea.heightRatio) : 1.0
        active: root.needsScroll
                && (flick.moving || flick.flicking || hovered || pressed)

        Binding on position {
            when: !scrollBar.pressed
            value: flick.visibleArea.yPosition
            restoreMode: Binding.RestoreBindingOrValue
        }

        onPositionChanged: {
            if (!pressed || flick.contentHeight <= 0)
                return
            var maximumY = Math.max(0, flick.contentHeight - flick.height)
            flick.contentY = Math.max(0, Math.min(maximumY,
                                                  position * flick.contentHeight))
        }
    }
}
