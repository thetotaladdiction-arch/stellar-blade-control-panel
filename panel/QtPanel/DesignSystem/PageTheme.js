.pragma library

function pageNeonColor(page, tokens) {
    if (!tokens) return "#42f0df"
    // Uniform cyan/teal accent across every page (no magenta/green/blue clashes).
    return tokens.neonCyan
}

function accent(tokens, page) {
    return pageNeonColor(page, tokens)
}

function loreCarousel(page) {
    var lines = {
        gameplay: [
            "Live tools while you control her — god mode, boss pins, movement.",
            "Angel of Xion. Blade drawn. City burning behind her.",
            "Every hit blocked is another second to save humanity.",
            "Pin the boss. Retry the fight. She does not know defeat."
        ],
        items: [
            "What the wasteland lost, Eve reclaims — one crate at a time.",
            "Tachy caches and nano cores — spoils of a dead world.",
            "Supply the Angel. The mission demands everything."
        ],
        settings: [
            "Tune the panel like Eve tunes her stance — precise, lethal, elegant.",
            "Xion's neon reflects in every window of this mod hub."
        ],
        support: [
            "Even angels need diagnostics. Keep the tools sharp.",
            "Logs and repairs — so Eve never falls to a broken script."
        ]
    }
    return lines[page] || lines.gameplay
}

function bannerMeta(page, tokens) {
    // Page titles match the sidebar names so the header always says where
    // you are; FriendlyCopy.pageSubtitle() adds one plain line under it.
    // No page has banner art (2.5.504 build 4 dropped the unused banner and
    // hero images from the bundle).
    var meta = {
        gameplay: {
            kicker: "",
            title: "Gameplay",
            subtitle: "Live tools while you control Eve"
        },
        items: {
            kicker: "",
            title: "Items & Money",
            subtitle: "Added through the game's own inventory request"
        },
        settings: {
            kicker: "",
            title: "Settings",
            subtitle: "Look, placement and the in-game overlay"
        },
        support: {
            kicker: "",
            title: "Support",
            subtitle: "Health checks, repairs, backups and logs"
        }
    }
    var base = meta[page] || meta.gameplay
    return {
        kicker: base.kicker,
        title: base.title,
        subtitle: base.subtitle,
        accent: accent(tokens, page)
    }
}

function signLabel(page) {
    if (page === "gameplay") return "LIVE"
    if (page === "items") return "GEAR"
    if (page === "settings") return "SYS"
    if (page === "support") return "HELP"
    return "MOD"
}

function sectionNeonTag(title) {
    var tags = {
        "God Mode": "GOD",
        "Boss Retry": "BOSS",
        "Game Session": "LIVE",
        "Movement": "MOVE",
        "Item catalog": "ITEMS",
        "Drop selected item": "DROP",
        "Money pickup": "MONEY",
        "Live Status": "HUB",
        "Appearance": "LOOK",
        "Window Position": "SCREEN",
        "Panel on screen": "SCREEN",
        "About this UI": "BUILD",
        "Install Health": "CHECK",
        "Reports & Saves": "DATA",
        "Activity Log": "LOG",
        "Patch Notes": "PATCH"
    }
    return tags[title] || ""
}

// Readable card titles for a card's identity tag, used when a card does not
// set its own title.
function sectionTitle(tag) {
    var titles = {
        "LIVE": "Game",
        "GOD": "God Mode",
        "BOSS": "Instant Boss Restart",
        "RETRY POINT": "Retry Point",
        "MOVEMENT": "Movement",
        "FOV": "Field of view",
        "ITEMS & MONEY": "Items & Money",
        "ITEMS": "Item catalog",
        "ADD": "Add Item",
        "MONEY": "Add Money"
    }
    return titles[String(tag || "")] || ""
}
