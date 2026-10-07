.pragma library

// The one line icon set (FINAL-VISUAL-SPEC.md section 6): a 24 px grid,
// 1.5 px stroke, square caps, mitred joins, no fills except the play
// triangle. SbIcon.qml draws these paths with a CurveRenderer Shape, so the
// colour is a plain binding (no tint effect) and edges stay sharp at 100 %
// and 150 %. Circles are written as two arcs because PathSvg takes path data
// only. Source: ICONS in ui-redesign/final/_build_final.py.

function circle(cx, cy, r) {
    return "M" + (cx - r) + " " + cy + "a" + r + " " + r + " 0 1 0 " + (2 * r) + " 0"
         + "a" + r + " " + r + " 0 1 0 " + (-2 * r) + " 0"
}

var paths = {
    // Navigation
    "dashboard": "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
    "gameplay": "M16.5 4H20v3.5L10.5 17 7 13.5zM5 12l7 7M7.5 16.5L4 20",
    "items": "M4 7.5L12 4l8 3.5v9L12 20l-8-3.5zM4 7.5l8 3.5 8-3.5M12 11v9",
    "settings": "M4 7h8M16 7h4M4 17h4M12 17h8M12 5h4v4h-4zM8 15h4v4H8z",
    "support": circle(12, 12, 8) + circle(12, 12, 3.5)
               + "M6.3 6.3l3.2 3.2M14.5 14.5l3.2 3.2M17.7 6.3l-3.2 3.2M9.5 14.5l-3.2 3.2",
    // Features
    "god": "M12 3.5l7 2.5v5.5c0 4.3-2.9 7.4-7 9-4.1-1.6-7-4.7-7-9V6zM9 12l2 2 4-4",
    "retry": "M6 21V4M6 4.5h11l-2.5 4 2.5 4H6",
    "boss": "M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4v4h4",
    "movement": "M5 6l6 6-6 6M12 6l6 6-6 6",
    // A bolt (Unlimited energy)
    "energy": "M13 3.5L5.5 13.5H11L10 20.5L18.5 10.5H13z",
    "overlay": "M3 4h18v12H3zM8 20h8M12 16v4M6.5 12.5l3-3 2.5 2 4.5-4.5",
    "panel": "M3 4h18v16H3zM3 8.5h18M14.5 8.5V20",
    "appearance": "M12 3l1.8 7.2L21 12l-7.2 1.8L12 21l-1.8-7.2L3 12l7.2-1.8z",
    // Actions and marks
    "refresh": "M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4v4h-4",
    "restart": "M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4v4h4",
    "chevronDown": "M6 9l6 6 6-6",
    "chevronUp": "M6 15l6-6 6 6",
    "chevronRight": "M9 6l6 6-6 6",
    "info": circle(12, 12, 8.5) + "M12 11v5.5M12 7.5v1",
    "play": "M8 5.5v13l10-6.5z",
    "stop": "M6 6h12v12H6z",
    "power": "M12 3.5v8M7 6.5a7.5 7.5 0 1 0 10 0",
    "check": "M5 12.5l4.5 4.5L19 7.5",
    "close": "M6 6l12 12M18 6L6 18",
    "search": circle(10.5, 10.5, 6) + "M15 15l5 5",
    "warning": "M12 4l9 16H3zM12 10v4.5M12 16.8v.4",
    "save": "M5 4h11l3 3v13H5zM8 4v5h7V4M8 20v-6h8v6",
    "folder": "M3 6h6l2 2h10v11H3z",
    "report": "M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7",
    // A coin with the game's diamond mark (Money card)
    "money": circle(12, 12, 8) + "M12 8.5l3 3.5-3 3.5-3-3.5z",
    // A list (Activity log) and a chip (Technical details)
    "log": "M4 6.5h2M9 6.5h11M4 12h2M9 12h11M4 17.5h2M9 17.5h11",
    "chip": "M7 7h10v10H7zM10 3.5V7M14 3.5V7M10 17v3.5M14 17v3.5M3.5 10H7M3.5 14H7M17 10h3.5M17 14h3.5"
}

// Old page / feature names and the mock's short names.
var aliases = {
    "dash": "dashboard", "sword": "gameplay", "sliders": "settings", "buoy": "support",
    "shield": "god", "flag": "retry", "move": "movement", "monitor": "overlay",
    "window": "panel", "star": "appearance", "down": "chevronDown", "up": "chevronUp",
    "right": "chevronRight", "x": "close", "warn": "warning",
    "godmode": "god", "retrypoint": "retry", "bossrestart": "boss", "fov": "movement",
    "coin": "money", "backup": "save"
}

var filled = { "play": true }

function resolve(name) {
    var key = String(name || "")
    if (paths[key] !== undefined)
        return key
    if (aliases[key] !== undefined)
        return aliases[key]
    return ""
}

function path(name) {
    var key = resolve(name)
    return key.length > 0 ? paths[key] : ""
}

function isFilled(name) {
    return filled[resolve(name)] === true
}

function has(name) {
    return resolve(name).length > 0
}
