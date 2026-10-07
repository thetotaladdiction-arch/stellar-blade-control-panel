import QtQuick

// One design vocabulary for the whole panel (FINAL-VISUAL-SPEC.md sections
// 2 and 8). Every surface, text colour, status colour, size, notch and
// duration comes from here so pages cannot drift. REDESIGN-SYSTEM.md lists
// every token and the components that use it.
//
// Older names (radiusGroup, surfaceCard, neonCyan, ...) are kept as aliases
// of the new values so every existing caller keeps working.
QtObject {
    // ── Live inputs (main.qml binds these) ──────────────────────────────
    // Device pixel ratio of the panel's screen: 1.0 on the 1440p monitor,
    // 1.5 on the 4K one. snap() rounds a logical coordinate to it.
    property real dpr: 1.0
    // Windows "Animation effects" off: nothing slides, scales or rotates.
    property bool reduceMotion: false
    // Settings > Neon accent. Off uses the softer teal.
    property bool neonAccent: true
    // Glass (spec 9.1): the one blurred art texture every surface samples,
    // and where it lies in the window. glassEpoch goes up whenever surfaces
    // may have moved in the window (scrolling, page slides, resizes), so each
    // surface re-reads its own window position.
    property Image glassTexture: null
    property rect glassArtRect: Qt.rect(0, 0, 0, 0)
    property int glassEpoch: 0
    function bumpGlass() { glassEpoch = glassEpoch + 1 }

    // ── Colour (spec 2.1) ────────────────────────────────────────────────
    // Colour means one thing: teal = press / selected, green = on,
    // bright outline = ready, grey = off, amber = waiting or experimental,
    // red = error or destructive.
    readonly property color background: "#05080c"
    readonly property color backgroundDeep: "#030507"
    // Glass: the blurred art under glassTint (80 %). glassSolid at 94 % is
    // the fallback while no blur texture is loaded.
    readonly property color glassSolid: "#0a0f15"
    readonly property real glassSolidOpacity: 0.94
    // rgba(7,11,16,0.86): 86 %, not the mock's 80 %, so muted text keeps
    // 4.5:1 over the brightest spot of the blurred art (tests check it).
    readonly property color glassTint: "#db070b10"
    readonly property color glassFill: Qt.rgba(0.0392, 0.0588, 0.0824, 0.94)
    // Menus, select popups, tooltips, toasts and dialogs: opaque.
    readonly property color surfaceRaised: "#0d131a"
    readonly property color edge: "#24bee6f0"               // rgba(190,230,240,0.14)
    readonly property color hairline: "#1abee6f0"           // rgba(190,230,240,0.10)
    readonly property color controlLine: "#38bee6f0"        // rgba(190,230,240,0.22)
    readonly property color controlLineHover: "#57bee6f0"   // 34 %
    readonly property color textPrimary: "#edf3f5"
    readonly property color textSecondary: "#a9b7c0"
    // About 5.3:1 on the glass (tests/test_ui_design_system.py checks 4.5:1).
    readonly property color textMuted: "#7b8994"
    readonly property color textDisabled: "#56626b"
    readonly property color accentNeon: "#56e0d3"
    readonly property color accentQuiet: "#43b3aa"
    readonly property color accent: neonAccent ? accentNeon : accentQuiet
    readonly property color accentHover: neonAccent ? "#6fe9dd" : "#52c2b9"
    readonly property color accentPressed: neonAccent ? "#45c7bb" : "#389c94"
    readonly property color accentInk: "#03201d"
    readonly property color statusOk: "#62dca0"
    readonly property color statusOkInk: "#93efc4"
    readonly property color statusReady: "#e4edf1"
    readonly property color statusOff: "#86939c"
    readonly property color statusWarn: "#ffb45e"
    readonly property color statusWarnInk: "#ffcd92"
    readonly property color statusError: "#ff7a72"
    readonly property color statusErrorInk: "#ffa39d"
    readonly property color statusInfo: accent
    readonly property color dangerInk: "#2a0806"
    readonly property color scrim: "#8c000000"              // rgba(0,0,0,0.55)
    readonly property color shadow: "#8c000000"
    readonly property color shadowDialog: "#99000000"
    readonly property color knobOff: "#7d8a94"
    readonly property color thumbRing: "#081016"

    // White washes used as fills (hover 4 %, secondary button 4.5 %, ...).
    function white(alpha) { return Qt.rgba(1, 1, 1, alpha) }
    // A token colour at a given alpha (accent 10 %, statusError 6 %, ...).
    function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }

    // Legacy names, mapped onto the new palette.
    readonly property color accentMuted: accentQuiet
    readonly property color accentGlow: "#1a4a46"
    readonly property color neonCyan: accent
    readonly property color neonMagenta: "#ff6eb4"
    readonly property color neonViolet: "#b088ff"
    readonly property color neonPink: "#ff6eb4"
    readonly property color electricBlue: "#5c9cff"
    readonly property color neonAmber: statusWarn
    readonly property color modAccent: accent
    readonly property color surface: "#0d131a"
    readonly property color surfaceElevated: "#0d131a"
    readonly property color surfaceHover: "#1a2027"
    readonly property color surfaceRaisedHover: "#141a21"
    readonly property color card: "#0a0f15"
    readonly property color hairlineStrong: "#38bee6f0"
    readonly property color green: statusOk
    readonly property color red: statusError
    readonly property color orange: statusWarn
    readonly property color blue: "#5c9cff"
    // Cards, the sidebar and the top bar (glass, solid fallback).
    readonly property color surfaceCard: "#0a0f15"
    readonly property real surfaceCardOpacity: 0.94
    readonly property color surfaceChrome: "#0a0f15"
    readonly property real surfaceChromeOpacity: 0.94
    // Disabled fields: flatter and dimmer than an enabled field.
    readonly property color surfaceDisabled: "#05ffffff"
    // Dims the artwork behind the content column (feature pages only).
    readonly property real contentScrimOpacity: 0.50
    readonly property color logBg: "#070b10"
    readonly property color noteBg: "#0d131a"

    // ── Space (spec 2.3, 4 px scale) ─────────────────────────────────────
    readonly property int spaceXxs: 4
    readonly property int spaceXs: 8
    readonly property int spaceSm: 12
    readonly property int spaceMd: 16
    readonly property int spaceLg: 24
    readonly property int spaceXl: 32
    readonly property int spaceXxl: 48
    readonly property int windowMargin: 16
    readonly property int gap: 16
    readonly property int cardPad: 16

    // ── Sizes ────────────────────────────────────────────────────────────
    readonly property int sidebarWidth: 216
    // Below `railBreakpoint` the sidebar folds to an icon rail.
    readonly property int sidebarRailWidth: 64
    readonly property int railBreakpoint: 980
    readonly property int wideBreakpoint: 1880
    readonly property int topBarHeight: 56
    // Readable line length: pages (the Dashboard included) never grow wider
    // than this, so a maximized window shows more backdrop instead of
    // stretched cards.
    readonly property int contentMaxWidth: 720
    readonly property int itemsWideWidth: 1216
    // Below this much room beside it, the column fills the window.
    readonly property int artMinWidth: 280
    readonly property int rowHeight: 48
    readonly property int rowCompact: 40
    readonly property int navItemHeight: 44
    readonly property int btnHeight: 40
    // The one smaller button: the top bar and Dashboard rows only.
    readonly property int btnHeightCompact: 32
    readonly property int fieldHeight: 40
    readonly property int fieldWidth: 240
    readonly property int chipHeight: 24
    readonly property int switchWidth: 44
    readonly property int switchHeight: 24
    readonly property int switchKnob: 16
    readonly property int iconSize: 20
    readonly property int iconSmall: 16
    readonly property int helpSize: 24
    readonly property int listRowHeight: 44
    readonly property int catalogRowHeight: 44
    readonly property int menuWidth: 216
    readonly property int menuItemHeight: 40
    readonly property int dialogWidth: 480
    readonly property int toastMinWidth: 320
    readonly property int toastMaxWidth: 480
    readonly property int tooltipMaxWidth: 320
    readonly property int primaryActionWidth: 160
    readonly property int controlWidth: 240
    readonly property int settingsLabelWidth: 300

    // ── Shape (spec 2.4): a notch instead of a radius ────────────────────
    readonly property int notchSurface: 12      // cards, sidebar, top bar, dialogs
    readonly property int notchControl: 8       // buttons, menus, toasts
    readonly property int notchSmall: 6         // compact buttons, fields, tooltips
    readonly property int radiusSmall: 2        // chips and switches only
    readonly property int tickWidth: 40
    // Every border is 1 logical px drawn as whole device pixels: 1 px at
    // 100 %, 2 px at 150 %.
    readonly property real hairlineW: Math.max(1, Math.round(dpr)) / dpr
    // Legacy radius names (callers that still draw a Rectangle).
    readonly property int radiusGroup: 12
    readonly property int radiusButton: 8
    readonly property int radiusChip: 8

    // ── Type (spec 2.2). Nothing smaller than 13. ────────────────────────
    //   page 22 · card title 18 · value 18 · body 15 · card line 14 · hint 13
    readonly property int fontTitle: 22
    readonly property int fontHeading: 18
    readonly property int fontValue: 18
    readonly property int fontBody: 15
    readonly property int fontCaption: 14
    readonly property int fontInfo: 14
    readonly property int fontLabel: 13
    readonly property int fontHint: 13
    readonly property int fontMin: 13
    // Full hinting (DirectWrite GDI-classic ClearType) snaps stems, x-height
    // and baseline to the pixel grid. main.py sets the same value on the
    // application font, so every Text inherits it.
    readonly property int textHinting: Font.PreferFullHinting
    // Each family below is a separate static family (checked with
    // QFontDatabase.families() on this PC), so no variable axis is involved.
    // "Segoe UI Variable Text" exposes only Regular and Bold to Qt, so a
    // Font.DemiBold request silently rendered Bold: emphasis names the real
    // Semibold instance instead.
    readonly property string typeFamily: "Segoe UI Variable Text"
    readonly property string typeSemibold: "Segoe UI Variable Text Semibold"
    readonly property string typeSmallSemibold: "Segoe UI Variable Small Semibold"
    // Titles, row names, buttons, values and the brand: Bahnschrift.
    readonly property string typeDisplay: "Bahnschrift"
    readonly property string typeDisplaySemibold: "Bahnschrift SemiBold"

    // ── Pixel snapping ───────────────────────────────────────────────────
    function snap(value) {
        var ratio = dpr > 0 ? dpr : 1.0
        return Math.round(value * ratio) / ratio
    }
    // Baseline that centres a capital-height run of text in a box, on a
    // whole device pixel. An odd leftover pixel goes below the text so
    // descenders (g, y, p) balance it. Text.y = baselineIn(...) - baselineOffset.
    function baselineIn(boxHeight, capHeight) {
        var ratio = dpr > 0 ? dpr : 1.0
        return Math.floor((boxHeight + capHeight) / 2 * ratio) / ratio
    }

    // ── Motion (spec 8.1). Property animations only, never timers. ───────
    // With reduceMotion every movement is 0 and fades are 80 ms.
    readonly property int animHover: 120      // fill, outline, label colour
    readonly property int animPressMs: 90                          // press / release colour
    readonly property int animChip: reduceMotion ? 80 : 180        // chip crossfade
    readonly property int animSwitch: reduceMotion ? 0 : 140       // knob travel
    readonly property int animNav: reduceMotion ? 0 : 180          // selection indicator
    readonly property int animPageOut: reduceMotion ? 80 : 120
    readonly property int animPageIn: 200
    readonly property int animMenuOpen: reduceMotion ? 80 : 140
    readonly property int animMenuClose: reduceMotion ? 80 : 100
    readonly property int animFold: reduceMotion ? 0 : 200
    readonly property int animTipIn: reduceMotion ? 80 : 120
    readonly property int animTipOut: 80
    readonly property int tipDelay: 500
    readonly property int animToastIn: reduceMotion ? 80 : 200
    readonly property int animToastOut: reduceMotion ? 80 : 160
    readonly property int animDialog: reduceMotion ? 80 : 160
    readonly property int animSlider: reduceMotion ? 0 : 180
    readonly property int animArt: 240
    readonly property int toastSuccessMs: 4000
    // Movement distances (whole logical px) that reduced motion zeroes.
    readonly property int pageRise: reduceMotion ? 0 : 8
    readonly property int popupRise: reduceMotion ? 0 : 4

    // Legacy motion names.
    readonly property int animFast: 120        // colour / border fades
    readonly property int animNormal: 200
    readonly property int animMove: reduceMotion ? 0 : 180         // slides, height, rotation
    readonly property int animPress: reduceMotion ? 0 : 90
    readonly property int animMicro: 120
    readonly property int animWheel: 170        // mouse-wheel glide
    readonly property int animTrackpad: 90      // trackpad is already 1:1, stay short
    readonly property int animFade: 180         // scrollbar show/hide
    readonly property int easeOut: Easing.OutCubic
    readonly property int easeIn: Easing.InCubic
    readonly property int easeInOut: Easing.InOutQuad
    readonly property int easeSoft: Easing.OutCubic
    // Retired from the chrome (spec 8.1); only unreferenced legacy files
    // (NeonShimmerBar, AnimeBackdrop) still read them.
    readonly property int animSlow: 2800
    readonly property int animShimmer: 2800
    readonly property int animNavPulse: 1100
    readonly property int animTickMs: 33
}
