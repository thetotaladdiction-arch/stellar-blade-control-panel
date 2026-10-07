pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "../DesignSystem/FriendlyCopy.js" as FriendlyCopy
import "../components" as Ui

// Settings (IA-SPEC 2.4, FINAL-VISUAL-SPEC 4.4): three open cards in one
// column, the one you change during play first.
//   1. In-game overlay: the switch, the size and one folded "Choose
//      numbers" row (the main numbers, then MORE NUMBERS). Size and numbers
//      show even while it is off (spec 4.4), so it can be set up first.
//   2. Panel: where it sits, always on top, temperature alerts, update check.
//   3. Appearance: the neon accent. (Motion effects and its pause switch
//      went with the Dashboard video in 2.5.504 build 4: every page is a
//      still image, so there is nothing left for them to start or pause.)
// The shortcuts sentence is gone: the sidebar and refresh tooltips show
// Ctrl+1 to Ctrl+4 and F5. There is no in-game hotkey editor: none of the
// shipped game mods reads hotkeys.ini (RELEASE-GATE B5), so a card for it
// would change nothing.
Ui.PageScroll {
    id: root
    property var appBackend
    property var windowRoot
    property bool stellarAccent: windowRoot ? windowRoot.stellarAccent : true
    pageId: "settings"

    // Two columns of number checkboxes when the card is wide enough.
    readonly property int metricColumns: root.width >= 600 ? 2 : 1
    readonly property bool overlayOn: !!appBackend && root.appBackend.performanceOverlayEnabled
    readonly property bool gameRunning: !!appBackend && root.appBackend.gameRunning
    // The "Choose numbers" fold; closed by default.
    property bool showMoreMetrics: false

    // The everyday numbers (on by default), shown first when the fold opens.
    readonly property var mainMetrics: [
        { key: "fps", label: "FPS" },
        { key: "frameTime", label: "Frame time" },
        { key: "onePercentLow", label: "1% low" },
        { key: "gpuUsage", label: "GPU usage" },
        { key: "gpuTemperature", label: "GPU temperature" },
        { key: "cpuUsage", label: "CPU usage" },
        { key: "cpuTemperature", label: "CPU temperature" },
        { key: "godMode", label: "God Mode", name: true }
    ]
    // Everything else, under MORE NUMBERS: frames first, then hardware.
    readonly property var moreMetrics: [
        { key: "pointOnePercentLow", label: "0.1% low" },
        { key: "frameGraph", label: "Frame-time graph" },
        { key: "stutters", label: "Recent stutters" },
        { key: "pacing", label: "Frame pacing" },
        { key: "minAvgMax", label: "Min / average / max" },
        { key: "gpuFrameTime", label: "GPU render time" },
        { key: "resolution", label: "Resolution" },
        { key: "vram", label: "VRAM used" },
        { key: "ram", label: "RAM used" },
        { key: "gpuPower", label: "GPU power" },
        { key: "gpuClock", label: "GPU clock" },
        { key: "gpuFan", label: "GPU fan" },
        { key: "cpuPower", label: "CPU power" },
        { key: "cpuClock", label: "CPU clock" },
        { key: "connection", label: "Game mod connection" }
    ]

    // What the fold row says while closed: which numbers are on, and how many.
    readonly property var metricState: appBackend && root.appBackend.performanceOverlayMetrics
                                       ? root.appBackend.performanceOverlayMetrics : ({})
    readonly property var metricsOn: mainMetrics.concat(moreMetrics).filter(function(m) {
        return !!root.metricState[m.key]
    })
    readonly property bool metricsAreDefault: mainMetrics.every(function(m) { return !!root.metricState[m.key] })
                                              && !moreMetrics.some(function(m) { return !!root.metricState[m.key] })
    readonly property string metricsSummary: {
        if (root.metricsOn.length === 0)
            return "None picked, so the overlay has nothing to show."
        if (root.metricsAreDefault)
            return "FPS, frame time, 1% low, GPU and CPU use and temperature, God Mode"
        var words = root.metricsOn.map(function(m) {
            // Mid-sentence lower case, except acronyms (FPS, GPU...) and names.
            return m.name || !/^[A-Z][a-z]/.test(m.label) ? m.label
                                                           : m.label.charAt(0).toLowerCase() + m.label.slice(1)
        })
        var sentence = words.join(", ")
        return sentence.charAt(0).toUpperCase() + sentence.slice(1)
    }

    Ui.SbCard {
        objectName: "settingsOverlayCard"
        appBackend: root.appBackend
        tokens: root.tokens
        icon: "overlay"
        title: "In-game overlay"
        subtitle: root.gameRunning ? "Shows in the game’s top-right corner."
                                   : "Shows in the game’s top-right corner once the game runs."
        helpTip: "Frame rate and temperatures in the game's top-right corner. It sits on top of the game "
                 + "without blocking your clicks. It stays up while you Alt-Tab "
                 + "or minimize the panel, hides when the game is minimized or closed, and follows the "
                 + "game's screen and scaling."
        // Ready: switched on, waiting for the game to run.
        status: !root.overlayOn ? "Off" : root.gameRunning ? "Active" : "Ready"
        statusKind: !root.overlayOn ? "off" : root.gameRunning ? "ok" : "ready"
        accentActive: root.overlayOn
        bodySpacing: 0
        Layout.fillWidth: true

        Ui.SettingsField {
            tokens: root.tokens
            label: "Show overlay"
            hasControl: true
            compactControl: true
            Ui.SbSwitch {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                tokens: root.tokens
                checked: root.appBackend.performanceOverlayEnabled
                onToggled: root.appBackend.setPerformanceOverlayEnabled(checked)
            }
        }

        Ui.SettingsField {
            tokens: root.tokens
            label: "Size"
            hasControl: true
            Ui.SbComboBox {
                id: overlaySizeBox
                objectName: "settingsOverlaySize"
                readonly property var sizes: ["compact", "standard", "large"]
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                tokens: root.tokens
                model: ["Compact", "Standard", "Large"]
                currentIndex: Math.max(0, sizes.indexOf(root.appBackend.performanceOverlaySize))
                onActivated: function(index) { root.appBackend.setPerformanceOverlaySize(sizes[index]) }
            }
        }

        // Only when it helps: the game runs with the overlay on, but no frame
        // numbers are coming in.
        Ui.FriendlyNote {
            Layout.fillWidth: true
            Layout.topMargin: root.tokens ? root.tokens.spaceXs : 8
            // 4 px: the fold row under it already has air above its words,
            // and the whole page still fits 1320x880 with the note showing.
            Layout.bottomMargin: root.tokens ? root.tokens.spaceXxs : 4
            visible: root.overlayOn && root.gameRunning && !root.appBackend.gameTelemetry.live
            tokens: root.tokens
            summary: "Waiting for frame readings. RivaTuner Statistics Server (RTSS) can supply them; check Support if they stay unavailable."
            detail: "RTSS can supply frame readings while it runs. If unavailable, the panel tries its frame-counter fallback. MSI Afterburner supplies CPU sensors and "
                    + "additional GPU sensors when available. Missing readings show N/A."
        }

        // Picking numbers is done once, so it waits behind one click.
        Ui.Disclosure {
            objectName: "settingsChooseNumbers"
            tokens: root.tokens
            text: "Choose numbers"
            hint: root.metricsSummary
            count: root.metricsOn.length + " on"
            expanded: root.showMoreMetrics
            onToggled: root.showMoreMetrics = !root.showMoreMetrics

            MetricGrid {
                Layout.topMargin: root.tokens ? root.tokens.spaceXxs : 4
                metrics: root.mainMetrics
            }

            Ui.SbSubhead {
                Layout.fillWidth: true
                Layout.topMargin: root.tokens ? root.tokens.spaceXs : 8
                tokens: root.tokens
                text: "More numbers"
            }

            MetricGrid {
                metrics: root.moreMetrics
            }
        }
    }

    Ui.SbCard {
        objectName: "settingsPanelCard"
        appBackend: root.appBackend
        tokens: root.tokens
        icon: "panel"
        title: "Panel"
        subtitle: "Where the panel sits and how it behaves."
        helpTip: FriendlyCopy.settingsPanelPlacementDetail()
        bodySpacing: 0
        Layout.fillWidth: true

        Ui.SettingsField {
            tokens: root.tokens
            label: "Screen position"
            hasControl: true
            Ui.DockSelect {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                tokens: root.tokens
                appBackend: root.appBackend
                onDockSelected: function(mode) { root.appBackend.dockPanel(mode) }
            }
        }
        Ui.SettingsField {
            tokens: root.tokens
            label: "Always on top"
            hint: "Keep the panel above other windows."
            hasControl: true
            compactControl: true
            Ui.SbSwitch {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                tokens: root.tokens
                checked: root.appBackend.alwaysOnTop
                onToggled: root.appBackend.setAlwaysOnTop(checked)
            }
        }
        // Here, not folded away: after an alert, its off switch is in sight.
        Ui.SettingsField {
            tokens: root.tokens
            label: "Temperature alerts"
            hint: "One quiet notice if the CPU or GPU stays in the red ("
                  + Math.round(root.appBackend.gameTelemetry.cpuTempRedLimit)
                  + " °C on this CPU) while the game runs, at most every 10 minutes."
            hasControl: true
            compactControl: true
            Ui.SbSwitch {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                tokens: root.tokens
                checked: root.appBackend.hardwareAlertsEnabled
                onToggled: root.appBackend.setHardwareAlertsEnabled(checked)
            }
        }
        // Once a day, in the background; a newer version shows one quiet
        // line on the Dashboard and Support. Nothing downloads by itself.
        Ui.SettingsField {
            tokens: root.tokens
            visible: !!root.appBackend && !!root.appBackend.updateCheckAvailable
            label: "Check for updates"
            hint: "Once a day, looks for a newer version. Nothing downloads on its own."
            hasControl: true
            compactControl: true
            showSeparator: false
            Ui.SbSwitch {
                objectName: "settingsUpdateCheck"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                tokens: root.tokens
                checked: root.appBackend.updateCheckEnabled
                onToggled: root.appBackend.setUpdateCheckEnabled(checked)
            }
        }
    }

    Ui.SbCard {
        objectName: "settingsAppearanceCard"
        appBackend: root.appBackend
        tokens: root.tokens
        icon: "appearance"
        title: "Appearance"
        subtitle: "How the panel looks."
        helpTip: "Neon accent picks a bright or a softer teal."
        bodySpacing: 0
        Layout.fillWidth: true

        Ui.SettingsField {
            tokens: root.tokens
            label: "Neon accent"
            // Tokens.accent: every switch, primary button and selection.
            hint: "Bright teal buttons, switches and selection. Off uses a softer teal."
            hasControl: true
            compactControl: true
            showSeparator: false
            Ui.SbSwitch {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                tokens: root.tokens
                checked: root.stellarAccent
                onToggled: root.appBackend.setStellarAccent(checked)
            }
        }
    }

    // Overlay numbers as checkboxes: 32 px rows, two columns 16 px apart when
    // the card is wide enough, filled row by row.
    component MetricGrid: GridLayout {
        id: grid
        property var metrics: []

        Layout.fillWidth: true
        columns: root.metricColumns
        columnSpacing: root.tokens ? root.tokens.spaceMd : 16
        rowSpacing: 0

        Repeater {
            model: grid.metrics
            delegate: Ui.SbCheckBox {
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                tokens: root.tokens
                text: modelData.label
                checked: !!root.metricState[modelData.key]
                onToggled: {
                    root.appBackend.setPerformanceOverlayMetric(modelData.key, checked)
                    // Keep showing what the panel saved, not only the click.
                    checked = Qt.binding(function() { return !!root.metricState[modelData.key] })
                }
            }
        }
    }
}
