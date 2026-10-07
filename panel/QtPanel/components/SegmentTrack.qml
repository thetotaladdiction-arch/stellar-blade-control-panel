import QtQuick
import QtQuick.Shapes

// A row of 6 px cells with 2 px gaps (the game's HP bar), in one colour.
// One Shape whose fill is a repeating linear gradient, so a 688 px track is
// four vertices instead of 86 rectangles, and the colour is a plain binding.
// Cells start at x = 0, or, with `alignRight`, the last cell ends exactly at
// `width` (SbSlider draws the empty track that way, so every track ends on
// the right edge its value and the switches share).
Shape {
    id: root
    property color color: "white"
    // Cell pitch and lit part of it.
    property real pitch: 8
    property real cell: 6
    property bool alignRight: false

    readonly property real edge: root.cell / root.pitch
    readonly property real phase: root.alignRight
                                  ? ((root.width - root.cell) % root.pitch + root.pitch) % root.pitch : 0
    preferredRendererType: Shape.CurveRenderer

    ShapePath {
        strokeWidth: -1
        strokeColor: "transparent"
        fillGradient: LinearGradient {
            x1: root.phase; y1: 0
            x2: root.phase + root.pitch; y2: 0
            spread: ShapeGradient.RepeatSpread
            GradientStop { position: 0.0; color: root.color }
            GradientStop { position: root.edge - 0.001; color: root.color }
            GradientStop { position: root.edge + 0.001; color: "transparent" }
            GradientStop { position: 1.0; color: "transparent" }
        }
        startX: 0; startY: 0
        PathLine { x: root.width; y: 0 }
        PathLine { x: root.width; y: root.height }
        PathLine { x: 0; y: root.height }
        PathLine { x: 0; y: 0 }
    }
}
