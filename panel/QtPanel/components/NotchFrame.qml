import QtQuick
import QtQuick.Shapes

// The one frame shape (FINAL-VISUAL-SPEC.md 2.4): a box with a 45-degree cut
// at its top-right corner instead of rounded corners. One CurveRenderer Shape
// draws the fill, the 1 px outline (inset by half its width so it covers
// whole device pixels) and, when `ring` is set, the 2 px keyboard-focus ring
// 2 px outside the box, following the notch. Nothing here clips, animates on
// its own or uses a layer.
//
// Place it on whole device pixels (tokens.snap) so the outline stays sharp.
Shape {
    id: root
    property var tokens: null
    // Size of the cut; 0 draws a plain box.
    property real notch: tokens ? tokens.notchControl : 8
    property color fillColor: "transparent"
    property color strokeColor: "transparent"
    property real strokeWidth: tokens ? tokens.hairlineW : 1
    // Keyboard focus ring: `ringWidth` wide, `ringGap` outside the box.
    property bool ring: false
    property color ringColor: tokens ? tokens.accent : "#56e0d3"
    property real ringWidth: 2
    property real ringGap: 2
    // The cut actually drawn: never more than half the box.
    readonly property real cut: Math.max(0, Math.min(notch, width / 2, height / 2))

    preferredRendererType: Shape.CurveRenderer

    // Corner points of the notched box inset by `i` (negative = outside).
    // The diagonal moves inward by i * sqrt(2), so the cut keeps 45 degrees.
    function nx(i) { return root.width - i - Math.max(0, root.cut - i * 0.41421356) }
    function ny(i) { return i + Math.max(0, root.cut - i * 0.41421356) }

    ShapePath {
        id: fillPath
        strokeWidth: -1
        strokeColor: "transparent"
        fillColor: root.fillColor
        startX: 0; startY: 0
        PathLine { x: root.nx(0); y: 0 }
        PathLine { x: root.width; y: root.ny(0) }
        PathLine { x: root.width; y: root.height }
        PathLine { x: 0; y: root.height }
        PathLine { x: 0; y: 0 }
    }

    ShapePath {
        id: strokePath
        readonly property real i: root.strokeWidth / 2
        strokeWidth: root.strokeColor.a > 0 ? root.strokeWidth : -1
        strokeColor: root.strokeColor
        fillColor: "transparent"
        joinStyle: ShapePath.MiterJoin
        capStyle: ShapePath.SquareCap
        startX: strokePath.i; startY: strokePath.i
        PathLine { x: root.nx(strokePath.i); y: strokePath.i }
        PathLine { x: root.width - strokePath.i; y: root.ny(strokePath.i) }
        PathLine { x: root.width - strokePath.i; y: root.height - strokePath.i }
        PathLine { x: strokePath.i; y: root.height - strokePath.i }
        PathLine { x: strokePath.i; y: strokePath.i }
    }

    ShapePath {
        id: ringPath
        readonly property real i: -(root.ringGap + root.ringWidth / 2)
        strokeWidth: root.ring ? root.ringWidth : -1
        strokeColor: root.ring ? root.ringColor : "transparent"
        fillColor: "transparent"
        joinStyle: ShapePath.MiterJoin
        capStyle: ShapePath.SquareCap
        startX: ringPath.i; startY: ringPath.i
        PathLine { x: root.nx(ringPath.i); y: ringPath.i }
        PathLine { x: root.width - ringPath.i; y: root.ny(ringPath.i) }
        PathLine { x: root.width - ringPath.i; y: root.height - ringPath.i }
        PathLine { x: ringPath.i; y: root.height - ringPath.i }
        PathLine { x: ringPath.i; y: ringPath.i }
    }
}
