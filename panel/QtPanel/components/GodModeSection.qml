import QtQuick
import QtQuick.Layouts
import "../DesignSystem/FriendlyCopy.js" as FriendlyCopy
import "../DesignSystem/Status.js" as Status
import "." as Ui

Ui.SbCard {
    id: root

    // Ready only when the God Mode game mod's own fresh report proves it is
    // set up on this exact game version; see services/god_service.py.
    readonly property var nativeStatus: root.appBackend && root.appBackend.nativeStatus
                                        ? root.appBackend.nativeStatus.god : null
    readonly property bool nativeApplied: root.appBackend && root.appBackend.nativeGodApplied
    // The same verdict as the Dashboard row (Status.godState): Active, Off,
    // Safety check (on, the game running, not protecting yet), Waiting for
    // game, Needs update, Couldn't start safely. A game mod that is simply
    // not installed reads a neutral Off, not a red fault.
    readonly property string godState: Status.godState(root.appBackend, root.nativeStatus)
    readonly property var chip: Status.godChip(root.godState)

    icon: "god"
    title: "God Mode"
    neonTag: "GOD"
    status: chip[0]
    statusKind: chip[1]
    helpTip: godState === "mod-off"
             ? "The God Mode game mod is not installed or not turned on, so God Mode stays off."
             : godState === "unavailable"
             ? "The God Mode game mod couldn't start safely, so God Mode stays off. Close Stellar Blade and run One-Click Repair on Support."
             : FriendlyCopy.godModeDetail(nativeApplied)
    accentActive: nativeApplied
    // The switch's objectName (the Dashboard's copy of this card names it
    // dashGodSwitch).
    property string switchName: "godModeSwitch"

    // Card anatomy (spec 4.2): title + chip, one line saying what is
    // happening (during the safety check, the game mod's own words when it
    // has any), then the one switch row. No second chip row: the header chip
    // is the only verdict.
    subtitle: root.godState === "needs-update" ? FriendlyCopy.godModeStatusNeedsUpdate()
              : root.godState === "mod-off" ? FriendlyCopy.godModeStatusModOff()
              : root.godState === "unavailable" ? FriendlyCopy.godModeStatusUnavailable()
              : root.godState === "active" ? FriendlyCopy.godModeStatusActive()
              : root.godState === "hit-got-through" && root.nativeStatus && root.nativeStatus.detail
                ? root.nativeStatus.detail
              : root.godState === "safety-check"
                ? (root.nativeStatus && root.nativeStatus.detail && root.nativeStatus.state !== "ready"
                   ? root.nativeStatus.detail : FriendlyCopy.godModeStatusTurningOn())
              : root.godState === "waiting" ? FriendlyCopy.godModeStatusNextLaunch()
              : FriendlyCopy.godModeStatusInactive()

    // One compact 40 px row (FINAL-VISUAL-SPEC.md 4.2). Its label is centred
    // in the row, so the row starts right under the card's line.
    Ui.SettingsField {
        Layout.topMargin: -(root.tokens ? root.tokens.spaceSm : 12)
        tokens: root.tokens
        label: "Protect Eve from damage"
        hasControl: true
        compactControl: true
        showSeparator: false
        Ui.SbSwitch {
            id: godModeSwitch
            objectName: root.switchName
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            tokens: root.tokens
            checked: root.appBackend.godMode
            // Only a deliberate user activation may change the panel-owned
            // desired state. `toggled` can also follow binding/focus churn as
            // the game takes focus, which previously disarmed God Mode during
            // a live fight. Release focus after activation so a later gameplay
            // Space press cannot toggle this control a second time.
            onClicked: {
                root.appBackend.setGodMode(checked)
                godModeSwitch.focus = false
            }
        }
    }
}
