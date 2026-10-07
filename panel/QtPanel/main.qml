import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Window
import "DesignSystem" as DS
import "DesignSystem/PageTheme.js" as PageTheme
import "components" as Ui

// The window frame (FINAL-VISUAL-SPEC.md 3): a 16 px window margin; the
// sidebar runs the full height (y 16 to H - 16); the top bar sits over the
// page column (y 16 to 72, as wide as the column); the first card starts at
// y 88 on every page, the Dashboard included, and its content edge lines up
// with the top bar's title. Every page sits on the same blurred backdrop
// (EveSceneBackdrop); 2.5.504 build 4 removed the sharp Eve art.

ApplicationWindow {
    id: window
    width: 1320
    height: 880
    // Small windows work: below tokens.railBreakpoint the sidebar folds to
    // an icon rail and every page is one scrolling column.
    minimumWidth: 720
    minimumHeight: 540
    visible: true
    title: "Stellar Blade Mod Suite"
    color: Material.background
    font.pixelSize: tokens.fontBody
    font.family: tokens.typeFamily
    font.hintingPreference: tokens.textHinting

    Material.theme: Material.Dark
    Material.accent: tokens.accent
    Material.background: tokens.background
    Material.foreground: tokens.textPrimary

    flags: Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowCloseButtonHint
           | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
           | (appBackend && appBackend.alwaysOnTop ? Qt.WindowStaysOnTopHint : 0)

    // The metrics overlay is another top-level Qt window. Closing this main
    // window must end the application rather than leaving an invisible process
    // alive to renew native feature leases.
    onClosing: function(closeEvent) {
        closeEvent.accepted = true
        if (appBackend)
            appBackend.persistWindowPlacement()
        Qt.quit()
    }

    property var appBackend: backend // qmllint disable unqualified
    property string activePage: "gameplay"
    property bool stellarAccent: appBackend ? appBackend.stellarAccent : true
    property int activeTheme: 4

    readonly property string backdropPage: activePage
    // Navigation updates activePage immediately for click feedback, while the
    // content/layout wait for the ready backdrop slot to commit. This prevents a
    // new page of cards appearing over the previous page's artwork while loading.
    readonly property string displayedPage: sceneBackdrop.displayedPage
    readonly property bool compactNav: width < tokens.railBreakpoint
    readonly property int navWidth: compactNav ? tokens.sidebarRailWidth : tokens.sidebarWidth

    // ── Column geometry (spec 3.1) ───────────────────────────────────────
    readonly property real contentLeft: tokens.windowMargin + navWidth + tokens.gap
    readonly property real contentAvailable: Math.max(0, width - tokens.windowMargin - contentLeft)
    readonly property bool wideItems: width >= tokens.wideBreakpoint && displayedPage === "items"
    // 720 px while at least artMinWidth is left beside it; otherwise the
    // column fills. Maximized Items & Money uses two 600 px columns (1216).
    readonly property real columnWidth: wideItems
                                        ? Math.min(tokens.itemsWideWidth, contentAvailable)
                                        : (contentAvailable - tokens.contentMaxWidth - tokens.gap >= tokens.artMinWidth
                                           ? tokens.contentMaxWidth : contentAvailable)
    readonly property real pageTop: tokens.windowMargin + tokens.topBarHeight + tokens.gap
    readonly property real pageAreaHeight: Math.max(0, height - pageTop - tokens.windowMargin)

    // Support shows how often the panel really redraws. Python counts the
    // window's frameSwapped events, and only while Support is on screen; no
    // frame clock runs here (a FrameAnimation forced a redraw every vsync).
    // The same flag lets the sensors poll slowly for Support's diagnostics.
    readonly property bool frameSamplingActive: window.visible
                                                && window.visibility !== Window.Minimized
                                                && window.displayedPage === "support"

    // Every page, the Dashboard included, is a still image on the same
    // blurred backdrop, so the window swaps no frames at rest (spec 8.2).
    // 2.5.504 review: the feature-page drift and embers redrew every vsync
    // (240 frames/s at 35 % of a core on the 4K monitor); build 4 removed the
    // 30 frames/s Dashboard video and the sharp Eve art.

    // The window's screen decides the device pixel ratio (1.0 on the 1440p
    // monitor, 1.5 on the 4K one); tokens.snap() rounds to its pixels.
    DS.Tokens {
        id: tokens
        dpr: window.Screen.devicePixelRatio > 0 ? window.Screen.devicePixelRatio : 1.0
        // Windows "Animation effects" off: no slides, scales or rotations.
        reduceMotion: !!window.appBackend && window.appBackend.reduceMotion
        // Settings > Neon accent.
        neonAccent: window.stellarAccent
    }

    Ui.PerformanceOverlay {
        appBackend: window.appBackend
        tokens: tokens
    }

    onFrameSamplingActiveChanged: {
        if (appBackend)
            appBackend.setSupportVisible(frameSamplingActive)
    }

    function goToPage(page) {
        activePage = page
        if (appBackend) appBackend.setActivePage(page)
    }

    Component.onCompleted: {
        appBackend = backend // qmllint disable unqualified
        if (appBackend && appBackend.savedActivePage)
            activePage = appBackend.savedActivePage
        if (appBackend && appBackend.version)
            window.title = "Stellar Blade Mod Suite v" + appBackend.version
        Qt.callLater(function() { window.requestActivate() })
    }

    Shortcut { sequence: "F5"; onActivated: window.appBackend.refresh() }
    Shortcut { sequence: "Ctrl+1"; onActivated: window.goToPage("gameplay") }
    Shortcut { sequence: "Ctrl+2"; onActivated: window.goToPage("items") }
    Shortcut { sequence: "Ctrl+3"; onActivated: window.goToPage("settings") }
    Shortcut { sequence: "Ctrl+4"; onActivated: window.goToPage("support") }

    Ui.EveSceneBackdrop {
        id: sceneBackdrop
        anchors.fill: parent
        z: -3
        tokens: tokens
        page: window.backdropPage
    }

    // Every glass surface samples the backdrop's blurred art (spec 9.1).
    Binding { target: tokens; property: "glassTexture"; value: sceneBackdrop.glassTexture }
    Binding { target: tokens; property: "glassArtRect"; value: sceneBackdrop.artRect }
    onWidthChanged: tokens.bumpGlass()
    onHeightChanged: tokens.bumpGlass()
    onDisplayedPageChanged: tokens.bumpGlass()

    Item {
        id: shell
        anchors.fill: parent
        anchors.margins: tokens.windowMargin
        z: 1

        Ui.SidebarNav {
            id: sidebar
            x: 0
            y: 0
            width: window.navWidth
            height: shell.height
            activePage: window.activePage
            tokens: tokens
            appBackend: window.appBackend
            compact: window.compactNav
            onPageSelected: function(page) { window.goToPage(page) }
        }

        Ui.TopBar {
            id: topBar
            x: window.navWidth + tokens.gap
            y: 0
            width: window.columnWidth
            height: tokens.topBarHeight
            appBackend: window.appBackend
            tokens: tokens
            title: PageTheme.bannerMeta(window.displayedPage, tokens).title
            onForceQuitRequested: forceQuitDialog.open()
        }

        Item {
            id: pageArea
            x: window.navWidth + tokens.gap
            y: tokens.topBarHeight + tokens.gap
            width: window.columnWidth
            height: window.pageAreaHeight

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                Item {
                    id: pageColumn
                    Layout.alignment: Qt.AlignTop | Qt.AlignLeft
                    Layout.preferredWidth: window.columnWidth
                    Layout.maximumWidth: window.columnWidth
                    Layout.fillHeight: true

                    Rectangle {
                        objectName: "pageHostFrame"
                        anchors.fill: parent
                        // No outer box: the cards float directly on the scene
                        // (each card has its own surface).
                        color: "transparent"
                        border.width: 0
                        // PageScroll places its drag rail in the divider beside
                        // this frame, off the artwork. Each page Flickable still
                        // clips its own content.
                        clip: false

                        readonly property int pageIndex: {
                            if (window.displayedPage === "gameplay") return 0
                            if (window.displayedPage === "items") return 1
                            if (window.displayedPage === "settings") return 2
                            if (window.displayedPage === "support") return 3
                            return 0
                        }

                        Ui.AnimatedPageHost {
                            id: pageHost
                            anchors.fill: parent
                            tokens: tokens
                            appBackend: window.appBackend
                            windowRoot: window
                            stellarAccent: window.stellarAccent
                            pageIndex: parent.pageIndex
                        }
                    }
                }
            }
        }
    }

    // Toasts sit at the bottom centre of the content column, never over the
    // sidebar, 16 px above the window's bottom edge (spec 5.13).
    Ui.SbToast {
        id: toast
        z: 50
        tokens: tokens
        x: Math.round(window.contentLeft + Math.max(0, (window.columnWidth - width) / 2))
        y: window.height - tokens.windowMargin - height
    }

    Connections {
        target: window.appBackend
        function onOperationNotice(msg, level) {
            var v = String(level || "").toUpperCase()
            toast.show(msg, v === "ERROR" ? "error" : v === "WARN" ? "warn" : v === "INFO" ? "info" : "ok")
        }
    }

    // Force quit asks first (spec 5.14); Enter and Esc both mean Cancel.
    Ui.SbDialog {
        id: forceQuitDialog
        objectName: "forceQuitDialog"
        tokens: tokens
        title: "Force quit the game?"
        body: "Progress since your last save is lost."
        iconName: "power"
        acceptText: "Force quit"
        destructive: true
        onAccepted: window.appBackend.forceQuitGame()
    }
}
