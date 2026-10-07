import QtQuick
import QtQuick.Shapes
import "../DesignSystem/Icons.js" as Icons

// One line icon from DesignSystem/Icons.js (FINAL-VISUAL-SPEC.md 6): a 24 px
// grid drawn at `size` logical px (20 in the nav and card headers, 16 in
// buttons, fields, menus and chips). The colour is a plain binding; idle
// icons are textMuted, live or selected ones accent.
Item {
    id: root
    property var tokens: null
    property string name: ""
    property real size: tokens ? tokens.iconSize : 20
    property color color: tokens ? tokens.textMuted : "#7b8994"
    // The set's stroke on its 24 px grid.
    property real stroke: 1.5

    readonly property bool known: Icons.has(root.name)
    readonly property real unit: root.size / 24

    implicitWidth: size
    implicitHeight: size
    width: size
    height: size

    Shape {
        anchors.fill: parent
        visible: root.known
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            scale: Qt.size(root.unit, root.unit)
            strokeColor: root.color
            strokeWidth: root.stroke * root.unit
            fillColor: Icons.isFilled(root.name) ? root.color : "transparent"
            capStyle: ShapePath.SquareCap
            joinStyle: ShapePath.MiterJoin
            PathSvg { path: Icons.path(root.name) }
        }
    }
}
