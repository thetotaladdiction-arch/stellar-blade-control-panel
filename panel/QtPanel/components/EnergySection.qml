import QtQuick
import QtQuick.Layouts
import "../DesignSystem/FriendlyCopy.js" as FriendlyCopy
import "../DesignSystem/Status.js" as Status
import "." as Ui

Ui.SbCard {
    id: root

    // Unlimited Beta / Burst energy: two more switches of the God Mode game
    // mod. They work with God Mode on or off, so this is its own card, right
    // under God Mode. The verdict is the panel's status check of the game
    // mod's own fresh report (services/god_service.py energy_status):
    // {state, reason, available, betaActive, burstActive}.
    readonly property var energy: root.appBackend && root.appBackend.energyStatus
                                  ? root.appBackend.energyStatus : null
    // False while the installed game mod has no energy switches (an older
    // build, not installed, or it couldn't start): both rows are greyed and
    // read off, and the card's line says why.
    readonly property bool available: !!root.energy && root.energy.available === true
    readonly property var chip: Status.energyChip(root.energy)

    icon: "energy"
    title: "Unlimited energy"
    neonTag: "ENERGY"
    status: chip[0]
    statusKind: chip[1]
    helpTip: FriendlyCopy.energyDetail()
    accentActive: !!root.energy && root.energy.state === "active"

    // Card anatomy (spec 4.2), as on the God Mode card: title + chip, one
    // line saying what is happening (with the reason when it couldn't start),
    // then the switch rows. The header chip is the only verdict.
    subtitle: FriendlyCopy.energyLine(root.energy ? String(root.energy.reason) : "")

    // Rows carry their own 40 px rhythm and hairline.
    bodySpacing: 0

    // Compact 40 px rows (FINAL-VISUAL-SPEC.md 4.2); the first one starts
    // right under the card's line, as God Mode's row does.
    Ui.SettingsField {
        Layout.topMargin: -(root.tokens ? root.tokens.spaceSm : 12)
        tokens: root.tokens
        enabled: root.available
        label: "Unlimited Beta Energy"
        hasControl: true
        compactControl: true
        Ui.SbSwitch {
            id: energyBetaSwitch
            objectName: "energyBetaSwitch"
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            tokens: root.tokens
            checked: root.available && root.appBackend.energyBeta === true
            Accessible.name: "Unlimited Beta Energy"
            // Only a deliberate click changes the remembered switch, and
            // focus is released so a later Space press in the game cannot
            // toggle it again (the God Mode switch's rule).
            onClicked: {
                root.appBackend.setUnlimitedBeta(checked)
                energyBetaSwitch.focus = false
            }
        }
    }

    Ui.SettingsField {
        tokens: root.tokens
        enabled: root.available
        label: "Unlimited Burst Energy"
        hasControl: true
        compactControl: true
        showSeparator: false
        Ui.SbSwitch {
            id: energyBurstSwitch
            objectName: "energyBurstSwitch"
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            tokens: root.tokens
            checked: root.available && root.appBackend.energyBurst === true
            Accessible.name: "Unlimited Burst Energy"
            onClicked: {
                root.appBackend.setUnlimitedBurst(checked)
                energyBurstSwitch.focus = false
            }
        }
    }
}
