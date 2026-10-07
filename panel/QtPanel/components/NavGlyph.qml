import QtQuick
import "." as Ui

// A page's 20 px line icon for the sidebar (FINAL-VISUAL-SPEC.md 6.2):
// textMuted at rest, textSecondary on hover, accent when its page is shown.
Ui.SbIcon {
    id: glyph
    property string page: "gameplay"
    property bool selected: false
    property bool hovered: false

    name: glyph.page
    size: tokens ? tokens.iconSize : 20
    color: glyph.selected ? (tokens ? tokens.accent : "#56e0d3")
           : glyph.hovered ? (tokens ? tokens.textSecondary : "#a9b7c0")
           : (tokens ? tokens.textMuted : "#7b8994")
}
