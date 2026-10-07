import QtQuick
import QtQuick.Layouts
import "../DesignSystem/FriendlyCopy.js" as FriendlyCopy
import "../DesignSystem/Status.js" as Status
import "../components" as Ui

// Gameplay (FINAL-VISUAL-SPEC.md 4.2, IA-SPEC.md 2.2): one column, most-used
// first - God Mode, Unlimited energy (the same game mod's two energy
// switches), Retry Point, Instant Boss Restart, then Movement &
// camera (set once, so it goes last). Every card has the same anatomy: icon,
// title and status chip, one line saying what is happening, then its
// controls. Starting, restarting and quitting the game live in the top bar
// on every page; Safe Reset is on Support.
Ui.PageScroll {
    id: root
    property var appBackend
    property var windowRoot
    pageId: "gameplay"

    readonly property var bossStatus: root.appBackend.nativeStatus.boss
    readonly property var retryPointStatus: root.appBackend.nativeStatus.retryPoint
    readonly property var movementStatus: root.appBackend.nativeStatus.movement

    // The game's own values; Back to normal returns to these.
    readonly property int normalSpeedPct: 100
    readonly property int normalJumpPct: 100
    readonly property int normalFovDegrees: 75

    Ui.GodModeSection {
        appBackend: root.appBackend
        tokens: root.tokens
        Layout.fillWidth: true
    }

    // Unlimited Beta / Burst energy: independent of the God Mode switch.
    Ui.EnergySection {
        appBackend: root.appBackend
        tokens: root.tokens
        Layout.fillWidth: true
    }

    // No heal control here by design. Writing health from the panel is not a
    // supported route in the current safe profile, and a button that silently
    // does nothing is worse than no button. Enforced by
    // test_hook_free_gameplay_surface_has_no_health_write_route.

    Ui.SbCard {
        id: retryCard
        appBackend: root.appBackend
        tokens: root.tokens
        icon: "retry"
        title: "Retry Point"
        neonTag: "RETRY POINT"
        helpTip: FriendlyCopy.retryPointDetail()
        // A usable saved point is part of the verdict, so the chip alone says
        // whether Return will work, and "Another area" as soon as the game
        // mod finds Eve outside the point's area (Status.retryPointChip, the
        // same words as the Dashboard). Return stays usable there: the game
        // mod checks the area on every Return and moves nothing if it differs.
        readonly property var chip: Status.retryPointChip(root.appBackend, root.retryPointStatus)
        status: chip[0]
        statusKind: chip[1]
        subtitle: root.appBackend.retryPointStatus
        accentActive: root.appBackend.retryPointAvailable && root.appBackend.retryPointCanReturn
        Layout.fillWidth: true

        // Three equal slots, left to right: Clear, Set Point, Return. Clear
        // shows only while a point is saved; its slot stays, so Set Point and
        // Return never move - only the primary highlight does (Return once a
        // point here can be returned to, Set Point before that). Hidden while
        // the game mod is not installed: dead buttons under "Off" say nothing
        // the chip does not.
        Item {
            id: retryButtons
            objectName: "retryPointButtons"
            visible: root.appBackend.retryPointInstalled
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredHeight: root.tokens ? root.tokens.btnHeight : 40
            implicitHeight: root.tokens ? root.tokens.btnHeight : 40

            readonly property real gapW: root.tokens ? root.tokens.spaceXs : 8
            // Whole device pixels, so every outline and notch stays sharp.
            readonly property real cellW: root.tokens ? root.tokens.snap((width - 2 * gapW) / 3)
                                                      : Math.floor((width - 2 * gapW) / 3)

            Ui.SbButton {
                objectName: "retryPointClear"
                x: 0
                width: retryButtons.cellW
                height: retryButtons.height
                tokens: root.tokens
                text: "Clear"
                danger: true
                visible: root.appBackend.retryPointSaved
                enabled: root.appBackend.retryPointSaved && !root.appBackend.retryPointBusy
                onClicked: root.appBackend.sendRetryPointCommand("clear")
            }
            Ui.SbButton {
                objectName: "retryPointSet"
                x: root.tokens ? root.tokens.snap(retryButtons.cellW + retryButtons.gapW)
                               : Math.round(retryButtons.cellW + retryButtons.gapW)
                width: retryButtons.cellW
                height: retryButtons.height
                tokens: root.tokens
                text: root.appBackend.retryPointBusy ? "Working…" : "Set Point"
                // The highlight follows whether a point exists (spec 4.2),
                // also while the game is closed.
                success: !root.appBackend.retryPointSaved
                enabled: root.appBackend.retryPointAvailable && !root.appBackend.retryPointBusy
                onClicked: root.appBackend.sendRetryPointCommand("save")
            }
            Ui.SbButton {
                objectName: "retryPointReturn"
                x: root.tokens ? root.tokens.snap(2 * (retryButtons.cellW + retryButtons.gapW))
                               : Math.round(2 * (retryButtons.cellW + retryButtons.gapW))
                width: retryButtons.width - x
                height: retryButtons.height
                tokens: root.tokens
                text: "Return"
                success: root.appBackend.retryPointSaved
                enabled: root.appBackend.retryPointAvailable
                         && root.appBackend.retryPointCanReturn
                         && !root.appBackend.retryPointBusy
                onClicked: root.appBackend.sendRetryPointCommand("return")
            }
        }
    }

    Ui.SbCard {
        appBackend: root.appBackend
        tokens: root.tokens
        icon: "boss"
        title: "Instant Boss Restart"
        neonTag: "BOSS"
        // The card and its tip say what the game mod does, never which
        // bosses were tested: in-game results change with each game mod
        // build and live in the release texts behind the release gate.
        helpTip: FriendlyCopy.bossRetryDetail(root.appBackend.bossSupportsStory)
        // This card is the SBInstantBossRestart game mod: the player presses
        // the game's own Revive and the game mod plays the boss intro again.
        // One switch; the chip and line are the game mod's own status (Off,
        // Waiting for game, Ready, Restarting while the screen is black,
        // Needs update, Couldn't start safely). God Mode adds an advisory;
        // it does not suspend the game mod (same verdict as Status.bossChip).
        readonly property var chip: Status.bossChip(root.appBackend, root.bossStatus)
        status: chip[0]
        statusKind: chip[1]
        subtitle: Status.bossLine(root.appBackend, root.bossStatus)
        accentActive: root.appBackend.bossEnabled && root.appBackend.bossReady
        // Rows carry their own 48 px rhythm and hairline; the list starts
        // 4 px under the line.
        bodySpacing: 0
        Layout.fillWidth: true

        // The one switch. It works right away, also while the game runs:
        // the game mod reads it at every death.
        Ui.SettingsField {
            tokens: root.tokens
            Layout.topMargin: -((root.tokens ? root.tokens.spaceSm : 12) - (root.tokens ? root.tokens.spaceXxs : 4))
            label: "Use Instant Boss Restart"
            hint: FriendlyCopy.bossSwitchHint()
            hasControl: true
            compactControl: true
            showSeparator: false
            Ui.SbSwitch {
                objectName: "bossSwitch"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                tokens: root.tokens
                checked: root.appBackend.bossEnabled
                Accessible.name: "Instant Boss Restart"
                onClicked: root.appBackend.sendBossCommand(checked ? "enable" : "disable")
            }
        }
    }

    // Movement and field of view are one game mod, so they are one card with
    // one chip (IA-SPEC 2.2). Run and walk are merged into one speed: the game
    // separates them internally, but you sprint nearly all the time so a
    // separate walk multiplier is not something you can feel. No Apply
    // button: every slider changes the game live as you drag, and the values
    // are remembered across restarts.
    Ui.SbCard {
        id: movementCard
        // MUST set appBackend: SbCard declares its own, so a bare
        // `root.appBackend.x` inside resolves to that null property instead of the
        // page's backend and silently reads as undefined.
        appBackend: root.appBackend
        tokens: root.tokens
        icon: "movement"
        title: "Movement & camera"
        neonTag: "MOVEMENT"
        helpTip: FriendlyCopy.movementDetail() + "\n\n" + FriendlyCopy.fovDetail()

        readonly property bool moveChanged: root.appBackend.speedPct !== root.normalSpeedPct
                                            || root.appBackend.jumpPct !== root.normalJumpPct
        readonly property bool fovChanged: root.appBackend.fovDegrees !== root.normalFovDegrees
        // Installed, ready and applied are deliberately separate. Never call a
        // stale or mismatched game mod active merely because a file exists.
        // Active needs every changed value confirmed in the game
        // (Status.movementApplied, shared with the Dashboard row).
        readonly property bool applied: Status.movementApplied(root.appBackend)
        readonly property var chip: Status.movementChip(root.appBackend, root.movementStatus)
        status: chip[0]
        statusKind: chip[1]
        accentActive: applied
        subtitle: !root.appBackend.movementAvailable
                  ? "The movement game mod isn't available, so changes can't be applied."
                  : !root.appBackend.gameRunning
                    ? "Your settings are saved and apply when the game is running."
                    : applied || root.appBackend.nativeMovementReady
                      ? "Changes apply live while you drag."
                      : "Waiting for the game mod to confirm it is running on this game version."
        Layout.fillWidth: true

        // Interactive while the game mod is installed, even before it is
        // ready: the values are saved and apply once it runs. With the game
        // mod not available ("changes can't be applied") the sliders use the
        // disabled style. The backend publishes each actual slider change
        // through the native lease; an idle slider writes none.
        Ui.SbSliderField {
            objectName: "movementSpeedSlider"
            enabled: root.appBackend.movementAvailable
            tokens: root.tokens
            label: "Movement speed"
            rangeText: "50–300%"
            valueText: root.appBackend.speedPct + "%"
            from: 50; to: 300; stepSize: 5
            normalValue: root.normalSpeedPct
            value: root.appBackend.speedPct
            onMoved: root.appBackend.setSpeed(value / 100.0)
        }

        Ui.SbSliderField {
            objectName: "jumpHeightSlider"
            enabled: root.appBackend.movementAvailable
            tokens: root.tokens
            label: "Jump height"
            rangeText: "50–300%"
            valueText: root.appBackend.jumpPct + "%"
            from: 50; to: 300; stepSize: 5
            normalValue: root.normalJumpPct
            value: root.appBackend.jumpPct
            onMoved: root.appBackend.setJump(value / 100.0)
        }

        // Actual degrees, live on drag. The gameplay camera rests near 75;
        // higher numbers show more around Eve. Values above 100 stay
        // selectable but are marked experimental: some areas do not contain
        // complete scenery outside the normal camera view.
        Ui.SbSliderField {
            objectName: "fieldOfViewSlider"
            enabled: root.appBackend.movementAvailable
            tokens: root.tokens
            label: "Field of view"
            rangeText: "50–170°"
            experimentalText: "experimental above 100°"
            valueText: root.appBackend.fovDegrees + "°"
            from: 50; to: 170; stepSize: 1
            normalValue: root.normalFovDegrees
            experimentalFrom: 100
            value: root.appBackend.fovDegrees
            onMoved: root.appBackend.setFov(value)
        }

        // The one place the normal values are written, and the way back to
        // them in one click. The button shows only when a value differs.
        Item {
            objectName: "movementFooter"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredHeight: root.tokens ? root.tokens.btnHeight : 40
            implicitHeight: root.tokens ? root.tokens.btnHeight : 40

            Text {
                anchors.left: parent.left
                anchors.right: backToNormal.visible ? backToNormal.left : parent.right
                anchors.rightMargin: backToNormal.visible ? (root.tokens ? root.tokens.spaceMd : 16) : 0
                anchors.verticalCenter: parent.verticalCenter
                text: "Normal is 100% speed, 100% jump and 75°."
                textFormat: Text.PlainText
                color: root.tokens ? root.tokens.textMuted : "#7b8994"
                font.pixelSize: root.tokens ? root.tokens.fontHint : 13
                font.hintingPreference: root.tokens ? root.tokens.textHinting : Font.PreferFullHinting
                elide: Text.ElideRight
                maximumLineCount: 1
            }

            Ui.SbButton {
                id: backToNormal
                objectName: "movementBackToNormal"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                height: parent.height
                tokens: root.tokens
                iconName: "restart"
                text: "Back to normal"
                visible: movementCard.moveChanged || movementCard.fovChanged
                onClicked: {
                    root.appBackend.setSpeed(root.normalSpeedPct / 100.0)
                    root.appBackend.setJump(root.normalJumpPct / 100.0)
                    root.appBackend.setFov(root.normalFovDegrees)
                }
            }
        }
    }

    Ui.UpdateNotice {
        objectName: "gameplayUpdateNotice"
        tokens: root.tokens
        appBackend: root.appBackend
    }
}
