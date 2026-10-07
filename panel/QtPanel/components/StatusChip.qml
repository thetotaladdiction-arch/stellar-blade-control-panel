import QtQuick
import "../DesignSystem/Status.js" as Status

// The one status chip (FINAL-VISUAL-SPEC.md 5.3). Every status in the panel
// (card headers, Dashboard rows, the top bar) is drawn by this component, so
// the same state always has the same colour and shape:
//   ok     filled green diamond, green 13 % fill        Active, Saved, Running
//   ready  hollow bright diamond, bright 40 % outline   Ready (available)
//   off    hollow grey diamond, white 4.5 % fill        Off, Game closed
//   warn   filled amber diamond, amber 13 % fill        Waiting, Safety check
//   error  filled red diamond, red 13 % fill            Needs update
// A chip whose kind is "ok" and whose words are "Ready" is drawn as `ready`,
// so Ready and Active never look alike. Busy states never spin or pulse.
//
// Crisp text: every coordinate inside the chip lands on a whole device pixel
// (tokens.snap), the diamond and the chip height are even so they centre
// exactly, and the label uses the real Semibold face.
Rectangle {
    id: root
    property var tokens: null
    property string text: ""
    property string kind: "off"
    property bool showDot: true
    // Room the chip may use, when its owner knows it (a Dashboard row sets
    // it); -1 = as wide as its words. Squeezed narrower than its words, the
    // chip drops its diamond before it shortens a word: the colour still
    // says it.
    property real availableWidth: -1
    // The top bar under 640 px: the diamond alone in a 24 x 24 box, with the
    // words in the owner's tooltip.
    property bool markOnly: false

    readonly property string variant: root.kind === "ok" && root.text === "Ready" ? "ready"
                                      : (root.kind === "ok" || root.kind === "ready" || root.kind === "warn"
                                         || root.kind === "error" || root.kind === "info") ? root.kind
                                      : "off"
    readonly property color tone: root.variant === "ready"
                                  ? (root.tokens ? root.tokens.statusReady : "#e4edf1")
                                  : Status.toneColor(root.kind, root.tokens)
    readonly property color ink: !root.tokens ? root.tone
                                 : root.variant === "ok" ? root.tokens.statusOkInk
                                 : root.variant === "warn" ? root.tokens.statusWarnInk
                                 : root.variant === "error" ? root.tokens.statusErrorInk
                                 : root.tone
    readonly property bool hollow: root.variant === "ready" || root.variant === "off"

    readonly property int padL: 8
    readonly property int padR: 9
    // Even so (chipHeight - dotSize) / 2 is a whole pixel at 100 % and 150 %.
    readonly property int dotSize: 6
    readonly property int dotGap: 8
    // +1: a hinted label can draw a pixel wider than its measured advance.
    readonly property int fullWidth: Math.ceil(metrics.advanceWidth) + padL + padR + (root.showDot ? dotSize + dotGap : 0) + 1
    readonly property bool dotShown: root.showDot && (root.markOnly || root.availableWidth < 0
                                                      || root.availableWidth >= root.fullWidth)
    readonly property int dotSpace: root.dotShown ? dotSize + dotGap : 0
    readonly property int labelInset: root.dotSpace

    function snap(v) { return root.tokens ? root.tokens.snap(v) : Math.round(v) }

    implicitHeight: tokens ? tokens.chipHeight : 24
    implicitWidth: root.markOnly ? implicitHeight
                                 : Math.ceil(metrics.advanceWidth) + padL + padR + dotSpace + 1
    radius: tokens ? tokens.radiusSmall : 2
    color: root.variant === "ready" ? Qt.rgba(1, 1, 1, 0.07)
           : root.variant === "off" ? Qt.rgba(1, 1, 1, 0.045)
           : Qt.rgba(root.tone.r, root.tone.g, root.tone.b, 0.13)
    border.width: root.variant === "ready" ? (tokens ? tokens.hairlineW : 1) : 0
    border.color: Qt.rgba(root.tone.r, root.tone.g, root.tone.b, 0.40)
    visible: root.text.length > 0
    Accessible.role: Accessible.StaticText
    Accessible.name: root.text

    // A state change fades its colours (Waiting -> Active) over 180 ms; the
    // width is not animated so the label never reflows mid-fade.
    Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animChip : 180; easing.type: Easing.InOutQuad } }

    TextMetrics {
        id: metrics
        text: root.text
        font: label.font
    }

    // Centre the capital height (not the line box, whose ascent and descent
    // differ) on the chip's centre line.
    FontMetrics {
        id: capMetrics
        font: label.font
    }
    readonly property real capHeight: capMetrics.tightBoundingRect("H").height
    readonly property real baselineY: root.tokens ? root.tokens.baselineIn(root.height, root.capHeight)
                                                  : Math.floor((root.height + root.capHeight) / 2)

    // The diamond: a 6 px square turned 45 degrees. Filled for ok / warn /
    // error; an outline for ready (1.5 px) and off (1 px).
    Rectangle {
        visible: root.dotShown
        x: root.snap(root.markOnly ? (root.width - width) / 2 : root.padL)
        y: root.snap((root.height - height) / 2)
        width: root.dotSize
        height: root.dotSize
        rotation: 45
        antialiasing: true
        color: root.hollow ? "transparent" : root.tone
        border.width: root.hollow ? (root.variant === "ready" ? 1.5 : 1) : 0
        border.color: root.tone
        Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animChip : 180; easing.type: Easing.InOutQuad } }
    }

    Text {
        id: label
        visible: !root.markOnly
        x: root.padL + root.labelInset
        y: root.snap(root.baselineY - baselineOffset)
        width: Math.max(0, root.width - x - root.padR)
        height: implicitHeight
        text: root.text
        textFormat: Text.PlainText
        renderType: Text.NativeRendering
        color: root.ink
        Behavior on color { ColorAnimation { duration: root.tokens ? root.tokens.animChip : 180; easing.type: Easing.InOutQuad } }
        font.family: root.tokens ? root.tokens.typeSmallSemibold : "Segoe UI Variable Small Semibold"
        font.pixelSize: root.tokens ? root.tokens.fontLabel : 13
        font.weight: Font.DemiBold
        font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
        elide: Text.ElideRight
        maximumLineCount: 1
    }
}
