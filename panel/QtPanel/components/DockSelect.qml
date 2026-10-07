import QtQuick
import "." as Ui

// Where the panel sits on screen. Uses the shared field look (SbComboBox).
Ui.SbComboBox {
    id: root
    property var appBackend: null
    signal dockSelected(string mode)

    implicitWidth: tokens ? tokens.controlWidth : 260

    readonly property var dockOptions: [
        { label: "Left side", mode: "left" },
        { label: "Right side", mode: "right" },
        { label: "Center", mode: "center" },
        { label: "Top", mode: "top" },
        { label: "Bottom", mode: "bottom" },
        { label: "Maximized", mode: "max" },
        { label: "Free (move it yourself)", mode: "free" }
    ]

    model: dockOptions.map(function(o) { return o.label })

    Component.onCompleted: syncIndex()

    Connections {
        target: root.appBackend
        function onSettingsChanged() { root.syncIndex() }
    }

    function syncIndex() {
        if (!appBackend) return
        for (var i = 0; i < dockOptions.length; i++) {
            if (dockOptions[i].mode === appBackend.dockMode) {
                currentIndex = i
                return
            }
        }
    }

    onActivated: function(index) {
        if (index >= 0 && index < dockOptions.length)
            dockSelected(dockOptions[index].mode)
    }
}
