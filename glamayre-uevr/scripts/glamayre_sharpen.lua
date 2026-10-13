-- Glamarye Sharpen: minimal UEVR LuaLoader panel.
-- This file is only UI; every GPU operation runs in the native DLL.
local state = {enabled=false,big=true,edges=true,split=false,debug=false,strength=0.4,limit=0.1,bias=0.02,xrHook=0,xrResolved=0,xrFrames=0,xrAcquire=0,xrRelease=0,xrEnd=0,xrProj=0,xrSize=0,xrEligible=0,xrEnumError=0}
local received = false
local pending = {}

local function send(key, value)
    if type(value) == "boolean" then value = value and 1 or 0 end
    uevr.api:dispatch_custom_event("glamayre_sharpen.set", key .. "=" .. tostring(value))
end

uevr.sdk.callbacks.on_lua_event(function(event, message)
    if event ~= "glamayre_sharpen.status" then return end
    received = true
    for key, raw in string.gmatch(message or "", "([%w]+)=([^;]+)") do
        local n = tonumber(raw)
        if n ~= nil then
            if key == "gpuError" then
                state.gpuError = n ~= 0
            elseif pending[key] == nil then
                if key == "enabled" or key == "big" or key == "edges" or key == "split" or key == "debug" then
                    state[key] = n ~= 0
                else
                    state[key] = n
                end
            end
        end
    end
end)

local function checkbox(label, key)
    local changed, value = imgui.checkbox(label, state[key] == true)
    if changed then
        state[key] = value
        send(key, value)
    end
end

local function slider(label, key, minimum, maximum)
    local changed, value = imgui.slider_float(label, state[key], minimum, maximum, "%.3f")
    local active = imgui.is_item_active()
    if changed then
        state[key] = value
        pending[key] = true
    end
    if pending[key] and not active then
        send(key, state[key])
        pending[key] = nil
    end
end

uevr.lua.add_script_panel("Glamarye Sharpen", function()
    if not received then
        imgui.text("Waiting for GlamaryeSharpenUEVR.dll")
        imgui.text("Install DLL in this game's UEVR plugins folder.")
        return
    end
    checkbox("Enable Intelligent Sharpen", "enabled")
    slider("Sharpen strength", "strength", 0.0, 2.0)
    checkbox("Bigger Sharpen (1.4 pixel radius)", "big")
    checkbox("Sharpen jagged edges less", "edges")
    slider("Maximum sharpen change", "limit", 0.01, 0.5)
    slider("FXAA edge detection bias", "bias", 0.0, 0.2)
    if imgui.tree_node("Diagnostics") then
        checkbox("TEST ONLY: draw red grid on headset image", "debug")
        imgui.text("Turn this OFF after confirming that sharpening reaches both eyes.")
        imgui.tree_pop()
    end
    if imgui.tree_node("Stereo image layout") then
        checkbox("Two eyes packed side-by-side in one texture", "split")
        imgui.text("Leave off for Mono and per-eye texture arrays.")
        imgui.tree_pop()
    end
    if state.gpuError then
        imgui.text("GPU initialization error: check UEVR.log. Sharpen is bypassed.")
    end
    if state.xrHook ~= 1 then
        imgui.text("OpenXR loader hook not active (check OpenXR mode and logs).")
    else
        imgui.text("OpenXR hooks: loader=" .. tostring(state.xrHook or 0)
            .. " runtime=" .. tostring(state.xrResolved or 0))
        imgui.text("Processed scene images: " .. tostring(state.xrFrames or 0))
        if imgui.tree_node("Frame path diagnostics") then
            imgui.text("Acquired: " .. tostring(state.xrAcquire or 0))
            imgui.text("Released: " .. tostring(state.xrRelease or 0))
            imgui.text("EndFrame: " .. tostring(state.xrEnd or 0))
            imgui.text("Projection matched: " .. tostring(state.xrProj or 0))
            imgui.text("HMD size matched: " .. tostring(state.xrSize or 0))
            imgui.text("Eligible submissions: " .. tostring(state.xrEligible or 0))
            imgui.text("Enumerate errors: " .. tostring(state.xrEnumError or 0))
            imgui.tree_pop()
        end
        if (state.xrFrames or 0) == 0 then
            imgui.text("No headset scene image processed; effect is not active.")
        end
    end
    imgui.text("Sharpening applies to projection-layer scene images only.")
    imgui.text("DLSS and Joey native stereo/mono renderers are unchanged.")
end)
