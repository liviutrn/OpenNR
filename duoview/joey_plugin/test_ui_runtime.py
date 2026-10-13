"""Execute the *real* packaged DuoView Lua menu against a restricted UEVR-shaped
runtime. This rejects accidental use of os.getenv, os.time, unrestricted io
and verifies status polling, user controls, and filesystem persistence.
Requires lupa and does not run STALKER 2 or modify the user profile.
"""
from pathlib import Path
import sys
from lupa import LuaRuntime

script = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("DuoViewJoeyUI.lua")).read_text(encoding="utf-8")

def scenario(with_fs: bool):
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.globals()
    env.os = lua.table()  # os.getenv / os.time deliberately unavailable
    env.io = None         # arbitrary io.open deliberately unavailable
    callback = []
    def register(fn):
        callback.append(fn)

    store = {
        "DuoViewJoey.ini": "[DuoView]\\nMode=2\\nCropWidth=0.50\\nCropHeight=0.50\\nPeripheralScale=0.2\\nFovealDensity=1.0\\nFeather=0.08\\nDebugBorder=1\\n".replace("\\n", "\n"),
        "DuoViewJoey.status": "Mode=2\\nHooks=active\\nReason=Waiting for paired views\\nEngineTicks=14\\nPresentCallbacks=25\\nOutputWidth=3000\\nOutputHeight=3000\\n".replace("\\n", "\n"),
    }
    requests = []
    controls = {"mode": False, "save": False, "crop": False}
    labels = []
    def fsread(key):
        return store.get(key, "")
    def fswrite(key, data):
        assert "/" not in key and "\\" not in key and ".." not in key, "Unsafe fs pathname"
        store[key] = data
        if key.endswith(".request"):
            requests.append(data)

    if with_fs:
        # Python callables appear as userdata in Lua; wrap them in Lua
        # functions to model the real UEVR fs.read/fs.write C bindings.
        env.fs = lua.eval("""
            function(pyread, pywrite)
                return {
                    read = function(name) return pyread(name) end,
                    write = function(name, data) return pywrite(name, data) end
                }
            end
        """)(fsread, fswrite)
    else:
        env.fs = None

    def header(label):
        assert label == "DuoView Mono - Joey original backend"
        return True
    def text(label):
        labels.append(label)
    def combo(label, selected, options):
        assert label == "Rendering mode (restart)"
        if controls["mode"]:
            return True, 4  # select PSVR2 eye-tracking, 1-based Lua combo
        return False, selected
    def drag(label, current, speed, low, high, fmt):
        if label == "Crop width" and controls["crop"]:
            return True, 0.3
        if label == "Foveal density" and controls.get("density_invalid"):
            return True, 4.0
        return False, current
    def checkbox(label, current):
        return False,current
    def button(label):
        return controls["save"] and label == "Save DuoView settings"
    env.imgui = lua.table_from({
        "collapsing_header":header,"text":text,"spacing":lambda:None,
        "combo":combo,"drag_float":drag,"checkbox":checkbox,"button":button,
        "same_line":lambda:None,
    })
    env.uevr = lua.table_from({"sdk":lua.table_from({"callbacks":lua.table_from({"on_draw_ui":register})})})
    lua.execute(script)
    assert len(callback)==1, "Menu callback did not register"
    callback[0]()
    if not with_fs:
        assert any("fs API is unavailable" in x for x in labels), "Missing fs should display error, not crash"
        return

    assert any("Native plugin: active" in x for x in labels), "Live status not displayed"
    assert len(requests)==1, "UI must request exactly one initial update"
    controls["mode"]=True
    controls["crop"]=True
    controls["save"]=True
    callback[0]()
    assert "Mode=3" in store["DuoViewJoey.ini"], "Save mode failed"
    assert "CropWidth=0.3" in store["DuoViewJoey.ini"], "Save crop failed"
    # Verify actual output-bound validation refuses an atlas overflow.
    config_before_invalid = store["DuoViewJoey.ini"]
    controls["crop"] = False
    controls["density_invalid"] = True
    callback[0]()
    assert store["DuoViewJoey.ini"] == config_before_invalid, "Invalid density must not save"
    controls["density_invalid"] = False
    assert len(requests)==1, "Status request was written every frame"
    for _ in range(44): callback[0]()
    assert len(requests)==2, "Periodic-on-menu-visible status request missing"
    assert not any("No native status" in x for x in labels), "Menu did not preserve native status"
    print("UEVR sandbox Lua UI: load, callbacks, config, status, save, throttling PASS")

scenario(True)
scenario(False)
print("UEVR sandbox Lua UI missing-fs fallback PASS")
