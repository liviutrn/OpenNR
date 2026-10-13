-- DuoView Joey-first controls rendered by UEVR's own Lua/ImGui UI.
-- Loaded automatically from the game's profile scripts directory.
-- This UI has no rendering hooks and does not touch Joey's binaries.
local appdata = os.getenv("APPDATA")
local base = appdata and (appdata .. "\\UnrealVRMod\\Stalker2-Win64-Shipping\\") or nil
local config_file = base and (base .. "DuoViewJoey.ini") or nil
local status_file = base and (base .. "DuoViewJoey.status") or nil
local options = {"Disabled (original Joey)", "Shared-pose two views", "Fixed fovea", "PSVR2 eye-tracked fovea"}
local config = {Mode=0,CropWidth=0.50,CropHeight=0.50,PeripheralScale=0.20,FovealDensity=1.00,Feather=0.08,DebugBorder=1}
local status = {}
local dirty = false
local last_poll = -1

local function read_pairs(path)
    local data = {}
    if not path then return data end
    local f = io.open(path,"r")
    if not f then return data end
    for line in f:lines() do
        local key, value = line:match("^%s*([%a][%w_]*)%s*=%s*(.-)%s*$")
        if key then data[key] = value end
    end
    f:close()
    return data
end

local function load_config()
    local loaded = read_pairs(config_file)
    for key, original in pairs(config) do
        if loaded[key] then
            local value = tonumber(loaded[key])
            if value then config[key] = value end
        end
    end
    config.Mode = math.max(0, math.min(3,math.floor(config.Mode)))
    dirty = false
end

local function save_config()
    if not config_file then return false end
    local f = io.open(config_file,"w")
    if not f then return false end
    f:write("[DuoView]\n")
    local keys={"Mode","CropWidth","CropHeight","PeripheralScale","FovealDensity","Feather","DebugBorder"}
    for _,key in ipairs(keys) do
        f:write(key,"=",tostring(config[key]),"\n")
    end
    f:close()
    dirty = false
    return true
end

load_config()
local message = "Changes are saved to your UEVR profile; restart the game to apply."
uevr.sdk.callbacks.on_draw_ui(function()
    if not imgui.collapsing_header("DuoView Mono - Joey original backend") then return end
    if not base then
        imgui.text("APPDATA is unavailable. Cannot read the game profile.")
        return
    end

    local now = os.time()
    if now ~= last_poll then
        last_poll = now
        status = read_pairs(status_file)
    end

    imgui.text("Backend: Joey 101226HELLRAISERp1 (unchanged)")
    imgui.text("Plugin hooks: "..(status.Hooks or "No native status: not initialized"))
    imgui.text("Native state: "..(status.Reason or "Check profile plugin installation"))
    imgui.text("Applied mode: "..(status.Mode or "unknown").."  |  Selected mode: "..tostring(config.Mode))
    imgui.text("Engine ticks: "..(status.EngineTicks or "0").."   LocateViews: "..(status.LocateViews or "0"))
    imgui.text("Paired views: "..(status.ProducerPairs or "0").."   Render callbacks: "..(status.RenderCallbacks or "0"))
    imgui.text("Matched frames: "..(status.MatchedPackets or "0").."   Composites: "..(status.CompositesQueued or "0"))
    imgui.text("XR end frames: "..(status.EndFrames or "0").."   Layers submitted: "..(status.SubmittedLayers or "0")..
        "   Rejected: "..(status.RejectedLayers or "0"))
    imgui.text("If counters do not advance, DuoView is NOT rendering.")
    imgui.spacing()
    local changed, next_mode = imgui.combo("Render mode", config.Mode + 1, options)
    if changed then config.Mode = next_mode - 1; dirty = true end

    local function control(name, key, lo, hi, speed)
        local did_change, next_value = imgui.drag_float(name, config[key], speed, lo, hi, "%.3f")
        if did_change then
            config[key] = math.max(lo, math.min(hi,next_value))
            dirty = true
        end
    end
    control("Crop width", "CropWidth", 0.05, 1.0, 0.01)
    control("Crop height", "CropHeight", 0.05, 1.0, 0.01)
    control("Peripheral scale", "PeripheralScale", 0.05, 0.50, 0.01)
    control("Foveal density", "FovealDensity", 0.25, 4.0, 0.05)
    control("Feather", "Feather", 0.0, 0.45, 0.01)
    local border = config.DebugBorder == 1
    local toggle, checked = imgui.checkbox("Debug fovea border", border)
    if toggle then config.DebugBorder = checked and 1 or 0; dirty = true end

    if imgui.button("Save settings") then
        message = save_config() and "Saved. Restart STALKER 2 to apply." or "Could not write DuoViewJoey.ini."
    end
    imgui.same_line()
    if imgui.button("Reload settings") then load_config(); message = "Reloaded from profile INI." end
    imgui.text(message)
    if dirty then imgui.text("Unsaved changes") end
    imgui.text("Use OpenXR + Native Stereo (ID 0) for active DuoView modes.")
end)
