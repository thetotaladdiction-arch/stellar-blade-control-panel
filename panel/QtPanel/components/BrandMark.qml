import QtQuick
import QtQuick.Controls.Material

Canvas {
    id: canvas
    property color glowColor: Material.accent
    property real size: 36

    width: size
    height: size

    onPaint: {
        var ctx = getContext("2d")
        ctx.clearRect(0, 0, width, height)
        var cx = width / 2
        var cy = height / 2
        var r = width * 0.42

        var glow = ctx.createRadialGradient(cx, cy, r * 0.2, cx, cy, r * 1.1)
        glow.addColorStop(0, Qt.rgba(glowColor.r, glowColor.g, glowColor.b, 0.55))
        glow.addColorStop(1, "rgba(0,0,0,0)")
        ctx.fillStyle = glow
        ctx.beginPath()
        ctx.arc(cx, cy, r * 1.1, 0, Math.PI * 2)
        ctx.fill()

        ctx.strokeStyle = Qt.rgba(0.94, 0.98, 1.0, 0.95)
        ctx.lineWidth = 2.2
        ctx.lineCap = "round"
        ctx.beginPath()
        ctx.arc(cx + r * 0.08, cy, r, Math.PI * 0.62, Math.PI * 1.38)
        ctx.stroke()

        ctx.strokeStyle = glowColor
        ctx.lineWidth = 1.6
        ctx.beginPath()
        ctx.arc(cx - r * 0.05, cy, r * 0.78, Math.PI * 0.72, Math.PI * 1.28)
        ctx.stroke()
    }

    Component.onCompleted: requestPaint()
    onGlowColorChanged: requestPaint()
    onSizeChanged: requestPaint()
}
