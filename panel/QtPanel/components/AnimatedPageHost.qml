pragma ComponentBehavior: Bound
import QtQuick
import "../pages" as Pages

// Pages are built once and then kept, so a page keeps its scroll position and
// inputs when you come back to it. Start-up builds the page you land on; the
// others are built in the background right after (see warmTimer).
Item {
    id: root
    property var tokens: null
    property var appBackend: null
    property var windowRoot: null
    property bool stellarAccent: true
    property int pageIndex: 0

    // Page change (FINAL-VISUAL-SPEC.md 8.1) is a fade-through: the page on
    // screen fades out over 120 ms (InCubic), then the new page fades in over
    // 200 ms (OutCubic) while it rises 8 px to rest on whole pixels. The two
    // pages are never both visible, so cards and text never double-expose.
    // With Windows animation effects off nothing rises and both fades are
    // 80 ms. These are property animations on the render loop; at rest
    // nothing runs.
    readonly property int animMs: tokens ? tokens.animPageIn : 200
    readonly property int outMs: tokens ? tokens.animPageOut : 120
    readonly property int moveMs: tokens ? tokens.animMove : 180

    // The page drawn now; it follows pageIndex after the outgoing fade.
    property int shownIndex: 0
    property int leavingIndex: -1
    property real leaveOpacity: 1.0

    onPageIndexChanged: {
        root.markVisited()
        if (root.pageIndex === root.shownIndex) {
            // Back to the page that was leaving: stop and show it again.
            leaveAnim.stop()
            root.leavingIndex = -1
            root.leaveOpacity = 1.0
            return
        }
        if (leaveAnim.running)
            return
        root.leavingIndex = root.shownIndex
        root.leaveOpacity = 1.0
        leaveAnim.restart()
    }

    NumberAnimation {
        id: leaveAnim
        target: root
        property: "leaveOpacity"
        from: 1.0
        to: 0.0
        duration: root.outMs
        easing.type: Easing.InCubic
        onFinished: {
            root.leavingIndex = -1
            root.shownIndex = root.pageIndex
            root.leaveOpacity = 1.0
        }
    }

    property var visited: ({})

    function markVisited() {
        if (root.visited[root.pageIndex])
            return
        var next = {}
        for (var key in root.visited)
            next[key] = true
        next[root.pageIndex] = true
        root.visited = next
    }

    Component.onCompleted: {
        root.shownIndex = root.pageIndex
        root.markVisited()
    }

    // 2.5.503: the pages not opened yet are built in the background, one at
    // a time, by Qt's incremental loader (between frames), so opening one
    // for the first time no longer builds it inside the page switch (that
    // stalled the switch 40-100 ms, measured 2026-09-28). A page opened
    // while it is still being built finishes at once (PageSlot below).
    property int warmIndex: 0
    Timer {
        id: warmTimer
        interval: 1500
        repeat: true
        running: true
        onTriggered: {
            while (root.warmIndex < 4 && root.visited[root.warmIndex])
                root.warmIndex++
            if (root.warmIndex >= 4) {
                running = false
                return
            }
            var next = {}
            for (var key in root.visited)
                next[key] = true
            next[root.warmIndex] = true
            root.visited = next
        }
    }

    component PageSlot: Loader {
        id: slot
        required property int index
        readonly property bool current: root.shownIndex === slot.index
        readonly property bool leaving: root.leavingIndex === slot.index
        property real slideY: current || root.moveMs === 0 ? 0 : 8

        anchors.fill: parent
        active: !!root.visited[slot.index]
        // Background builds are incremental; the page on screen is built now.
        asynchronous: !current && !leaving
        visible: (current || leaving) && status === Loader.Ready
        enabled: current && root.leavingIndex < 0
        opacity: leaving ? root.leaveOpacity : (current ? 1 : 0)
        z: current ? 2 : (leaving ? 1 : 0)

        Behavior on opacity {
            enabled: !slot.leaving
            NumberAnimation { duration: root.animMs; easing.type: Easing.OutCubic }
        }
        Behavior on slideY {
            NumberAnimation { duration: root.animMs; easing.type: Easing.OutCubic }
        }
    }

    PageSlot {
        id: gameplaySlot
        index: 0
        sourceComponent: Component {
            Pages.GameplayPage {
                appBackend: root.appBackend
                tokens: root.tokens
                windowRoot: root.windowRoot
                active: gameplaySlot.current
                slideY: gameplaySlot.slideY
            }
        }
    }

    PageSlot {
        id: itemsSlot
        index: 1
        sourceComponent: Component {
            Pages.ItemsPage {
                appBackend: root.appBackend
                tokens: root.tokens
                windowRoot: root.windowRoot
                active: itemsSlot.current
                slideY: itemsSlot.slideY
            }
        }
    }

    PageSlot {
        id: settingsSlot
        index: 2
        sourceComponent: Component {
            Pages.SettingsPage {
                appBackend: root.appBackend
                tokens: root.tokens
                windowRoot: root.windowRoot
                stellarAccent: root.stellarAccent
                active: settingsSlot.current
                slideY: settingsSlot.slideY
            }
        }
    }

    PageSlot {
        id: supportSlot
        index: 3
        sourceComponent: Component {
            Pages.SupportPage {
                appBackend: root.appBackend
                tokens: root.tokens
                windowRoot: root.windowRoot
                active: supportSlot.current
                slideY: supportSlot.slideY
            }
        }
    }
}
