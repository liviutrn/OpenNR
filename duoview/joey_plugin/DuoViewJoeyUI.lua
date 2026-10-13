-- DuoView UI using ONLY the Lua APIs exposed by Joey/UEVR.
-- No os.getenv, os.time, io.open, arbitrary filesystem paths, or standalone overlay.
-- UEVR's fs API operates inside this game's UnrealVRMod/<game>/data sandbox.
local CONFIG = "DuoViewJoey.ini"
local STATUS = "DuoViewJoey.status"
local REQUEST = "DuoViewJoey.status.request"
local options = {"Disabled (original Joey)", "Shared-pose reference", "Fixed fovea", "PSVR2 eye-tracked fovea"}
local config = {Mode=0, CropWidth=0.5, CropHeight=0.5, PeripheralScale=0.2, FovealDensity=1.0, Feather=0.08, DebugBorder=1}
local status = {}
local dirty = false
local draw_count = 0
local message = "Settings apply on next game launch."
local available = type(fs) == "table" and type(fs.read) == "function" and type(fs.write) == "function"

local function read_pairs(filename)
    local values = {}
    if not available then return values end
    local success, contents = pcall(fs.read,filename)
    if not success or type(contents) ~= "string" then return values end
    for line in contents:gmatch("[^\r\n]+") do
        local key,value=line:match("^%s*([%a][%w_]*)%s*=%s*(.-)%s*$")
        if key and value then values[key] = value end
    end
    return values
end

local function write_file(filename, contents)
    if not available then return false end
    local success, result = pcall(fs.write, filename, contents)
    -- Return value may be void, depending on the UEVR binding version.
    return success and result ~= false
end

local function reload_settings()
    local saved=read_pairs(CONFIG)
    for key,_ in pairs(config) do
        local num=tonumber(saved[key])
        if num then config[key]=num end
    end
    config.Mode=math.max(0,math.min(3,math.floor(config.Mode)))
    dirty=false
end

local keys={"Mode","CropWidth","CropHeight","PeripheralScale","FovealDensity","Feather","DebugBorder"}
local function save_settings()
    local lines={"[DuoView]"}
    for _,key in ipairs(keys) do
        lines[#lines+1] = key.."="..tostring(config[key])
    end
    if write_file(CONFIG,table.concat(lines,"\n").."\n") then
        dirty=false
        message="Saved. Restart STALKER 2 to apply the new configuration."
    else
        message="ERROR: Cannot save DuoViewJoey.ini via UEVR fs."
    end
end

reload_settings()

uevr.sdk.callbacks.on_draw_ui(function()
    if not imgui.collapsing_header("DuoView Mono - Joey original backend") then return end
    if not available then
        imgui.text("ERROR: UEVR sandbox fs API is unavailable; UI cannot save/read native settings.")
        imgui.text("Joey original injector is not modified.")
        return
    end
    draw_count=draw_count+1
    if draw_count==1 or draw_count%45==0 then
        status=read_pairs(STATUS)
        write_file(REQUEST,"1")
    end

    imgui.text("Native plugin: "..(status.Hooks or "No native status"))
    imgui.text("Reason: "..(status.Reason or "Waiting for native plugin initial state"))
    imgui.text("Applied mode: "..(status.Mode or "?").."; menu selected: "..tostring(config.Mode))
    imgui.text("Present callbacks: "..(status.PresentCallbacks or "0").." / Engine ticks: "..(status.EngineTicks or "0"))
    imgui.text("OpenXR LocateViews: "..(status.LocateViews or "0").." / XR end frames: "..(status.EndFrames or "0"))
    imgui.text("Paired UE views: "..(status.ProducerPairs or "0").." / Renderer callbacks: "..(status.RenderCallbacks or "0"))
    imgui.text("Matching producer frames: "..(status.MatchedPackets or "0").." / GPU composites queued: "..(status.CompositesQueued or "0"))
    imgui.text("XR accepted: "..(status.XRSubmitAccepted or "0").." / XR rejected: "..(status.XRSubmitFailed or "0"))
    imgui.text("Withheld scene layers: "..(status.RejectedLayers or "0"))
    imgui.text("Only incrementing paired views + composites + accepted XR frames indicates runtime progress.")
    imgui.spacing()

    local changed,new_mode=imgui.combo("Rendering mode (restart)",config.Mode+1,options)
    if changed then
        config.Mode=math.max(0,math.min(3,new_mode-1))
        dirty=true
    end
    local function slider(label,key,minval,maxval,step)
        local changed,newval=imgui.drag_float(label,config[key],step,minval,maxval,"%.3f")
        if changed then config[key]=math.max(minval,math.min(maxval,newval)); dirty=true end
    end
    slider("Crop width","CropWidth",0.05,1.0,0.01)
    slider("Crop height","CropHeight",0.05,1.0,0.01)
    slider("Peripheral resolution scale","PeripheralScale",0.05,0.5,0.01)
    slider("Foveal density","FovealDensity",0.25,4.0,0.05)
    slider("Blend feather","Feather",0.0,0.45,0.01)
    local changed,border=imgui.checkbox("Show fovea border",config.DebugBorder==1)
    if changed then config.DebugBorder=border and 1 or 0;dirty=true end

    if imgui.button("Save DuoView settings") then save_settings() end
    imgui.same_line()
    if imgui.button("Reload from disk") then reload_settings();message="Reloaded from UEVR data profile." end
    imgui.text(message)
    if dirty then imgui.text("Unsaved changes") end
    imgui.text("Use OpenXR and Native Stereo ID 0 for DuoView modes 1-3.")
end)
