import QtQuick

// Smooth wheel scrolling for a Flickable.
//
// Two very different input devices arrive through the same handler:
//   * A mouse wheel sends coarse notches (angleDelta). Those need to be
//     animated into a glide, or scrolling reads as a series of jumps.
//   * A trackpad sends real pixel deltas (pixelDelta) that are already smooth,
//     so a long animation there just adds lag. It gets a short catch-up instead.
//
// Rapid notches accumulate onto the in-flight target rather than restarting
// from the current position, so spinning the wheel produces one continuous
// glide instead of repeatedly stuttering back to a near-stop.
//
// Bounds come from the view's real extent, not from 0..contentHeight. A
// ListView's content does not always start at y = 0: after a search removes
// rows above the viewport its originY moves (to 920 px, say). Clamping to
// 0..contentHeight-height glided the list into empty space above the first
// row - the item catalog showed "171 shown" over a blank box - and stopped
// short of its last rows. topMargin/bottomMargin are part of the extent too.
//
// A nested list (the item catalog inside a scrolling page) hands the wheel to
// the page once it is resting at its end, so the page never feels stuck under
// the pointer. WheelHandler cannot un-accept a wheel event after the fact, so
// the hand-off drives the enclosing Flickable directly.
WheelHandler {
    id: root
    required property Flickable view
    property var tokens: null

    // How far one wheel notch travels. The old value (56) was about half a
    // card, so long pages needed a lot of spinning.
    property int wheelStep: 110

    // Continue into the nearest enclosing Flickable when the view is resting
    // at its bound in the direction of the wheel.
    property bool chainAtBounds: true

    property real targetY: 0
    property real chainTargetY: 0
    property Flickable chainView: null

    readonly property int wheelMs: tokens ? tokens.animWheel : 260
    readonly property int trackpadMs: tokens ? tokens.animTrackpad : 90
    readonly property int easeKind: tokens ? tokens.easeSoft : Easing.OutCubic

    property var scrollAnimation: NumberAnimation {
        target: root.view
        property: "contentY"
        easing.type: root.easeKind
    }

    property var chainAnimation: NumberAnimation {
        target: root.chainView
        property: "contentY"
        easing.type: root.easeKind
    }

    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad

    function minYOf(flick: Flickable): real {
        return flick.originY - flick.topMargin
    }

    function maxYOf(flick: Flickable): real {
        return Math.max(minYOf(flick),
                        flick.originY + flick.contentHeight + flick.bottomMargin - flick.height)
    }

    function clampFor(flick: Flickable, y: real): real {
        return Math.max(minYOf(flick), Math.min(maxYOf(flick), y))
    }

    function clampY(y: real): real {
        return clampFor(root.view, y)
    }

    function stop(): void {
        root.scrollAnimation.stop()
        root.targetY = root.view.contentY
    }

    function enclosingFlickable(): Flickable {
        let item = root.view ? root.view.parent : null
        while (item) {
            const flick = item as Flickable
            if (flick)
                return flick
            item = item.parent
        }
        return null
    }

    function deltaFor(pixelDeltaY: real, angleDeltaY: real, inverted: bool): real {
        let dy = pixelDeltaY
        if (dy === 0)
            dy = (angleDeltaY / 120) * wheelStep
        return inverted ? -dy : dy
    }

    // Glide `flick` by -dy using `anim`; `target` is the in-flight target.
    // Returns the new target, or NaN when the view cannot move that way.
    function glide(flick: Flickable, anim: var, target: real, dy: real, fromTrackpad: bool): real {
        const running = anim.running
        const base = running ? clampFor(flick, target) : flick.contentY
        const next = clampFor(flick, base - dy)
        if (Math.abs(next - base) < 0.5 && !running) {
            // Snap a view that was left outside its extent back inside it.
            const inside = clampFor(flick, flick.contentY)
            if (Math.abs(inside - flick.contentY) >= 0.5) {
                flick.contentY = inside
                return inside
            }
            return NaN
        }
        anim.stop()
        anim.from = flick.contentY
        anim.to = next
        anim.duration = fromTrackpad ? root.trackpadMs : root.wheelMs
        anim.start()
        return next
    }

    // Returns true when the view (or, at its bound, the enclosing page) moved.
    function scrollByDeltas(pixelDeltaY: real, angleDeltaY: real, inverted: bool): bool {
        const fromTrackpad = pixelDeltaY !== 0
        const dy = deltaFor(pixelDeltaY, angleDeltaY, inverted)
        if (dy === 0)
            return false

        const moved = glide(root.view, root.scrollAnimation, root.targetY, dy, fromTrackpad)
        if (!isNaN(moved)) {
            root.targetY = moved
            return true
        }
        if (!root.chainAtBounds)
            return false
        if (!root.chainView)
            root.chainView = enclosingFlickable()
        if (!root.chainView || !root.chainView.interactive)
            return false
        const chained = glide(root.chainView, root.chainAnimation, root.chainTargetY, dy, fromTrackpad)
        if (isNaN(chained))
            return false
        root.chainTargetY = chained
        return true
    }

    onWheel: (event) => {
        root.scrollByDeltas(event.pixelDelta.y, event.angleDelta.y, event.inverted)
        event.accepted = true
    }

    // A glide aimed at a position computed before the rows changed would land
    // somewhere that no longer exists. A change to the view's origin (rows
    // removed or inserted above the viewport) or a user drag cancels it.
    // (WheelHandler has no default property, so the watcher is held in a
    // property like the animations above.)
    property Connections viewWatch: Connections {
        target: root.view
        function onMovementStarted() { root.stop() }
        function onOriginYChanged() {
            if (root.scrollAnimation.running)
                root.stop()
        }
    }
}
