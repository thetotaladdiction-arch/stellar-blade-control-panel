pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import "." as Ui

// The select field (FINAL-VISUAL-SPEC.md 5.8, 5.6): 40 px (32 only in the
// top bar), 240 px wide by default, the shared FieldFrame, 15 px text and a
// 16 px chevron in textSecondary. Its popup is the shared menu surface:
// raised, 1 px control line, 8 px notch, 4 px vertical padding, 40 px rows,
// an accent 10 % highlight with a 2 px inset bar, and a 16 px accent check
// on the chosen row. It opens under the field, left-aligned, and flips up
// when there is no room below. Keyboard: arrows, Home / End, Enter and
// type-ahead (ComboBox's own key search).
ComboBox {
    id: root
    property var tokens: null
    property bool compact: false
    // The window this field sits in (the popup flips up near its bottom).
    readonly property var hostWindow: Window.window

    hoverEnabled: true
    HoverHandler {
        cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
    }

    implicitHeight: root.compact ? (root.tokens ? root.tokens.btnHeightCompact : 32) : (root.tokens ? root.tokens.fieldHeight : 40)
    implicitWidth: root.tokens ? root.tokens.fieldWidth : 240
    font.pixelSize: root.tokens ? root.tokens.fontBody : 15
    font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
    leftPadding: 12
    rightPadding: 36
    topInset: 0
    bottomInset: 0

    background: Ui.FieldFrame {
        tokens: root.tokens
        enabled: root.enabled
        hovered: root.hovered
        focused: root.visualFocus || root.popup.visible
    }

    indicator: Ui.ChevronIndicator {
        width: 24
        height: 24
        x: root.width - width - 8
        y: Math.round((root.height - height) / 2)
        tokens: root.tokens
        highlighted: root.enabled && root.hovered
        pressed: root.down
        expanded: root.popup.visible
    }

    contentItem: Text {
        text: root.displayText
        textFormat: Text.PlainText
        font: root.font
        color: !root.enabled ? (root.tokens ? root.tokens.textDisabled : "#56626b")
               : (root.tokens ? root.tokens.textPrimary : "#edf3f5")
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    delegate: ItemDelegate {
        id: option
        required property var modelData
        required property int index
        width: ListView.view ? ListView.view.width : root.width
        height: root.tokens ? root.tokens.menuItemHeight : 40
        text: root.textRole.length > 0 && modelData !== null && typeof modelData === "object"
              ? String(modelData[root.textRole]) : String(modelData)
        highlighted: root.highlightedIndex === index
        hoverEnabled: true
        padding: 0
        leftPadding: 12
        rightPadding: 12

        contentItem: Item {
            Text {
                anchors.left: parent.left
                anchors.right: check.left
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                text: option.text
                textFormat: Text.PlainText
                color: root.tokens ? root.tokens.textPrimary : "#edf3f5"
                font.pixelSize: root.tokens ? root.tokens.fontBody : 15
                elide: Text.ElideRight
            }
            Ui.SbIcon {
                id: check
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                visible: root.currentIndex === option.index
                tokens: root.tokens
                name: "check"
                size: 16
                color: root.tokens ? root.tokens.accent : "#56e0d3"
            }
        }

        background: Item {
            Rectangle {
                anchors.fill: parent
                color: option.highlighted || option.hovered
                       ? (root.tokens ? Qt.rgba(root.tokens.accent.r, root.tokens.accent.g, root.tokens.accent.b, 0.10)
                                      : Qt.rgba(0.337, 0.878, 0.827, 0.10))
                       : "transparent"
            }
            Rectangle {
                visible: option.highlighted || option.hovered
                width: 2
                height: parent.height
                color: root.tokens ? root.tokens.accent : "#56e0d3"
            }
        }

        HoverHandler { cursorShape: Qt.PointingHandCursor }
    }

    popup: Popup {
        id: listPopup
        readonly property int rowH: root.tokens ? root.tokens.menuItemHeight : 40
        readonly property real fullHeight: Math.min(contentItem.implicitHeight + 8, 8 * rowH + 8)
        readonly property bool roomBelow: {
            if (!root.hostWindow)
                return true
            var bottom = root.mapToItem(null, 0, root.height).y + 4 + fullHeight
            return bottom <= root.hostWindow.height - 8
        }
        // Animated by the enter transition (-4 -> 0) so y keeps its binding.
        property real rise: 0
        y: (roomBelow ? root.height + 4 : -fullHeight - 4) + rise
        x: 0
        width: Math.max(root.width, 160)
        // Material insets popups by its elevation shadow (-32 px); the frame
        // here is drawn exactly at the popup's edges.
        topInset: 0
        bottomInset: 0
        leftInset: 0
        rightInset: 0
        implicitHeight: fullHeight
        topPadding: 4
        bottomPadding: 4
        leftPadding: 0
        rightPadding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            boundsBehavior: Flickable.StopAtBounds
            ScrollIndicator.vertical: ScrollIndicator { }
        }

        background: Item {
            RectangularShadow {
                anchors.fill: parent
                offset.y: 16
                blur: 32
                color: root.tokens ? root.tokens.shadow : Qt.rgba(0, 0, 0, 0.55)
            }
            Ui.NotchFrame {
                anchors.fill: parent
                tokens: root.tokens
                notch: root.tokens ? root.tokens.notchControl : 8
                fillColor: root.tokens ? root.tokens.surfaceRaised : "#0d131a"
                strokeColor: root.tokens ? root.tokens.controlLine : Qt.rgba(0.745, 0.902, 0.941, 0.22)
            }
        }

        enter: Transition {
            ParallelAnimation {
                NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: root.tokens ? root.tokens.animMenuOpen : 140; easing.type: Easing.OutCubic }
                NumberAnimation {
                    property: "rise"
                    from: -(root.tokens ? root.tokens.popupRise : 4)
                    to: 0
                    duration: root.tokens ? root.tokens.animMenuOpen : 140
                    easing.type: Easing.OutCubic
                }
            }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; from: 1.0; to: 0.0; duration: root.tokens ? root.tokens.animMenuClose : 100; easing.type: Easing.InCubic }
        }
    }
}
