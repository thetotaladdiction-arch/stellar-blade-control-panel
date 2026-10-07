import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "../DesignSystem/Status.js" as Status

Window {
    id: root
    property var appBackend: null
    property var tokens: null

    readonly property var telemetry: appBackend ? appBackend.gameTelemetry : null
    readonly property var values: telemetry ? telemetry.values : ({})
    readonly property var selected: appBackend ? appBackend.performanceOverlayMetrics : ({})
    readonly property int edgeMargin: 18
    // Optional reading size from Settings (Compact / Standard / Large). Qt
    // already scales logical pixels by the game monitor's DPI; this is a
    // user preference on top of that, not a DPI correction.
    readonly property string hudSize: appBackend && appBackend.performanceOverlaySize
                                      ? appBackend.performanceOverlaySize : "standard"
    readonly property real hudScale: hudSize === "compact" ? 0.85
                                     : hudSize === "large" ? 1.25 : 1.0
    function px(value) { return Math.round(value * hudScale) }
    // Crisp HUD text on the game's 150 % monitor: full hinting (as the panel)
    // and hairlines that cover whole device pixels (1 logical px would be a
    // soft 1.5 device px line there).
    readonly property int textHinting: tokens ? tokens.textHinting : Font.PreferFullHinting
    readonly property real hudDpr: Screen.devicePixelRatio > 0 ? Screen.devicePixelRatio : 1.0
    readonly property real hairline: Math.max(1, Math.round(hudDpr)) / hudDpr

    // Telemetry reports the game window and its screen in Qt logical pixels
    // (see infrastructure/screen_geometry.py). Clamp to that screen so the HUD
    // can never land on another monitor or above a screen's top edge.
    readonly property bool hasGameScreen: !!telemetry
                                          && telemetry.screenRight > telemetry.screenLeft
                                          && telemetry.screenBottom > telemetry.screenTop
    readonly property int anchorX: telemetry ? telemetry.windowRight - width - edgeMargin : 0
    readonly property int anchorY: telemetry ? telemetry.windowTop + edgeMargin : 0
    readonly property var gameScreen: {
        if (!telemetry || !telemetry.gameScreenName)
            return null
        var screens = Qt.application.screens
        var sameOrigin = null
        for (var i = 0; i < screens.length; ++i) {
            var candidate = screens[i]
            if (candidate.virtualX !== telemetry.screenLeft || candidate.virtualY !== telemetry.screenTop)
                continue
            if (candidate.name === telemetry.gameScreenName)
                return candidate
            if (!sameOrigin)
                sameOrigin = candidate
        }
        return sameOrigin
    }

    // Put the HUD window on the game's screen so it uses that screen's DPI.
    Binding {
        target: root
        property: "screen"
        value: root.gameScreen
        when: !!root.gameScreen
        restoreMode: Binding.RestoreNone
    }

    // Telemetry arrives at 10 Hz and each sample is drawn once, as it
    // arrives: no interpolating animations, so this topmost window over the
    // game redraws ten times a second instead of at the monitor's refresh.
    // Temperatures and usage come pre-smoothed (2 s moving average) and every
    // colour is a latched level from Python (controllers/telemetry_levels.py):
    // it changes only after a value stays past a limit for about 5 s and
    // returns only after it stays 5 inside the limit for about 10 s, so rows
    // never blink while a reading wobbles around a threshold.
    readonly property color okColor: tokens ? tokens.textPrimary : "#f4f7ff"
    readonly property color goodColor: "#6ee7a8"
    readonly property color warnColor: "#ffb347"
    readonly property color critColor: "#ff6b6b"
    readonly property color mutedColor: "#9aa8c0"

    function levelColor(key, normalColor) {
        var level = String(values["level_" + key] || "none")
        return level === "crit" ? critColor
               : level === "warn" ? warnColor
               : level === "ok" ? normalColor : mutedColor
    }

    function smoothValue(key) {
        return hasValue("smooth_" + key) ? numberValue("smooth_" + key) : numberValue(key)
    }

    function numberValue(key) {
        var value = Number(values[key] || 0)
        return isFinite(value) ? value : 0
    }

    function hasValue(key) {
        if (!values || values[key] === undefined || values[key] === null)
            return false
        return isFinite(Number(values[key]))
    }

    function fixedValue(key, digits, suffix) {
        var value = numberValue(key)
        return hasValue(key) ? value.toFixed(digits) + suffix : "N/A"
    }

    function formattedMetric(key, value, digits, suffix) {
        return hasValue(key) ? value.toFixed(digits) + suffix : "N/A"
    }

    function ramMetric() {
        if (!hasValue("ram_mb") || numberValue("ram_mb") < 0)
            return "N/A"
        var used = Math.round(numberValue("ram_mb") / 1024)
        var total = hasValue("ram_total_mb") && numberValue("ram_total_mb") > 0
                    ? String(Math.round(numberValue("ram_total_mb") / 1024)) : "—"
        return used + "/" + total + " GB"
    }

    function smoothMetric(key, digits, suffix) {
        return formattedMetric(key, smoothValue(key), digits, suffix)
    }

    function cpuTemperatureLabel() {
        var label = String(values["cpu_temp_label"] || "CPU temperature")
        return values["cpu_sample_fresh"] === false ? label + " (stale)" : label
    }

    // A distinct title keeps single-instance focus logic from ever matching
    // this click-through HUD instead of the panel window.
    title: "Mod Suite in-game overlay"
    width: px(246)
    height: Math.max(1, shell.implicitHeight)
    x: hasGameScreen
       ? Math.max(telemetry.screenLeft, Math.min(anchorX, telemetry.screenRight - width))
       : anchorX
    y: hasGameScreen
       ? Math.max(telemetry.screenTop, Math.min(anchorY, telemetry.screenBottom - height))
       : anchorY
    color: "transparent"
    // This HUD belongs to the visible game window, not to keyboard focus or to
    // the control-panel window. Explicitly clearing the implicit transient
    // parent keeps Alt-Tab and panel minimization from taking the HUD down.
    transientParent: null
    visible: !!appBackend
             && appBackend.performanceOverlayEnabled
             && appBackend.gameRunning
             && telemetry
             && telemetry.windowRight > telemetry.windowLeft
             && telemetry.windowBottom > telemetry.windowTop
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
           | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus

    component MetricLine: RowLayout {
        property string label: ""
        property string value: ""
        property color valueColor: root.tokens ? root.tokens.textPrimary : "#f4f7ff"
        Layout.fillWidth: true
        spacing: root.px(14)

        Text {
            Layout.fillWidth: true
            text: parent.label
            color: root.tokens ? root.tokens.textSecondary : "#c8d4ea"
            font.family: "Segoe UI"
            font.pixelSize: root.px(13)
            renderType: Text.NativeRendering
            font.hintingPreference: root.textHinting
        }
        Text {
            text: parent.value
            color: parent.valueColor
            font.family: "Segoe UI Semibold"
            font.pixelSize: root.px(13)
            horizontalAlignment: Text.AlignRight
            renderType: Text.NativeRendering
            font.hintingPreference: root.textHinting
        }
    }

    Rectangle {
        id: shell
        anchors.fill: parent
        implicitHeight: content.implicitHeight + root.px(22)
        radius: root.px(12)
        color: Qt.rgba(0.025, 0.055, 0.075, 0.94)
        border.color: Qt.rgba(0.26, 0.94, 0.87, 0.72)
        border.width: root.hairline

        Rectangle {
            anchors.fill: parent
            anchors.margins: root.hairline
            radius: parent.radius - root.hairline
            color: "transparent"
            border.color: Qt.rgba(1, 1, 1, 0.06)
            border.width: root.hairline
        }

        ColumnLayout {
            id: content
            anchors.fill: parent
            anchors.margins: root.px(11)
            spacing: root.px(5)

            RowLayout {
                Layout.fillWidth: true
                spacing: root.px(8)
                Text {
                    Layout.fillWidth: true
                    text: "STELLAR BLADE"
                    color: root.tokens ? root.tokens.textPrimary : "#f4f7ff"
                    font.family: "Segoe UI Semibold"
                    font.pixelSize: root.px(13)
                    font.letterSpacing: 1.0
                    renderType: Text.NativeRendering
                    font.hintingPreference: root.textHinting
                }
                // Same shape and words as the panel's status chips: a pill,
                // sentence case, nothing smaller than 13 px.
                Rectangle {
                    implicitWidth: sourceText.implicitWidth + root.px(16)
                    implicitHeight: root.px(22)
                    radius: height / 2
                    color: root.telemetry && root.telemetry.live
                           ? Qt.rgba(0.26, 0.94, 0.87, 0.15)
                           : Qt.rgba(1.0, 0.60, 0.16, 0.14)
                    border.color: root.telemetry && root.telemetry.live
                                  ? "#42f0df" : "#ff9a29"
                    border.width: 1
                    Text {
                        id: sourceText
                        anchors.centerIn: parent
                        text: root.telemetry && root.telemetry.live ? "Live" : "Waiting"
                        color: parent.border.color
                        font.family: "Segoe UI Semibold"
                        font.pixelSize: root.px(13)
                        renderType: Text.NativeRendering
                        font.hintingPreference: root.textHinting
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: Qt.rgba(0.26, 0.94, 0.87, 0.20)
            }

            MetricLine {
                visible: !!root.selected.fps
                label: "FPS"
                value: root.formattedMetric("fps", root.numberValue("fps"), 0, "")
                valueColor: root.levelColor("fps", root.goodColor)
            }
            MetricLine {
                visible: !!root.selected.frameTime
                label: "Frame time"
                value: root.formattedMetric("frame_time_ms", root.numberValue("frame_time_ms"), 1, " ms")
                valueColor: root.levelColor("fps", root.okColor)
            }
            MetricLine {
                visible: !!root.selected.onePercentLow
                label: "1% low"
                value: root.formattedMetric("one_percent_low", root.numberValue("one_percent_low"), 0, " FPS")
            }
            MetricLine {
                visible: !!root.selected.pointOnePercentLow
                label: "0.1% low"
                value: root.formattedMetric("point_one_percent_low", root.numberValue("point_one_percent_low"), 0, " FPS")
            }
            MetricLine {
                visible: !!root.selected.minAvgMax
                label: "Min / avg / max"
                value: root.fixedValue("min_fps", 0, "") + " / "
                       + root.fixedValue("stat_average_fps", 0, "") + " / "
                       + root.fixedValue("max_fps", 0, "")
            }
            MetricLine {
                visible: !!root.selected.pacing
                label: "Frame pacing"
                value: root.formattedMetric("pacing_deviation_ms", root.numberValue("pacing_deviation_ms"), 2, " ms")
            }
            MetricLine {
                visible: !!root.selected.stutters
                label: "Recent stutters"
                value: String(root.numberValue("stutters").toFixed(0))
            }

            Canvas {
                id: frameGraph
                visible: !!root.selected.frameGraph
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? root.px(42) : 0
                antialiasing: true

                Connections {
                    target: root.telemetry
                    enabled: frameGraph.visible && root.visible
                    function onChanged() { frameGraph.requestPaint() }
                }

                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var samples = root.telemetry ? root.telemetry.frameHistory : []
                    if (!samples || samples.length < 2)
                        return
                    var ceiling = 16.67
                    for (var i = 0; i < samples.length; ++i)
                        ceiling = Math.max(ceiling, Number(samples[i]) || 0)
                    ceiling = Math.min(66.67, ceiling * 1.12)
                    ctx.strokeStyle = "rgba(66,240,223,0.90)"
                    ctx.lineWidth = 1.25
                    ctx.beginPath()
                    for (var j = 0; j < samples.length; ++j) {
                        var px = j * width / Math.max(1, samples.length - 1)
                        var py = height - Math.min(height, (Number(samples[j]) || 0) / ceiling * height)
                        if (j === 0) ctx.moveTo(px, py)
                        else ctx.lineTo(px, py)
                    }
                    ctx.stroke()
                    ctx.strokeStyle = "rgba(255,179,71,0.28)"
                    ctx.lineWidth = 1
                    var lineY = height - Math.min(height, 16.67 / ceiling * height)
                    ctx.beginPath(); ctx.moveTo(0, lineY); ctx.lineTo(width, lineY); ctx.stroke()
                }
            }

            Rectangle {
                visible: hardwareGroup.visible
                Layout.fillWidth: true
                height: 1
                color: Qt.rgba(1, 1, 1, 0.08)
            }

            // Plain numbers only. Clock-limit and power-cap reasons are
            // diagnostics: they live on the Support page, never here.
            ColumnLayout {
                id: hardwareGroup
                Layout.fillWidth: true
                spacing: root.px(5)
                visible: !!root.selected.gpuFrameTime || !!root.selected.gpuUsage
                         || !!root.selected.gpuTemperature || !!root.selected.gpuPower
                         || !!root.selected.gpuClock || !!root.selected.gpuFan
                         || !!root.selected.vram || !!root.selected.cpuUsage
                         || !!root.selected.cpuTemperature || !!root.selected.cpuPower
                         || !!root.selected.cpuClock || !!root.selected.ram

                MetricLine {
                    visible: !!root.selected.gpuFrameTime
                    label: String(root.values["gpu_frame_label"] || "GPU render time")
                    value: root.formattedMetric("gpu_frame_ms", root.numberValue("gpu_frame_ms"), 1, " ms")
                }
                MetricLine { visible: !!root.selected.gpuUsage; label: "GPU usage"; value: root.smoothMetric("gpu_usage", 0, "%") }
                MetricLine {
                    visible: !!root.selected.gpuTemperature
                    label: "GPU temperature"
                    value: root.smoothMetric("gpu_temp", 0, " \u00b0C")
                    valueColor: root.levelColor("gpu_temp", root.okColor)
                }
                MetricLine { visible: !!root.selected.gpuPower; label: "GPU power"; value: root.formattedMetric("gpu_power", root.numberValue("gpu_power"), 0, " W") }
                MetricLine { visible: !!root.selected.gpuClock; label: "GPU clock"; value: root.formattedMetric("gpu_clock", root.numberValue("gpu_clock"), 0, " MHz") }
                MetricLine { visible: !!root.selected.gpuFan; label: "GPU fan"; value: root.formattedMetric("gpu_fan", root.numberValue("gpu_fan"), 0, "%") }
                MetricLine { visible: !!root.selected.vram; label: "VRAM used"; value: root.formattedMetric("vram_mb", root.numberValue("vram_mb"), 0, " MB") }
                MetricLine { visible: !!root.selected.cpuUsage; label: "CPU usage"; value: root.smoothMetric("cpu_usage", 0, "%") }
                MetricLine {
                    visible: !!root.selected.cpuTemperature
                    label: root.cpuTemperatureLabel()
                    value: root.smoothMetric("cpu_temp", 0, " \u00b0C")
                    valueColor: root.levelColor("cpu_temp", root.okColor)
                }
                MetricLine { visible: !!root.selected.cpuPower; label: "CPU power"; value: root.formattedMetric("cpu_power", root.numberValue("cpu_power"), 0, " W") }
                MetricLine { visible: !!root.selected.cpuClock; label: "CPU clock"; value: root.formattedMetric("cpu_clock", root.numberValue("cpu_clock"), 0, " MHz") }
                MetricLine { visible: !!root.selected.ram; label: "RAM used"; value: root.ramMetric() }
            }

            Rectangle {
                visible: statusGroup.visible
                Layout.fillWidth: true
                height: 1
                color: Qt.rgba(1, 1, 1, 0.08)
            }

            ColumnLayout {
                id: statusGroup
                Layout.fillWidth: true
                spacing: root.px(5)
                visible: !!root.selected.resolution || !!root.selected.connection || !!root.selected.godMode
                MetricLine {
                    visible: !!root.selected.resolution
                    label: "Resolution"
                    value: root.numberValue("resolution_x") > 0
                           ? root.numberValue("resolution_x").toFixed(0) + " × "
                             + root.numberValue("resolution_y").toFixed(0)
                           : "N/A"
                }
                MetricLine {
                    visible: !!root.selected.connection
                    // Same words as the top bar: either connection route counts.
                    readonly property bool connected: !!root.appBackend
                        && (root.appBackend.modConnected || root.appBackend.connectionTier === "external")
                    label: "Game mods"
                    value: connected ? "Connected" : "Not connected"
                    valueColor: connected ? "#6ee7a8" : "#ffb347"
                }
                MetricLine {
                    // The HUD reports the God Mode game mod's own truth:
                    // "Active" only when its fresh report confirms Eve is
                    // protected. The panel switch alone is only a request.
                    // SBGodNative 1.3.0+: armed but a hit reached Eve anyway
                    // reads amber "Hit got through" (Status.godState, the
                    // same verdict as the God card), never green "Active".
                    readonly property bool godApplied: !!root.appBackend && !!root.appBackend.nativeGodApplied
                    readonly property bool godRequested: !!root.appBackend && !!root.appBackend.godMode
                    readonly property var godStatus: root.appBackend && root.appBackend.nativeStatus
                                                     ? root.appBackend.nativeStatus.god : null
                    readonly property bool godHitGotThrough: godApplied
                        && Status.godState(root.appBackend, godStatus) === "hit-got-through"
                    visible: !!root.selected.godMode
                    label: "God Mode"
                    value: godHitGotThrough ? Status.godChip("hit-got-through")[0]
                           : godApplied ? "Active"
                           : !godRequested ? "Off"
                           : godStatus && godStatus.state !== "ready" && godStatus.label ? godStatus.label
                           : root.appBackend.gameRunning ? "Turning on" : "Waiting for game"
                    valueColor: godHitGotThrough ? "#ffb347" : godApplied ? "#6ee7a8" : godRequested ? "#ffb347" : "#c8d4ea"
                }
            }
        }
    }
}
