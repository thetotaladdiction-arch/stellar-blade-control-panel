import QtQuick
import QtQuick.Controls.Material
import "." as Ui

// The panel's mark (FINAL-VISUAL-SPEC.md 6.3): the alpha-cut logo, with no
// navy box behind it. It ships with the QML (DesignSystem/brand) so it never
// depends on the art folder: 1:1 at 100 % (mark-32), and mark-64 above that,
// so it stays sharp at 150 % and 200 %. BrandMark draws a stand-in if the
// image cannot load. Dark backgrounds only (the cut makes the mark's dark
// inner detail transparent).
Item {
    id: root
    property var appBackend: null
    property var tokens: null
    property color glowColor: Material.accent
    property real size: 32

    readonly property real dpr: root.tokens ? root.tokens.dpr : 1.0

    width: size
    height: size
    implicitWidth: size
    implicitHeight: size

    Image {
        id: markImg
        anchors.fill: parent
        source: root.size * root.dpr <= 32.5 ? "../DesignSystem/brand/mark-32.png"
                                             : root.size * root.dpr <= 64.5 ? "../DesignSystem/brand/mark-64.png"
                                             : "../DesignSystem/brand/mark-128.png"
        fillMode: Image.PreserveAspectFit
        asynchronous: false
        smooth: true
        mipmap: false
        visible: status === Image.Ready
    }

    Ui.BrandMark {
        anchors.centerIn: parent
        glowColor: root.glowColor
        size: root.size
        visible: markImg.status === Image.Error
    }
}
