import QtQuick
import "." as Ui

// A card that starts folded: 56 px (icon, title, summary, chevron) until
// its header is clicked (SbCard does the folding).
Ui.SbCard {
    collapsible: true
}
