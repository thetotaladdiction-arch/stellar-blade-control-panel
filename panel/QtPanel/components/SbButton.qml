import QtQuick
import QtQuick.Controls
import "." as Ui

// The one button (FINAL-VISUAL-SPEC.md 5.5): 40 px (32 compact, only in the
// top bar and Dashboard rows), 16 px padding (12 compact), 15 px Bahnschrift
// SemiBold, an 8 px notch (6 compact) drawn with its outline by one Shape.
//
//   secondary      white 4.5 % fill, control-line outline, primary text
//   primary        accent fill, accent-ink text (at most one per card)
//   danger         red 6 % fill, red 50 % outline, red ink (Clear)
//   dangerPrimary  solid red (dialogs only)
//
// Set `variant`, or the older flags: success / active = primary, danger.
// Hover 120 ms, press 90 ms, colour only (no scale, which blurs text). The
// keyboard focus ring is a separate 2 px outline 2 px outside that follows
// the notch; a mouse click never leaves a ring. Disabled buttons dim through
// their colours, never through opacity (the software renderer draws
// translucent text without ClearType).
//
// An icon-only button (iconName set, no text) is a 32 x 32 square with a
// 16 px icon. `trailingIcon` adds a chevron after the words ("Game").
Button {
    id: root
    property var tokens: null
    // "secondary" | "primary" | "danger" | "dangerPrimary"; empty = from flags.
    property string variant: ""
    property bool danger: false
    property bool success: false
    property bool active: false
    property bool compact: false
    // Line icon (DesignSystem/Icons.js) before the words.
    property string iconName: ""
    // Line icon after the words (a menu chevron).
    property string trailingIcon: ""
    // The button's menu is open: accent 10 % fill, accent 50 % outline, and
    // a trailing chevron turned 180 degrees.
    property bool menuOpen: false
    // Notch override (split buttons draw the notch on their tail only).
    property real notchSize: -1

    readonly property string kind: root.variant.length > 0 ? root.variant
                                   : root.danger ? "danger"
                                   : (root.success || root.active) ? "primary"
                                   : "secondary"
    readonly property bool primary: root.kind === "primary"
    readonly property bool iconOnly: root.iconName.length > 0 && root.text.length === 0
    readonly property color accentTone: tokens ? tokens.accent : "#56e0d3"
    readonly property color dangerTone: tokens ? tokens.statusError : "#ff7a72"

    hoverEnabled: true
    flat: true
    focusPolicy: Qt.StrongFocus
    font.pixelSize: tokens ? tokens.fontBody : 15
    font.family: tokens ? tokens.typeDisplaySemibold : "Bahnschrift SemiBold"
    font.weight: Font.DemiBold
    font.letterSpacing: 0.3
    font.hintingPreference: tokens ? tokens.textHinting : Font.PreferFullHinting
    padding: 0
    horizontalPadding: root.iconOnly ? 0 : (root.compact ? 12 : 16)
    spacing: 8

    HoverHandler { cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }

    // Material insets the background 6 px top and bottom, so a "40 px"
    // button drew a 28 px box beside 40 px fields. The button is exactly as
    // tall as it says.
    topInset: 0
    bottomInset: 0
    leftInset: 0
    rightInset: 0
    implicitHeight: root.compact || root.iconOnly ? (tokens ? tokens.btnHeightCompact : 32)
                                                  : (tokens ? tokens.btnHeight : 40)
    implicitWidth: root.iconOnly ? implicitHeight
                                 : Math.max(root.compact ? 64 : 96, contentItem.implicitWidth + horizontalPadding * 2)

    // Disabled ink is mixed toward the fill instead of made translucent.
    readonly property real dim: root.enabled ? 1.0 : 0.45
    readonly property color dimBase: tokens ? tokens.surfaceRaised : "#0d131a"
    function dimmed(value) {
        var c = Qt.tint(value, "transparent")   // string or color -> color
        if (root.enabled)
            return c
        return Qt.rgba(c.r * root.dim + root.dimBase.r * (1 - root.dim),
                       c.g * root.dim + root.dimBase.g * (1 - root.dim),
                       c.b * root.dim + root.dimBase.b * (1 - root.dim), 1.0)
    }

    readonly property color inkColor: {
        if (!root.tokens)
            return "#edf3f5"
        if (root.kind === "primary")
            return root.enabled ? root.tokens.accentInk : root.dimmed(root.tokens.accent)
        if (root.kind === "dangerPrimary")
            return root.enabled ? root.tokens.dangerInk : root.dimmed(root.tokens.statusError)
        if (root.kind === "danger")
            return root.dimmed(root.tokens.statusErrorInk)
        if (!root.enabled)
            return root.tokens.textDisabled
        return root.iconOnly ? (root.hovered ? root.tokens.textPrimary : root.tokens.textSecondary)
                             : root.tokens.textPrimary
    }

    readonly property color fillColor: {
        var t = root.tokens
        if (!t)
            return Qt.rgba(1, 1, 1, 0.045)
        if (root.kind === "primary") {
            if (!root.enabled) return Qt.rgba(t.accent.r, t.accent.g, t.accent.b, 0.22)
            return root.down ? t.accentPressed : root.hovered ? t.accentHover : t.accent
        }
        if (root.kind === "dangerPrimary") {
            if (!root.enabled) return Qt.rgba(t.statusError.r, t.statusError.g, t.statusError.b, 0.22)
            return root.down ? Qt.darker(t.statusError, 1.12) : root.hovered ? Qt.lighter(t.statusError, 1.08)
                                                                              : t.statusError
        }
        if (root.kind === "danger") {
            var a = !root.enabled ? 0.03 : root.down ? 0.16 : root.hovered ? 0.11 : 0.06
            return Qt.rgba(t.statusError.r, t.statusError.g, t.statusError.b, a)
        }
        if (root.menuOpen)
            return Qt.rgba(t.accent.r, t.accent.g, t.accent.b, 0.10)
        if (!root.enabled)
            return Qt.rgba(1, 1, 1, 0.02)
        return Qt.rgba(1, 1, 1, root.down ? 0.12 : root.hovered ? 0.085 : 0.045)
    }

    readonly property color outlineColor: {
        var t = root.tokens
        if (!t)
            return Qt.rgba(0.745, 0.902, 0.941, 0.22)
        if (root.kind === "primary")
            return !root.enabled ? "transparent" : root.fillColor
        if (root.kind === "dangerPrimary")
            return !root.enabled ? "transparent" : root.fillColor
        if (root.kind === "danger")
            return Qt.rgba(t.statusError.r, t.statusError.g, t.statusError.b,
                           !root.enabled ? 0.18 : root.hovered ? 0.70 : 0.50)
        if (root.menuOpen)
            return Qt.rgba(t.accent.r, t.accent.g, t.accent.b, 0.50)
        if (!root.enabled)
            return Qt.rgba(0.745, 0.902, 0.941, 0.10)
        return root.hovered || root.down ? t.controlLineHover : t.controlLine
    }

    contentItem: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight

        Row {
            id: row
            anchors.centerIn: parent
            spacing: root.spacing

            Ui.SbIcon {
                visible: root.iconName.length > 0
                anchors.verticalCenter: parent.verticalCenter
                tokens: root.tokens
                name: root.iconName
                size: root.tokens ? root.tokens.iconSmall : 16
                color: root.inkColor
            }

            Text {
                id: label
                visible: root.text.length > 0
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth,
                                Math.max(0, root.availableWidth
                                            - (root.iconName.length > 0 ? 16 + root.spacing : 0)
                                            - (root.trailingIcon.length > 0 ? 16 + root.spacing : 0)))
                text: root.text
                font: root.font
                renderType: Text.NativeRendering
                color: root.inkColor
                elide: Text.ElideRight
                wrapMode: Text.NoWrap
                Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animHover : 120; easing.type: Easing.OutCubic } }
            }

            Ui.SbIcon {
                visible: root.trailingIcon.length > 0
                anchors.verticalCenter: parent.verticalCenter
                tokens: root.tokens
                name: root.trailingIcon
                size: root.tokens ? root.tokens.iconSmall : 16
                color: root.inkColor
                rotation: root.menuOpen ? 180 : 0
                Behavior on rotation {
                    NumberAnimation { duration: root.tokens ? root.tokens.animMenuOpen : 140; easing.type: Easing.OutCubic }
                }
            }
        }
    }

    background: Ui.NotchFrame {
        tokens: root.tokens
        notch: root.notchSize >= 0 ? root.notchSize
               : root.compact || root.iconOnly ? (root.tokens ? root.tokens.notchSmall : 6)
               : (root.tokens ? root.tokens.notchControl : 8)
        fillColor: root.fillColor
        strokeColor: root.outlineColor
        // Keyboard focus only (Tab): 2 px, 2 px outside, following the notch.
        ring: root.visualFocus
        ringColor: root.accentTone

        Behavior on fillColor { ColorAnimation { duration: root.down ? 90 : (root.tokens ? root.tokens.animHover : 120); easing.type: Easing.OutCubic } }
        Behavior on strokeColor { ColorAnimation { duration: root.tokens ? root.tokens.animHover : 120; easing.type: Easing.OutCubic } }
    }
}
