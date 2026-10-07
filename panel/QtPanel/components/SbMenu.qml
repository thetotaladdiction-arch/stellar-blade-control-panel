pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import "." as Ui

// The one menu (FINAL-VISUAL-SPEC.md 3.2, 5.6): 216 px wide, raised
// surface, 1 px control line, 8 px notch, 4 px vertical padding, a static
// drop shadow, 40 px SbMenuItem rows and SbMenuSeparator hairlines.
// openUnder(button) places it 4 px below its button with the right edges
// aligned, and flips it above when there are fewer than 8 px left below.
// Opens over 140 ms (opacity, y -4 -> 0) and closes over 100 ms.
// Keyboard: arrows, Enter, Esc (Menu's own navigation).
Menu {
    id: root
    property var tokens: null

    width: root.tokens ? root.tokens.menuWidth : 216
    // Material insets popups by its elevation shadow (-32 px); the frame
    // here is drawn exactly at the popup's edges.
    topInset: 0
    bottomInset: 0
    leftInset: 0
    rightInset: 0
    topPadding: 4
    bottomPadding: 4
    leftPadding: 0
    rightPadding: 0
    margins: 8
    modal: false
    dim: false
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

    // Right edges aligned, 4 px below; above when it would not fit.
    function openUnder(item, alignLeft) {
        var h = root.implicitHeight
        var win = item.Window.window
        var below = item.mapToItem(null, 0, item.height).y + 4 + h
        var y = (!win || below <= win.height - 8) ? item.height + 4 : -h - 4
        var x = alignLeft ? 0 : item.width - root.width
        root.popup(item, x, y)
    }

    delegate: Ui.SbMenuItem { tokens: root.tokens }

    background: Item {
        implicitWidth: root.tokens ? root.tokens.menuWidth : 216
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
                property: "y"
                from: root.y - (root.tokens ? root.tokens.popupRise : 4)
                to: root.y
                duration: root.tokens ? root.tokens.animMenuOpen : 140
                easing.type: Easing.OutCubic
            }
        }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1.0; to: 0.0; duration: root.tokens ? root.tokens.animMenuClose : 100; easing.type: Easing.InCubic }
    }
}
