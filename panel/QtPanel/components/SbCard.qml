import QtQuick
import QtQuick.Layouts
import "../DesignSystem/PageTheme.js" as PageTheme
import "." as Ui

// Feature card (FINAL-VISUAL-SPEC.md 5.1): the glass surface with its 12 px
// notch, 1 px edge and 40 px tick; 16 px padding measured from the outer
// edge; a 24 px header (icon, title, chip, (i)); one 14 px line 4 px under
// it; then the controls 12 px lower. A header-only card ends right under its
// line. A collapsible card is 56 px closed (header, summary, chevron) and
// grows into a normal card, its height animating over 200 ms with a clip.
//
// No shadow (cards are glass on art), no glow, nothing animates at rest.
Item {
    id: root
    property var tokens: null
    property string title: ""
    // The card's one line (14 px, one line; the full words go to the (i)).
    property string subtitle: ""
    property string helpTip: ""
    // Line icon (DesignSystem/Icons.js) at the start of the header.
    property string icon: ""
    // Stable identity of the card ("GOD", "BOSS", "MOVEMENT"...). It names
    // the card for tests and supplies a title when none is given.
    property string neonTag: ""
    property bool showTag: false
    property var appBackend: null
    // The feature is live: the header icon turns accent.
    property bool accentActive: false
    // Kept so older pages still bind them; the frame is one colour now.
    property color pageAccent: "transparent"
    property color statusAccent: "transparent"
    property bool tagOnly: false
    // Header status, drawn by the shared StatusChip (e.g. "Active" + "ok").
    property string status: ""
    property string statusKind: "off"
    property bool collapsible: false
    property bool expanded: true
    // Collapsed cards show this at the right of the header.
    property string summary: ""
    // Gap between the body's controls: 12 (sliders, rows); 8 for button rows.
    property int bodySpacing: tokens ? tokens.spaceSm : 12
    // Padding: 16 on every side. The Dashboard's list card uses 8 top and
    // bottom, 16 left and right.
    property int padX: tokens ? tokens.cardPad : 16
    property int padY: tokens ? tokens.cardPad : 16
    readonly property int pad: padX

    readonly property string resolvedTitle: title.length > 0 ? title : PageTheme.sectionTitle(neonTag)
    readonly property bool headerShown: root.resolvedTitle.length > 0 || root.subtitle.length > 0
                                        || root.status.length > 0
    readonly property real bodyOpacity: !root.collapsible || root.expanded ? 1.0 : 0.0

    default property alias content: body.data

    Layout.fillWidth: true
    Layout.minimumWidth: 0

    // Folding animates the card's height. The animation is enabled only for
    // the moment of a click, so window resizes and live text changes re-flow
    // at once instead of trailing behind.
    property bool animateHeight: false
    readonly property real openHeight: inner.implicitHeight + padY * 2
    readonly property real closedHeight: header.implicitHeight + padY * 2
    implicitHeight: !root.collapsible || root.expanded ? openHeight : closedHeight
    Behavior on implicitHeight {
        enabled: root.animateHeight
        NumberAnimation {
            duration: root.tokens ? root.tokens.animFold : 200
            easing.type: Easing.OutCubic
            onRunningChanged: if (!running) root.animateHeight = false
        }
    }
    function toggleExpanded() {
        root.animateHeight = root.tokens ? root.tokens.animFold > 0 : true
        root.expanded = !root.expanded
    }

    // Glass: reduced-effects fill, tokens.surfaceCardOpacity (94 %).
    Ui.GlassSurface {
        id: cardShell
        anchors.fill: parent
        tokens: root.tokens
    }

    // Clips only while the height animates, so nothing spills past the edge
    // mid-fold and nothing is clipped at rest.
    Item {
        anchors.fill: parent
        clip: root.animateHeight

        ColumnLayout {
            id: inner
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: root.padX
            anchors.rightMargin: root.padX
            anchors.topMargin: root.padY
            // The gap under the header belongs to the body: a card whose
            // controls are all hidden (Retry Point while its game mod is not
            // installed) ends right under its line instead of 12 px lower.
            spacing: 0

            Ui.NeonSectionTitle {
                id: header
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.bottomMargin: body.visible && body.implicitHeight > 0 ? (tokens ? tokens.spaceSm : 12) : 0
                visible: root.headerShown
                tokens: root.tokens
                text: root.resolvedTitle
                subtitle: root.subtitle
                helpTip: root.helpTip
                icon: root.icon
                highlighted: root.accentActive
                status: root.status
                statusKind: root.statusKind
                summary: root.summary
                showChevron: root.collapsible
                expanded: root.expanded
                onHeaderTapped: root.toggleExpanded()
            }

            ColumnLayout {
                id: body
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                // A header-only card (title, chip, one line) adds no empty
                // body gap under its line.
                visible: root.bodyOpacity > 0.01 && body.children.length > 0
                opacity: root.bodyOpacity
                spacing: root.bodySpacing

                Behavior on opacity {
                    NumberAnimation { duration: root.tokens ? root.tokens.animFold : 200; easing.type: Easing.OutCubic }
                }
            }
        }
    }
}
