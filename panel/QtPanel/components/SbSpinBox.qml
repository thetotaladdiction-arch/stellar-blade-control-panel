pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import "." as Ui

// Material SpinBox whose +/- glyphs sit on whole pixels. The stock
// indicators size the bars as width / 3 (44 / 3 = 14.67 px) and centre them
// arithmetically, so every bar straddled two pixels and the +/- read blurred.
SpinBox {
    id: control
    property var tokens: null

    function snap(value) { return control.tokens ? control.tokens.snap(value) : Math.round(value) }
    // Bar length with the same parity as the indicator, so it centres exactly.
    function glyphLength(size) {
        var length = Math.round(size / 3)
        return (Math.round(size) - length) % 2 === 0 ? length : length + 1
    }

    font.hintingPreference: control.tokens ? control.tokens.textHinting : Font.PreferFullHinting
    hoverEnabled: true
    font.pixelSize: control.tokens ? control.tokens.fontBody : 15
    implicitHeight: control.tokens ? control.tokens.fieldHeight : 40

    // The shared field box (FINAL-VISUAL-SPEC.md 5.8), as SbTextField and
    // SbComboBox: fieldHeight tall, 6 px notch, control line; disabled is
    // surfaceDisabled with a hairline (FieldFrame).
    background: Ui.FieldFrame {
        implicitWidth: 148
        implicitHeight: control.tokens ? control.tokens.fieldHeight : 40
        tokens: control.tokens
        enabled: control.enabled
        hovered: control.hovered
        focused: control.activeFocus
    }

    component Glyph: Item {
        id: glyph
        property bool plus: false
        property bool pressed: false
        property bool hovered: false
        // The indicator's own enabled state: SpinBox turns the "-" off at
        // `from` and the "+" off at `to` (as the stock Material glyphs show).
        readonly property color ink: glyph.enabled ? (control.tokens ? control.tokens.textPrimary : "#edf3f5")
                                                   : (control.tokens ? control.tokens.textDisabled : "#56626b")
        readonly property int length: control.glyphLength(width)

        implicitWidth: control.Material.touchTarget
        implicitHeight: control.Material.touchTarget
        height: control.height
        width: height

        Rectangle {
            x: control.spacing
            y: control.spacing
            width: parent.width - 2 * control.spacing
            height: parent.height - 2 * control.spacing
            radius: control.tokens ? control.tokens.radiusSmall : 2
            color: glyph.pressed ? Qt.rgba(1, 1, 1, 0.12) : glyph.hovered ? Qt.rgba(1, 1, 1, 0.06) : "transparent"
        }

        Rectangle {
            x: control.snap((glyph.width - width) / 2)
            y: control.snap((glyph.height - height) / 2)
            width: glyph.length
            height: 2
            color: glyph.ink
        }
        Rectangle {
            visible: glyph.plus
            x: control.snap((glyph.width - width) / 2)
            y: control.snap((glyph.height - height) / 2)
            width: 2
            height: glyph.length
            color: glyph.ink
        }
    }

    up.indicator: Glyph {
        plus: true
        x: control.mirrored ? 0 : control.width - width
        pressed: control.up.pressed
        hovered: control.up.hovered
    }

    down.indicator: Glyph {
        x: control.mirrored ? control.width - width : 0
        pressed: control.down.pressed
        hovered: control.down.hovered
    }
}
