.pragma library

// Player-facing sentences. One short line is shown on the card; the longer
// explanation lives behind the (i) help tip. No internal words (see
// tests/test_user_copy.py).

function godModeDetail(on) {
    return "God Mode on requests protection; Active means the game mod reports protection is running. In our tests it stopped normal hits. Falls, bombs and some scripted deaths are not fully verified. "
         + "The game mod checks that it is really Eve when protection is requested, after a game start "
         + "and when its player or stage changes. Eve can take damage until Active appears. "
         + "There is no guaranteed time or first hit for the check to pass. "
         + "Turning God Mode off and on starts the check again.\n\n"
         + "Turn it off before Instant Boss Restart so Eve can die normally."
}

function godModeStatusActive() {
    return "Protection is running."
}

function godModeStatusInactive() {
    return "Eve takes damage normally."
}

function godModeStatusTurningOn() {
    return "Protection is requested. Eve can take damage until the card shows Active."
}

function godModeStatusNextLaunch() {
    return "Protection is requested for the next game session. Wait for Active before relying on it."
}

function godModeStatusModOff() {
    return "The God Mode game mod is not installed or not turned on."
}

function godModeStatusUnavailable() {
    return "Run One-Click Repair on Support with the game closed."
}

function godModeStatusNeedsUpdate() {
    return "The game was updated. God Mode needs an updated game mod."
}

// Unlimited energy card (Gameplay, under God Mode). What it does, without
// promising more: a bar that is empty stays empty until the first gain.
function energyDetail() {
    return "While a switch is on, that energy bar does not go down, so its skills stay ready. "
         + "An empty bar fills on its next normal energy gain. Only Eve is affected. "
         + "It works with God Mode on or off.\n\n"
         + "Active means the game mod reports it is running. The Burst switch does not unlock "
         + "Burst Energy; that still happens in the game."
}

// The card's one line. The reason is the code from the panel's status check
// (services/god_service.py energy_status); the game mod's own reason words
// stay in the activity log on Support.
function energyLine(reason) {
    if (reason === "off") return "Skills use energy normally."
    if (reason === "active") return "The bar fills on its next normal energy gain, then stays full."
    if (reason === "active-burst-locked") return "Beta Energy is on. Burst Energy isn't unlocked in this save yet."
    if (reason === "burst-locked") return "Burst Energy isn't unlocked in this save yet."
    if (reason === "game-closed") return "Starts when Stellar Blade is running."
    if (reason === "no-report") return "Waiting for the game mod to report in."
    if (reason === "switching-on") return "Switching on."
    if (reason === "switching-off") return "Switching off."
    if (reason === "waiting-for-eve") return "Waiting for Eve. Load your save and it switches on by itself."
    if (reason === "stopped") return "It stopped itself after a problem in the game. Restart Stellar Blade to use it again."
    if (reason === "identity-check-failed") return "It couldn't confirm Eve, so it stays off. Restart Stellar Blade to try again."
    if (reason === "hooks-not-installed") return "The game mod didn't start in this game session. Run One-Click Repair on Support with the game closed."
    if (reason === "unknown-report") return "The game mod reported something this panel doesn't know. Update the Mod Suite."
    if (reason === "mod-problem") return "The God Mode game mod couldn't start safely. Run One-Click Repair on Support with the game closed."
    if (reason === "mod-off") return "The God Mode game mod is not installed or not turned on."
    if (reason === "mod-older") return "The installed God Mode game mod is older than this feature. Update the Mod Suite to use it."
    if (reason === "mod-unknown") return "The installed game mod is newer than this panel. Update the Mod Suite to use it."
    if (reason === "not-supported") return "Not supported on this game version. It needs an updated game mod."
    if (reason === "game-updated") return "The game was updated. This needs an updated game mod."
    return "Checking the game mod."
}

function gameSessionSummary() {
    return "Start, restart or quit Stellar Blade."
}

function gameSessionDetail() {
    return "Start or quit Stellar Blade from here. Most tools only work after the game is "
         + "running and you are controlling Eve (not menus or death screens).\n\n"
         + "Safe Reset and Force Quit Game are on Support, for when something went wrong."
}

// The switch's own line on Gameplay.
function bossSwitchHint() {
    return "Press Revive after dying in a supported boss fight to restart it."
}

function bossRetryDetail(supportsStory) {
    var scope = supportsStory
              ? "Works with supported Boss Challenge fights and boss fights in the main story once you have entered them. "
              : "Works in Boss Challenge fights. Other deaths use normal respawn. "
    return "Press Revive after dying in a supported boss fight. The screen goes black while the fight resets. "
         + scope + "If a safe restart is unavailable, the game respawns you normally."
}

function retryPointDetail() {
    return "Separate from Instant Boss Restart. Set Point saves Eve's current spot in the loaded area. "
         + "Return asks the game to warp her back once, then checks that it worked. Loading or changing "
         + "areas makes the old point unusable until you are back in that same area."
}

function movementDetail() {
    return "How fast Eve moves and how high she jumps, where 100% is normal. Changes happen live as you drag. Your original values return when the panel closes, and the game is never permanently changed.";
}

function fovDetail() {
    return "The gameplay camera's field of view in degrees. It changes live as you drag and is remembered "
         + "next time. The full 50-170 degree range is available; values above 100 can show missing "
         + "scenery or strong stretching at the edges."
}

function dashGameDetail() {
    return "Whether Stellar Blade is running. Start game opens it."
}

function dashModDetail() {
    return "Shows how the panel is connected to the game. Either state is normal and safe."
}

function dashGodDetail() {
    return "Green once the game mod reports protection is running. The switch turns God Mode on or off."
}

function dashBossDetail() {
    return "Instant Boss Restart. Ready: press Revive in a supported Boss Challenge or learned story boss fight. "
         + "Restarting: the screen is black while the fight resets. Other fights or Off: normal respawn."
}

function dashRetryPointDetail() {
    return "Set Point saves Eve's spot in the loaded area. Once a point is saved, Return takes her back."
}

function dashSpawnDetail() {
    return "Whether Items & Money can add items right now. The game mod checks again after session changes, when you open Items & Money and while the page stays open."
}

function dashMoveDetail() {
    return "Whether your movement speed, jump height and field of view are applied in game."
}

function dashAtAGlanceSummary() {
    return "What each feature is doing, with one quick action each."
}

function dashAtAGlanceDetail() {
    return "One line per feature: what it is doing and one quick action. Click a name to open its "
         + "page for every setting."
}

function pageSubtitle(page) {
    if (page === "gameplay") return "God Mode, Retry Point, boss restarts, movement and camera."
    if (page === "items") return "Add items through the game's own inventory. Saves are never edited."
    if (page === "settings") return "The panel and the in-game overlay."
    if (page === "support") return "Fix problems, back up saves and share a report."
    return ""
}

function itemsIntroSummary() {
    return "Items are added through the game's own inventory, one click at a time. Saves are never edited."
}

function itemsIntroDetail() {
    return "Each click sends one short request that expires after about two seconds. If the game mod "
         + "can't confirm it is safe right now, the button stays off and nothing is changed. Money and "
         + "inventory values are never edited directly."
}

function settingsPanelPlacementDetail() {
    return "Choose where this panel appears on your monitor: Left side, Right side, Center, "
         + "Top, Bottom, Maximized, or Free (move it yourself). Your choice is remembered."
}
