-- SBInstantBossRestart v0.5.2: Boss Challenge and learned story boss restarts.
-- The panel switch controls both modes. The player's own Revive starts one
-- attempt: black -> normal resurrection -> game-owned warp -> intro or fight.
-- Story requires a catalog INTRO or observed Nest014 RETRY entry in this life
-- and a learned point inside its box. Nest waits for its game-selected native
-- retry cinematic; other RETRY/NONE, revival items and map loads stay normal.
-- Missing objects, re-arm or intro fall back to the game's normal respawn.
-- Exact supported game build only; all object work is on the game thread.
-- No input or save-file edits. settings/status/learned records and the bounded
-- session log live beside Scripts. story-probe.txt enables developer detail,
-- teleport requests, cost measurements and pause controls only.

local THIS_DIR = (debug.getinfo(1, "S").source or ""):match("^@?(.*[\\/])") or ""
local MOD_DIR = THIS_DIR .. "../"
local EXE = THIS_DIR .. "../../../../SB-Win64-Shipping.exe"
local WANT_SIZE, WANT_TDS = 359186432, 0x6A6A3B74
local VERSION = "0.5.2"
-- SHA256 of these exact source bytes with this one BUILD_SHA value set to 64 zeroes.
local BUILD_SHA = "F20823E14FFF17E794C03D68EDB7B0B9909083324BAED5380DBC3C2CCC5FDA7D"
local STATUS_FILE = MOD_DIR .. "status.txt"
local SETTINGS_FILE = MOD_DIR .. "settings.txt"
local LOG_FILE = MOD_DIR .. "SBInstantBossRestart.log"
local LOG_PREVIOUS = MOD_DIR .. "SBInstantBossRestart.previous.log"
local LOG_MAX_BYTES = 4 * 1024 * 1024
-- story probe switch (developer only): read once at load
local PROBE_FILE = MOD_DIR .. "story-probe.txt"
local PROBE_ON = false
do local pf = io.open(PROBE_FILE, "r"); if pf then pf:close(); PROBE_ON = true end end
local SPX = {}   -- story core entry points; diagnostics are marker-gated

-- ---------------------------------------------------------------- status for the panel (status.txt)
-- Written at load and whenever a value changes, never on a timer. "end=1" closes a complete file.
local ST = { state = "starting", enabled = "1", phase = "idle", restarts = 0, last = "none", last_at = 0,
    loaded = os.time() }
local statusBody = nil
local function writeStatus()
    local body = string.format("version=%s\nbuild=%s\nstate=%s\nenabled=%s\nphase=%s\nrestarts=%d\nlast=%s\nlast_at=%d\nloaded=%d\nend=1\n",
        VERSION, BUILD_SHA:sub(1, 12), ST.state, ST.enabled, ST.phase, ST.restarts, ST.last, ST.last_at, ST.loaded)
    if body == statusBody then return end
    local tmp = STATUS_FILE .. ".tmp"
    local f = io.open(tmp, "w")
    if not f then return end
    f:write(body)
    f:close()
    os.remove(STATUS_FILE)
    if os.rename(tmp, STATUS_FILE) then statusBody = body else os.remove(tmp) end
end
-- the switch alone (the rest of settings.txt is read at each death, see loadCfg)
local function readEnabled()
    local f = io.open(SETTINGS_FILE, "r")
    if not f then return "1" end
    local on = "1"
    for line in f:lines() do
        local v = line:match("^%s*enabled%s*=%s*([^%s#]*)")
        if v then on = (v == "0") and "0" or "1" end
    end
    f:close()
    return on
end
ST.enabled = readEnabled()

-- ---------------------------------------------------------------- version gate
local function exeIdentity()
    local f = io.open(EXE, "rb")
    if not f then return nil, nil end
    local size = f:seek("end")
    f:seek("set", 0x3C)
    local lfanew = string.unpack("<I4", f:read(4))
    f:seek("set", lfanew + 8)
    local tds = string.unpack("<I4", f:read(4))
    f:close()
    return size, tds
end
local okId, EXE_SIZE, EXE_TDS = pcall(exeIdentity)
if not okId or EXE_SIZE ~= WANT_SIZE or EXE_TDS ~= WANT_TDS then
    ST.state = (okId and EXE_SIZE ~= nil) and "needs_update" or "no_game_file"
    writeStatus()
    print(string.format("[SBInstantBossRestart] %s (size=%s tds=%s); doing nothing\n", ST.state,
        tostring(EXE_SIZE), EXE_TDS and string.format("0x%08X", EXE_TDS) or "nil"))
    return
end

-- ---------------------------------------------------------------- log
local t0s = os.time()
local spinEnd = os.clock() + 1.2
while os.time() == t0s and os.clock() < spinEnd do end
local baseWall, baseClk = os.time(), os.clock()
os.remove(LOG_PREVIOUS)
os.rename(LOG_FILE, LOG_PREVIOUS)
local logf = io.open(LOG_FILE, "w")
local logBytes = 0
local seq = 0
local function now() return os.clock() end
local function stamp()
    local c = os.clock()
    local w = baseWall + (c - baseClk)
    local s = math.floor(w)
    return string.format("%s.%03d", os.date("%H:%M:%S", s), math.floor((w - s) * 1000))
end
local function log(...)
    local parts = {}
    for i = 1, select("#", ...) do parts[#parts + 1] = tostring((select(i, ...))) end
    seq = seq + 1
    if logf then
        local line = string.format("%s #%05d %s\n", stamp(), seq, table.concat(parts, " "))
        logBytes = logBytes + #line
        if logBytes > LOG_MAX_BYTES then
            logf:write("log size limit reached; later lines are not written\n")
            logf:close()
            logf = nil
            return
        end
        logf:write(line)
        logf:flush()
    end
end
local function evt(name, fmt, ...)
    log("EVT " .. name .. " " .. (fmt and string.format(fmt, ...) or ""))
end
log(string.format("SBInstantBossRestart %s loaded; exe size=%d tds=0x%08X OK; epoch=%d", VERSION, EXE_SIZE, EXE_TDS, baseWall))
print("[SBInstantBossRestart] " .. VERSION .. " loaded\n")

-- ---------------------------------------------------------------- settings (settings.txt, re-read at each death)
-- Only known keys; a number that does not read as a number keeps its default.
local cfg = {}
local function loadCfg()
    local c = { enabled = "1", intro = "warp", black = "1", hide_hud = "1", fade_out = "0.35", fade_in = "0.5",
        fade_priority = "100000", revive_timeout = "12.0", settle = "0.9", intro_timeout = "4.0",
        cine_wait = "1.5", hold_max = "14.0" }
    local f = io.open(SETTINGS_FILE, "r")
    if f then
        for line in f:lines() do
            local k, v = line:match("^%s*([%w_]+)%s*=%s*([^%s#]*)")
            if k and c[k] ~= nil and (tonumber(c[k]) == nil or tonumber(v) ~= nil) then c[k] = v end
        end
        f:close()
    end
    c.enabled = (c.enabled == "0") and "0" or "1"
    cfg = c
    ST.enabled = c.enabled
end
loadCfg()

-- ---------------------------------------------------------------- helpers
local function valid(o)
    local ok, v = pcall(function() return o ~= nil and o:IsValid() end)
    return ok and v
end
local function fullName(o)
    local ok, v = pcall(function() return o:GetFullName() end)
    return ok and v or "?"
end
local function v3(v)
    if not v then return nil end
    local ok, r = pcall(function() return { X = v.X + 0.0, Y = v.Y + 0.0, Z = v.Z + 0.0 } end)
    return ok and r or nil
end
local function addr(o)
    local ok, a = pcall(function() return o:GetAddress() end)
    return ok and a or nil
end
local function same(a, b)
    if a == nil or b == nil then return false end
    local x, y = addr(a), addr(b)
    return x ~= nil and x == y
end
local function fv(p) return p and string.format("(%.1f,%.1f,%.1f)", p.X, p.Y, p.Z) or "nil" end
local function dist(a, b)
    if not a or not b then return 1e30 end
    local dx, dy, dz = a.X - b.X, a.Y - b.Y, a.Z - b.Z
    return math.sqrt(dx * dx + dy * dy + dz * dz)
end
local function shortName(o) local fn = fullName(o); return fn:match("%.([%w_]+)$") or fn end

-- ---------------------------------------------------------------- live objects, found fresh every tick
-- After unload/collection even IsValid can read freed memory. The player
-- controller and its pawn/camera are reached each tick from the process-lived
-- engine. Current-world trigger/character/widget caches avoid costly world
-- scans; map reset, actor EndPlay and death-widget Destruct drop references.
local engine = nil
local function getPC()
    if not engine then
        local e = FindFirstOf("GameEngine")
        if valid(e) then engine = e else return nil end
    end
    local ok, pc = pcall(function() return engine.GameViewport.GameInstance.LocalPlayers[1].PlayerController end)
    if ok and valid(pc) then return pc end
    return nil
end
local function getPawn(pc)
    pc = pc or getPC()
    if not pc then return nil end
    local ok, p = pcall(function() return pc.Pawn end)
    if ok and valid(p) then return p end
    return nil
end
local function getPS(pc)
    pc = pc or getPC()
    if not pc then return nil end
    local ok, p = pcall(function() return pc.PlayerState end)
    if ok and valid(p) then return p end
    return nil
end
local function getPCM(pc)
    pc = pc or getPC()
    if not pc then return nil end
    local ok, m = pcall(function() return pc.PlayerCameraManager end)
    if ok and valid(m) then return m end
    return nil
end
local function actorLoc(a)
    local ok, l = pcall(function() return a:K2_GetActorLocation() end)
    return ok and v3(l) or nil
end
local function actorYaw(a)
    local ok, r = pcall(function() return a:K2_GetActorRotation().Yaw end)
    return ok and r or 0.0
end
local function battleState(a)
    local ok, b = pcall(function() return a.bBattleState end)
    return ok and tostring(b) or "?"
end

-- Combat discovery uses only cached characters after the initial quiet scan.
-- A catalog entry also holds discovery until combat has actually ended.
local combatObjects, combatEntered, combatSeen = {}, false, false
local function fighting()
    local live = battleState(getPawn()) == "true"
    for _, b in pairs(combatObjects) do
        if valid(b.o) and addr(b.o) == b.a and battleState(b.o) == "true" then live = true end
    end
    if live then combatSeen = true elseif combatSeen then combatEntered, combatSeen = false, false end
    return live or combatEntered
end
local function cacheCombat(center)
    if fighting() then return end
    for _, b in ipairs(FindAllOf("SBCharacter") or {}) do
        if valid(b) and not fullName(b):find("Default__", 1, true) and dist(center, actorLoc(b)) < 20000 then
            local a = addr(b)
            if a then combatObjects[a] = { o = b, a = a } end
        end
    end
end
-- Only the observed Nest entry trigger is supported among RETRY catalog rows.
-- The game chooses its native retry variant; the mod never starts a theater directly.
local NEST_RETRY_ALIAS = "Nest_10_ZTrigger_014"
local STORY_INTRO_NAMES = {
    DED10_ZTrigger_103 = { ["MV_DED01_EliteNative_Entrance_Master"] = true },
    DED10_ZTrigger_016 = { ["MV_DED01_EliteNative_Entrance_Master"] = true },
    DED20_ZTrigger_011 = { ["MV_DED02_Elite_GrubShooter_Master"] = true },
    ZT_EQ_DED_Q01_M01 = { ["MV_DED03_BetaNative_Intro_01_QTE"] = true, ["MV_DED03_BetaNative_Intro_01_QTE_Master"] = true },
    AYL_06_ZTrigger_001 = { ["MV_AYL06_Maelstrom"] = true },
    ATL_03_ZTrigger_009 = { ["MV_ATL03_OuterwallMove"] = true },
    ME_03_ZTrigger_004 = { ["MV_ME03_EliteNative_Entrance"] = true },
    ME_05_ZTrigger_009 = { ["MV_ME05_EliteNative_Entrance_Transit"] = true, ["MV_ME05_EliteNative_Entrance_Main"] = true },
    ME_06_ZTrigger_024 = { ["MV_ME06_Tachy_Entrance_Master"] = true },
    SE_06_ZTrigger_005 = { ["MV_SE06_LobbyEliteSpawn_Main"] = true },
    SE_08_ZTrigger_002 = { ["MV_SE08_PassengerElevatorcelingCollapse_After"] = true },
    SE_10_ZTrigger_001 = { ["MV_SE10_AlphaNative_Entrance_Master"] = true },
    Xion_21_ZTrigger_001 = { ["MV_Xion06_RavenAppearance"] = true },
    WLA_10_ZTrigger_016 = { ["MV_Nest_Intro"] = true },
    WLA_40_ZTrigger_031 = { ["MV_WLA40_BruteIntro_Main"] = true },
    WLA_40_ZTrigger_035 = { ["MV_Quest_Sub_033_Gorilla"] = true },
    WLA_40_ZTrigger_065 = { ["MV_WLA40_GrubShooter_Intro"] = true },
    WLB_20_ZTrigger_005 = { ["MV_TowerSawshark"] = true, ["MV_TowerSawshark_Master"] = true },
    WLB_30_ZTrigger_012 = { ["MV_WLB30_Behemoth_Entrance"] = true },
    WLB_50_ZTrigger_010 = { ["MV_WLB50_Abaddon"] = true },
}
-- Karakuri: the game creates this entrance object whenever the trigger re-arms (map load and every
-- respawn zone reset, Eve at the camp), not when Eve enters. Its creation is neither native playback
-- nor entry proof; a restart warp is followed by no new object.
local ARM_CREATED_ENTRANCE = { SE_08_ZTrigger_002 = true }
local NATIVE_FIGHT_ALIAS = "DED40_ZTrigger_026"
local NATIVE_FIGHT_WORLD = "/Game/Art/BG/WorldMap/Level_P/F01.F01"
local function storyRestartSupported(alias, c)
    return c and ((c.mode == "INTRO" and STORY_INTRO_NAMES[alias] ~= nil) or (c.mode == "RETRY" and alias == NEST_RETRY_ALIAS)
        or (c.mode == "FIGHT" and alias == NATIVE_FIGHT_ALIAS))
end
local function nestRetryIntro(name)
    -- Live sequence objects add a 32-hex identity suffix; accept no other suffix.
    local baseName, suffix = name:match("^(MV_Nest_Retry_[%w]+_Battle)_([%x]+)$")
    if suffix and #suffix == 32 then name = baseName end
    return name == "MV_Nest_Retry_Exosuit_Battle" or name == "MV_Nest_Retry_Elder_Battle"
        or name == "MV_Nest_Retry_Elder2_Battle"
end
-- Native Phase2 may relocate Eve after completion; this is arena evidence, never a scene selector.
local function nestArenaIntro(name)
    if nestRetryIntro(name) then return true end
    local baseName, suffix = name:match("^(MV_Nest_BattleAdam_Phase2_Master)_([%x]+)$")
    if suffix and #suffix == 32 then name = baseName end
    return name == "MV_Nest_BattleAdam_Phase2_Master"
end
local STORY_LEARN_FORMAT = "story-intro-v1"
local function storyIntroName(name)
    if type(name) ~= "string" then return nil end
    local short = name:match("^LevelSequencePlayer /Game/Art/BG/WorldMap/[^:]+:PersistentLevel%.([%w_]+)%.AnimationPlayer$") or name
    if not short:match("^[%w_]+$") then return nil end
    local base, suffix = short:match("^(.-)_([%x]+)$")
    if suffix and #suffix == 32 then short = base end
    return short
end
local function storyIntroMatches(alias, name)
    local short = storyIntroName(name)
    if not short then return false end
    if alias == NEST_RETRY_ALIAS then return nestRetryIntro(short) end
    local names = STORY_INTRO_NAMES[alias]
    if names ~= nil and ARM_CREATED_ENTRANCE[alias] then
        -- Re-created level objects may receive a numeric instance suffix; this remains arm evidence only.
        local placed = short:match("^(.+)_%d+$")
        if placed and names[placed] == true then return true end
    end
    return names ~= nil and names[short] == true
end
local function storyRecordValid(alias, r)
    if type(r) ~= "table" or r.format ~= STORY_LEARN_FORMAT or r.alias ~= alias or r.bind ~= "story" or type(r.point) ~= "table" then return false end
    local function finite(v) return type(v) == "number" and v == v and math.abs(v) < 1e9 end
    if not finite(r.point.X) or not finite(r.point.Y) or not finite(r.point.Z) or not finite(r.yaw) or
        not finite(r.armed) or r.armed < 0 or r.armed % 1 ~= 0 then return false end
    if alias == NEST_RETRY_ALIAS then return r.armed == 1 and (r.intro == "trigger-entry" or storyIntroMatches(alias, r.intro)) end
    if alias == "SE_10_ZTrigger_001" and r.armed ~= 0 then return false end
    return storyIntroMatches(alias, r.intro)
end
local function bossIntro(fn)
    local lower = fn:lower()
    return fn:find("/Game/", 1, true) and fn:find("MV_", 1, true)
        and not fn:find("Default__", 1, true) and not lower:find("/ui/", 1, true)
        and not lower:match("[_/%.]ui[_/%.]")
        and not lower:find("menu", 1, true) and not lower:find("studio", 1, true)
end

-- ---------------------------------------------------------------- death widget: values only
-- RefreshState supplies plain state values and a current-world widget cache.
-- The cache is dropped at Destruct and map load.
local W = { st = nil, bc = nil, at = -1, probeUntil = -1, probeAt = -10 }
-- after a map load (and when the mod starts) the widget is read a few times through a fresh
-- FindAllOf until the widget is cached, Boss Challenge is reported, or 20 s
-- pass. No discovery scan runs while combat is active.
local function probeWidget()
    local t = os.clock()
    if t > W.probeUntil or W.bc == true or t - W.probeAt < 1.0 then return end
    W.probeAt = t
    -- the widget found once is re-read through the kept object (valid + same address); a full
    -- scan (~40 ms in a story map) only when there is none yet
    if W.o and valid(W.o) and addr(W.o) == W.oa then
        local ok, st, bc = pcall(function() return W.o.CurrentState, W.o.bBossChallengeMode end)
        if ok and st ~= nil then W.st, W.bc = st, bc end
        return
    end
    W.o, W.oa = nil, nil
    if fighting() then return end
    for _, w in ipairs(FindAllOf("WB_MainHUD_Dead_C") or {}) do
        local fn = fullName(w)
        if valid(w) and not fn:find("Default__", 1, true) and fn:find("/Engine/Transient", 1, true) then
            local ok, st, bc = pcall(function() return w.CurrentState, w.bBossChallengeMode end)
            if ok and st ~= nil then W.st, W.bc, W.o, W.oa = st, bc, w, addr(w) end
        end
    end
end
local function readW(w)
    local ok, s, bc = pcall(function() return w.CurrentState, w.bBossChallengeMode end)
    if ok then return s, bc end
    return nil, nil
end

-- ---------------------------------------------------------------- zone triggers (Boss Challenge arenas only)
-- Trigger actors are cached for the current world, dropped on EndPlay, Exit
-- and map load. Combat discovery uses cached objects only.
local trigs, trigListAt = {}, -100
local curSample = { id = 0 }   -- Eve's position sample of this tick, taken BEFORE the trigger poll
local fireEvents = {}          -- {t, key, kind, sid}
local function trigKey(t) local fn = fullName(t); return fn:match("PersistentLevel%.([%w_]+)$") or fn end
local function readTrig(t)
    local ok, r = pcall(function()
        return {
            alias = t.TriggerAlias:ToString(), bind = t.BindZoneAlias:ToString(),
            count = t.InitialDoingCount, pending = t.bPendingCheck, active = t.bActiveTrigger,
        }
    end)
    return ok and r or nil
end
local function trigObj(e)
    if not e or not e.o then return nil end
    if valid(e.o) then return e.o end
    e.o = nil
    return nil
end
local learnedMap = {}  -- alias -> { alias, bind, point, yaw, from, at }
local function learnedFile(alias) return MOD_DIR .. "learned-" .. alias:gsub("[^%w_%-]", "_") .. ".txt" end
local function loadLearned(e)
    if learnedMap[e.alias] then return end
    local f = io.open(learnedFile(e.alias), "r")
    if not f then return end
    local s = f:read("a"); f:close()
    local x, y, z, yaw = s:match("point=([%-%d%.]+),([%-%d%.]+),([%-%d%.]+) yaw=([%-%d%.]+)")
    if x then
        local L = { alias = e.alias, bind = e.bind, point = { X = tonumber(x), Y = tonumber(y), Z = tonumber(z) }, yaw = tonumber(yaw), from = "file", at = -1 }
        learnedMap[e.alias] = L
        evt("LEARN_LOADED", "trigger=%s alias=%s point=%s yaw=%.1f", e.key, e.alias, fv(L.point), L.yaw)
    end
end
local function dropTriggers(why)
    local n = 0
    for _ in pairs(trigs) do n = n + 1 end
    if n > 0 then log(string.format("triggers dropped (%d): %s", n, why)) end
    trigs = {}
    trigListAt = now()
end
local function refreshTrigList(center)
    if fighting() then return end
    trigListAt = now()
    cacheCombat(center)
    for _, t in ipairs(FindAllOf("SBZoneTriggerActor") or {}) do
        local fn = fullName(t)
        if valid(t) and not fn:find("Default__", 1, true) then
            local r = readTrig(t)
            local loc = actorLoc(t)
            if r and r.bind ~= "None" and loc and (not center or dist(loc, center) < 30000) then
                local k = trigKey(t)
                local e = trigs[k]
                if not e or e.a ~= addr(t) or not trigObj(e) then
                    local ext = nil
                    pcall(function() ext = v3(t.BoxExtent) end)
                    local sc = { X = 1, Y = 1, Z = 1 }
                    pcall(function() sc = v3(t:GetActorScale3D()) or sc end)
                    trigs[k] = { o = t, a = addr(t), key = k, full = fn, alias = r.alias, bind = r.bind, loc = loc,
                        yaw = actorYaw(t), ext = ext, scale = sc, count = r.count, pending = r.pending }
                    log(string.format("trigger tracked %s alias=%s bind=%s loc=%s yaw=%.1f ext=%s scale=%s count=%s pending=%s active=%s",
                        k, r.alias, r.bind, fv(loc), actorYaw(t), fv(ext), fv(sc), tostring(r.count), tostring(r.pending), tostring(r.active)))
                    loadLearned(trigs[k])
                end
            end
        end
    end
end
local function pollTrigs()
    for k, e in pairs(trigs) do
        local o = trigObj(e)
        if not o then
            log("trigger gone " .. k); trigs[k] = nil
        else
            local r = readTrig(o)
            if r then
                if r.count ~= e.count or r.pending ~= e.pending then
                    local kind = nil
                    if r.count < e.count then kind = "count-drop" elseif e.pending and not r.pending then kind = "pending-done" end
                    log(string.format("TRIG %s alias=%s count %s->%s pending %s->%s", k, e.alias,
                        tostring(e.count), tostring(r.count), tostring(e.pending), tostring(r.pending)))
                    if kind then fireEvents[#fireEvents + 1] = { t = now(), key = k, kind = kind, sid = curSample.id } end
                    e.count, e.pending = r.count, r.pending
                end
            end
        end
    end
end
local function trigSnapshot()
    local out = {}
    for k, e in pairs(trigs) do out[#out + 1] = string.format("%s[%s c=%s p=%s]", k, e.alias, tostring(e.count), tostring(e.pending)) end
    table.sort(out)
    return table.concat(out, " ")
end
local function insideBox(e, p, margin)
    if not e or not e.ext or not p then return false end
    margin = margin or 0
    local dx, dy, dz = p.X - e.loc.X, p.Y - e.loc.Y, p.Z - e.loc.Z
    local a = math.rad(-(e.yaw or 0))
    local lx = dx * math.cos(a) - dy * math.sin(a)
    local ly = dx * math.sin(a) + dy * math.cos(a)
    -- Captured BoxExtent already includes actor scale; do not scale it twice.
    local sx, sy, sz = e.ext.X, e.ext.Y, e.ext.Z
    -- Preserve the requested inset without shaving more than 2% off a thin axis.
    local mx, my, mz = math.min(margin, sx * 0.02), math.min(margin, sy * 0.02), math.min(margin, sz * 0.02)
    return math.abs(lx) <= sx - mx and math.abs(ly) <= sy - my and math.abs(dz) <= sz - mz
end
pcall(RegisterHook, "/Script/Engine.Actor:ReceiveEndPlay", function(ctx)
    local a = nil
    pcall(function() a = addr(ctx:get()) end)
    if not a then return end
    for k, e in pairs(trigs) do
        if e.a == a then e.o = nil; trigs[k] = nil; log("trigger end play " .. k) end
    end
    combatObjects[a] = nil
    if SPX.endPlay then pcall(SPX.endPlay, a) end
end)

-- ---------------------------------------------------------------- Eve position ring (plain values)
local ring, sampleId = {}, 0
local function pushRing(p, yaw)
    sampleId = sampleId + 1
    ring[#ring + 1] = { t = now(), p = p, yaw = yaw, id = sampleId }
    if #ring > 900 then table.remove(ring, 1) end
end

-- ---------------------------------------------------------------- intro detection + learning
local introEvents = {}
local function learnFromIntro(ie)
    -- the trigger whose doing count dropped closest to the intro sequence creation
    local best, bestD = nil, 1e9
    for _, fe in ipairs(fireEvents) do
        local d = math.abs(fe.t - ie.t)
        if fe.t <= ie.t + 1.0 and fe.t >= ie.t - 2.5 then
            local score = d + (fe.kind == "count-drop" and 0 or 0.5)
            if score < bestD then best, bestD = fe, score end
        end
    end
    if not best then log("learn: no trigger fire near intro " .. ie.name) return end
    local e = trigs[best.key]
    if not e then return end
    -- Eve's position when the trigger fired. Samples are taken every tick before the trigger poll:
    -- the sample of the detection tick (best.sid) may already be moved by the intro sequence (it put
    -- Eve at the stair top once, and that point never fires the trigger), so the last sample BEFORE
    -- the detection tick is used; the detection-tick sample only when it continues her walk.
    local point, yaw, how = nil, nil, nil
    local pre, post
    for i = #ring, 1, -1 do
        if ring[i].id < best.sid then pre = ring[i]; post = ring[i + 1]; break end
    end
    local trail = {}
    for i = #ring, 1, -1 do
        local s = ring[i]
        if s.id <= best.sid + 3 and s.id >= best.sid - 3 then table.insert(trail, 1, string.format("%d:%s", s.id - best.sid, fv(s.p))) end
    end
    log("learn: samples around the fire " .. table.concat(trail, " "))
    -- Native BC entry can fire at the box edge; use the captured bounds for learning and replay.
    if pre and insideBox(e, pre.p, 0) then point, yaw, how = pre.p, pre.yaw, "pre-fire"
    elseif pre and post and post.id == best.sid and dist(pre.p, post.p) < 60 and insideBox(e, post.p, 0) then point, yaw, how = post.p, post.yaw, "fire-tick"
    else
        for i = #ring, 1, -1 do
            local s = ring[i]
            if s.id < best.sid and s.t >= best.t - 2.5 and insideBox(e, s.p, 0) then point, yaw, how = s.p, s.yaw, "last-inside" break end
        end
    end
    if not point then log("learn: trigger " .. e.key .. " fired but no pre-fire Eve sample inside its box") return end
    local L = { alias = e.alias, bind = e.bind, point = point, yaw = yaw or 0.0, from = "walk-in", at = now() }
    learnedMap[e.alias] = L
    evt("LEARN", "intro=%s trigger=%s alias=%s fire=%s dt=%.2f point=%s yaw=%.1f sample=%s", ie.name, e.key, e.alias, best.kind,
        best.t - ie.t, fv(point), L.yaw, how)
    local f = io.open(learnedFile(e.alias), "w")
    if f then f:write(string.format("trigger=%s alias=%s bind=%s point=%.3f,%.3f,%.3f yaw=%.3f intro=%s\n", e.key, e.alias, e.bind,
        point.X, point.Y, point.Z, L.yaw, ie.name)); f:close() end
end

pcall(function()
    NotifyOnNewObject("/Script/LevelSequence.LevelSequencePlayer", function(o)
        local stamp = SPX.stalkerCameraStamp and SPX.stalkerCameraStamp()
        local fn = fullName(o)
        if bossIntro(fn) then
            local ie = { t = now(), name = fn:match("(MV_[%w_]+)") or fn, full = fn, done = false,
                sa = stamp and addr(o) or nil, stalkerStamp = stamp }
            if SPX.stalkerCameraScene then SPX.stalkerCameraScene(ie) end
            introEvents[#introEvents + 1] = ie
        end
        if SPX.autoEntryPlayer then SPX.autoEntryPlayer(o, fn) end
        if SPX.newSeq then SPX.newSeq(fn) end
    end)
end)
local finishPending, finishAt = 0, nil
pcall(function()
    RegisterHook("/Script/SB.SBTheaterLevelSequenceObserver:OnFinishLevelSequence", function()
        finishPending = finishPending + 1
        finishAt = now() -- plain callback time; do not attribute an older queued finish to a new scene
        if SPX.finish then SPX.finish() end
    end)
end)

local S = { phase = "idle", gen = 0 }

-- ---------------------------------------------------------------- black hold (game camera fade + HUD opacity)
local BLACK = { R = 0.0, G = 0.0, B = 0.0, A = 1.0 }
local H = { on = false, dir = 0 }
local function guidCopy(g)
    local ok, r = pcall(function() return { A = g.A, B = g.B, C = g.C, D = g.D } end)
    if ok and r and r.A ~= nil then return r end
    return nil
end
-- HUD: hidden through the fresh death widget's master, restored through that
-- cached master. A quiet-world fallback never scans during combat.
local function hudHide(why, w)
    if cfg.hide_hud ~= "1" or H.hudAddr then return end
    local m = nil
    pcall(function() m = w:GetOuter():GetOuter() end)
    if not (valid(m) and fullName(m):find("WB_MainHUD_Master_C", 1, true)) then log("hud: master widget not found (" .. why .. ")") return end
    local ok, op = pcall(function() return m:GetRenderOpacity() end)
    H.hudAddr, H.hudOp, H.hudObj = addr(m), (ok and op) or 1.0, m
    pcall(function() m:SetRenderOpacity(0.0) end)
    log(string.format("hud hidden (%s) was opacity=%.2f", why, H.hudOp))
end
local function hudRestore(why)
    if not H.hudAddr then return end
    local a, op, k = H.hudAddr, H.hudOp or 1.0, H.hudObj
    H.hudAddr, H.hudOp, H.hudObj = nil, nil, nil
    local done = false
    -- the master widget kept from hudHide (valid + same address); full scan only as a fallback
    if k and valid(k) and addr(k) == a then pcall(function() k:SetRenderOpacity(op) end); done = true end
    if not done and not fighting() then
        for _, m in ipairs(FindAllOf("WB_MainHUD_Master_C") or {}) do
            if valid(m) and addr(m) == a then pcall(function() m:SetRenderOpacity(op) end); done = true end
        end
    end
    log(string.format("hud restored (%s) opacity=%.2f found=%s", why, op, tostring(done)))
end
-- The game's manual priority camera fade (SetManualCameraFadePriority) darkens the picture on this
-- build (the animated StartCameraFadePriority did not hold). Ramps are made by replacing the entry
-- every game tick: set the new amount first, then stop the previous entry (never a tick without one).
-- The previous entry is only stopped on the same camera manager (compared by address).
local function fadeSet(amount)
    local pcm = getPCM()
    if not pcm then return false, "no camera manager" end
    local ok, g = pcall(function() return pcm:SetManualCameraFadePriority(amount, BLACK, false, tonumber(cfg.fade_priority)) end)
    local ng = ok and guidCopy(g) or nil
    if not ng then return false, "SetManualCameraFadePriority failed: " .. tostring(g) end
    local pa = addr(pcm)
    if H.guid and H.pcmAddr == pa then local og = H.guid; pcall(function() pcm:StopCameraFadePriority(og) end) end
    H.pcmAddr, H.guid, H.amount = pa, ng, amount
    return true
end
local function fadeClear()
    local pcm = getPCM()
    if H.guid and pcm and addr(pcm) == H.pcmAddr then local og = H.guid; pcall(function() pcm:StopCameraFadePriority(og) end) end
    H.guid, H.amount = nil, nil
end
-- The area banner is separate from the HUD. Discover it before combat,
-- hide with the story black, and restore when the intro ends or is cancelled.
local function cacheArea()
    if fighting() then return end
    for _, a in ipairs(FindAllOf("WB_Theater_Area_Master_C") or {}) do
        local fn = fullName(a)
        if valid(a) and not fn:find("Default__", 1, true) and fn:find("/Engine/Transient", 1, true) then
            H.areaKeep, H.areaKeepAddr = a, addr(a)
            return
        end
    end
end
local function areaHide(why)
    if H.areaHidden then return end
    local k = H.areaKeep
    if k and valid(k) and addr(k) == H.areaKeepAddr then
        local okO, op = pcall(function() return k:GetRenderOpacity() end)
        H.areaObj, H.areaAddr, H.areaOp, H.areaUntil, H.areaHidden = k, H.areaKeepAddr, (okO and op) or 1.0, now() + 30, true
        pcall(function() k:SetRenderOpacity(0.0) end)
        log("area banner hidden (" .. why .. ")")
        return
    end
end
local function areaRestore(why)
    local a = H.areaObj
    if not a then return end
    H.areaObj, H.areaUntil, H.areaHidden = nil, nil, false
    if valid(a) and addr(a) == H.areaAddr then pcall(function() a:SetRenderOpacity(H.areaOp or 1.0) end) end
    log("area banner restored (" .. why .. ")")
end
local function blackStart(why)
    if H.on or cfg.black ~= "1" then return H.on end
    H.t = now()
    local ok, e = fadeSet(0.0)
    if not ok then evt("BLACK_SKIP", "gen=%d %s: %s", S.gen, why, tostring(e)) return false end
    H.on, H.dir = true, 1
    if S.story then areaHide(why) end
    evt("BLACK_ON", "gen=%d %s fade_out=%s priority=%s", S.gen, why, cfg.fade_out, cfg.fade_priority)
    return true
end
-- called every game tick while H.on or while fading back in
local function blackTick()
    local t = now()
    if H.dir == 1 then
        local a = math.min(1.0, (t - H.t) / math.max(0.01, tonumber(cfg.fade_out)))
        local pcm = getPCM()
        if a < 1.0 or H.amount ~= 1.0 or (pcm and addr(pcm) ~= H.pcmAddr) then
            fadeSet(a)
            if a >= 1.0 then log("black: full") end
        end
    elseif H.dir == -1 then
        local a = math.max(0.0, 1.0 - (t - H.tIn) / math.max(0.01, tonumber(cfg.fade_in)))
        if a > 0.0 then fadeSet(a) else fadeClear(); H.dir = 0; log("black: faded back in") end
    end
end
-- instant=true: the intro owns the picture now, drop the black in the same tick.
-- instant=false: something went wrong, fade back into the normal game.
local function blackEnd(why, instant)
    if not H.on then hudRestore(why) return end
    H.on = false
    local held = now() - (H.t or now())
    if instant then
        fadeClear(); H.dir = 0
        H.hudRestoreAt = now() + 0.5
    else
        H.dir, H.tIn = -1, now()
        hudRestore(why)
        areaRestore(why)
    end
    evt("BLACK_OFF", "gen=%d %s instant=%s held=%.2f", S.gen, why, tostring(instant), held)
end

-- ---------------------------------------------------------------- world changes
-- Map load (menu <-> arena, title, quitting) and the death screen's Exit: give the HUD back while the
-- old world still exists, forget everything of the old world and stay idle until the new one is up.
local suspendUntil = -1
local function worldReset(why, suspend)
    log("world reset: " .. why .. " (phase " .. S.phase .. ", black " .. tostring(H.on) .. ")")
    if H.hudAddr then pcall(hudRestore, "world reset") end
    if H.areaObj then pcall(areaRestore, "world reset") end
    H.areaKeep, H.areaKeepAddr = nil, nil
    fadeClear()
    H.on, H.dir, H.guid, H.pcmAddr, H.hudAddr, H.hudOp, H.hudRestoreAt, H.hudObj = false, 0, nil, nil, nil, nil, nil, nil
    W.o, W.oa = nil, nil
    combatObjects, combatEntered, combatSeen = {}, false, false
    dropTriggers(why)
    fireEvents, introEvents, ring = {}, {}, {}
    curSample = { id = 0 }
    W.st, W.bc = nil, nil
    S = { phase = "idle", gen = S.gen, t = now() }
    finishPending, finishAt = 0, nil
    ST.phase = "idle"
    writeStatus()
    suspendUntil = now() + suspend
end
local okPre = pcall(RegisterLoadMapPreHook, function()
    if SPX.loadMap then pcall(SPX.loadMap, "pre") end
    worldReset("LoadMap pre", 3600)
end)
local okPost = pcall(RegisterLoadMapPostHook, function()
    log("world: LoadMap post"); suspendUntil = now() + 1.0; W.probeUntil = now() + 21.0
    if SPX.loadMap then pcall(SPX.loadMap, "post") end
end)
W.probeUntil = now() + 20.0
log(string.format("map hooks: LoadMapPre=%s LoadMapPost=%s", tostring(okPre), tostring(okPost)))

-- ---------------------------------------------------------------- death cycle state machine
local function setPhase(p, why)
    log(string.format("phase %s -> %s (%s)", S.phase, p, why or ""))
    S.phase, S.t = p, now()
    ST.phase = p
    writeStatus()
end
-- how the last death cycle ended, for the panel: "restarted", or why it was the normal respawn
local function result(code)
    if code == "restarted" then ST.restarts = ST.restarts + 1 end
    ST.last, ST.last_at = code, os.time()
    writeStatus()
end
local function cancelDisabledRestart()
    S.nativeLead, S.nativeLeadAlias = nil, nil
    S.nativeRespawn = nil
    local ph = S.phase
    if S.corrupter then
        S.corrupter = nil; blackEnd("switched off", false); result("disabled")
        setPhase(W.st == 0 and "idle" or "wait_clear", "switched off: normal respawn"); return
    end
    if ph ~= "dead" and ph ~= "reviving" and ph ~= "settle" and ph ~= "intro_wait" and ph ~= "intro_cam" then return end
    blackEnd("switched off in the panel", false)
    S.story = nil
    result("disabled")
    setPhase(W.st == 0 and "idle" or "wait_clear", "switched off: normal respawn")
end

local function introTarget()
    -- a learned intro trigger of THIS arena (tracked near Eve), re-armed by the revive, with the point inside its box
    local best, why = nil, "no intro trigger learned for this arena (Eve has not walked into its intro yet)"
    for _, e in pairs(trigs) do
        local L = learnedMap[e.alias]
        local o = L and trigObj(e)
        if o then
            local r = readTrig(o)
            if not r then why = "trigger " .. e.alias .. " unreadable"
            elseif not (r.count and r.count >= 1) then why = "trigger " .. e.alias .. " not re-armed (count=" .. tostring(r.count) .. ")"
            elseif not r.active then why = "trigger " .. e.alias .. " inactive"
            elseif not insideBox(e, L.point, 0) then why = "learned point not inside " .. e.alias
            elseif not best or L.at > best.L.at then best = { e = e, L = L } end
        end
    end
    if not best then return nil, why end
    return { e = best.e, point = best.L.point, yaw = best.L.yaw }
end
local function callWarp(point, yaw, armCurrent)
    local pc = getPC()
    if armCurrent and not armCurrent(pc) then return false, "arm authority revoked before PlayerState" end
    local ps = getPS(pc)
    if armCurrent and not armCurrent(pc, ps) then return false, "arm authority revoked before PlayerId" end
    if not pc or not ps then return false, "no PC/PlayerState" end
    local pid = ps.PlayerId
    if armCurrent and not armCurrent(pc, ps) then return false, "arm authority revoked before native submission" end
    if not pid or pid <= 0 then return false, "PlayerId=" .. tostring(pid) end
    pc:ServerRequest_WarpPosition(pid, { X = point.X, Y = point.Y, Z = point.Z }, { Pitch = 0.0, Yaw = (yaw or 0.0) + 0.0, Roll = 0.0 })
    return true, "pid=" .. tostring(pid)
end
local function viewTargetInfo()
    -- AController::GetViewTarget (the camera manager's own GetViewTarget is not reflected on this build)
    local pc, pcm = getPC(), getPCM()
    if not pc or not pcm then return nil, "no pc/pcm" end
    local ok, vt = pcall(function() return pc:GetViewTarget() end)
    if not ok or not valid(vt) then return nil, "no view target" end
    local pend = nil
    local pendingReadOK = pcall(function() local p = pcm.PendingViewTarget.Target; if valid(p) then pend = p end end)
    return vt, fullName(vt), pend, pendingReadOK
end

-- This native entrance starts with an authored Eve-view shot before a camera cut.
-- Accept playback only for the exact current-life Xion entry; keep only scalar identities.
local function nativeLeadIdentity()
    local pc = getPC()
    local pawn = pc and getPawn(pc)
    if not pc or not pawn then return nil end
    local ca, pa = addr(pc), addr(pawn)
    if type(ca) ~= "number" or ca <= 0 or type(pa) ~= "number" or pa <= 0 then return nil end
    local world = "/Game/Art/BG/WorldMap/Level_P/E04.E04"
    local pn, en = fullName(pc), fullName(pawn)
    if not en:match("^CH_P_EVE_01_Blueprint_C%s+") or pn:match("^%S+ (.-):PersistentLevel%.") ~= world or
        en:match("^%S+ (.-):PersistentLevel%.") ~= world then return nil end
    return ca, pa, world .. ":PersistentLevel."
end
local function nativeLeadArm(ie, t)
    if not S.story or W.bc ~= false or W.st ~= 0 or not H.on or S.phase ~= "intro_cam" or S.gen <= 0 or
        S.nativeLeadAlias ~= "Xion_21_ZTrigger_001" or not S.tFire or ie.t < S.tFire or t - ie.t >= 2 then return end
    local suffix = ie.name:match("^MV_Xion06_RavenAppearance_([%x]+)$")
    local ca, pa, world = nativeLeadIdentity()
    if not suffix or #suffix ~= 32 or not ca or ie.full ~= "LevelSequencePlayer " .. world .. ie.name .. ".AnimationPlayer" then return end
    S.nativeLead = { gen = S.gen, fire = S.tFire, story = S.story, at = ie.t, next = t, ca = ca, pa = pa,
        full = ie.full, outer = world .. ie.name, name = ie.name }
end
local function nativeLeadPlaying(t)
    local d = S.nativeLead
    if not d then return false end
    local function current()
        local at = now()
        return S.nativeLead == d and at >= d.at and at - d.at < 2 and d.gen == S.gen and d.fire == S.tFire and
            d.story == S.story and S.nativeLeadAlias == "Xion_21_ZTrigger_001" and d.at == S.tIntro and S.introGen == d.gen and
            W.st == 0 and W.bc == false and H.on and S.phase == "intro_cam" and cfg.enabled == "1" and
            H.t and at - H.t <= tonumber(cfg.hold_max)
    end
    if not current() then S.nativeLead = nil; return false end
    if t < d.next then return false end
    d.next = t + 0.05
    if readEnabled() ~= "1" then S.nativeLead = nil; return false end
    local ca, pa = nativeLeadIdentity()
    if ca ~= d.ca or pa ~= d.pa then S.nativeLead = nil; return false end
    local found, outer = pcall(FindObject, nil, d.name) -- supported short-name overload, not a raw FName call
    if not current() then return false end
    if not found or not valid(outer) then return false end
    local oa = addr(outer)
    if type(oa) ~= "number" or oa <= 0 or fullName(outer):match("^%S+ (.+)$") ~= d.outer or (d.oa and d.oa ~= oa) then
        S.nativeLead = nil; return false
    end
    d.oa = oa
    local okP, player = pcall(function() return outer:GetSequencePlayer() end) -- BlueprintPure
    if not current() then return false end
    if not okP or not valid(player) then return false end
    local sa = addr(player)
    if type(sa) ~= "number" or sa <= 0 or fullName(player) ~= d.full or (d.sa and d.sa ~= sa) then
        S.nativeLead = nil; return false
    end
    d.sa = sa
    local ok, playing = pcall(function() return player:IsPlaying() end) -- playback, not camera certification
    if not ok or type(playing) ~= "boolean" or not playing then return false end
    if not current() or readEnabled() ~= "1" then S.nativeLead = nil; return false end
    local ca2, pa2 = nativeLeadIdentity()
    if ca2 ~= d.ca or pa2 ~= d.pa or addr(player) ~= sa or fullName(player) ~= d.full or addr(outer) ~= oa or
        fullName(outer):match("^%S+ (.+)$") ~= d.outer then S.nativeLead = nil; return false end
    S.nativeLead = nil
    evt("INTRO_PLAYBACK", "gen=%d exact Xion native entrance playing dtIntro=%.3f", S.gen, t - d.at)
    return true
end

-- Stalker may retain Eve's view during its entrance. A timeout is not camera proof.
-- Keep only scalar UObject identities; resolve its exact notified player on the game thread.
SPX.stalkerCameraStamp = function()
    if not S.stalkerCameraScope or not S.story or not H.on or not SPX.stalkerCameraContext then return nil end
    local life, epoch, post = SPX.stalkerCameraContext()
    return { state = S, gen = S.gen, story = S.story, life = life, epoch = epoch, post = post }
end
SPX.stalkerCameraDeadline = function(t)
    local hold = tonumber(cfg.hold_max)
    local base = (H.t or t) + hold
    local d = S.stalkerCamera
    if not S.stalkerCameraScope or not d or d.invalid or not d.seenPlaying or not d.proofLive or
        not d.checkedAt or t < d.checkedAt or t - d.checkedAt > 0.1 or not SPX.stalkerCameraContext then return base end
    local life, epoch, post = SPX.stalkerCameraContext()
    if S ~= d.state or S.gen ~= d.gen or S.story ~= d.story or life ~= d.life or epoch ~= d.epoch or post ~= d.post or
        S.phase ~= "intro_cam" or S.tIntro ~= d.at or S.introGen ~= d.gen or W.st ~= 0 or W.bc ~= false or
        cfg.enabled ~= "1" or t < d.at then return base end
    -- Do not reset H.t: BLACK_OFF must report the real total hold duration.
    return math.min(base + hold, d.at + hold)
end
SPX.stalkerCameraCurrent = function(d, released)
    if not d or d.invalid or not SPX.stalkerCameraContext then return false end
    local life, epoch, post = SPX.stalkerCameraContext()
    local at = now()
    return S == d.state and S.gen == d.gen and S.story == d.story and S.stalkerCameraScope and
        life == d.life and epoch == d.epoch and post == d.post and cfg.enabled == "1" and
        S.phase == "intro_cam" and W.st == 0 and W.bc == false and (H.on or released) and
        H.t and at >= H.t and at <= SPX.stalkerCameraDeadline(at)
end
SPX.stalkerCameraScene = function(ie)
    local d = S.stalkerCamera
    if d and (ie.full ~= d.full or ie.sa ~= d.sa) then d.invalid = true end
end
SPX.stalkerCameraArm = function(ie)
    if not S.stalkerCameraScope then return end
    local d = ie.stalkerStamp
    if not d then return end
    d.at, d.full, d.sa = ie.t, ie.full, ie.sa
    d.path = ie.full:match("^LevelSequencePlayer (.+)$")
    S.stalkerCamera = d
    if not SPX.stalkerCameraCurrent(d) or type(d.sa) ~= "number" or d.sa <= 0 or not d.path then d.invalid = true; return end
    local pc = getPC(); local pawn = pc and getPawn(pc); local pcm = pc and getPCM(pc)
    d.ca, d.pa, d.ma = pc and addr(pc), pawn and addr(pawn), pcm and addr(pcm)
    local pn, en = fullName(pc), fullName(pawn)
    d.world = en:match("^%S+ (.-):PersistentLevel%.")
    if not SPX.stalkerCameraCurrent(d) or not d.world or pn:match("^%S+ (.-):PersistentLevel%.") ~= d.world or
        d.path ~= d.world .. ":PersistentLevel." .. ie.name .. ".AnimationPlayer" then d.invalid = true; return end
    for _, a in ipairs({ d.ca or 0, d.pa or 0, d.ma or 0 }) do
        if type(a) ~= "number" or a <= 0 then d.invalid = true; return end
    end
end
SPX.stalkerCameraComplete = function(t)
    local d = S.stalkerCamera
    local function reject() if d then d.proofLive = false end; return false end
    if not SPX.stalkerCameraCurrent(d) or d.at ~= S.tIntro or S.introGen ~= d.gen then return reject() end
    if d.next and t < d.next then return false end
    d.next = t + 0.05
    local pc = getPC(); local pawn = pc and getPawn(pc); local pcm = pc and getPCM(pc)
    local function identity()
        return pc and pawn and pcm and valid(pc) and valid(pawn) and valid(pcm) and
            addr(pc) == d.ca and addr(pawn) == d.pa and addr(pcm) == d.ma and
            fullName(pc):match("^%S+ (.-):PersistentLevel%.") == d.world and
            fullName(pawn):match("^%S+ (.-):PersistentLevel%.") == d.world and SPX.stalkerCameraCurrent(d)
    end
    if not identity() or not SPX.stalkerCameraCurrent(d) then return reject() end
    local found, player = pcall(StaticFindObject, d.path)
    if not SPX.stalkerCameraCurrent(d) or not found or not valid(player) then return reject() end
    if addr(player) ~= d.sa or fullName(player) ~= d.full then d.invalid = true; return reject() end
    if not SPX.stalkerCameraCurrent(d) then return reject() end
    local ok, playing = pcall(function() return player:IsPlaying() end) -- BlueprintPure, not camera certification
    if not ok or type(playing) ~= "boolean" or not identity() or addr(player) ~= d.sa or fullName(player) ~= d.full or
        not SPX.stalkerCameraCurrent(d) then return reject() end
    d.checkedAt, d.proofLive = now(), true
    if playing then
        if d.stopped then d.invalid = true else d.seenPlaying = true end
        return false
    end
    if not d.seenPlaying then return false end
    d.stopped = true
    local viewOK, vt = pcall(function() return pc:GetViewTarget() end)
    local pendOK, pend = pcall(function() return pcm.PendingViewTarget.Target end)
    if not pendOK then return reject() end
    if pend ~= nil then
        local validOK, isValid = pcall(function() return pend:IsValid() end)
        if not validOK or isValid ~= false or addr(pend) ~= 0 then return reject() end
    end
    local battleOK, battle = pcall(function() return pawn.bBattleState end)
    local point = actorLoc(pawn)
    if not viewOK or not valid(vt) or addr(vt) ~= d.pa or not battleOK or battle ~= true or not point or
        not identity() or addr(player) ~= d.sa or fullName(player) ~= d.full or readEnabled() ~= "1" or
        not SPX.stalkerCameraCurrent(d) then return reject() end
    return true, point, d
end

local function startDeath(t, bc, how)
    S.nativeFight, S.nativeFightEntry, S.nativeFightGen = nil, nil, nil
    S.nativeLead, S.nativeLeadAlias = nil, nil
    S.nativeRespawn = nil
    S.stalkerCameraScope, S.stalkerCamera = nil, nil
    S.corrupter = nil
    S.gen = S.gen + 1
    loadCfg()
    local pawn = getPawn()
    evt("DEAD", "gen=%d bc=%s via=%s eve=%s trig={%s}", S.gen, tostring(bc), how, fv(pawn and actorLoc(pawn)), trigSnapshot())
    S.tDead = t
    S.story = nil
    if not bc then
        -- Story boss whose catalog intro/fight trigger was entered in this life.
        local key, why, entry = nil, "not Boss Challenge: no action", nil
        if SPX.storyEligible then key, why, entry = SPX.storyEligible() end
        if not key then setPhase("wait_clear", "story: " .. tostring(why)) return false end
        S.story = key
        S.stalkerCameraScope = why == "ME_03_ZTrigger_004"
        if entry then S.nativeFightEntry, S.nativeFightGen = entry, S.gen end
        evt("STORY_DEATH", "gen=%d target=%s", S.gen, tostring(why))
    end
    if cfg.enabled == "0" then setPhase("wait_clear", "switched off in the panel: normal respawn") return false end
    setPhase("dead", "waiting for the player's own Revive")
    return true
end
local function reviveAccepted(t, st, how)
    cfg.enabled = readEnabled()
    ST.enabled = cfg.enabled
    if cfg.enabled == "0" then cancelDisabledRestart(); return end
    S.tRev = t
    evt("REVIVE_PRESSED", "gen=%d widget state %s via %s: the player revived (any device) dtDead=%.2f", S.gen, tostring(st), how, t - (S.tDead or t))
    blackStart("revive gen " .. S.gen)
    setPhase("reviving", "player revive")
end

-- w: the death widget, only when called from its own hook (fresh object), else nil
local function cycle(st, bc, how, w)
    local t = now()
    -- Story death screen: 3 = dead with the respawn choice, 5 = respawn chosen, 4 = revival item
    if bc ~= true then
        -- The same native respawn may keep its accepted Revive widget visible during the intro.
        if S.nativeRespawn and (S.phase == "intro_cam" or S.phase == "fight_wait") and (st == 2 or st == 5) then st = 0 end
        if st == 3 then st = 1
        elseif st == 5 and (S.phase == "dead" or S.phase == "reviving") then st = 2 end
    end
    local ph = S.phase
    if st == 6 and ph ~= "exit" then
        -- the death screen's Exit: the arena is about to be torn down
        if ph == "dead" then evt("DEATH_LEFT", "gen=%d widget state 1 -> 6 (Exit) without Revive; no action", S.gen) end
        if H.on then blackEnd("exit", false) end
        worldReset("death screen Exit", 30)
        S.phase = "exit"
        return
    end
    if ph == "exit" then
        if st == 0 then setPhase("idle", "death widget back to normal after the Exit"); suspendUntil = -1 end
        return
    end
    if ph == "idle" or ph == "fight_wait" then
        if st == 1 then
            startDeath(t, bc, how)
        elseif st == 2 then
            if startDeath(t, bc, how) then reviveAccepted(t, st, how) end
        elseif st ~= 0 then
            evt("DEATH_OTHER", "gen=%d widget state %s: not a Revive; no action", S.gen, tostring(st))
            setPhase("wait_clear", "other death-screen state")
        end
        if S.phase == "fight_wait" and t - S.t > 120 then setPhase("idle", "intro finish not seen in 120 s") end
        return
    end
    if ph == "dead" then
        if st == 2 then reviveAccepted(t, st, how) return end
        if st == 1 then return end
        evt("DEATH_LEFT", "gen=%d widget state 1 -> %s without Revive (WB Pump / other); no action", S.gen, tostring(st))
        setPhase(st == 0 and "idle" or "wait_clear", "not a Revive")
        return
    end
    if ph == "reviving" then
        if st == 0 then
            if w then hudHide("respawn gen " .. S.gen, w) end
            local pawn = getPawn()
            S.lastP, S.stableSince = nil, nil
            evt("REVIVED", "gen=%d dt=%.2f eve=%s battle=%s trig={%s}", S.gen, t - S.tRev,
                fv(pawn and actorLoc(pawn)), pawn and battleState(pawn) or "?", trigSnapshot())
            setPhase("settle", "widget hidden")
        elseif st ~= 2 then
            evt("REVIVE_LEFT", "gen=%d widget state 2 -> %s; releasing the black", S.gen, tostring(st))
            blackEnd("revive left", false)
            setPhase("wait_clear", "death screen changed")
        elseif t - S.tRev > tonumber(cfg.revive_timeout) then
            evt("REVIVE_FAIL", "gen=%d widget still in Revive after %.1f s; releasing the black", S.gen, t - S.tRev)
            blackEnd("revive timeout", false)
            result("revive_timeout")
            setPhase("wait_clear", "revive not completed")
        end
        return
    end
    if ph == "settle" then
        if st ~= 0 then evt("INTRO_SKIP", "gen=%d death widget state %s", S.gen, tostring(st)); blackEnd("died again", false); result("died_again"); setPhase("wait_clear", "died again") return end
        local pawn = getPawn()
        local p = pawn and actorLoc(pawn)
        if p and S.lastP and dist(p, S.lastP) < 3 then S.stableSince = S.stableSince or t else S.stableSince = nil end
        S.lastP = p
        local tgt, why
        if S.story and SPX.storyTarget then tgt, why = SPX.storyTarget(S.story) else tgt, why = introTarget() end
        -- as on the proven v0.2 path: >= settle s after the respawn and Eve standing still >= 0.3 s
        -- (a warp 0.18 s after the respawn left the intro trigger pending forever, 12:19 run)
        if t - S.t < tonumber(cfg.settle) or not S.stableSince or t - S.stableSince < 0.3 or not tgt then
            if t - S.t > 6 then
                evt("INTRO_SKIP", "gen=%d %s", S.gen, tgt and "Eve not settled in 6 s" or tostring(why))
                blackEnd("no intro target", false)
                result(tgt and "not_settled" or "no_intro")
                setPhase("idle", "no intro")
            end
            return
        end
        if cfg.intro ~= "warp" then evt("INTRO_SKIP", "gen=%d intro=%s", S.gen, tostring(cfg.intro)); blackEnd("intro off", false); result("intro_off"); setPhase("idle", "intro off") return end
        -- Recheck at the action boundary: OFF can arrive between the 2 s
        -- settings polls while Eve settles. One read per attempted warp.
        cfg.enabled = readEnabled()
        ST.enabled = cfg.enabled
        if cfg.enabled == "0" then cancelDisabledRestart(); return end
        -- Freeze this row's original authority before reflected camera reads/native submission.
        local armRequired = S.story and SPX.storyArmCreated and SPX.storyArmCreated(S.story)
        local armState, armGen, armPhase = S, S.gen, S.phase
        local armAttempt = armRequired and SPX.storyArmWarpBegin(S.story)
        local fightAttempt = tgt.nativeFight and SPX.nativeFightWarpBegin(S.story)
        local function armCanceled()
            if tgt.nativeFight and not SPX.nativeFightCurrent(fightAttempt) then
                if S == armState and S.gen == armGen and S.phase == armPhase then
                    evt("NATIVE_FIGHT_SKIP", "gen=%d submission authority revoked", S.gen)
                    blackEnd("native fight invalid", false); result("attempt_invalid"); setPhase("idle", "attempt invalid")
                end
                return true
            end
            if not armRequired then return false end
            if armAttempt and SPX.storyArmWarpCurrent(armAttempt) then return false end
            -- Preserve a callback's new death/map state; never overwrite its lifecycle.
            if S == armState and S.gen == armGen and S.phase == armPhase then
                evt("INTRO_SKIP", "gen=%d arm-created native submission authority revoked", S.gen)
                blackEnd("attempt invalid", false); result("attempt_invalid"); setPhase("idle", "attempt invalid")
            end
            return true
        end
        if armCanceled() then return end
        local vtg = viewTargetInfo()
        local vtGameAddr = vtg and addr(vtg) or nil
        if armCanceled() then return end
        S.vtGameAddr = vtGameAddr
        local ok, res, info = pcall(callWarp, tgt.point, tgt.yaw,
            armAttempt and function() return SPX.storyArmWarpCurrent(armAttempt) end or
            fightAttempt and function(pc, ps) return SPX.nativeFightActionCurrent(fightAttempt, pc, ps) end or nil)
        if armCanceled() then return end
        S.tFire = now()
        if ok and res then
            if armAttempt then
                local boundOK, bound = pcall(SPX.storyWarped, S.story, tgt.point, tgt.yaw, armAttempt)
                if not boundOK or not bound then armAttempt.invalid = true end
                if armCanceled() then return end
            end
            S.nativeLeadAlias = tgt.e.alias == "Xion_21_ZTrigger_001" and tgt.e.alias or nil
            evt(tgt.nativeFight and "NATIVE_FIGHT_FIRE" or "INTRO_FIRE", "gen=%d trigger=%s alias=%s warp=%s from=%s moved=%.0f %s black=%s", S.gen, tgt.e.key, tgt.e.alias, fv(tgt.point), fv(p),
                dist(p, tgt.point), info, tostring(H.on))
            if S.story and SPX.storyWarped and not armAttempt and not tgt.nativeFight then pcall(SPX.storyWarped, S.story, tgt.point, tgt.yaw) end
            if tgt.e.alias == "DED20_ZTrigger_011" then
                S.corrupter = SPX.corrupterArm(S.story)
                if not S.corrupter then
                    evt("INTRO_SKIP", "gen=%d Corrupter attempt identity unavailable", S.gen)
                    blackEnd("attempt invalid", false); result("attempt_invalid"); setPhase("idle", "attempt invalid"); return
                end
            end
            setPhase(tgt.nativeFight and "native_fight_wait" or "intro_wait", "warp into trigger")
        else
            evt("INTRO_SKIP", "gen=%d warp failed: %s", S.gen, tostring(ok and info or res))
            blackEnd("warp failed", false)
            result("warp_failed")
            setPhase("idle", "warp failed")
        end
        return
    end
    if ph == "native_fight_wait" then
        local attempt = S.nativeFight
        local ready = st == 0 and SPX.nativeFightReady(attempt)
        if not SPX.nativeFightCurrent(attempt) then
            if attempt and S == attempt.state and S.gen == attempt.sgen and S.phase == "native_fight_wait" then
                blackEnd("native fight invalid", false); result("attempt_invalid"); setPhase("idle", "attempt invalid")
            end
        elseif ready then
            local cut, why = SPX.nativeFightCameraCut(attempt)
            if not SPX.nativeFightCurrent(attempt) then return end
            if not cut then
                evt("NATIVE_FIGHT_CAMERA_CUT_FAIL", "gen=%d %s", S.gen, tostring(why):gsub("[\r\n]", " "):sub(1, 120))
                blackEnd("native camera cut unavailable", false)
                if not SPX.nativeFightCurrent(attempt) then return end
                result("attempt_invalid"); setPhase("idle", "native camera unavailable")
                S.nativeFight, S.nativeFightEntry, S.nativeFightGen = nil, nil, nil
                return
            end
            evt("NATIVE_FIGHT_CAMERA_CUT", "gen=%d alias=%s", S.gen, NATIVE_FIGHT_ALIAS)
            blackEnd("native fight entered", true)
            if not SPX.nativeFightCurrent(attempt) then return end
            evt("NATIVE_FIGHT_ENTERED", "gen=%d alias=%s own rearm/consumption and grounded gameplay view", S.gen, NATIVE_FIGHT_ALIAS)
            result("restarted"); setPhase("idle", "native fight entered")
            S.nativeFight, S.nativeFightEntry, S.nativeFightGen = nil, nil, nil
        elseif t - S.tFire > tonumber(cfg.intro_timeout) then
            blackEnd("native fight not confirmed", false)
            if not SPX.nativeFightCurrent(attempt) then return end
            result("fight_unconfirmed"); setPhase("idle", "native fight not confirmed")
        end
        return
    end
    if ph == "intro_wait" then
        if st ~= 0 then evt("INTRO_SKIP", "gen=%d death widget state %s", S.gen, tostring(st)); blackEnd("died again", false); result("died_again"); setPhase("wait_clear", "died again") return end
        -- A changed trigger count or elapsed time does not prove this boss restarted.
        -- INTRO rows need their own matched entrance; arbitrary cached characters are not boss identity.
        -- Arm-created objects prove rearm, not playback. Consumption may release
        -- the fade; count a restart only when a current cinematic camera owns the view.
        if S.story and S.tFire and SPX.storyArmConsumed then
            local consumed, current = SPX.storyArmConsumed(S.story, S.tRev, S.tFire)
            if current and not current() then return end
            if consumed then
                local wait = SPX.storyNoIntroWait(S.story)
                if not current() then return end
                if t - S.tFire >= wait then
                    if not S.armAuthority.consumedAt then
                        S.armAuthority.consumedAt = t
                        evt("INTRO_ARM_CONSUMED", "gen=%d own rearm object and trigger consumed after warp dtFire=%.3f", S.gen, t - S.tFire)
                        blackEnd("arm-created trigger consumed", false)
                        if not current() then return end
                    end
                    local vt, vtn = viewTargetInfo()
                    if not current() then return end
                    if vt and type(vtn) == "string" and vtn:match("^CineCameraActor%s") then
                        S.introGen = S.gen; S.tIntro = t
                        evt("INTRO_ARMED", "gen=%d own rearm and consumption confirmed; cinematic camera owns view dtFire=%.3f", S.gen, t - S.tFire)
                        result("restarted"); setPhase("fight_wait", "arm-created cinematic view")
                        return
                    end
                end
            end
        end
        if t - S.t > tonumber(cfg.intro_timeout) then
            -- This streamed entrance may arrive after 4 s; the existing black watchdog is the absolute bound.
            if S.corrupter and H.on and t - H.t <= tonumber(cfg.hold_max) then
                if not S.corrupter.grace then S.corrupter.grace = true; evt("INTRO_GRACE", "gen=%d alias=DED20_ZTrigger_011 existing black watchdog only", S.gen) end
                return
            end
            local pawn = getPawn()
            evt("INTRO_FAIL", "gen=%d no intro %.1f s after the warp; eve=%s trig={%s}", S.gen, t - S.tFire, fv(pawn and actorLoc(pawn)), trigSnapshot())
            blackEnd("intro not seen", false)
            result(S.story and "fight_unconfirmed" or "intro_not_seen")
            setPhase("idle", "intro not seen")
        end
        return
    end
    if ph == "intro_cam" then
        local cameraStamp = S.stalkerCameraScope and SPX.stalkerCameraStamp()
        if S.stalkerCameraScope then
            local complete, point, d = SPX.stalkerCameraComplete(t)
            if complete then
                blackEnd("own Stalker playback completed; native control returned", false)
                if not SPX.stalkerCameraCurrent(d, true) then return end
                evt("INTRO_READY", "gen=%d alias=ME_03_ZTrigger_004 exact own playback completed", S.gen)
                areaRestore("native control returned")
                if not SPX.stalkerCameraCurrent(d, true) then return end
                S.fightCheck = { at = t + 3.0, p = point, gen = S.gen }
                result(S.nativeRespawn and "native_respawn" or "restarted")
                setPhase("idle", "own playback and native control returned"); return
            end
            if not SPX.stalkerCameraCurrent(cameraStamp) then return end
        end
        if nativeLeadPlaying(t) then
            blackEnd("native entrance playback", true)
            result("restarted"); setPhase("fight_wait", "native entrance playing")
            return
        end
        -- the intro sequence exists; release the black on the first tick its camera owns the view
        local vt, vtn, pend = viewTargetInfo()
        local pawn = getPawn()
        local isGame = vt and ((pawn and same(vt, pawn)) or (S.vtGameAddr ~= nil and addr(vt) == S.vtGameAddr))
        -- A confirmed cinematic target can render while a camera blend is pending.
        local isCine = type(vtn) == "string" and vtn:match("^CineCameraActor%s") ~= nil
        if cameraStamp and not SPX.stalkerCameraCurrent(cameraStamp) then return end
        if vt and not isGame and (not pend or isCine) then
            evt("INTRO_CAMERA", "gen=%d view=%s dtIntro=%.3f", S.gen, tostring(vtn), t - S.tIntro)
            blackEnd("intro camera", true)
            if cameraStamp and not SPX.stalkerCameraCurrent(cameraStamp, true) then return end
            if not S.corrupter then result(S.nativeRespawn and "native_respawn" or "restarted") end
            setPhase("fight_wait", "intro playing")
        elseif not S.corrupter and not S.stalkerCameraScope and t - S.tIntro > tonumber(cfg.cine_wait) then
            evt("INTRO_CAMERA", "gen=%d view=%s pending=%s after %.2f s: releasing anyway", S.gen, tostring(vtn), tostring(pend ~= nil), t - S.tIntro)
            blackEnd("intro camera wait timeout", true)
            if not S.corrupter then result(S.nativeRespawn and "native_respawn" or "restarted") end
            setPhase("fight_wait", "intro playing")
        end
        return
    end
    if ph == "wait_clear" then
        if st == 0 then setPhase("idle", "death widget hidden") end
        return
    end
end

-- ================================================================ STORY CORE
-- Cached trigger learning/restart always runs; detailed diagnostics only with
-- story-probe.txt. Initial/map/streaming discovery waits for a quiet world.
do
    local SPLOG, SPLOG_OLD = MOD_DIR .. "story-probe.log", MOD_DIR .. "story-probe.previous.log"
    local SPLOG_MAX = 48 * 1024 * 1024
    local spf
    if PROBE_ON then os.remove(SPLOG_OLD); os.rename(SPLOG, SPLOG_OLD); spf = io.open(SPLOG, "w") end
    local spBytes, spSeq = 0, 0
    local function L(fmt, ...)
        if not PROBE_ON then return end
        local ok, msg = pcall(string.format, fmt, ...)
        if not ok then msg = fmt .. " <format error: " .. tostring(msg) .. ">" end
        spSeq = spSeq + 1
        if not spf then return end
        local line = string.format("%s S%05d %s\n", stamp(), spSeq, msg)
        spBytes = spBytes + #line
        if spBytes > SPLOG_MAX then spf:write("story probe log size limit reached\n"); spf:close(); spf = nil; return end
        spf:write(line)
        spf:flush()
    end
    local function f1(x) return x and string.format("%.1f", x) or "-" end

    -- the boss catalog (STORY-PLAN.md 3.7): intro alias -> row|boss|v1 mode|class
    local CAT = {
        DED10_ZTrigger_103 = "2|Abaddon (Eidos 7)|INTRO|A", DED10_ZTrigger_016 = "2|Abaddon (Eidos 7)|INTRO|A",
        DED20_ZTrigger_011 = "3|Corrupter (Eidos 7)|INTRO|A", ZT_EQ_DED_Q01_M01 = "4|Gigas (Eidos 7)|INTRO|A",
        ATL_03_ZTrigger_009 = "25|Maelstrom (Altess Levoire)|INTRO|B",
        AYL_06_ZTrigger_001 = "6|Maelstrom (Abyss Levoire)|INTRO|A", ME_03_ZTrigger_004 = "7|Stalker (Matrix 11)|INTRO|A",
        ME_05_ZTrigger_009 = "8|Juggernaut (Matrix 11)|INTRO|A", ME_05_ZTrigger_010 = "8|Juggernaut flavour theater|DENY|-",
        ME_06_ZTrigger_024 = "9|Tachy (Matrix 11)|INTRO|A", ME_06_ZTrigger_025 = "9|Tachy other trigger|DENY|-",
        ME_06_ZTrigger_029 = "9|Tachy other trigger|DENY|-", SE_06_ZTrigger_005 = "11|Belial encounter 1 (Spire 4)|INTRO|A",
        SE_06_ZTrigger_004 = "11|Belial other trigger|DENY|-", SE_08_ZTrigger_002 = "12|Karakuri (Spire 4)|INTRO|B",
        SE_10_ZTrigger_001 = "13|Democrawler (High Orbit Station)|INTRO|B", SE_10_ZTrigger_007 = "14|Demogorgon (High Orbit Station)|RETRY|B",
        Xion_21_ZTrigger_001 = "15|Unidentified Naytiba (Burning Xion)|INTRO|A", WLA_10_ZTrigger_016 = "16|Raven (Wasteland)|INTRO|A",
        Nest_10_ZTrigger_014 = "17|Adam/Providence/Elder (Nest)|RETRY|B", WLA_40_ZTrigger_031 = "18|Brute (Wasteland)|INTRO|B",
        WLA_40_ZTrigger_035 = "19|Gigas (Wasteland)|INTRO|B", WLA_40_ZTrigger_065 = "20|Corrupter (Wasteland)|INTRO|B",
        WLB_20_ZTrigger_005 = "21|Stalker (Great Desert)|INTRO|B", WLB_30_ZTrigger_012 = "22|Behemoth (Great Desert)|INTRO|B",
        WLB_50_ZTrigger_010 = "23|Abaddon (Great Desert)|INTRO|B",
        DED40_ZTrigger_026 = "24|Corrupter + Dozer (Eidos 9)|FIGHT|B", -- authored no-theater fight, native zone reset
    }
    local catCache = {}
    local function cat(alias)
        if not alias then return nil end
        local c = catCache[alias]
        if c ~= nil then return c or nil end
        local s = CAT[alias]
        if s then
            local row, boss, mode, cls = s:match("^(%d+)|([^|]*)|([^|]*)|([^|]*)$")
            c = { row = tonumber(row), boss = boss, mode = mode, cls = cls }
        end
        catCache[alias] = c or false
        return c
    end
    local ZONES = { "SD_10", "DED10", "DED20", "DED30", "DED40", "AYL_06", "ATL_03", "ME_03", "ME_05", "ME_06", "SE_04", "SE_06",
        "SE_08", "SE_10", "Xion_21", "WLA_10", "WLA_40", "Nest_10", "WLB_20", "WLB_30", "WLB_50" }
    local function zoneOf(alias, bind)
        for _, z in ipairs(ZONES) do
            if (alias or ""):sub(1, #z + 1) == z .. "_" or (bind or ""):find("_" .. z, 1, true) then return z end
        end
        return nil
    end

    local T, byAddr, watch = {}, {}, {}
    local SP = { gen = 0, life = { t = now(), consumed = {}, why = "module start" }, snapAt = -100, watchAt = -100, snapMs = 0,
        quietUntil = now() + 3.0, hotUntil = -1, ringAt = -1, ring = {}, seqNew = {}, seqs = {}, finish = 0, q = {},
        active = false, learned = {}, stats = { n = 0, sum = 0, max = 0, at = now() } }
    SP.armSeq = {}   -- arm-created entrance objects seen in this map: alias -> { t, name, world }
    SP.armEpoch = 0 -- any EndPlay conservatively cancels only a pending arm-created proof
    local function world()
        local pawn = getPawn()
        if not pawn then return "no pawn" end
        local fn = fullName(pawn)
        return fn:match(" (/[^:]+):") or fn
    end
    local function loadCtx()
        local pc = getPC()
        if not pc then return "no controller" end
        local s = "unreadable"
        pcall(function()
            local c = pc.CurrentLoadContext
            local slot = "?"
            pcall(function() slot = c.SlotName:ToString() end)
            s = string.format("slot=%s loadAfterDead=%s isPending=%s fillAndPending=%s writeAndPending=%s showUI=%s tickAutoSave=%s",
                slot, tostring(c.bLoadAfterDead), tostring(c.bIsPending), tostring(c.bFillAndPending), tostring(c.bWriteAndPending),
                tostring(c.bShowUI), tostring(c.bTickBasedAutoSave))
        end)
        return s
    end
    -- AUTO_ENTRY_GATE_BEGIN
    -- TEST ONLY: scalar lifecycle tickets, not a numerical HP/alive assertion.
    local AE = { epoch = 0, loading = true, ended = {}, lastEmit = -100 }
    local function aeIdentity()
        if not PROBE_ON or now() < suspendUntil or AE.loading or now() < SP.quietUntil then return nil, "loading" end
        if SP.dead or S.phase ~= "idle" then return nil, "death/retry/scene" end
        local pc, pawn = getPC(), getPawn()
        local ps, pcm = getPS(pc), getPCM(pc)
        if not valid(pc) or not valid(pawn) or not valid(ps) or not valid(pcm) then return nil, "local chain" end
        local ids = { pc = addr(pc), pawn = addr(pawn), ps = addr(ps), pcm = addr(pcm), world = world() }
        for _, k in ipairs({ "pc", "pawn", "ps", "pcm" }) do
            if not ids[k] or ids[k] == 0 or AE.ended[ids[k]] then return nil, "ended/unknown identity" end
        end
        if ids.world:sub(1, 1) ~= "/" then return nil, "unknown world" end
        local ok, pending = pcall(function()
            local c = pc.CurrentLoadContext
            return c.bIsPending == false and c.bFillAndPending == false and c.bWriteAndPending == false
        end)
        if not ok or not pending then return nil, "pending/unknown load" end
        local st, bc = W.st, W.bc
        if W.o then
            if not valid(W.o) or addr(W.o) ~= W.oa then return nil, "stale death widget" end
            st, bc = readW(W.o)
            if st == nil then return nil, "unreadable death widget" end
        end
        if (st ~= nil and st ~= 0) or bc == true or battleState(pawn) ~= "false" or fighting() then return nil, "death/battle" end
        local view, _, nextView, readOK = viewTargetInfo()
        if not readOK or not valid(view) then return nil, "unknown camera" end
        if not same(view, pawn) or nextView then return nil, "scene" end
        -- Object creation delays readiness; the camera above still cancels an active scene.
        if #SP.seqNew > 0 or #SP.seqs > 0 then return nil, "sequence objects" end
        return ids
    end
    local function aeSame(a, b)
        return a and b and a.pc == b.pc and a.pawn == b.pawn and a.ps == b.ps and a.pcm == b.pcm and a.world == b.world
    end
    local function aeRun()
        local f = io.open(PROBE_FILE, "r")
        if not f then return nil end
        local run = f:read(128); f:close()
        return run and run:match("^(codex%-%w[%w_%-]*)\n$")
    end
    -- Retain only bounded player references from the existing native creation callback.
    -- Object creation is never playback proof; every current-world live player must read stopped.
    SPX.autoEntryPlayer = function(o, fn)
        if not PROBE_ON then return end
        AE.groundPlayers = AE.groundPlayers or {}
        if #AE.groundPlayers >= 32 then AE.groundPlayerOverflow = true; return end
        AE.groundPlayers[#AE.groundPlayers + 1] = { o = o, full = fn }
    end
    -- TheaterStudio class-default AnimationPlayer subobjects are not world playback.
    -- Require the exact directory and matching asset/CDO class, independent of template name.
    local function aeTheaterTemplateDefault(fn)
        if type(fn) ~= "string" then return false end
        local asset, class = fn:match("^LevelSequencePlayer /Game/GameDesign/Level/Theater/TheaterStudio/Blueprints/([A-Za-z_][A-Za-z0-9_]*)%.Default__([A-Za-z_][A-Za-z0-9_]*)_C:AnimationPlayer$")
        return asset ~= nil and asset == class
    end
    local function aeGroundStopped(world)
        if AE.groundPlayerOverflow then return false, "playback-overflow" end
        for _, player in ipairs(AE.groundPlayers or {}) do
            if valid(player.o) and not aeTheaterTemplateDefault(player.full) then
                local owner = player.full:match("^LevelSequencePlayer (/[^:]+):PersistentLevel%.")
                if not owner then return false, "playback-owner-unknown full=" .. (type(player.full) == "string" and player.full:gsub("[^ -~]", "?"):sub(1, 180) or "?") end -- unknown owner cannot authorize test placement
                if owner == world then
                    local ok, playing = pcall(function() return player.o:IsPlaying() end) -- native BlueprintPure
                    if not ok then return false, "playback-read-error" end
                    if playing ~= false then return false, type(playing) == "boolean" and "playback-active" or "playback-value-unknown" end -- unknown and active both hold
                end
            end
        end
        return true
    end
    local function aeNew(why)
        AE.epoch = AE.epoch + 1
        AE.event = { ticket = AE.epoch, why = why, class = AE.hadDeath and "developer_rescue" or "automatic_entry" }
        AE.stable, AE.ready, AE.used, AE.lastEmit = nil, nil, false, -100
        AE.advert, AE.adverts = 0, {}
    end
    SPX.autoEntryLoad = function(which)
        if not PROBE_ON then return end
        AE.loading, AE.ready, AE.stable = which == "pre", nil, nil
        if which == "pre" then
            AE.groundPlayers, AE.groundPlayerOverflow = {}, false
            AE.event = nil; SP.life.autoEntry = nil
            if AE.submission then AE.submission.invalid = true end
        else AE.ended = {}; aeNew("LoadMapPost") end
    end
    SPX.autoEntryDeath = function()
        if not PROBE_ON then return end
        SP.life.autoEntry = nil
        if AE.submission then AE.submission.invalid = true end
        AE.hadDeath, AE.deadPawn = true, addr(getPawn())
        AE.event, AE.ready, AE.stable, AE.used = nil, nil, nil, false
    end
    SPX.autoEntryEndPlay = function(a)
        if not PROBE_ON then return end
        local e = SP.life.autoEntry
        if e and (a == e.address or a == e.ids.pc or a == e.ids.pawn or a == e.ids.ps or a == e.ids.pcm) then SP.life.autoEntry = nil end
        local submitted = AE.submission
        if submitted and (a == submitted.address or a == submitted.ids.pc or a == submitted.ids.pawn or a == submitted.ids.ps or a == submitted.ids.pcm) then
            submitted.invalid = true
        end
        local old = AE.ready or AE.stable
        if (old and (old.pc == a or old.pawn == a or old.ps == a or old.pcm == a)) or a == AE.lastPawn or a == AE.deadPawn then
            AE.ended[a] = true
            AE.event, AE.ready, AE.stable = nil, nil, nil
            AE.replaceWanted = true
        end
    end
    SPX.autoEntryScene = function(fn)
        if not PROBE_ON then return end
        AE.ready, AE.stable = nil, nil
        -- Known boss scenes revoke the ticket even before the camera switches.
        -- Incidental objects retain it through the queue, then need fresh stability.
        local short = storyIntroName(fn)
        if not short then return end
        if short == "MV_Nest_Intro" or nestArenaIntro(short) then AE.event = nil; return end
        for _, names in pairs(STORY_INTRO_NAMES) do
            if names[short] then AE.event = nil; return end
        end
    end
    SPX.autoEntryTick = function(t)
        if not PROBE_ON then return end
        if AE.tickAt and t - AE.tickAt < 0.1 then return end
        AE.tickAt = t
        local ids, why = aeIdentity()
        if not ids then
            AE.ready, AE.stable = nil, nil
            if why == "death/battle" or why == "death/retry/scene" or why == "scene" then AE.event = nil end
            return
        end
        if not AE.event and AE.lastPawn and ids.pawn ~= AE.lastPawn and
            (AE.replaceWanted or (SP.post and SP.post.respawnPos and SP.post.d and ids.pawn ~= SP.post.d.pawn)) then
            aeNew("proved pawn replacement/completed respawn")
        end
        if not AE.lastPawn or AE.event then AE.lastPawn = ids.pawn end
        if not AE.event or AE.used then return end
        -- A hidden death screen alone never certifies a reused dead pawn.
        if AE.deadPawn == ids.pawn and AE.event.why ~= "LoadMapPost" then return end
        if not aeSame(AE.stable, ids) then AE.stable, AE.stableAt, AE.ready = ids, t, nil; return end
        if t - AE.stableAt < 0.5 then return end
        AE.ready, AE.readyAt = ids, t
        local run = aeRun()
        if run and t - AE.lastEmit >= 1 then
            AE.lastEmit = t
            AE.advert = AE.advert + 1; AE.adverts[AE.advert] = t
            AE.adverts[AE.advert - 3] = nil
            L("AUTO_ENTRY_READY ticket=%d run=%s world=%s pc=%s pawn=%s ps=%s pcm=%s classification=%s proof=no_death_observed_new_spawn advert=%d",
                AE.event.ticket, run, ids.world, tostring(ids.pc), tostring(ids.pawn), tostring(ids.ps), tostring(ids.pcm), AE.event.class, AE.advert)
        end
    end
    SPX.autoEntryWarp = function(line, paused)
        local alias, run, ticket, nonce, expectedWorld, advert = line:match("^([%w_]+)\tAUTO_ENTRY_V1\t([%w_%-]+)\t(%d+)\t([a-f0-9]+)\t(/[^%s]+)\t(%d+)$")
        local function refused(why)
            L("AUTO_ENTRY_REFUSED ticket=%s nonce=%s why=%s", tostring(ticket), nonce and nonce:sub(1, 32) or "?", why)
            return false, why
        end
        if paused or not alias or #nonce ~= 32 or aeRun() ~= run then return refused("protocol/run/paused") end
        local advertisedAt = AE.adverts and AE.adverts[tonumber(advert)]
        local ids, why = aeIdentity()
        if not advertisedAt or now() - advertisedAt > 3 then return refused("stale request advertisement") end
        if not ids or not AE.event or AE.used or tonumber(ticket) ~= AE.event.ticket or
            not AE.readyAt or now() - AE.readyAt > 2 or not aeSame(ids, AE.ready) or ids.world ~= expectedWorld then
            return refused(why or "stale/duplicate/foreign ticket")
        end
        local found, key
        for k, r in pairs(T) do
            if r.present and r.o and valid(r.o) then
                local ok, nativeAlias = pcall(function() return r.o.TriggerAlias:ToString() end)
                if ok and nativeAlias == alias then found, key = r.o, k; break end
            end
        end
        if not found then return refused("configured trigger not loaded") end
        -- TEST ONLY initial026 navigation; never authorizes a retry or learned entrance.
        if alias == NATIVE_FIGHT_ALIAS then
            local event, epoch, life, gen, armEpoch = AE.event, AE.epoch, SP.life, SP.gen, SP.armEpoch
            local point = { X = -49597.1, Y = -106334.1, Z = 17626.0 }
            local function scalar()
                return PROBE_ON and not AE.hadDeath and not AE.initialUsed and event and event.class == "automatic_entry" and
                    AE.event == event and AE.epoch == epoch and SP.life == life and SP.gen == gen and SP.armEpoch == armEpoch and
                    not AE.loading and not SP.dead and ids.world == NATIVE_FIGHT_WORLD and aeRun() == run
            end
            local initialReason = "not-reached"
            local function diagnosticText(value)
                return type(value) == "string" and value:gsub("[%c]", " "):sub(-160) or "unknown"
            end
            local function denied(reason)
                initialReason = reason
                return false
            end
            local function current()
                if not scalar() then return denied("life-before-read") end
                local live = aeIdentity()
                if not scalar() or not aeSame(ids, live) then return denied("identity-or-life") end
                local stopped, playbackReason = aeGroundStopped(ids.world)
                if not stopped or not scalar() then return denied(playbackReason or "life-after-playback") end
                local ownedName, ownedMode
                local owned, ownedError = pcall(function()
                    local pc, pawn = getPC(), getPawn(); if not scalar() then error("revoked") end
                    if not same(pc.AcknowledgedPawn, pawn) or not scalar() then error("foreign pawn") end
                    local name = fullName(pawn); if not scalar() then error("revoked") end
                    ownedName = name -- already-read scalar string, never an extra native lookup
                    if not name:match("^CH_P_EVE_01_Blueprint_C " .. NATIVE_FIGHT_WORLD:gsub("([^%w])", "%%%1") .. ":PersistentLevel%.CH_P_EVE_01_Blueprint_C_%d+$") then error("foreign Eve") end
                    local movement = pawn.CharacterMovement; if not scalar() or not valid(movement) then error("unknown movement") end
                    if not same(movement.CharacterOwner, pawn) or not scalar() then error("foreign movement") end
                    local mode = movement.MovementMode; ownedMode = mode
                    if not scalar() or (mode ~= 1 and mode ~= 2) then error("not grounded camp") end
                end)
                if not owned or not scalar() then
                    local why = diagnosticText(ownedError); why = why:match(": ([^:]+)$") or why
                    local mode = type(ownedMode) == "number" and string.format("%g", ownedMode) or type(ownedMode)
                    return denied("owner:" .. why .. " name=" .. diagnosticText(ownedName) .. " mode=" .. mode)
                end
                local ok, box, boxReason = pcall(function()
                    if not valid(found) or not scalar() then return nil, "box-trigger-or-life" end
                    local address = addr(found); if not scalar() or not T[key] or address ~= T[key].a then return nil, "box-address-or-life" end
                    local location = actorLoc(found); if not scalar() then return nil, "life-after-box-location" end
                    local extent = v3(found.BoxExtent); if not scalar() then return nil, "life-after-box-extent" end
                    local yaw = actorYaw(found); if not scalar() then return nil, "life-after-box-yaw" end
                    local count = found.InitialDoingCount; if not scalar() then return nil, "life-after-box-count" end
                    local pending = found.bPendingCheck; if not scalar() then return nil, "life-after-box-pending" end
                    local active = found.bActiveTrigger; if not scalar() then return nil, "life-after-box-active" end
                    local nativeAlias = found.TriggerAlias:ToString(); if not scalar() then return nil, "life-after-box-alias" end
                    return { loc = location, ext = extent, yaw = yaw, count = count, pending = pending, active = active, alias = nativeAlias }
                end)
                -- The same ordered short-circuit tests; labels use only their cached values.
                if not ok then return denied("box-read-error:" .. diagnosticText(box)) end
                if not scalar() then return denied("life-after-box-read") end
                if not box then return denied(boxReason or "box-no-snapshot") end
                if box.alias ~= NATIVE_FIGHT_ALIAS then return denied("box-alias") end
                if type(box.count) ~= "number" or not (box.count >= 1) then return denied("box-count") end
                if box.pending ~= false then return denied("box-pending") end
                if box.active ~= true then return denied("box-inactive") end
                if not box.loc then return denied("box-location") end
                if not box.ext then return denied("box-extent") end
                if type(box.yaw) ~= "number" then return denied("box-yaw") end
                if not insideBox(box, point, 0) then return denied("box-target-outside") end
                initialReason = "accepted"
                return true
            end
            if not current() then return refused("initial026:" .. initialReason) end
            AE.used = true -- irreversible attempt; action predicate must retain the captured initial life.
            local ok, reason = callWarp(point, 180, current)
            AE.initialUsed = true
            AE.ready = nil
            L("AUTO_ENTRY_RESULT ticket=%s nonce=%s classification=automatic_entry alias=%s ok=%s native_retry_pass=false reason=%s gate=%s", ticket, nonce, alias, tostring(ok), tostring(reason), initialReason)
            return ok, reason
        end
        local loc, yaw = actorLoc(found), actorYaw(found)
        if not loc then return refused("trigger location unavailable") end
        local last = aeIdentity()
        if not aeSame(ids, last) or not valid(found) then return refused("action boundary changed") end
        AE.used, AE.ready = true, nil -- one attempt per lifecycle event, including native failure
        local point = { X = loc.X, Y = loc.Y, Z = loc.Z + 50 }
        -- A submitted Stalker entry is pending evidence, never consumed by the warp alone.
        -- Bind BEFORE the native call, whose synchronous callbacks can revoke it.
        local r, entry = T[key], nil
        local classification = AE.event.class
        if alias == "WLB_20_ZTrigger_005" and r and r.count == 0 and insideBox(r, point, 20) and
            ids.world == "/Game/Art/BG/WorldMap/E05_GreatDesert_P/E05_GreatDesert_P.E05_GreatDesert_P" then
            entry = { key = key, alias = alias, t = now(), p = point, yaw = yaw, address = r.a,
                world = ids.world, ids = ids, life = SP.life, gen = SP.gen, epoch = AE.epoch, armed = 0 }
            AE.submission = entry -- scalars only; not eligible or available to the learner
        end
        local ok, reason = callWarp(point, yaw)
        if entry then
            AE.submission = nil
            if ok and not entry.invalid and entry.life == SP.life and entry.gen == SP.gen and entry.epoch == AE.epoch and
                not AE.loading and not SP.dead and (W.st == nil or W.st == 0) and (W.bc == nil or W.bc == false) then SP.life.autoEntry = entry end
        end
        if ok and (alias == "SE_10_ZTrigger_001" or alias == "DED20_ZTrigger_011") then SPX.storyWarped(key, point, yaw) end
        L("AUTO_ENTRY_RESULT ticket=%s nonce=%s classification=%s alias=%s ok=%s native_retry_pass=false reason=%s",
            ticket, nonce, classification, alias, tostring(ok), tostring(reason))
        return ok, reason
    end
    -- AUTO_ENTRY_GATE_END

    local function readFull(o, fn)
        local r = {}
        local ok = pcall(function()
            r.alias = o.TriggerAlias:ToString(); r.bind = o.BindZoneAlias:ToString()
            r.count = o.InitialDoingCount; r.pending = o.bPendingCheck; r.active = o.bActiveTrigger
        end)
        if not ok then return nil end
        pcall(function() r.zone = o.ZoneAlias:ToString() end)
        pcall(function() r.btrig = o.BindTriggerAlias:ToString() end)
        pcall(function() r.inout = o.bInOutTrigger end)
        pcall(function() r.ttype = o.TriggerType end)
        pcall(function() r.dtype = o.DoingType end)
        pcall(function() r.ignoreCount = o.bIgnoreDoingCount end)
        pcall(function() r.ext = v3(o.BoxExtent) end)
        r.scale = { X = 1, Y = 1, Z = 1 }
        pcall(function() r.scale = v3(o:GetActorScale3D()) or r.scale end)
        r.loc = actorLoc(o)
        r.yaw = actorYaw(o)
        r.path = fn:match("^%S+ (.+)$") or fn
        r.level = fn:match("/([%w_]+)%.[%w_]+:PersistentLevel") or "?"
        r.name = fn:match("PersistentLevel%.([%w_]+)$") or fn
        r.cls = fn:match("^(%S+)") or "?"
        return r
    end
    local function interesting(r, p)
        local c = cat(r.alias)
        if c then return "catalog row " .. c.row end
        local z = zoneOf(r.alias, r.bind)
        if z then return "zone " .. z end
        if p and r.loc and dist(p, r.loc) < 20000 then return "near" end
        return nil
    end
    local function applyValues(k, r, cnt, pend, act, t, tPrev, p, src)
        if cnt == r.count and pend == r.pending and act == r.active then return end
        local how = nil
        if cnt ~= nil and r.count ~= nil and cnt < r.count then how = "count-drop"
        elseif r.pending == true and pend == false then how = "pending-done"
        elseif cnt ~= nil and r.count ~= nil and cnt > r.count then how = "REARM" end
        L("TCHG %s alias=%s count %s->%s pending %s->%s active %s->%s how=%s src=%s window=%.2fs eve=%s dEve=%.0f%s",
            k, r.alias, tostring(r.count), tostring(cnt), tostring(r.pending), tostring(pend), tostring(r.active), tostring(act),
            tostring(how), src, t - (tPrev or t), fv(p), dist(p, r.loc), r.int and (" [" .. r.int .. "]") or "")
        if how == "count-drop" and SPX.learnOnFire then pcall(SPX.learnOnFire, k, r, t, p) end
        if how == "count-drop" or how == "pending-done" then
            if cat(r.alias) then combatEntered = true end
            local c = SP.life.consumed
            c[#c + 1] = { key = k, alias = r.alias, t = t, tPrev = tPrev, how = how, p = p }
            if #c > 200 then table.remove(c, 1) end
        end
        if cnt ~= r.count then r.prevCount, r.changedAt = r.count, t end
        r.count, r.pending, r.active = cnt, pend, act
        if how == "count-drop" and r.prevCount == 1 and cnt == 0 and SPX.nativeFightConsume then
            SPX.nativeFightConsume(k, r, t)
        end
    end
    -- Exact no-theater route. These records contain scalars/Lua life tokens only;
    -- no UObject or learned INTRO file is retained by this branch.
    local NF = { epoch = 0 }
    local function nfAddress(a) return type(a) == "number" and a > 0 and a < 1e16 and a % 1 == 0 end
    local function nfSame(a, b)
        if not a or not b then return false end
        for _, k in ipairs({ "pc", "pawn", "ps", "pcm", "movement" }) do if a[k] ~= b[k] then return false end end
        return true
    end
    local function nfSnapshot(current, key, deathOK)
        -- A synchronous EndPlay can happen before a new record has any known
        -- addresses. Revoke that read even if the address is subsequently reused.
        local epoch, oldCurrent = SP.armEpoch, current
        current = function() return oldCurrent() and SP.armEpoch == epoch end
        local function read(fn)
            if not current() then return nil, false end
            local ok, v = pcall(fn)
            return v, ok and current()
        end
        local pc = read(getPC); if not pc then return end
        local pawn = read(function() return getPawn(pc) end); if not pawn then return end
        local ps = read(function() return getPS(pc) end); if not ps then return end
        local pcm = read(function() return getPCM(pc) end); if not pcm then return end
        local movement = read(function() return pawn.CharacterMovement end); if not movement then return end
        local ids = {}
        for k, o in pairs({ pc = pc, pawn = pawn, ps = ps, pcm = pcm, movement = movement }) do
            if read(function() return valid(o) end) ~= true then return end
            local a, ok = read(function() return addr(o) end)
            if not ok or not nfAddress(a) then return end
            ids[k] = a
        end
        local owner = read(function() return movement.CharacterOwner end)
        if not owner or read(function() return valid(owner) end) ~= true or
            read(function() return addr(owner) end) ~= ids.pawn then return end
        local ack = read(function() return pc.AcknowledgedPawn end)
        if not ack or read(function() return valid(ack) end) ~= true or
            read(function() return addr(ack) end) ~= ids.pawn then return end
        local name = read(function() return fullName(pawn) end)
        if type(name) ~= "string" or not name:match("^CH_P_EVE_01_Blueprint_C " .. NATIVE_FIGHT_WORLD:gsub("([^%w])", "%%%1") ..
            ":PersistentLevel%.CH_P_EVE_01_Blueprint_C_%d+$") then return end
        local r = T[key]
        if not r or r.alias ~= NATIVE_FIGHT_ALIAS or not r.present or not r.o then return end
        if read(function() return valid(r.o) end) ~= true then return end
        local address = read(function() return addr(r.o) end)
        if not nfAddress(address) or address ~= r.a then return end
        local live = read(function() return readTrig(r.o) end)
        if not live or live.active ~= true or live.pending ~= false then return end
        local alias = read(function() return r.o.TriggerAlias:ToString() end)
        if alias ~= NATIVE_FIGHT_ALIAS then return end
        local boxLoc = read(function() return actorLoc(r.o) end)
        local boxYaw = read(function() return actorYaw(r.o) end)
        local boxExt = read(function() return v3(r.o.BoxExtent) end)
        if not boxLoc or type(boxYaw) ~= "number" or boxYaw ~= boxYaw or not boxExt then return end
        local p = read(function() return actorLoc(pawn) end)
        local yaw = read(function() return actorYaw(pawn) end)
        if not p or type(yaw) ~= "number" or yaw ~= yaw then return end
        if not W.o or read(function() return valid(W.o) end) ~= true or
            read(function() return addr(W.o) end) ~= W.oa then return end
        local w = read(function() local st, bc = readW(W.o); return { st = st, bc = bc } end)
        if not w or w.bc ~= false or (deathOK and w.st ~= 1 and w.st ~= 3) or
            (not deathOK and w.st ~= 0) then return end
        if not deathOK then
            local ctx = read(function() return pc.CurrentLoadContext end); if not ctx then return end
            for _, field in ipairs({ "bIsPending", "bFillAndPending", "bWriteAndPending" }) do
                if read(function() return ctx[field] end) ~= false then return end
            end
            local vt = read(function() return pc:GetViewTarget() end)
            if not vt or read(function() return valid(vt) end) ~= true or
                read(function() return addr(vt) end) ~= ids.pawn then return end
            local pending, ok = read(function() return pcm.PendingViewTarget.Target end)
            if not ok then return end
            if pending ~= nil then
                local pendingValid, validOK = read(function() return pending:IsValid() end)
                if not validOK or pendingValid ~= false then return end
                local pendingAddress, addressOK = read(function() return pending:GetAddress() end)
                if not addressOK or pendingAddress ~= 0 then return end
            end
        end
        local mode = read(function() return movement.MovementMode end)
        local battle = read(function() return pawn.bBattleState end)
        if not current() then return end
        return { ids = ids, p = p, yaw = yaw, count = live.count, address = address,
            box = { loc = boxLoc, yaw = boxYaw, ext = boxExt },
            grounded = mode == 1 or mode == 2, mode = mode, battle = battle }
    end
    local function nfLearningCurrent(e)
        local enabled = readEnabled()
        return enabled == "1" and e and not e.invalid and e.epoch == NF.epoch and e.life == SP.life and e.gen == SP.gen and
            now() >= e.t and now() - e.t <= 2.5 and
            not SP.dead and W.st == 0 and W.bc == false and now() >= suspendUntil and now() >= SP.quietUntil and
            T[e.key] and T[e.key].a == e.address and T[e.key].present == true
    end
    SPX.nativeFightConsume = function(key, r, t)
        if r.alias ~= NATIVE_FIGHT_ALIAS then return end
        local e = { key = key, address = r.a, epoch = NF.epoch, life = SP.life, gen = SP.gen, t = t }
        local c = nfSnapshot(function() return nfLearningCurrent(e) end, key)
        if not c or c.count ~= 0 or (c.mode ~= 1 and c.mode ~= 2 and c.mode ~= 3) or not insideBox(c.box, c.p, 20) then
            L("NATIVE_FIGHT_LEARN_SKIP alias=%s count=%s mode=%s fresh entry/read/lifecycle unavailable", r.alias,
                c and tostring(c.count) or "?", c and tostring(c.mode) or "?"); return
        end
        e.ids = c.ids; NF.pending = e
        L("NATIVE_FIGHT_PENDING alias=%s native1->0 mode=%s bounded grounded sample only", r.alias, tostring(c.mode))
    end
    SPX.nativeFightTick = function(t)
        local e = NF.pending
        if not e then return end
        if not nfLearningCurrent(e) or t - e.t > 2.5 then
            NF.pending = nil; L("NATIVE_FIGHT_LEARN_SKIP alias=%s pending expired/revoked", NATIVE_FIGHT_ALIAS); return
        end
        if e.checked and t - e.checked < 0.1 then return end
        e.checked = t
        local c = nfSnapshot(function() return nfLearningCurrent(e) end, e.key)
        if not c or c.count ~= 0 or not nfSame(e.ids, c.ids) or not c.grounded or c.battle ~= true or
            not insideBox(c.box, c.p, 20) or not nfLearningCurrent(e) then return end
        e.point, e.yaw, e.world = c.p, c.yaw, NATIVE_FIGHT_WORLD
        SP.life.nativeFightEntry, NF.pending = e, nil
        L("NATIVE_FIGHT_LEARN alias=%s native1->0 grounded point=%s yaw=%.1f", NATIVE_FIGHT_ALIAS, fv(c.p), c.yaw)
    end
    SPX.nativeFightEligible = function(key)
        local e, life, epoch = SP.life.nativeFightEntry, SP.life, NF.epoch
        local function current() return e and not e.invalid and e.life == SP.life and SP.life == life and
            e.gen == SP.gen and e.epoch == NF.epoch and NF.epoch == epoch and W.bc == false and (W.st == 1 or W.st == 3) end
        if not current() or e.key ~= key then return nil, "no grounded native entry in this life" end
        local c = nfSnapshot(current, key, true)
        -- Native DEAD may clear the combat-mode flag. Live learning and
        -- post-warp confirmation still require true; death requires its fresh widget.
        if not c or c.count ~= 0 or type(c.battle) ~= "boolean" or not nfSame(e.ids, c.ids) or
            not insideBox(c.box, c.p, 20) or not insideBox(c.box, e.point, 20) or not current() then return nil, "native fight identity/arena changed" end
        return key, NATIVE_FIGHT_ALIAS, e
    end
    SPX.nativeFightCurrent = function(a)
        local enabled = readEnabled()
        return enabled == "1" and a and not a.invalid and S == a.state and S.gen == a.sgen and S.story == a.key and
            S.nativeFight == a and S.nativeFightEntry == a.entry and S.nativeFightGen == S.gen and
            not a.entry.invalid and a.epoch == NF.epoch and a.life == SP.life and a.gen == SP.gen and
            not SP.dead and W.st == 0 and W.bc == false and (S.phase == "settle" or S.phase == "native_fight_wait") and
            T[a.key] and T[a.key].present == true and T[a.key].a == a.address
    end
    SPX.nativeFightTarget = function(key)
        local e, r = S.nativeFightEntry, T[key]
        if not e or e.invalid or e.key ~= key or S.nativeFightGen ~= S.gen or e.epoch ~= NF.epoch or
            not r or not r.present or r.a ~= e.address or r.count ~= 1 or r.prevCount ~= 0 or
            not r.changedAt or not S.tRev or r.changedAt < S.tRev or r.pending ~= false or r.active ~= true or
            not insideBox(r, e.point, 20) then return nil, "native fight entry/rearm unavailable" end
        return { e = { key = key, alias = NATIVE_FIGHT_ALIAS }, point = e.point, yaw = e.yaw, nativeFight = true }
    end
    SPX.nativeFightWarpBegin = function(key)
        local target = SPX.nativeFightTarget(key)
        if not target then return end
        local a = { state = S, sgen = S.gen, life = SP.life, gen = SP.gen, epoch = NF.epoch,
            entry = S.nativeFightEntry, key = key, address = T[key].a, at = now() }
        S.nativeFight = a
        local c = nfSnapshot(function() return SPX.nativeFightCurrent(a) end, key)
        if not c or c.count ~= 1 or not c.grounded or not insideBox(c.box, a.entry.point, 20) or
            not SPX.nativeFightCurrent(a) then a.invalid = true; return end
        a.ids = c.ids
        return a
    end
    SPX.nativeFightActionCurrent = function(a, pc, ps)
        if not SPX.nativeFightCurrent(a) then return false end
        local c = nfSnapshot(function() return SPX.nativeFightCurrent(a) end, a.key)
        if not c or c.count ~= 1 or not c.grounded or not nfSame(a.ids, c.ids) or not insideBox(c.box, a.entry.point, 20) then return false end
        local ca, pa = pc and addr(pc), ps and addr(ps)
        return SPX.nativeFightCurrent(a) and (not pc or ca == a.ids.pc) and (not ps or pa == a.ids.ps)
    end
    SPX.nativeFightReady = function(a)
        if not SPX.nativeFightCurrent(a) then return false end
        local c = nfSnapshot(function() return SPX.nativeFightCurrent(a) end, a.key)
        local r = T[a.key]
        return c and c.count == 0 and r.prevCount == 1 and r.changedAt and r.changedAt >= a.at and
            c.grounded and c.battle == true and nfSame(a.ids, c.ids) and insideBox(c.box, c.p, 20) and SPX.nativeFightCurrent(a)
    end
    -- One renderer cut on this confirmed E9 return, before dropping its mask.
    -- Keep the PCM local to this game-thread callback; revalidate the full attempt.
    SPX.nativeFightCameraCut = function(a)
        local epoch = SP.armEpoch
        local function current() return SP.armEpoch == epoch and SPX.nativeFightCurrent(a) end
        local function read(fn)
            if not current() then return nil, false end
            local ok, v = pcall(fn)
            return v, ok and current()
        end
        local pc, pcOK = read(getPC)
        if not pcOK or not pc then return false, "current controller unavailable" end
        local pcm, pcmOK = read(function() return getPCM(pc) end)
        if not pcmOK or not pcm then return false, "current camera unavailable" end
        local ca, caOK = read(function() return addr(pc) end)
        local ma, maOK = read(function() return addr(pcm) end)
        if not caOK or not maOK or ca ~= a.ids.pc or ma ~= a.ids.pcm then
            return false, "camera identity changed"
        end
        if not SPX.nativeFightReady(a) or not current() then return false, "native entry authority changed" end
        local ok, err = pcall(function() pcm:SetGameCameraCutThisFrame() end) -- reflected void/no arguments
        if not current() then return false, "camera call authority revoked" end
        return ok, ok and nil or err
    end
    SPX.nativeFightEndPlay = function(a)
        local function matches(e) return e and (e.address == a or (e.ids and
            (e.ids.pc == a or e.ids.pawn == a or e.ids.ps == a or e.ids.pcm == a or e.ids.movement == a))) end
        if matches(NF.pending) then NF.pending.invalid = true; NF.pending = nil end
        if matches(SP.life.nativeFightEntry) then SP.life.nativeFightEntry.invalid = true end
        if matches(S.nativeFightEntry) then S.nativeFightEntry.invalid = true end
        if matches(S.nativeFight) then S.nativeFight.invalid = true end
    end
    SPX.nativeFightLoad = function() NF.epoch = NF.epoch + 1; NF.pending = nil end
    SPX.nativeFightScene = function()
        NF.pending = nil
        if S.nativeFight then S.nativeFight.invalid = true end
    end
    local function describe(k, r, p)
        return string.format("%s alias=%s cls=%s bind=%s zone=%s btrig=%s count=%s pending=%s active=%s inout=%s ttype=%s dtype=%s ignoreCount=%s loc=%s yaw=%.1f ext=%s scale=%s dEve=%.0f",
            k, r.alias, r.cls, tostring(r.bind), tostring(r.zone), tostring(r.btrig), tostring(r.count), tostring(r.pending), tostring(r.active),
            tostring(r.inout), tostring(r.ttype), tostring(r.dtype), tostring(r.ignoreCount), fv(r.loc), r.yaw or 0, fv(r.ext), fv(r.scale), dist(p, r.loc))
    end
    local function snap(why, p, force)
        if fighting() then return end
        cacheArea()
        cacheCombat(p)
        local t = now()
        local c0 = os.clock()
        local ok, list = pcall(function() return FindAllOf("SBZoneTriggerActor") or {} end)
        if not ok then L("SNAP %s FindAllOf failed: %s", why, tostring(list)) return end
        local c1 = os.clock()
        local seen, nNew, nBack, nGone, nAll = {}, 0, 0, 0, 0
        for _, o in ipairs(list) do
            if valid(o) then
                local a = addr(o)
                local k = a and byAddr[a]
                if k then
                    local r0 = T[k]
                    local okA, al = pcall(function() return o.TriggerAlias:ToString() end)
                    if not okA or not r0 or al ~= r0.alias then k = nil end
                end
                if k then
                    local r = T[k]
                    r.o, r.a = o, a
                    if not r.present then
                        r.present = true; nBack = nBack + 1
                        if r.int then L("TBACK %s alias=%s away=%.1fs (same object)", k, r.alias, t - (r.goneAt or t)) end
                    end
                    if r.int or (p and dist(p, r.loc) < 60000) then
                        local okV, cnt, pend, act = pcall(function() return o.InitialDoingCount, o.bPendingCheck, o.bActiveTrigger end)
                        if okV then applyValues(k, r, cnt, pend, act, t, SP.snapAt, p, "snap") end
                    end
                else
                    local fn = fullName(o)
                    if not fn:find("Default__", 1, true) then
                        local r = readFull(o, fn)
                        if r then
                            k = r.level .. "." .. r.name
                            if a then byAddr[a] = k end
                            local old = T[k]
                            if not old then
                                r.int = interesting(r, p)
                                r.present, r.firstAt = true, t
                                r.o, r.a = o, a
                                T[k] = r
                                nNew = nNew + 1
                                if r.int then L("TSEEN %s [%s]", describe(k, r, p), r.int) end
                            else
                                local wasPresent = old.present
                                old.path, old.present = r.path, true
                                old.o, old.a = o, a
                                if not wasPresent then
                                    nBack = nBack + 1
                                    if old.int then
                                        L("TBACK %s alias=%s reloaded after %.1fs: count %s->%s pending %s->%s active %s->%s (last value before unload -> now)",
                                            k, old.alias, t - (old.goneAt or t), tostring(old.count), tostring(r.count), tostring(old.pending),
                                            tostring(r.pending), tostring(old.active), tostring(r.active))
                                    end
                                end
                                applyValues(k, old, r.count, r.pending, r.active, t, SP.snapAt, p, wasPresent and "snap" or "reload")
                            end
                        end
                    end
                end
                if k then seen[k] = true; nAll = nAll + 1 end
            end
        end
        for k, r in pairs(T) do
            if r.present and not seen[k] then
                r.present, r.goneAt, r.o = false, t, nil
                nGone = nGone + 1
                if r.int then L("TGONE %s alias=%s last count=%s pending=%s active=%s dEve=%.0f", k, r.alias, tostring(r.count), tostring(r.pending), tostring(r.active), dist(p, r.loc)) end
            end
        end
        local ms = (os.clock() - c0) * 1000
        SP.snapAt, SP.snapMs = t, ms
        local st = SP.stats
        st.n, st.sum, st.max = st.n + 1, st.sum + ms, math.max(st.max, ms)
        if force or nNew > 0 or nBack > 0 or nGone > 0 or why ~= "idle" then
            L("SNAP %s triggers=%d new=%d back=%d gone=%d findAll=%.1fms total=%.1fms eve=%s", why, nAll, nNew, nBack, nGone, (c1 - c0) * 1000, ms, fv(p))
        end
        watch = {}
        for k2, r in pairs(T) do
            if r.present and r.int and (cat(r.alias) or (p and dist(p, r.loc) < 30000)) then watch[#watch + 1] = k2 end
        end
    end
    local function watchTick(p)
        local t = now()
        for _, k in ipairs(watch) do
            local r = T[k]
            -- StaticFindObject by path cost ~14 ms per call in this UE4SS (22 per tick = 3 FPS in
            -- Matrix 11); the object kept from the last snapshot is checked like the released trigger poll.
            local o = r and r.present and r.o
            if o and valid(o) and addr(o) == r.a then
                local okV, cnt, pend, act = pcall(function() return o.InitialDoingCount, o.bPendingCheck, o.bActiveTrigger end)
                if okV then applyValues(k, r, cnt, pend, act, t, SP.watchAt, p, "watch") end
            elseif r then
                r.o, r.present, r.count, r.active, r.pending = nil, false, nil, nil, nil
            end
        end
        SP.watchAt = t
    end
    local function catalogState(why, p)
        local parts = {}
        for _, r in pairs(T) do
            local c = cat(r.alias)
            if c then
                parts[#parts + 1] = string.format("%s(row %d %s %s)=%s count=%s active=%s pending=%s d=%.0f", r.alias, c.row, c.mode, c.cls,
                    r.present and "loaded" or "unloaded", tostring(r.count), tostring(r.active), tostring(r.pending), dist(p, r.loc))
            end
        end
        table.sort(parts)
        L("CATALOG %s: %s", why, #parts > 0 and table.concat(parts, " | ") or "no catalog intro trigger seen in this game session")
    end
    local function lifeTarget(life)
        for i = #life.consumed, 1, -1 do
            local e = life.consumed[i]
            local c = cat(e.alias)
            if c then return e, c end
        end
        return nil, nil
    end
    -- Carry only a previously eligible life after the native revival-item state.
    -- Keep scalar identities, never retain UObject references for this outcome.
    local function pumpIdentity(d)
        if not d or d.invalid or not d.pumpKey or d.gen ~= SP.gen then return false end
        if not d.widget or d.widget == 0 or not d.pawn or d.pawn == 0 or
            not d.pc or d.pc == 0 or not d.trigger or d.trigger == 0 or
            type(d.world) ~= "string" or d.world:sub(1, 1) ~= "/" then return false end
        local r = T[d.pumpKey]
        return d.world == world() and d.widget == W.oa and d.pawn == addr(getPawn()) and
            d.pc == addr(getPC()) and r and r.present and r.a == d.trigger and
            r.o and valid(r.o) and addr(r.o) == d.trigger
    end
    local function discardPump(why)
        SP.pendingPump = nil
        if SP.pumpLife and SP.life == SP.pumpLife.life then
            SP.life = { t = now(), consumed = {}, why = why }
        end
        SP.pumpLife = nil
    end
    local function carryPump(d)
        local e = d and lifeTarget(d.life)
        if not d or not d.tPump or d.tRev or not e or e.key ~= d.pumpKey or not pumpIdentity(d) then return false end
        SP.life, SP.pumpLife, SP.pendingPump = d.life, d, nil
        L("PUMP_LIFE gen=%d native state4; keeping previously eligible %s", d.gen, e.alias)
        return true
    end
    local function dryE(d, p, nb)
        local e, c = lifeTarget(d.life)
        if e and e.alias == NATIVE_FIGHT_ALIAS then
            local admitted = S.story == e.key and S.nativeFightEntry == d.life.nativeFightEntry and S.nativeFightGen == S.gen
            L("DRY_E gen=%d alias=%s native-fight grounded-life admission=%s (no INTRO cache/movie proof)", d.gen, e.alias, tostring(admitted))
            return
        end
        local why = {}
        local r = e and T[e.key]
        if not e then why[#why + 1] = "E3 no catalog intro trigger consumed in this life"
        else
            if c.mode ~= "INTRO" and c.mode ~= "RETRY" then why[#why + 1] = "E3/E6 mode " .. c.mode end
            local dd = r and dist(p, r.loc) or 1e30
            if dd > 12000 then why[#why + 1] = string.format("E4 died %.0f uu from the trigger", dd) end
            if nb == 0 then why[#why + 1] = "E4 nobody in battle" end
            local Ld = SP.learned[e.alias]
            if not Ld then why[#why + 1] = "E5 no learned point"
            elseif r and not insideBox(r, Ld.point, 20) then why[#why + 1] = "E5 learned point outside the box" end
        end
        d.target = e and e.key or nil
        local cons = {}
        for _, x in ipairs(d.life.consumed) do cons[#cons + 1] = string.format("%s(%s %.1fs ago)", x.alias, x.how, now() - x.t) end
        L("DRY_E gen=%d target=%s row=%s mode=%s class=%s -> %s | consumed this life: %s", d.gen, e and e.alias or "none", c and tostring(c.row) or "-",
            c and c.mode or "-", c and c.cls or "-", #why == 0 and "ELIGIBLE (the story rules would act on this death)" or ("no action: " .. table.concat(why, "; ")),
            #cons > 0 and table.concat(cons, ", ") or "none")
    end
    local function dryG(P, p, m)
        local d = P.d
        local k = d and d.target
        local r = k and T[k]
        if not r then L("DRY_G gen=%d +%ss no target (E3 failed at death)", P.gen, tostring(m)) return end
        local Ld = SP.learned[r.alias]
        local why = {}
        if not r.present then why[#why + 1] = "G1 trigger not loaded" end
        if not (r.count and r.count >= 1) then why[#why + 1] = "G2 not re-armed (count=" .. tostring(r.count) .. ")" end
        if not r.active then why[#why + 1] = "G2 inactive" end
        if r.pending then why[#why + 1] = "G3 pending" end
        if not Ld then why[#why + 1] = "E5 no learned point" elseif not insideBox(r, Ld.point, 20) then why[#why + 1] = "E5 point outside box" end
        L("DRY_G gen=%d +%ss target=%s loaded=%s count=%s active=%s pending=%s eveToTrigger=%.0f learned=%s -> %s", P.gen, tostring(m), r.alias,
            tostring(r.present), tostring(r.count), tostring(r.active), tostring(r.pending), dist(p, r.loc), Ld and fv(Ld.point) or "none",
            #why == 0 and "WOULD WARP (all gates pass)" or ("normal respawn: " .. table.concat(why, "; ")))
    end
    local function nearest(p, n)
        local out = {}
        for k, r in pairs(T) do
            if r.present and r.loc then out[#out + 1] = { d = dist(p, r.loc), s = string.format("%s[%s %s] d=%.0f", r.alias, r.cls, k, dist(p, r.loc)) } end
        end
        table.sort(out, function(x, y) return x.d < y.d end)
        local parts = {}
        for i = 1, math.min(n, #out) do parts[#parts + 1] = out[i].s end
        return table.concat(parts, "; ")
    end
    local function nativeEntryCurrent(e)
        -- Pure scalar authority after any reflected or validation callback.
        return readEnabled() == "1" and e.confirmed and not e.invalid and
            SP.life.autoEntry == e and e.life == SP.life and e.gen == SP.gen and e.epoch == AE.epoch and
            not AE.loading and not SP.dead and W.st == 0 and W.bc == false and now() - e.t <= tonumber(cfg.hold_max)
    end
    local function armLifeCurrent(e)
        -- Scalar authority only: callers recheck after reflected/cache validation.
        return e and e.life == SP.life and e.gen == SP.gen and e.epoch == SP.armEpoch and
            e.state == S and e.sgen == S.gen and not SP.dead and W.st == 0 and W.bc == false
    end
    local function armEntryCurrent(e)
        local pend = SP.life.pendingEntries and SP.life.pendingEntries[e.alias]
        local r = T[e.key]
        return armLifeCurrent(e) and SP.armLearn == e and pend == e.pending and
            pend.life == SP.life and pend.key == e.key and pend.t == e.t and now() - e.t <= 3.0 and
            SP.armSeq[e.alias] == e.seq and e.seq.world == pend.world and e.seq.t <= e.t and
            r == e.trigger and r.alias == e.alias and r.present == true and r.o == e.actor and
            r.a == pend.address and r.a == e.address and insideBox(r, pend.point, 20)
    end
    -- New Abaddon derived entries never use wrappers that hide multiple reflected
    -- reads. Each returned object/property is cancellable before the next access.
    local function abaddonRead(current, fn)
        if not current() then return nil, false end
        local ok, value = pcall(fn)
        if not current() then return nil, false end
        return value, ok
    end
    local function abaddonIdentity(current)
        local read = function(fn) return abaddonRead(current, fn) end
        local viewport, ok = read(function() return engine.GameViewport end)
        if not ok or not viewport then return nil end
        local gi; gi, ok = read(function() return viewport.GameInstance end)
        if not ok or not gi then return nil end
        local players; players, ok = read(function() return gi.LocalPlayers end)
        if not ok or not players then return nil end
        local player; player, ok = read(function() return players[1] end)
        if not ok or not player then return nil end
        local pc; pc, ok = read(function() return player.PlayerController end)
        if not ok or not pc then return nil end
        local pcValid; pcValid, ok = read(function() return pc:IsValid() end)
        if not ok or pcValid ~= true then return nil end
        local pawn; pawn, ok = read(function() return pc.Pawn end)
        if not ok or not pawn then return nil end
        local pawnValid; pawnValid, ok = read(function() return pawn:IsValid() end)
        if not ok or pawnValid ~= true then return nil end
        local address; address, ok = read(function() return pawn:GetAddress() end)
        if not ok or not address or address == 0 then return nil end
        local name; name, ok = read(function() return pawn:GetFullName() end)
        if not ok or type(name) ~= "string" then return nil end
        local w = name:match(" (/[^:]+):") or name
        if w:sub(1, 1) ~= "/" then return nil end
        return { pc = pc, pawn = pawn, address = address, world = w }
    end
    local function storeStoryLearned(alias, key, point, yaw, armed, intro, nativeEntry, armEntry, publishCurrent)
        local old = SPX.storyReadLearned and SPX.storyReadLearned(alias) or SP.learned[alias]
        if (publishCurrent and not publishCurrent()) or (nativeEntry and not nativeEntryCurrent(nativeEntry)) or
            (armEntry and (readEnabled() ~= "1" or not armEntryCurrent(armEntry))) then return nil, false end
        local oldValid = storyRecordValid(alias, old)
        if (publishCurrent and not publishCurrent()) or (armEntry and not armEntryCurrent(armEntry)) then return nil, false end
        if oldValid then return old, false end
        local r = { format = STORY_LEARN_FORMAT, alias = alias, bind = "story", intro = intro == "trigger-entry" and intro or storyIntroName(intro),
            point = { X = point.X, Y = point.Y, Z = point.Z }, yaw = yaw or 0, armed = armed, at = now() }
        local newValid = storyRecordValid(alias, r)
        if not newValid or (publishCurrent and not publishCurrent()) or (armEntry and not armEntryCurrent(armEntry)) then return nil, false end
        local path = learnedFile(alias)
        local existing, readError, readCode = io.open(path, "r")
        if not existing and readCode ~= 2 then
            L("LEARN_DRY %s: existing cache read refused errno=%s", alias, tostring(readCode)); return nil, false
        end
        if existing then
            existing:close()
            if (publishCurrent and not publishCurrent()) or (nativeEntry and not nativeEntryCurrent(nativeEntry)) or
            (armEntry and (readEnabled() ~= "1" or not armEntryCurrent(armEntry))) then return nil, false end
            local retained = false
            for i = 1, 32 do
                local dest = path .. ".rejected-m4-" .. i
                local check = io.open(dest, "r")
                if check then check:close()
                else
                    if (publishCurrent and not publishCurrent()) or (armEntry and (readEnabled() ~= "1" or not armEntryCurrent(armEntry))) then return nil, false end
                    retained = os.rename(path, dest) and true or false; break
                end
            end
            if not retained then L("LEARN_DRY %s: old cache retention refused", alias); return nil, false end
        end
        if (publishCurrent and not publishCurrent()) or (nativeEntry and not nativeEntryCurrent(nativeEntry)) or
            (armEntry and (readEnabled() ~= "1" or not armEntryCurrent(armEntry))) then return nil, false end
        local f = io.open(path, "w")
        if not f then L("LEARN_DRY %s: cache open refused", alias); return nil, false end
        f:write(string.format("format=%s trigger=%s alias=%s bind=story point=%.3f,%.3f,%.3f yaw=%.3f armed=%d intro=%s\n",
            r.format, key, alias, r.point.X, r.point.Y, r.point.Z, r.yaw, r.armed, r.intro)); f:close()
        SP.learned[alias] = r
        return r, true
    end
    local function learnStoryIntro(sq)
        -- Case69 streamed Eve below the box before any inside sample. Require the
        -- exact current-world native entrance AND its observed 0->1 count change.
        local e = SP.life.autoEntry
        if e and not e.confirmed and e.life == SP.life and e.gen == SP.gen and e.epoch == AE.epoch and not AE.loading and not SP.dead and
            W.st == 0 and W.bc == false and readEnabled() == "1" and
            e.t <= sq.t and now() - e.t <= tonumber(cfg.hold_max) and
            storyIntroMatches(e.alias, sq.name) and sq.full and
            sq.full:match("^LevelSequencePlayer (/[^:]+):PersistentLevel%.[%w_]+%.AnimationPlayer$") == e.world then
            local pc, pawn = getPC(), getPawn()
            local ps, pcm = getPS(pc), getPCM(pc)
            local ids = { pc = addr(pc), pawn = addr(pawn), ps = addr(ps), pcm = addr(pcm), world = world() }
            local live = valid(pc) and valid(pawn) and valid(ps) and valid(pcm) and aeSame(e.ids, ids)
            for _, k in ipairs({ "pc", "pawn", "ps", "pcm" }) do
                if not ids[k] or ids[k] == 0 or AE.ended[ids[k]] then live = false end
            end
            local ok, loadClear = pcall(function()
                local c = pc.CurrentLoadContext
                return c.bIsPending == false and c.bFillAndPending == false and c.bWriteAndPending == false
            end)
            local r = T[e.key]
            if live and ok and loadClear and r and r.alias == e.alias and r.present and r.active == true and r.pending == false and
                r.a == e.address and e.address and e.address ~= 0 and valid(r.o) and addr(r.o) == e.address and
                r.prevCount == 0 and r.count == 1 and r.changedAt and r.changedAt >= e.t and r.changedAt <= sq.t + 1.5 and
                insideBox(r, e.p, 20) and
                -- Reflected getters above can invoke lifecycle callbacks. No native
                -- read follows this final scalar guard before consumption.
                readEnabled() == "1" and now() - e.t <= tonumber(cfg.hold_max) and
                SP.life.autoEntry == e and e.life == SP.life and e.gen == SP.gen and e.epoch == AE.epoch and
                not AE.loading and not SP.dead and W.st == 0 and W.bc == false then
                e.how, e.tPrev = "native-auto-entry", e.t
                SP.life.consumed[#SP.life.consumed + 1] = e
                combatEntered = true
                e.confirmed = true -- retain callback revocation through learned-file publication
                L("AUTO_ENTRY_CONFIRMED alias=%s point=%s native=%s count=0->1", e.alias, fv(e.p), sq.name)
            end
        end
        local best, bd, bestWarp = nil, 1e9, false
        for _, e in ipairs(SP.life.consumed) do
            -- Corrupter streaming can skip all inside samples and create its native scene after 4 s.
            local corrupterWarp = e.alias == "DED20_ZTrigger_011" and e.how == "restart-warp"
            local stalkerEntry = e.alias == "WLB_20_ZTrigger_005" and e.how == "native-auto-entry"
            local window = (corrupterWarp or stalkerEntry) and tonumber(cfg.hold_max) or 3.0
            if storyIntroMatches(e.alias, sq.name) and e.t >= sq.t - window and (e.tPrev or e.t) <= sq.t + 1.5 then
                local dd = math.abs(e.t - sq.t)
                local r = T[e.key]
                local scopedWarp = ((e.alias == "SE_10_ZTrigger_001" or corrupterWarp) and e.how == "restart-warp") or stalkerEntry
                -- Native SE001 entry can clamp Eve before a closer count-drop.
                -- Keep the successful pre-entrance warp, with live identity/box
                -- proof, ahead of that later observation of the same entry.
                local captured = scopedWarp and
                    e.t <= sq.t and storyIntroMatches(e.alias, sq.name) and e.p and e.address and e.address ~= 0 and
                    e.world == world() and r and r.alias == e.alias and r.present and r.a == e.address and
                    r.o and valid(r.o) and addr(r.o) == e.address and insideBox(r, e.p, 20) and true or false
                if (not scopedWarp or captured) and ((captured and not bestWarp) or (captured == bestWarp and dd < bd)) then
                    best, bd, bestWarp = e, dd, captured
                end
            end
        end
        if not best then L("LEARN_DRY seq=%s: no trigger consumed within -3..+1.5 s", sq.name) return end
        if not storyIntroMatches(best.alias, sq.name) then L("LEARN_DRY seq=%s: not the native entrance for %s", sq.name, best.alias) return end
        local r = T[best.key]
        local hi = best.t + 0.001   -- the last sample at or before the tick the drop was seen
        local pt, how = nil, nil
        -- An intro observed inside the trigger already supplies its actual entry sample.
        -- Keep that sample ahead of an older ring position taken before the crossing.
        if (best.how == "intro-inside" or best.how == "restart-warp" or best.how == "native-auto-entry") and best.p and r and insideBox(r, best.p, 20) then
            pt, how = { p = best.p, yaw = best.yaw or r.yaw or 0 }, "captured-entry"
        end
        if not pt then
            for i = #SP.ring, 1, -1 do
                local s = SP.ring[i]
                if s.t <= hi and s.t >= (best.tPrev or best.t) - 2.5 and r and insideBox(r, s.p, 20) then pt, how = s, "last-inside" break end
            end
        end
        if not pt and r then
            -- the sample taken just after the drop was seen, if it continues her walk (as 0.4.0's fire-tick rule)
            for i = 2, #SP.ring do
                local s, pr = SP.ring[i], SP.ring[i - 1]
                if s.t > hi and s.t <= hi + 0.15 and dist(s.p, pr.p) < 120 and insideBox(r, s.p, 20) then pt, how = s, "fire-tick" break end
            end
        end
        local c = cat(best.alias)
        L("LEARN_DRY seq=%s trigger=%s alias=%s how=%s fired in (%.2f,%.2f] s vs seq %.2f -> point=%s yaw=%s catalog=%s",
            sq.name, best.key, best.alias, best.how, (best.tPrev or best.t) - sq.t, best.t - sq.t, 0.0, pt and (fv(pt.p) .. " (" .. how .. ")") or "none inside the box",
            pt and string.format("%.1f", pt.yaw) or "-", c and ("row " .. c.row .. " " .. c.mode) or "no")
        -- Belial can relocate Eve at the same tick as its native entrance.
        -- Only the already matched fire+entrance may certify this provisional point.
        local publishCurrent, edgePending
        if not pt and best.alias == "SE_06_ZTrigger_005" and r then
            local pending = SP.life.pendingEntries and SP.life.pendingEntries[best.alias]
            if pending and pending.derived and pending.key == best.key then
                local life, state, gen, sgen, epoch = SP.life, S, SP.gen, S.gen, SP.armEpoch
                local actor, address = r.o, r.a
                local function scalarsCurrent()
                    return SP.life == life and pending.life == life and S == state and S.gen == sgen and
                        SP.gen == gen and SP.armEpoch == epoch and not SP.dead and W.st == 0 and W.bc == false and
                        SP.life.pendingEntries and SP.life.pendingEntries[best.alias] == pending and
                        T[best.key] == r and r.present and r.o == actor and r.a == address
                end
                local function current()
                    if not scalarsCurrent() then return false end
                    local w = world()
                    if not scalarsCurrent() then return false end
                    local alive = valid(actor)
                    if not scalarsCurrent() then return false end
                    local a = addr(actor)
                    return readEnabled() == "1" and scalarsCurrent() and alive and a == address and
                        pending.address == address and pending.world == w and pending.t <= sq.t + 0.15 and
                        sq.t - pending.t <= 3 and now() - pending.t <= 3 and insideBox(r, pending.point, 20) and
                        sq.full:match("^LevelSequencePlayer (/[^:]+):PersistentLevel%.[%w_]+%.AnimationPlayer$") == w
                end
                if current() then
                    pt, how = { p = pending.point, yaw = pending.yaw }, "projected-entry"
                    publishCurrent = current
                end
            end
        end
        if best.alias == "WLB_50_ZTrigger_010" then
            local pending = SP.life.pendingEntries and SP.life.pendingEntries[best.alias]
            if pending and pending.edge then
                local edge, actor, address = pending.edge, r and r.o, r and r.a
                local function scalarsCurrent()
                    return SP.life == edge.life and pending.life == edge.life and SP.gen == edge.gen and
                        S == edge.state and S.gen == edge.sgen and SP.armEpoch == edge.epoch and
                        not SP.dead and W.st == 0 and W.bc == false and SP.life.pendingEntries and
                        SP.life.pendingEntries[best.alias] == pending and T[best.key] == r and r and r.present and
                        r.o == actor and r.a == address and pending.address == address
                end
                local function current()
                    if not scalarsCurrent() then return false end
                    local live, ok = abaddonRead(scalarsCurrent, function() return actor:IsValid() end)
                    if not ok or live ~= true then return false end
                    local a; a, ok = abaddonRead(scalarsCurrent, function() return actor:GetAddress() end)
                    if not ok or a ~= address then return false end
                    local identity = abaddonIdentity(scalarsCurrent)
                    if not identity then return false end
                    local enabled = readEnabled()
                    return enabled == "1" and scalarsCurrent() and identity.address == edge.pawn and
                        pending.world == identity.world and pending.key == best.key and pending.t <= sq.t + 0.15 and
                        sq.t - pending.t <= 3 and now() - pending.t <= 3 and best.how == "count-drop" and
                        r.prevCount == 1 and r.count == 0 and r.changedAt == pending.t and
                        storyIntroMatches(best.alias, sq.name) and insideBox(r, pending.point, 20) and
                        sq.full:match("^LevelSequencePlayer (/[^:]+):PersistentLevel%.[%w_]+%.AnimationPlayer$") == identity.world
                end
                if not current() then return end
                pt, how = { p = pending.point, yaw = pending.yaw }, "observed-edge-inset"
                publishCurrent, edgePending = current, pending
            end
        end
        if pt then
            if edgePending then
                if not publishCurrent() then return end
            elseif not r or not r.present or not r.o or not valid(r.o) or addr(r.o) ~= r.a then return end
            local pending = edgePending or (SP.life.pendingEntries and SP.life.pendingEntries[best.alias])
            if not edgePending and not (pending and pending.key == best.key and pending.life == SP.life and pending.world == world() and
                pending.address == r.a and pending.t <= sq.t and sq.t - pending.t <= 3 and insideBox(r, pending.point, 20)) then pending = nil end
            if not bestWarp and pending then pt = { p = pending.point, yaw = pending.yaw } end
            local old = SPX.storyReadLearned(best.alias)
            local armed = old and old.armed or (pending and pending.armed) or best.armed or (best.alias == "SE_10_ZTrigger_001" and 0 or 1)
            storeStoryLearned(best.alias, best.key, pt.p, pt.yaw, armed, sq.name,
                best.how == "native-auto-entry" and best or nil, nil, publishCurrent)
        end
    end
    local function startPost(why)
        local d = SP.dead
        local t = now()
        SP.post = { t0 = t, why = why, gen = d and d.gen or SP.gen, d = d, marks = {}, nextSample = 0 }
        SP.pendingPump, SP.pumpLife = nil, nil
        if not carryPump(d) then
            SP.life = { t = t, consumed = {}, why = "respawn gen " .. tostring(d and d.gen) }
            -- Hidden can be processed before native state4. This prior life is
            -- unavailable until the next matching transition confirms the pump.
            if d and not d.tRev and pumpIdentity(d) then
                SP.pendingPump = { d = d, emptyLife = SP.life }
            end
        end
        L("RESPAWN_START gen=%s via %s dtRevive=%s dtDead=%s states=%s ctx=%s", tostring(d and d.gen), why,
            d and d.tRev and f1(t - d.tRev) or "-", d and f1(t - d.t) or "-", d and table.concat(d.states, ">") or "-", loadCtx())
        SP.dead = nil
    end
    local function postTick(t, p, pawn)
        local P = SP.post
        local dt = t - P.t0
        if p and P.lastP and dist(p, P.lastP) < 3 then P.stable = P.stable or t else P.stable = nil end
        P.lastP = p
        if not P.respawnPos and p and P.stable and t - P.stable >= 0.3 then
            P.respawnPos = p
            L("RESPAWNED gen=%d at %s yaw=%.1f (still since +%.2fs) fromDeathSpot=%.0f world=%s nearest triggers: %s", P.gen, fv(p),
                pawn and actorYaw(pawn) or 0, P.stable - P.t0, dist(p, P.d and P.d.p), world(), nearest(p, 6))
        end
        if dt >= P.nextSample and dt <= 25 then
            P.nextSample = P.nextSample + 1.0
            local vt, vtn = viewTargetInfo()
            local tgt = P.d and P.d.target and T[P.d.target]
            L("POST gen=%d +%.1fs eve=%s fromDeath=%.0f toTarget=%s eveBattle=%s view=%s", P.gen, dt, fv(p), dist(p, P.d and P.d.p),
                tgt and string.format("%.0f", dist(p, tgt.loc)) or "-", pawn and battleState(pawn) or "?",
                vt and ((pawn and same(vt, pawn)) and "Eve" or tostring(vtn)) or tostring(vtn))
        end
        for _, m in ipairs({ 0.5, 2, 6, 12, 25 }) do
            if dt >= m and not P.marks[m] then
                P.marks[m] = true
                catalogState("post+" .. m, p)
                dryG(P, p, m)
            end
        end
        if dt > 26 then L("POST_END gen=%d", P.gen); SP.post, SP.pendingPump = nil, nil end
    end
    local function handle(what, p, pawn)
        local d = SP.dead
        if not PROBE_ON and what ~= "hidden" then return end
        if what == "death" and d then
            L("DEATH gen=%d state=%s eve=%s yaw=%s world=%s ctx=%s", d.gen, tostring(d.st), fv(d.p), f1(d.yaw), world(), loadCtx())
            catalogState("death", p)
            dryE(d, d.p or p, -1)   -- no character scan at death (it was a 40 ms hitch)
        elseif what == "revive" and d then
            L("REVIVE gen=%d (the player's own choice) state=%s dtDead=%.2f ctx=%s", d.gen, d.states[#d.states], d.tRev - d.t, loadCtx())
        elseif what == "pump" and d then
            L("REVIVAL ITEM used (ComaRevival) gen=%d dtDead=%.2f eve=%s", d.gen, d.tPump - d.t, fv(p))
        elseif what == "exit" and d then
            L("DEATH SCREEN EXIT gen=%d dtDead=%.2f", d.gen, now() - d.t)
            SP.dead = nil
        elseif what == "hidden" and d then
            startPost("death widget hidden (" .. table.concat(d.states, ">") .. ")")
        end
    end

    SPX.widget = function(st, bc, what)
        if bc == true then return end
        if st == SP.lastSt then return end
        local t = now()
        local prev = SP.lastSt
        SP.lastSt = st
        local pawn = getPawn()
        local p = pawn and actorLoc(pawn)
        L("WIDGET %s -> %s (%s) eve=%s dtDeath=%s", tostring(prev), tostring(st), what, fv(p), SP.dead and f1(t - SP.dead.t) or "-")
        if st ~= 0 and st ~= 4 then SP.pendingPump = nil end
        if st == 2 or st == 5 or st == 6 then discardPump("revive or Exit") end
        if st == 4 and not SP.dead then
            local pending = SP.pendingPump
            SP.pendingPump = nil
            if prev == 0 and pending and pending.emptyLife == SP.life and SP.post and SP.post.d == pending.d and
                t >= SP.post.t0 and t - SP.post.t0 <= 26 then
                pending.d.tPump = t
                pending.d.states[#pending.d.states + 1] = "4"
                carryPump(pending.d)
            end
        end
        if (st == 1 or st == 3) and not SP.dead then
            SPX.autoEntryDeath()
            SP.gen = SP.gen + 1
            SP.pumpLife = nil -- The new death has its own validation/outcome.
            local key = S.phase == "dead" and S.story or nil
            local r = key and T[key]
            SP.dead = { gen = SP.gen, t = t, p = p, yaw = pawn and actorYaw(pawn), st = st, life = SP.life, states = { tostring(st) },
                pumpKey = key, world = world(), widget = W.oa, pawn = pawn and addr(pawn), pc = addr(getPC()), trigger = r and r.a }
            SP.q[#SP.q + 1] = "death"
            SP.hotUntil = t + 30
        elseif SP.dead then
            local d = SP.dead
            d.states[#d.states + 1] = tostring(st)
            if st == 2 or st == 5 then d.tRev = t; SP.q[#SP.q + 1] = "revive"
            elseif st == 4 then d.tPump = t; SP.q[#SP.q + 1] = "pump"
            elseif st == 6 then SP.q[#SP.q + 1] = "exit"
            elseif st == 0 then d.tHidden = t; SP.q[#SP.q + 1] = "hidden" end
        end
    end
    SPX.event = function(name, st, bc)
        if bc == true then return end
        L("W_EVENT %s state=%s dtDeath=%s", name, tostring(st), SP.dead and f1(now() - SP.dead.t) or "-")
    end
    SPX.newSeq = function(fn)
        if W.bc == true or not bossIntro(fn) then return end
        SPX.nativeFightScene()
        SPX.autoEntryScene(fn)
        SP.seqNew[#SP.seqNew + 1] = { t = now(), name = fn }
    end
    SPX.finish = function() SP.finish = SP.finish + 1 end
    SPX.note = function(msg) L("%s", msg) end
    local okN = pcall(NotifyOnNewObject, "/Script/SB.SBZoneTriggerActor", function()
        SP.snapDue = math.max(SP.snapDue or 0, now() + 1.5)   -- plain value only; the object is not kept
    end)
    L("new-trigger notify: %s", tostring(okN))
    local function storyLearned(alias)
        if storyRecordValid(alias, SP.learned[alias]) then return SP.learned[alias] end
        SP.learned[alias] = nil
        local f = io.open(learnedFile(alias), "r")
        if not f then return nil end
        local txt = f:read(4097) or ""; f:close()
        if #txt > 4096 then return nil end
        local fields = {}
        for k, v in txt:gmatch("([%w_]+)=([^%s]+)") do
            if fields[k] then return nil end
            fields[k] = v
        end
        if fields.format ~= STORY_LEARN_FORMAT or fields.alias ~= alias or fields.bind ~= "story" or not fields.point then return nil end
        local x, y, z = fields.point:match("^(%-?[%d%.]+),(%-?[%d%.]+),(%-?[%d%.]+)$")
        local r = { format = fields.format, alias = alias, bind = fields.bind, intro = fields.intro,
            point = { X = tonumber(x), Y = tonumber(y), Z = tonumber(z) }, yaw = tonumber(fields.yaw), armed = tonumber(fields.armed), at = now() }
        if not storyRecordValid(alias, r) then return nil end
        SP.learned[alias] = r
        return r
    end
    SPX.storyReadLearned = storyLearned
    -- some story fights have no intro cutscene (Karakuri on a finished save): the spot is learned
    -- when the boss trigger itself fires, from Eve's last position inside its box.
    local function belialEntryPoint(r, t)
        if r.alias ~= "SE_06_ZTrigger_005" or not r.loc or not r.ext then return nil end
        local a = math.rad(-(r.yaw or 0)); local co, si = math.cos(a), math.sin(a)
        local hx = r.ext.X - math.min(20, r.ext.X * 0.02)
        local hy = r.ext.Y - math.min(20, r.ext.Y * 0.02)
        local hz = r.ext.Z - math.min(20, r.ext.Z * 0.02)
        for i = #SP.ring, 2, -1 do
            local s = SP.ring[i]
            if s.t < t - 0.001 and t - s.t <= 0.25 then
                local dx, dy, dz = s.p.X - r.loc.X, s.p.Y - r.loc.Y, s.p.Z - r.loc.Z
                local lx, ly = dx * co - dy * si, dx * si + dy * co
                local px, py = math.max(-hx, math.min(hx, lx)), math.max(-hy, math.min(hy, ly))
                local ox, oy = lx - px, ly - py
                if math.abs(dz) <= hz and ox * ox + oy * oy > 0 and ox * ox + oy * oy <= 120 * 120 then
                    for j = i - 1, 1, -1 do
                        local pr = SP.ring[j]
                        if s.t - pr.t > 0.25 then break end
                        local vx, vy, vz = s.p.X - pr.p.X, s.p.Y - pr.p.Y, s.p.Z - pr.p.Z
                        local travel = vx * vx + vy * vy + vz * vz
                        if travel >= 1 then
                            local vlx, vly = vx * co - vy * si, vx * si + vy * co
                            if travel <= 120 * 120 and math.abs(vz) <= 20 and
                                (ox == 0 or ox * vlx < 0) and (oy == 0 or oy * vly < 0) then
                                return { p = { X = r.loc.X + px * co + py * si,
                                    Y = r.loc.Y - px * si + py * co, Z = s.p.Z }, yaw = s.yaw or r.yaw or 0, derived = true }
                            end
                            break
                        end
                    end
                end
            end
        end
        return nil
    end
    -- The native Abaddon scene starts at its rotated raw-box edge. Only this
    -- observed count-drop may project its real XY sample into the unchanged inset.
    local function abaddonEdgePoint(r, t, p)
        if r.alias ~= "WLB_50_ZTrigger_010" or r.count ~= 1 or not r.loc or not r.ext or not p then return nil end
        local function finite(v) return type(v) == "number" and v == v and v > -math.huge and v < math.huge end
        for _, axis in ipairs({ "X", "Y", "Z" }) do
            if not finite(p[axis]) or not finite(r.loc[axis]) or not finite(r.ext[axis]) then return nil end
        end
        if not finite(r.yaw) then return nil end
        local sx, sy, sz = r.ext.X, r.ext.Y, r.ext.Z
        if sx <= 0 or sy <= 0 or sz <= 0 then return nil end
        local a = math.rad(-r.yaw); local co, si = math.cos(a), math.sin(a)
        local dx, dy, dz = p.X - r.loc.X, p.Y - r.loc.Y, p.Z - r.loc.Z
        local lx, ly = dx * co - dy * si, dx * si + dy * co
        local hx, hy, hz = sx - math.min(20, sx * 0.02), sy - math.min(20, sy * 0.02), sz - math.min(20, sz * 0.02)
        if math.abs(lx) > sx or math.abs(ly) > sy or math.abs(dz) > hz or insideBox(r, p, 20) then return nil end
        -- One unit on a clipped axis protects the three-decimal cache round-trip.
        local px = math.abs(lx) > hx and math.max(-hx + 1, math.min(hx - 1, lx)) or lx
        local py = math.abs(ly) > hy and math.max(-hy + 1, math.min(hy - 1, ly)) or ly
        if (lx - px)^2 + (ly - py)^2 > 20^2 then return nil end
        local point = { X = r.loc.X + px * co + py * si, Y = r.loc.Y - px * si + py * co, Z = p.Z }
        if not insideBox(r, point, 20) then return nil end
        local e = { life = SP.life, gen = SP.gen, state = S, sgen = S.gen, epoch = SP.armEpoch }
        local actor, triggerAddress = r.o, r.a
        local function current()
            return e.life == SP.life and e.gen == SP.gen and e.state == S and e.sgen == S.gen and
                e.epoch == SP.armEpoch and not SP.dead and W.st == 0 and W.bc == false and
                r.present and r.o == actor and r.a == triggerAddress and r.count == 1
        end
        local identity = abaddonIdentity(current)
        if not identity then return nil end
        local rotation, ok = abaddonRead(current, function() return identity.pawn:K2_GetActorRotation() end)
        if not ok or not rotation then return nil end
        local yaw; yaw, ok = abaddonRead(current, function() return rotation.Yaw end)
        if not ok or not finite(yaw) then return nil end
        e.pawn, e.world = identity.address, identity.world
        return { p = point, yaw = yaw, derived = true, edge = e }
    end
    SPX.learnOnFire = function(k, r, t, p)
        if r.alias == NATIVE_FIGHT_ALIAS then return end -- no INTRO cache or point inferred from the warp
        local arm = ARM_CREATED_ENTRANCE[r.alias] and { life = SP.life, gen = SP.gen,
            epoch = SP.armEpoch, state = S, sgen = S.gen }
        if r.alias == "WLB_20_ZTrigger_005" or r.alias == "WLA_10_ZTrigger_016" then return end -- native entrance must supply its learning proof
        local c = cat(r.alias)
        if not storyRestartSupported(r.alias, c) or storyLearned(r.alias) then return end
        if arm and not armLifeCurrent(arm) then return end
        local pt = nil
        for i = #SP.ring, 1, -1 do
            local s0 = SP.ring[i]
            if s0.t <= t + 0.001 and s0.t >= t - 2.5 and insideBox(r, s0.p, 20) then pt = s0 break end
        end
        if not pt and p and insideBox(r, p, 20) then pt = { p = p, yaw = r.yaw or 0 } end
        if not pt then pt = abaddonEdgePoint(r, t, p) end
        if not pt then pt = belialEntryPoint(r, t) end
        if not pt then L("LEARN_FIRE %s: no Eve sample inside the box", r.alias) return end
        if c.mode == "INTRO" then
            -- Keep the actual fire point provisional until its own named entrance is observed.
            if arm then
                local w = world()
                if not armLifeCurrent(arm) then return end
                SP.life.pendingEntries = SP.life.pendingEntries or {}
                local pend = { key = k, life = SP.life, address = r.a, world = w, t = t,
                    point = { X = pt.p.X, Y = pt.p.Y, Z = pt.p.Z }, yaw = pt.yaw or 0, armed = r.count or 1 }
                SP.life.pendingEntries[r.alias] = pend
                -- Object creation is rearm evidence; this entry still needs a cinematic view.
                local seq = SP.armSeq[r.alias]
                if seq and seq.t <= t and seq.world == w then
                    arm.alias, arm.key, arm.t, arm.pending, arm.seq = r.alias, k, t, pend, seq
                    arm.trigger, arm.actor, arm.address = r, r.o, r.a
                    SP.armLearn = arm
                end
            else
                SP.life.pendingEntries = SP.life.pendingEntries or {}
                local edge = pt.edge
                local w = edge and edge.world or world()
                if edge then
                    local function current()
                        return edge.life == SP.life and edge.gen == SP.gen and edge.state == S and edge.sgen == S.gen and
                            edge.epoch == SP.armEpoch and not SP.dead and W.st == 0 and W.bc == false
                    end
                    if not current() then return end -- recheck after world()
                    local enabled = readEnabled()
                    if not current() or enabled ~= "1" then return end
                end
                SP.life.pendingEntries[r.alias] = { key = k, life = SP.life, address = r.a, world = w, t = t,
                    point = { X = pt.p.X, Y = pt.p.Y, Z = pt.p.Z }, yaw = pt.yaw or 0, armed = r.count or 1, derived = pt.derived, edge = edge }
            end
            return
        end
        -- The existing Nest RETRY entry is trigger evidence, never an INTRO name claim.
        local _, created = storeStoryLearned(r.alias, k, pt.p, pt.yaw, r.count or 1, "trigger-entry")
        if created then L("LEARN_FIRE %s point=%s yaw=%.1f (native retry trigger entry)", r.alias, fv(pt.p), pt.yaw or 0) end
    end
    -- how long to wait for an intro after the warp before fading in: count-up triggers never show the
    -- fire itself (their intro came 1.0 s after the warp in the 19:32 run)
    SPX.storyNeedsNativeRetry = function(key)
        local r = T[key]
        return r and r.alias == NEST_RETRY_ALIAS
    end
    SPX.stalkerCameraContext = function() return SP.life, SP.armEpoch, SP.loadPostAt end
    SPX.storyIntroMatches = function(key, name, t, fireAt)
        local r = T[key]
        return r and storyIntroMatches(r.alias, name) and ((r.alias ~= "SE_10_ZTrigger_001" and r.alias ~= "WLB_20_ZTrigger_005" and r.alias ~= "DED20_ZTrigger_011" and r.alias ~= "WLA_10_ZTrigger_016") or t >= fireAt)
    end
    SPX.corrupterArm = function(key)
        local r, pc = T[key], getPC()
        local pawn = pc and getPawn(pc)
        if not r or r.alias ~= "DED20_ZTrigger_011" or not r.present or not valid(r.o) then return nil end
        local c = { key = key, trigger = r.a, world = world(), life = SP.life, gen = S.gen,
            pc = pc and addr(pc), pawn = pawn and addr(pawn), widget = W.oa }
        for _, k in ipairs({ "trigger", "pc", "pawn", "widget" }) do if c[k] == nil or c[k] == 0 then return nil end end
        if not valid(W.o) or addr(W.o) ~= c.widget or addr(r.o) ~= c.trigger then return nil end
        return c
    end
    SPX.corrupterValid = function(c)
        local r, pc = T[c.key], getPC()
        local pawn = pc and getPawn(pc)
        return not c.invalid and cfg.enabled ~= "0" and c.gen == S.gen and c.life == SP.life and c.world == world() and
            pc and pawn and addr(pc) == c.pc and addr(pawn) == c.pawn and
            W.st == 0 and valid(W.o) and W.oa == c.widget and addr(W.o) == c.widget and
            r and r.alias == "DED20_ZTrigger_011" and r.present and valid(r.o) and addr(r.o) == c.trigger
    end
    SPX.storyNoIntroWait = function(key)
        local r = T[key]
        local Ld = r and storyLearned(r.alias)
        return (Ld and Ld.armed and Ld.armed < 1) and 2.5 or 0.6
    end
    SPX.storyArmCreated = function(key)
        local r = T[key]
        return r ~= nil and ARM_CREATED_ENTRANCE[r.alias] == true
    end
    -- This respawn's own zone reset re-created the entrance (between the Revive and the warp) and the
    -- re-armed trigger was then observed consumed (1 -> 0) after the warp, on the same live object.
    SPX.storyArmWarpCurrent = function(e)
        local r = e and T[e.key]
        return armLifeCurrent(e) and not e.invalid and S.phase == e.phase and S.story == e.key and
            S.tRev == e.tRev and r == e.trigger and r.alias == e.alias and r.present == true and
            r.o == e.actor and e.actor ~= nil and r.a == e.address and SP.armSeq[e.alias] == e.seq
    end
    SPX.storyArmWarpBegin = function(key)
        local r = T[key]
        if not r or not ARM_CREATED_ENTRANCE[r.alias] then return nil end
        local e = { life = SP.life, gen = SP.gen, epoch = SP.armEpoch, state = S, sgen = S.gen,
            phase = S.phase, tRev = S.tRev, key = key, alias = r.alias, trigger = r,
            actor = r.o, address = r.a, seq = SP.armSeq[r.alias] }
        if not SPX.storyArmWarpCurrent(e) then return nil end
        local w = world()
        if not SPX.storyArmWarpCurrent(e) then return nil end
        local live = valid(e.actor)
        if not SPX.storyArmWarpCurrent(e) then return nil end
        local a = live and addr(e.actor)
        if not SPX.storyArmWarpCurrent(e) or not live or a ~= e.address then return nil end
        e.world = w
        return e
    end
    SPX.storyArmConsumed = function(key, tRev, tFire)
        local r = T[key]
        local seq = r and ARM_CREATED_ENTRANCE[r.alias] and SP.armSeq[r.alias]
        local e = S.armAuthority
        if not seq or not tRev or not tFire or not e then return false end
        local actor, address = r.o, r.a
        local function current()
            return armLifeCurrent(e) and S.phase == "intro_wait" and S.story == key and
                S.tRev == tRev and S.tFire == tFire and e.tRev == tRev and e.tFire == tFire and
                e.key == key and e.trigger == r and e.actor == actor and e.address == address and e.seq == seq and
                T[key] == r and SP.armSeq[r.alias] == seq and r.present == true and
                r.o == actor and actor ~= nil and r.a == address
        end
        if not current() then return false, current end
        local w = world()
        if not current() then return false, current end
        local live = valid(actor)
        if not current() then return false, current end
        local a = live and addr(actor)
        -- No reflected read follows this last cancellation check.
        return current() and seq.world == w and seq.t >= tRev and seq.t <= tFire and live and
            a == address and r.prevCount == 1 and r.count == 0 and r.changedAt ~= nil and r.changedAt >= tFire, current
    end
    -- the restart's own warp counts as walking into the fight for the next death (a count-up trigger may not
    -- change again, so nothing else would mark it)
    SPX.storyWarped = function(key, point, yaw, armAttempt)
        local r = T[key]
        if not r then return end
        if ARM_CREATED_ENTRANCE[r.alias] and S.story == key and S.phase == "settle" then
            if not SPX.storyArmWarpCurrent(armAttempt) then return false end
            armAttempt.tFire = S.tFire
            S.armAuthority = armAttempt -- retain the PRE-call epoch/identity, never adopt post-call authority
        end
        local cons = SP.life.consumed
        cons[#cons + 1] = { key = key, alias = r.alias, t = now(), tPrev = now(), how = "restart-warp",
            p = point and { X = point.X, Y = point.Y, Z = point.Z }, yaw = yaw, address = r.a, world = world(), armed = r.count }
        if armAttempt then return SPX.storyArmWarpCurrent(armAttempt) end
    end
    SPX.storyFired = function(key)
        local r = T[key]
        if not r or not r.present or not r.o or not valid(r.o) or addr(r.o) ~= r.a or r.count == nil then return false end
        -- Democrawler retains count=1 through some retries: that value proves no new fight.
        -- Its observed native entrance must confirm the warp instead.
        if r.alias == "SE_10_ZTrigger_001" or r.alias == "WLB_20_ZTrigger_005" or r.alias == "DED20_ZTrigger_011" or r.alias == "WLA_10_ZTrigger_016" then return false end
        local Ld = storyLearned(r.alias)
        return r.count ~= ((Ld and Ld.armed) or 1)
    end
    -- some boss triggers count up when entered (Democrawler 0 -> 1) instead of down; the boss intro
    -- starting while Eve is inside a catalog trigger marks it walked into, and its value before that is kept
    -- as the "ready" value the respawn must bring back.
    SPX.introInside = function(t, p, pawn, name)
        if not p then return end
        for k, r in pairs(T) do
            local c = cat(r.alias)
            if c and c.mode == "INTRO" and storyIntroMatches(r.alias, name) and r.present and insideBox(r, p, 20) then
                combatEntered = true
                local yaw = pawn and actorYaw(pawn) or 0
                local cons = SP.life.consumed
                local last = cons[#cons]
                if not (last and last.key == k and t - last.t < 3.0) then
                    cons[#cons + 1] = { key = k, alias = r.alias, t = t, tPrev = t, how = "intro-inside", p = p, yaw = yaw, armed = (r.changedAt and t - r.changedAt < 1.5 and r.prevCount) or r.count or 1 }
                end
                -- Persistence waits for learnStoryIntro's matched entrance and fire/warp point.
                -- A cinematic movement sample cannot overwrite or preempt that point.
            end
        end
    end
    local function nestSceneValid(scene)
        local r = scene and T[scene.key]
        local e = lifeTarget(SP.life)
        return scene and scene.life == SP.life and scene.world == world() and
            e and e.key == scene.key and e.alias == NEST_RETRY_ALIAS and
            r and r.alias == NEST_RETRY_ALIAS and r.a == scene.address and r.present and
            r.o and valid(r.o) and addr(r.o) == scene.address
    end
    SPX.nestSceneStart = function(name, t)
        -- Every new cinematic invalidates previous remote-arena evidence.
        SP.life.nestScene, SP.life.nestArena = nil, nil
        if W.bc == true or not nestArenaIntro(name) then return end
        local e = lifeTarget(SP.life)
        local r = e and T[e.key]
        if not e or e.alias ~= NEST_RETRY_ALIAS or not r then return end
        local scene = { life = SP.life, key = e.key, address = r.a, world = world(), t = t }
        if nestSceneValid(scene) then SP.life.nestScene = scene end
    end
    SPX.nestSceneFinish = function(t)
        local scene = SP.life.nestScene
        if t and nestSceneValid(scene) and t > scene.t and not scene.finished then scene.finished = t end
    end
    local function captureNestArena(t, p, pawn)
        local scene = SP.life.nestScene
        if not scene or not scene.finished or SP.life.nestArena then return end
        if not nestSceneValid(scene) or t - scene.finished > 15 then SP.life.nestScene = nil; return end
        local r = T[scene.key]
        local view = viewTargetInfo()
        -- Phase2 can finish at P1: wait for actual remote battle with Eve's view back.
        -- Freeze the first proved point once; never follow Eve or persist coordinates.
        if W.st ~= 0 or not p or battleState(pawn) ~= "true" or not same(view, pawn) or
            dist(p, r.loc) <= 12000 then return end
        SP.life.nestRemote = true -- same-life tombstone survives later cinematic invalidation
        SP.life.nestArena = { life = SP.life, key = scene.key, address = scene.address, world = scene.world,
            point = { X = p.X, Y = p.Y, Z = p.Z } }
        L("NEST_ARENA key=%s point=%s (native scene completed; remote battle)", scene.key, fv(p))
    end
    SPX.storyEligible = function()
        if SP.pumpLife and not pumpIdentity(SP.pumpLife) then discardPump("pump identity changed") end
        local pawn = getPawn(); local p = pawn and actorLoc(pawn)
        local e, c = lifeTarget(SP.life)
        if not e then return nil, "no boss intro trigger walked into in this life" end
        if e.alias == NATIVE_FIGHT_ALIAS then return SPX.nativeFightEligible(e.key) end
        if not storyRestartSupported(e.alias, c) then return nil, e.alias .. " mode " .. tostring(c.mode) end
        local r = T[e.key]
        if not r or not p then return nil, "died away from " .. e.alias end
        local arena = e.alias == NEST_RETRY_ALIAS and SP.life.nestArena
        if e.alias == NEST_RETRY_ALIAS and SP.life.nestRemote then
            -- Once the game moved this life to P2, invalidation cannot restore entry/camp eligibility.
            if not arena or not nestSceneValid(arena) or dist(p, arena.point) > 12000 then
                return nil, "died away from native Nest arena"
            end
        elseif dist(p, r.loc) > 12000 then return nil, "died away from " .. e.alias end
        if e.alias == "SE_06_ZTrigger_005" then
            local Ld = storyLearned(e.alias)
            if not Ld or not insideBox(r, Ld.point, 20) then return nil, "E5 no learned point for " .. e.alias end
        end
        return e.key, e.alias
    end
    SPX.storyTarget = function(key)
        local r = T[key]
        if not r then return nil, "story target unknown" end
        if r.alias == NATIVE_FIGHT_ALIAS then return SPX.nativeFightTarget(key) end
        local Ld = storyLearned(r.alias)
        if not r.present or not r.o or not valid(r.o) or addr(r.o) ~= r.a then
            r.o, r.present, r.count, r.active, r.pending = nil, false, nil, nil, nil
            return nil, "G1 " .. r.alias .. " not loaded"
        end
        local live = readTrig(r.o)
        if not live then return nil, "G1 " .. r.alias .. " unreadable" end
        r.count, r.active, r.pending = live.count, live.active, live.pending
        -- count-up triggers (Democrawler: 0 -> 1 at the intro) stay at 1 after the respawn, so the re-arm check
        -- only applies to the count-down kind
        local armed = Ld and Ld.armed
        if not (armed and armed < 1) and not (r.count and r.count >= 1) then return nil, "G2 " .. r.alias .. " not re-armed" end
        if not r.active then return nil, "G2 " .. r.alias .. " inactive" end
        if r.pending then return nil, "G3 " .. r.alias .. " pending" end
        if not Ld then return nil, "E5 no learned point for " .. r.alias end
        if not insideBox(r, Ld.point, 20) then return nil, "E5 learned point outside " .. r.alias end
        return { e = { key = key, alias = r.alias }, point = Ld.point, yaw = Ld.yaw }
    end
    -- Developer teleport (marker only): warp-to.txt holds a trigger alias (Eve is put at that
    -- trigger, which starts its fight like walking in) or "x y z [yaw]". One use per file; the file is removed.
    SPX.warpTo = function(line, autoPaused)
        if line:find("AUTO_ENTRY_", 1, true) then return SPX.autoEntryWarp(line, autoPaused) end
        if not PROBE_ON then return end
        local x, y, z, yw = line:match("^%s*(%-?[%d%.]+)%s+(%-?[%d%.]+)%s+(%-?[%d%.]+)%s*(%-?[%d%.]*)")
        if x then
            local okW, why = callWarp({ X = tonumber(x), Y = tonumber(y), Z = tonumber(z) }, tonumber(yw) or 0)
            L("WARP_DEV point (%s,%s,%s) ok=%s %s", x, y, z, tostring(okW), tostring(why))
            return
        end
        local alias = line:match("^%s*([%w_]+)")
        if not alias then L("WARP_DEV: empty request") return end
        local list = {}
        for _, r in pairs(T) do if r.present and r.o then list[#list + 1] = r.o end end
        local found, foundKey, near = nil, nil, {}
        local pawn = getPawn(); local p = pawn and actorLoc(pawn)
        for _, o in ipairs(list) do
            if valid(o) then
                local okA, al = pcall(function() return o.TriggerAlias:ToString() end)
                if okA and al == alias then
                    found = o
                    for k, r in pairs(T) do if r.present and r.o == o then foundKey = k; break end end
                    break
                end
                if okA and al and al:sub(1, #alias - 3) == alias:sub(1, #alias - 3) then near[#near + 1] = al .. "@" .. fv(actorLoc(o)) end
            end
        end
        if not found then
            L("WARP_DEV %s: trigger not loaded here; same-zone triggers loaded: %s", alias, table.concat(near, " "))
            return
        end
        local loc, tyaw = actorLoc(found), actorYaw(found)
        local point = { X = loc.X, Y = loc.Y, Z = loc.Z + 50 }
        local okW, why = callWarp(point, tyaw)
        if okW and (alias == "SE_10_ZTrigger_001" or alias == "DED20_ZTrigger_011") and foundKey then
            SPX.storyWarped(foundKey, point, tyaw)
        end
        L("WARP_DEV %s -> %s yaw=%.1f from eve=%s ok=%s %s", alias, fv(loc), tyaw or 0, fv(p), tostring(okW), tostring(why))
    end   -- poll's cost meter writes here, never to the main log
    SPX.endPlay = function(a)
        SP.armEpoch = SP.armEpoch + 1
        SPX.nativeFightEndPlay(a)
        SPX.autoEntryEndPlay(a)
        local function matches(d)
            return d and (a == d.widget or a == d.pawn or a == d.pc or a == d.trigger)
        end
        if matches(S.corrupter) then S.corrupter.invalid = true end
        if matches(SP.dead) then SP.dead.invalid = true end
        if SP.pendingPump and matches(SP.pendingPump.d) then SP.pendingPump.d.invalid = true; SP.pendingPump = nil end
        if matches(SP.pumpLife) then discardPump("pump identity EndPlay") end
        local k = byAddr[a]
        if k and T[k] then T[k].o, T[k].present = nil, false end
        byAddr[a] = nil
    end
    SPX.loadMap = function(which)
        SPX.autoEntryLoad(which)
        local t = now()
        if which == "pre" then
            SPX.nativeFightLoad()
            SP.loadPreAt = t
            local d = SP.dead
            L("LOADMAP pre deathOpen=%s revived=%s dtRevive=%s", tostring(d ~= nil), tostring(d and d.tRev ~= nil), d and d.tRev and f1(t - d.tRev) or "-")
            for _, r in pairs(T) do r.o = nil; if r.present then r.present, r.goneAt = false, t end end
            T, byAddr, watch = {}, {}, {}
            SP.dead, SP.post, SP.lastSt, SP.snapDue = nil, nil, nil, nil
            SP.pendingPump, SP.pumpLife = nil, nil
            SP.life = { t = t, consumed = {}, why = "map load" }
            SP.ring, SP.seqNew, SP.seqs, SP.q, SP.finish = {}, {}, {}, {}, 0
            SP.armSeq, SP.armLearn = {}, nil
            SP.snapAt, SP.ringAt, SP.watchAt = -100, -1, -100
        else
            SP.loadPostAt = t
            SP.snapDue = t + 2.0
            L("LOADMAP post %.2fs after pre", t - (SP.loadPreAt or t))
            SP.quietUntil = t + 3.0
            SP.lastSt = nil
            SP.active = false
        end
    end
    SPX.tick = function(t)
        if W.bc == true then
            if SP.active then SP.active = false; L("probe paused: Boss Challenge") end
            SP.seqNew, SP.q = {}, {}
            return
        end
        if t < SP.quietUntil then return end
        local pawn = getPawn()
        if not pawn then return end
        local p = actorLoc(pawn)
        captureNestArena(t, p, pawn)
        if not SP.active then
            SP.active = true
            L("story active: world=%s eve=%s widget=%s/%s ctx=%s", world(), fv(p), tostring(W.st), tostring(W.bc), loadCtx())
        end
        if p and t - SP.ringAt >= 0.045 then
            SP.ringAt = t
            SP.ring[#SP.ring + 1] = { t = t, p = p, yaw = actorYaw(pawn) }
            if #SP.ring > 1500 then table.remove(SP.ring, 1) end
        end
        local q = SP.q
        SP.q = {}
        for _, what in ipairs(q) do handle(what, p, pawn) end
        if SP.dead and SP.dead.tRev and SP.loadPostAt and SP.loadPostAt > SP.dead.tRev and not SP.post then startPost("map load after the Revive") end
        if #SP.seqNew > 0 then
            for _, s in ipairs(SP.seqNew) do
                local nm = s.name:match("PersistentLevel%.([%w_]+)") or s.name:match("([%w_]+)%.AnimationPlayer") or s.name
                if SPX.introInside then pcall(SPX.introInside, t, p, pawn, nm) end
                L("SEQ_NEW %s eve=%s deathOpen=%s post=%s full=%s", nm, fv(p), tostring(SP.dead ~= nil), SP.post and f1(t - SP.post.t0) or "-", s.name)
                for alias in pairs(ARM_CREATED_ENTRANCE) do
                    if storyIntroMatches(alias, nm) then SP.armSeq[alias] = { t = s.t, name = nm, world = world() } end
                end
                SP.seqs[#SP.seqs + 1] = { t = s.t, name = nm, full = s.name, learnAt = t + 1.5 }
            end
            SP.seqNew = {}
            SP.hotUntil = math.max(SP.hotUntil, t + 6)
            watchTick(p)
        end
        for i = #SP.seqs, 1, -1 do
            local sq = SP.seqs[i]
            if t >= sq.learnAt then table.remove(SP.seqs, i); learnStoryIntro(sq) end
        end
        -- a full trigger scan (~40 ms) only at start, 2 s after a map load and 1.5 s after new trigger
        -- actors appear (streaming), and never during a death, a restart, an intro or the fight after it
        if SP.snapAt < 0 then SP.snapDue = t end
        if SP.snapDue and t >= SP.snapDue and S.phase == "idle" and not SP.dead and not fighting() then
            SP.snapDue = nil
            snap("scan", p)
        end
        if t - SP.watchAt >= 0.1 then watchTick(p) end
        SPX.nativeFightTick(t)
        local al = SP.armLearn
        if al then
            -- Camera ownership is entry evidence, never an IsPlaying/render claim.
            local pend, seq, r = al.pending, al.seq, al.trigger
            local live = armEntryCurrent(al)
            if live then
                local w = world()
                live = armEntryCurrent(al) and pend.world == w
            end
            if live then
                local validActor = valid(al.actor)
                live = armEntryCurrent(al) and validActor
            end
            if live then
                local a = addr(al.actor)
                live = armEntryCurrent(al) and a == al.address
            end
            if not live then
                if SP.armLearn == al then SP.armLearn = nil end
                L("LEARN_DRY %s: arm-created entry authority changed or expired", al.alias)
            else
                local learned = storyLearned(al.alias)
                if not armEntryCurrent(al) then
                    if SP.armLearn == al then SP.armLearn = nil end
                    return
                end
                if learned then SP.armLearn = nil
                else
                    local vt, vtn = viewTargetInfo()
                    if not armEntryCurrent(al) then
                        if SP.armLearn == al then SP.armLearn = nil end
                        return
                    end
                    if vt and type(vtn) == "string" and vtn:match("^CineCameraActor%s") then
                        local _, created = storeStoryLearned(al.alias, al.key, pend.point, pend.yaw, pend.armed, seq.name, nil, al)
                        if SP.armLearn == al then SP.armLearn = nil end
                        if created then
                            L("LEARN_ARM %s point=%s yaw=%.1f seq=%s cinematic view %.2f s after the trigger entry stored=true", al.alias,
                                fv(pend.point), pend.yaw or 0, seq.name, t - al.t)
                        end
                    end
                end
            end
        end
        if PROBE_ON and SP.post then postTick(t, p, pawn) elseif SP.post and t - SP.post.t0 > 26 then SP.post = nil end
        if SP.finish > 0 then L("SEQ_FINISH x%d eve=%s", SP.finish, fv(p)); SP.finish = 0 end
        local st = SP.stats
        if PROBE_ON and t - st.at >= 60 then
            local nk, nw = 0, #watch
            for _ in pairs(T) do nk = nk + 1 end
            L("STATS 60s: snapshots=%d avg=%.1fms max=%.1fms triggersKnown=%d watched=%d eve=%s world=%s", st.n, st.n > 0 and st.sum / st.n or 0, st.max, nk, nw, fv(p), world())
            st.n, st.sum, st.max, st.at = 0, 0, 0, t
        end
    end
    if PROBE_ON then
        L("SBInstantBossRestart %s story diagnostics on; developer controls enabled", VERSION)
        log("story diagnostics on: logging to story-probe.log")
    end
end

-- death widget BP hooks: every state change arrives here, in the same game tick
local DW = "/Game/Art/UI/Widget/HUD/WB_MainHUD_Dead.WB_MainHUD_Dead_C:"
local bpHooked, bpTryAt = false, -10
local lastSt = "init"
local function onWidget(ctx, what)
    if now() < suspendUntil then return end
    local o = nil
    pcall(function() o = ctx:get() end)
    local st, bc = nil, nil
    if valid(o) then st, bc = readW(o) end
    log(string.format("widget %s state=%s bc=%s phase=%s", what, tostring(st), tostring(bc), S.phase))
    if st == nil then return end
    W.st, W.bc, W.at, W.o, W.oa = st, bc, now(), o, addr(o)
    local stS = tostring(st) .. "/" .. tostring(bc)
    if stS ~= lastSt then log("deadW state " .. lastSt .. " -> " .. stS .. " phase=" .. S.phase .. " (" .. what .. ")"); lastSt = stS end
    local ok, e = pcall(cycle, st, bc, "hook", o)
    if not ok then log("cycle error (hook): " .. tostring(e)) end
    if SPX.widget then
        local okP, eP = pcall(SPX.widget, st, bc, what)
        if not okP then log("story core error (widget): " .. tostring(eP)) end
    end
end
local function hookWidget()
    if bpHooked or now() - bpTryAt < 3.0 then return end
    bpTryAt = now()
    local ok1 = pcall(RegisterHook, DW .. "RefreshState", function(ctx) onWidget(ctx, "RefreshState") end)
    if not ok1 then return end
    local ok2 = pcall(RegisterHook, DW .. "FinishYouDieAnimation", function(ctx) onWidget(ctx, "FinishYouDieAnimation") end)
    local ok3 = pcall(RegisterHook, DW .. "FinishPressAnimation", function(ctx) onWidget(ctx, "FinishPressAnimation") end)
    local ok4 = pcall(RegisterHook, DW .. "FinishExistBossChallenge", function(ctx) onWidget(ctx, "FinishExistBossChallenge") end)
    local ok5 = pcall(RegisterHook, DW .. "Destruct", function()
        W.o, W.oa, W.st, W.bc = nil, nil, nil, nil
        log("widget Destruct")
    end)
    pcall(RegisterHook, DW .. "EventNotification", function(ctx, ev)
        local o, s = nil, "?"
        pcall(function() o = ctx:get(); s = ev:get():ToString() end)
        local st, bc = nil, nil
        if valid(o) then st, bc = readW(o) end
        if st ~= nil and (st ~= W.st or bc ~= W.bc) then log(string.format("widget EventNotification '%s' state=%s bc=%s", s, tostring(st), tostring(bc))); W.st, W.bc, W.at = st, bc, now() end
        if SPX.event then pcall(SPX.event, "EventNotification '" .. tostring(s) .. "'", st, bc) end
    end)
    if PROBE_ON then
        -- story probe only: the revival-item (WB Pump) animations, the two death-screen buttons, construction
        for _, fnName in ipairs({ "FinishUseItemAnimation", "FinishDisuseItemAnimation", "FinishResurrectionAnimation",
            "WB_Common_btn_1_Event_0", "WB_Common_btn_2_Event_0", "PlayDieSoundEvent", "Construct" }) do
            local okH = pcall(RegisterHook, DW .. fnName, function(ctx)
                local o, st, bc = nil, nil, nil
                pcall(function() o = ctx:get() end)
                if valid(o) then st, bc = readW(o) end
                if SPX.event then pcall(SPX.event, fnName, st, bc) end
            end)
            log("story probe hook " .. fnName .. "=" .. tostring(okH))
        end
    end
    bpHooked = true
    log(string.format("widget hooks: RefreshState=%s FinishYouDie=%s FinishPress=%s FinishExistBC=%s Destruct=%s",
        tostring(ok1), tostring(ok2), tostring(ok3), tostring(ok4), tostring(ok5)))
end

-- ---------------------------------------------------------------- game-thread poll
local lastSlow, lastSwitch, pending = -10, -10, false
-- the probe measures its own game-thread time; story-probe-pause.txt pauses it live, and it
-- pauses itself if it takes more than 15 % of a 10 s window.
local PAUSE_FILE = MOD_DIR .. "story-probe-pause.txt"
local WARP_FILE = MOD_DIR .. "warp-to.txt"
local PC = { sum = 0, max = 0, n = 0, at = -1, paused = false, auto = false, tickMax = 0 }
local function fileThere(path) local f = io.open(path, "r"); if f then f:close(); return true end; return false end
local function poll()
    local t = now()
    -- the panel's switch, for status.txt (a death re-reads every setting itself)
    if t - lastSwitch >= 2.0 then
        lastSwitch = t; ST.enabled = readEnabled(); writeStatus()
        cfg.enabled = ST.enabled
        if cfg.enabled == "0" then cancelDisabledRestart() end
        if SPX.tick then
            local pz = PROBE_ON and (PC.auto or fileThere(PAUSE_FILE))
            local wf = PROBE_ON and SPX.warpTo and io.open(WARP_FILE, "r")
            if wf then
                local line = wf:read("*l") or ""
                wf:close()
                local auto = line:find("AUTO_ENTRY_", 1, true)
                local retained = true
                if auto then
                    local nonce = line:match("\t([a-f0-9]+)\t/[^%s]+\t%d+$")
                    local dest = nonce and #nonce == 32 and (MOD_DIR .. "auto-entry-consumed-" .. nonce .. ".txt")
                    if not dest or fileThere(dest) then retained = false
                    else retained = os.rename(WARP_FILE, dest) and true or false end
                else os.remove(WARP_FILE) end
                local okW, eW = true, nil
                if retained then okW, eW = pcall(SPX.warpTo, line, pz)
                else SPX.note("AUTO_ENTRY_REFUSED retention/nonce conflict; request left intact") end
                if not okW then SPX.note("WARP_DEV error: " .. tostring(eW)) end
            end
            if pz ~= PC.paused then PC.paused = pz; SPX.note("story probe " .. (pz and "PAUSED" or "RESUMED") .. (PC.auto and " (auto: too slow)" or " (pause file)")) end
        end
    end
    if t < suspendUntil then return end
    local slow = t - lastSlow >= 0.1
    if slow then lastSlow = t end
    if slow then hookWidget(); probeWidget() end
    if H.on or H.dir == -1 then blackTick() end
    local st, bc = W.st, W.bc
    local arena = bc == true and S.phase ~= "exit"
    local pawn = getPawn()
    local p = pawn and actorLoc(pawn)
    if arena then
        if p then pushRing(p, actorYaw(pawn)); curSample = ring[#ring] end
        local n = 0
        for _ in pairs(trigs) do n = n + 1 end
        -- rescan only while no trigger is known (arena triggers load with the arena; end play drops them)
        if slow and p and n == 0 and t - trigListAt > 3.0 then refreshTrigList(p) end
        pollTrigs()
    elseif next(trigs) ~= nil then
        dropTriggers("not in a Boss Challenge arena")
    end
    if S.corrupter and not SPX.corrupterValid(S.corrupter) then
        S.corrupter = nil; evt("INTRO_SKIP", "gen=%d Corrupter attempt identity/state changed", S.gen)
        blackEnd("attempt invalid", false); result("attempt_invalid"); setPhase(st == 0 and "idle" or "wait_clear", "attempt invalid")
    end
    -- intro events -> learning + cycle confirmation
    for _, ie in ipairs(introEvents) do
        if not ie.done then
            ie.done = true
            if SPX.nestSceneStart then SPX.nestSceneStart(ie.name, ie.t) end
            ie.learnAt = (arena and (S.phase == "idle" or S.phase == "fight_wait")) and (ie.t + 1.2) or nil
            evt("INTRO_STARTED", "name=%s phase=%s gen=%d dtFire=%s", ie.name, S.phase, S.gen,
                (S.phase == "intro_wait" and S.tFire) and string.format("%.3f", ie.t - S.tFire) or "-")
            if S.corrupter and ie.t >= S.tFire and storyIntroMatches("DED20_ZTrigger_011", ie.name) then
                S.corrupter.sceneAt, S.corrupter.finishAt = ie.t, nil
            end
            -- The Karakuri object is normally made at camp during re-arm, not playback.
            -- Preserve the existing native no-warp path if its matched event really has a cinematic view.
            local armCreationOnly = S.story and SPX.storyArmCreated and SPX.storyArmCreated(S.story)
            if armCreationOnly then
                local vt, vtn = viewTargetInfo()
                armCreationOnly = not (vt and type(vtn) == "string" and vtn:match("^CineCameraActor%s"))
            end
            local nativeOwn = (S.phase == "reviving" or S.phase == "settle") and S.story and S.tRev
                and ie.t >= S.tRev and SPX.storyIntroMatches and SPX.storyIntroMatches(S.story, ie.name, ie.t, S.tRev)
                and (not (SPX.storyNeedsNativeRetry and SPX.storyNeedsNativeRetry(S.story)) or nestRetryIntro(ie.name))
                and not armCreationOnly
            if nativeOwn then
                -- The game has already begun this boss's native respawn. Never warp or replay it again.
                S.nativeRespawn = true; S.introGen = S.gen; S.tIntro = ie.t
                S.vtGameAddr = pawn and addr(pawn) or nil
                evt("NATIVE_RESPAWN", "gen=%d native entrance already playing; no mod warp: %s", S.gen, ie.name)
                setPhase("intro_cam", "native entrance already playing")
                SPX.stalkerCameraArm(ie)
            elseif S.phase == "intro_wait" then
                local nestRetry = S.story and SPX.storyNeedsNativeRetry and SPX.storyNeedsNativeRetry(S.story)
                local storyMatch = not S.story or (ie.t >= S.tFire and SPX.storyIntroMatches and SPX.storyIntroMatches(S.story, ie.name, ie.t, S.tFire))
                if storyMatch and (not nestRetry or (ie.t >= S.tFire and nestRetryIntro(ie.name))) then
                    S.introGen = S.gen; S.tIntro = ie.t; setPhase("intro_cam", "intro created; waiting for its camera")
                    nativeLeadArm(ie, t)
                    SPX.stalkerCameraArm(ie)
                else
                    evt("INTRO_IGNORED", "gen=%d story retry requires its native entrance; got %s", S.gen, ie.name)
                end
            end
        end
        if ie.learnAt and t >= ie.learnAt then ie.learnAt = nil; learnFromIntro(ie) end
    end
    if #introEvents > 20 and not introEvents[1].learnAt then table.remove(introEvents, 1) end
    while #fireEvents > 40 do table.remove(fireEvents, 1) end
    if H.hudRestoreAt and t >= H.hudRestoreAt then H.hudRestoreAt = nil; hudRestore("intro running") end
    if H.areaUntil and t >= H.areaUntil and not H.on then areaRestore("safety timeout") end
    if H.on and t > SPX.stalkerCameraDeadline(t) then
        evt("BLACK_WATCHDOG", "gen=%d black held %.1f s in phase %s; releasing", S.gen, t - H.t, S.phase)
        blackEnd("watchdog", false)
        result("watchdog"); S.corrupter = nil
        if S.phase ~= "fight_wait" then setPhase("idle", "watchdog") end
    end
    if finishPending > 0 then
        local finishedAt = finishAt
        finishPending, finishAt = 0, nil
        if SPX.nestSceneFinish then SPX.nestSceneFinish(finishedAt) end
        evt("INTRO_FINISHED", "phase=%s gen=%d eve=%s", S.phase, S.gen, fv(p))
        if not S.corrupter and not S.nativeFight and not (S.stalkerCameraScope and S.phase == "intro_cam") then
            areaRestore("intro finished")
            S.fightCheck = { at = t + 3.0, p = p, gen = S.gen }
        end
        if S.corrupter then S.corrupter.finishAt = finishedAt
        elseif S.phase == "fight_wait" then setPhase("idle", "fight running") end
    end
    if S.corrupter and S.phase == "fight_wait" then
        local c = S.corrupter
        local vt, _, pend, pendingReadOK = viewTargetInfo() -- existing reflected read path; never changes the camera
        if c.sceneAt and c.finishAt and c.finishAt > c.sceneAt and vt and same(vt, pawn) and pendingReadOK and not pend and battleState(pawn) == "true" then
            evt("INTRO_READY", "gen=%d alias=DED20_ZTrigger_011 eve=%s", S.gen, fv(p))
            areaRestore("native control returned"); S.fightCheck = { at = t + 3.0, p = p, gen = S.gen }
            S.corrupter = nil; result("restarted"); setPhase("idle", "native camera and battle returned")
        elseif t - S.t > 120 then
            S.corrupter = nil; evt("INTRO_FAIL", "gen=%d native control not returned in 120 s", S.gen)
            result("intro_control_not_seen"); setPhase("idle", "native control timeout")
        end
    end
    if S.fightCheck and t >= S.fightCheck.at then
        local fc = S.fightCheck
        S.fightCheck = nil
        evt("FIGHT_CHECK", "gen=%d eveAtIntroEnd=%s eveNow=%s eveMoved=%.0f eveBattle=%s st=%s bosses=%s", fc.gen, fv(fc.p), fv(p),
            dist(fc.p, p), pawn and battleState(pawn) or "?", tostring(st), "not scanned")   -- cached diagnosis; never scan during the fight
    end
    if st ~= nil then
        local ok, e = pcall(cycle, st, bc, "poll", nil)
        if not ok then log("cycle error: " .. tostring(e)) end
    end
    if SPX.tick and (not PROBE_ON or not PC.paused) then
        local c0 = os.clock()
        local okP, eP = pcall(SPX.tick, t)
        if not okP then log("story core error: " .. tostring(eP)) end
        local ms = (os.clock() - c0) * 1000
        if PROBE_ON then PC.sum, PC.n, PC.max = PC.sum + ms, PC.n + 1, math.max(PC.max, ms) end
    end
    if PROBE_ON and SPX.autoEntryTick and not PC.paused then SPX.autoEntryTick(t) end
    if PROBE_ON and SPX.tick then
        if PC.at < 0 then PC.at = t end
        if t - PC.at >= 10 then
            SPX.note(string.format("PROBE_COST 10s: %.0f ms (%.1f%%) ticks=%d max=%.1f ms whole-mod tick max=%.1f ms%s", PC.sum, PC.sum / ((t - PC.at) * 10), PC.n, PC.max, PC.tickMax, PC.paused and " paused" or ""))
            PC.tickMax = 0
            if not PC.paused and PC.sum > (t - PC.at) * 150 then PC.auto = true; lastSwitch = -10; SPX.note("PROBE_AUTO_PAUSE: probe used more than 15 % of the game thread") end
            PC.sum, PC.n, PC.max, PC.at = 0, 0, 0, t
        end
    end
end

ST.state = "ready"
writeStatus()

LoopAsync(5, function()
    if not pending then
        pending = true
        ExecuteInGameThread(function()
            local c0 = os.clock()
            local ok, e = pcall(poll)
            local ms = (os.clock() - c0) * 1000
            if PROBE_ON and ms > PC.tickMax then PC.tickMax = ms end
            if not ok then log("poll error: " .. tostring(e)) end
            pending = false
        end)
    end
    return false
end)
