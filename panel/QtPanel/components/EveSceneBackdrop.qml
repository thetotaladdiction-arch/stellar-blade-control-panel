import QtQuick

// The one backdrop (FINAL-VISUAL-SPEC.md 7.4, the ambient backdrop), the
// same on every page, the Dashboard included: the blurred art, a static 8 px
// dot grid and a dark vertical gradient.
//
// 2.5.504 build 4:
// no page shows the sharp Eve art any more. The Dashboard is laid out like
// Gameplay, Settings and Support, and the 3840x2160 frame and both Dashboard
// videos left the bundle (the videos ran at 30 frames/s, under the 60
// frames/s minimum for anything that moves, and their decoder cost 7-8 % CPU
// and 550-700 MB). Nothing here moves, so nothing redraws at rest (8.2).
//
// The blurred copy (glassTexture) is also the texture every glass surface
// samples (9.1), so it keeps the authored art's placement: the glass under
// a card shows the same colours it always did.
Item {
    id: root
    property var tokens: null
    property string page: "gameplay"
    anchors.fill: parent
    clip: true

    // Every page shares the one backdrop, so a page shows at once.
    readonly property string displayedPage: page

    // The blurred art every glass surface samples, and where it lies in the
    // window (the art's rectangle).
    readonly property Image glassTexture: blurArt
    readonly property rect artRect: Qt.rect(artX, artY, artWidth, artHeight)

    // The authored art's 16:9 placement (960x540 source units): it fills
    // the window, its focal point (x=520) stays near the window's centre,
    // and its top edge (y=25) sits under the top bar.
    readonly property real sourceWidth: 960.0
    readonly property real sourceHeight: 540.0
    readonly property real sourceTop: 25.0
    readonly property real sourceAspect: sourceWidth / sourceHeight
    readonly property real focalX: 520.0 / sourceWidth
    readonly property real viewportAspect: height > 0 ? width / height : sourceAspect
    readonly property real topSafe: Math.min(72.0, height * 0.12)
    readonly property real artScale: Math.max(width / sourceWidth,
                                              Math.max(1.0, height - topSafe) / (sourceHeight - sourceTop))
    readonly property real artWidth: sourceWidth * artScale
    readonly property real artHeight: sourceHeight * artScale
    readonly property real artX: viewportAspect >= sourceAspect
                                 ? width - artWidth
                                 : Math.max(width - artWidth, Math.min(0.0, width * 0.5 - artWidth * focalX))
    readonly property real artY: topSafe - sourceTop * artScale

    Rectangle {
        anchors.fill: parent
        color: "#071019"
    }

    // The blurred art (tools/make_glass_blur.py: 320x180, Gaussian radius 5)
    // stretched over the art's rectangle with linear filtering.
    Image {
        id: blurArt
        objectName: "glassBlurArt"
        x: root.artX
        y: root.artY
        width: root.artWidth
        height: root.artHeight
        source: "../DesignSystem/brand/art-dashboard.blur.jpg"
        fillMode: Image.Stretch
        smooth: true
        mipmap: false
        cache: true
    }

    // The rows above the art (none once it reaches the window top) are the
    // background colour, fading into the art over 24 px.
    readonly property real headerMaskHeight: Math.max(0, Math.ceil(artY))
    Rectangle {
        x: 0
        y: 0
        width: root.width
        height: root.headerMaskHeight
        color: "#071019"
        visible: height > 0
    }
    Rectangle {
        x: 0
        y: root.headerMaskHeight
        width: root.width
        height: 24
        visible: root.headerMaskHeight > 0
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#071019" }
            GradientStop { position: 1.0; color: "#00071019" }
        }
    }

    // Ambient veil (spec 7.4): a static 8 px dot grid (white 3.5 %) and a
    // vertical rgba(4,7,11, 0.45 -> 0.70) gradient over the blurred art.
    Image {
        objectName: "ambientDots"
        anchors.fill: parent
        source: "../DesignSystem/brand/dots-8.png"
        fillMode: Image.Tile
        smooth: false
    }
    Rectangle {
        objectName: "ambientVeil"
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0.016, 0.027, 0.043, 0.45) }
            GradientStop { position: 1.0; color: Qt.rgba(0.016, 0.027, 0.043, 0.70) }
        }
    }
}
