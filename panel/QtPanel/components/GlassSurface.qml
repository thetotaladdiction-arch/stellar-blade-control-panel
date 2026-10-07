import QtQuick
import QtQuick.Shapes
import "." as Ui

// The one surface (FINAL-VISUAL-SPEC.md 2.4, 9.1) behind the sidebar, the
// top bar and every card: glass fill, 1 px edge, a 12 px notch at the
// top-right and the 40 px accent tick on the top edge, flush with the left
// corner. The tick is part of the frame, not a state signal.
//
// Glass: the one pre-blurred art texture (tokens.glassTexture), sampled in
// window coordinates so it lines up with the art behind, under glassTint
// (80 %). Sharp art never shows through. No layer, live blur or effect.
// While no texture is loaded the fill is the 94 % solid fallback.
Item {
    id: root
    property var tokens: null
    property real notch: tokens ? tokens.notchSurface : 12
    property color strokeColor: tokens ? tokens.edge : Qt.rgba(0.745, 0.902, 0.941, 0.14)
    property bool showTick: true
    property color tickColor: tokens ? tokens.accent : "#56e0d3"

    readonly property Image blurTexture: tokens ? tokens.glassTexture : null
    readonly property bool blurred: !!blurTexture && blurTexture.status === Image.Ready
                                    && blurTexture.sourceSize.width > 0
    readonly property color fillColor: !tokens ? Qt.rgba(0.039, 0.059, 0.082, 0.94)
                                       : blurred ? tokens.glassTint
                                       : Qt.rgba(tokens.glassSolid.r, tokens.glassSolid.g, tokens.glassSolid.b,
                                                 tokens.glassSolidOpacity)

    // This surface's top-left in the window. mapToItem() does not track the
    // ancestors' positions, so glassEpoch (bumped on scroll, page slides,
    // layout and window changes) and the own size re-run it.
    function windowPosition(epoch, w, h) {
        return root.mapToItem(null, 0, 0)
    }
    readonly property point windowPos: windowPosition(tokens ? tokens.glassEpoch : 0, width, height)

    Shape {
        id: blurFill
        anchors.fill: parent
        visible: root.blurred
        preferredRendererType: Shape.CurveRenderer
        readonly property real cut: Math.max(0, Math.min(root.notch, root.width / 2, root.height / 2))
        readonly property rect art: root.tokens ? root.tokens.glassArtRect : Qt.rect(0, 0, 1, 1)
        readonly property real dpr: root.tokens ? root.tokens.dpr : 1.0

        ShapePath {
            strokeWidth: -1
            strokeColor: "transparent"
            fillItem: root.blurTexture
            // The texture spans sourceSize / dpr logical px at the shape's
            // origin (measured in Qt 6.11.1 at 100 % and 150 %): scale it to
            // the art's rectangle and move it to this surface's window spot.
            fillTransform: PlanarTransform.fromAffineMatrix(
                               blurFill.art.width * blurFill.dpr / Math.max(1, root.blurTexture ? root.blurTexture.sourceSize.width : 1), 0,
                               0, blurFill.art.height * blurFill.dpr / Math.max(1, root.blurTexture ? root.blurTexture.sourceSize.height : 1),
                               blurFill.art.x - root.windowPos.x, blurFill.art.y - root.windowPos.y)
            startX: 0; startY: 0
            PathLine { x: root.width - blurFill.cut; y: 0 }
            PathLine { x: root.width; y: blurFill.cut }
            PathLine { x: root.width; y: root.height }
            PathLine { x: 0; y: root.height }
            PathLine { x: 0; y: 0 }
        }
    }

    Ui.NotchFrame {
        anchors.fill: parent
        tokens: root.tokens
        notch: root.notch
        fillColor: root.fillColor
        strokeColor: root.strokeColor
    }

    Rectangle {
        visible: root.showTick
        x: 0
        y: 0
        width: Math.min(root.tokens ? root.tokens.tickWidth : 40, root.width)
        height: root.tokens ? root.tokens.hairlineW : 1
        color: root.tickColor
    }
}
