from pathlib import Path

ROOT = Path("psvr2toolkit")


def replace(path, old, new):
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Pattern not found in {path}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")

# ---------------------------------------------------------------------------
# 1) SteamVR settings: independent PRE-CROP HMD recommendation override.
# Current crop: H 80% remaining, top -10%, bottom -25%.
# Native PSVR2 recommendation: 3400 x 3468.
# Projection-span ratios: H=0.755013, V=0.531673.
# Desired final target ~= 2567 x 1844.
# SteamVR's FOV letterboxing should apply V relative factor 0.65/0.80=0.8125,
# so advertise 2568 x 2268 before that transform.
# ---------------------------------------------------------------------------
settings = "projects/psvr2_openvr_driver_ex/utils/driver_settings.h"
replace(settings,
'''#define STEAMVR_SETTINGS_DISABLE_HIDDEN_AREA_MESH "disableHiddenAreaMesh"\n''',
'''#define STEAMVR_SETTINGS_DISABLE_HIDDEN_AREA_MESH "disableHiddenAreaMesh"\n#define STEAMVR_SETTINGS_RENDER_TARGET_OVERRIDE "renderTargetOverride"\n#define STEAMVR_SETTINGS_RENDER_TARGET_WIDTH "renderTargetWidth"\n#define STEAMVR_SETTINGS_RENDER_TARGET_HEIGHT "renderTargetHeight"\n''')
replace(settings,
'''#define SETTING_DISABLE_HIDDEN_AREA_MESH_DEFAULT_VALUE false\n''',
'''#define SETTING_DISABLE_HIDDEN_AREA_MESH_DEFAULT_VALUE false\n#define SETTING_RENDER_TARGET_OVERRIDE_DEFAULT_VALUE true\n#define SETTING_RENDER_TARGET_WIDTH_DEFAULT_VALUE 2568\n#define SETTING_RENDER_TARGET_HEIGHT_DEFAULT_VALUE 2268\n''')

# ---------------------------------------------------------------------------
# 2) Hook the authoritative IVRDisplayComponent getter that SteamVR calls.
# ---------------------------------------------------------------------------
hmd = "projects/psvr2_openvr_driver_ex/driver_hooks/hmd_device_hooks.cpp"
replace(hmd,
'''void *(*sie__psvr2__HmdDevice__GetComponent)(void *, char *) = nullptr;\nvoid *sie__psvr2__HmdDevice__GetComponentHook(void *thisptr, char *pchComponentNameAndVersion) {\n''',
'''using DisplayGetRecommendedRenderTargetSizeFn = void (*)(void *, uint32_t *, uint32_t *);\nstatic DisplayGetRecommendedRenderTargetSizeFn g_originalDisplayGetRecommendedRenderTargetSize = nullptr;\nstatic bool g_displayRenderTargetHookInstalled = false;\n\nvoid DisplayGetRecommendedRenderTargetSizeHook(void *thisptr, uint32_t *pnWidth, uint32_t *pnHeight) {\n  g_originalDisplayGetRecommendedRenderTargetSize(thisptr, pnWidth, pnHeight);\n  if (!pnWidth || !pnHeight) {\n    return;\n  }\n\n  if (DriverSettings::GetBool(STEAMVR_SETTINGS_RENDER_TARGET_OVERRIDE, SETTING_RENDER_TARGET_OVERRIDE_DEFAULT_VALUE)) {\n    int width = DriverSettings::GetInt32(STEAMVR_SETTINGS_RENDER_TARGET_WIDTH, SETTING_RENDER_TARGET_WIDTH_DEFAULT_VALUE);\n    int height = DriverSettings::GetInt32(STEAMVR_SETTINGS_RENDER_TARGET_HEIGHT, SETTING_RENDER_TARGET_HEIGHT_DEFAULT_VALUE);\n    if (width > 0 && height > 0) {\n      *pnWidth = static_cast<uint32_t>(width);\n      *pnHeight = static_cast<uint32_t>(height);\n    }\n  }\n}\n\nvoid *(*sie__psvr2__HmdDevice__GetComponent)(void *, char *) = nullptr;\nvoid *sie__psvr2__HmdDevice__GetComponentHook(void *thisptr, char *pchComponentNameAndVersion) {\n''')
replace(hmd,
'''  return sie__psvr2__HmdDevice__GetComponent(thisptr, pchComponentNameAndVersion);\n}\n\ninline const int64_t GetHostTimestamp() {\n''',
'''  void *component = sie__psvr2__HmdDevice__GetComponent(thisptr, pchComponentNameAndVersion);\n\n  if (component && strcmp(pchComponentNameAndVersion, vr::IVRDisplayComponent_Version) == 0 && !g_displayRenderTargetHookInstalled) {\n    // IVRDisplayComponent vtable slot 3 = GetRecommendedRenderTargetSize.\n    void **vtable = *reinterpret_cast<void ***>(component);\n    if (vtable && vtable[3]) {\n      HookLib::InstallHook(vtable[3], reinterpret_cast<void *>(DisplayGetRecommendedRenderTargetSizeHook),\n                           reinterpret_cast<void **>(&g_originalDisplayGetRecommendedRenderTargetSize));\n      g_displayRenderTargetHookInstalled = true;\n      Util::DriverLog("Installed direct IVRDisplayComponent render-target override hook.");\n    }\n  }\n\n  return component;\n}\n\ninline const int64_t GetHostTimestamp() {\n''')

# ---------------------------------------------------------------------------
# 3) EXACT haptics behavior recovered byte-for-byte from the user's uploaded
# DLL against a clean build of the same upstream commit. The old DLL used this
# 128-entry signed-magnitude LUT, not a simple multiply.
# ---------------------------------------------------------------------------
sense = "projects/psvr2_openvr_driver_ex/sense_controller.cpp"
replace(sense,
'''std::atomic<std::thread *> hapticsThread;\n''',
'''std::atomic<std::thread *> hapticsThread;\n\nstatic constexpr uint8_t kUserHapticsGainLut[128] = {\n    0,9,17,25,33,40,47,53,59,65,70,76,80,85,89,93,96,100,103,106,108,111,113,115,117,118,120,121,122,123,124,125,\n    125,126,126,126,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,\n    127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,\n    127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127,127\n};\n''')
replace(sense,
'''    buffer.settings.timeStampMicrosecondsLastSend = static_cast<uint32_t>(GetHostTimestamp());\n''',
'''    // Exact behavior from the user's prior DLL: transform all 32 final PCM samples\n    // through the recovered signed-magnitude LUT. -128 is clamped to magnitude 127.\n    for (int i = 0; i < sizeof(buffer.hapticPCM); ++i) {\n      int sample = static_cast<int>(static_cast<int8_t>(buffer.hapticPCM[i]));\n      if (sample < 0) {\n        int magnitude = -sample;\n        if (magnitude > 127) magnitude = 127;\n        int output = -static_cast<int>(kUserHapticsGainLut[magnitude]);\n        buffer.hapticPCM[i] = static_cast<uint8_t>(static_cast<int8_t>(output));\n      } else {\n        buffer.hapticPCM[i] = kUserHapticsGainLut[sample];\n      }\n    }\n\n    buffer.settings.timeStampMicrosecondsLastSend = static_cast<uint32_t>(GetHostTimestamp());\n''')

# ---------------------------------------------------------------------------
# 4) EXACT stick LUT and right-R2 remap recovered from the user's uploaded DLL.
# The binary patch only transformed the active controller's two stick axes.
# ---------------------------------------------------------------------------
libpad = "projects/psvr2_openvr_driver_ex/driver_hooks/libpad_hooks.cpp"
replace(libpad,
'''const int32_t k_stablePhasePeriod = 9;\n\nenum class CalibrationState {\n''',
'''const int32_t k_stablePhasePeriod = 9;\n\nstatic constexpr uint8_t kUserStickCurveLut[256] = {\n    0,2,4,6,8,10,12,14,15,17,19,21,23,24,26,28,29,31,33,34,36,38,39,41,42,44,45,47,48,50,51,53,\n    54,55,57,58,59,61,62,63,64,66,67,68,69,70,71,72,73,75,76,77,78,79,80,80,81,82,83,84,85,86,86,87,\n    88,89,89,90,91,92,92,93,93,94,95,95,96,96,97,97,97,98,98,99,99,99,100,100,100,101,101,101,101,102,102,102,\n    102,102,102,102,102,102,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,\n    128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,153,153,153,154,154,154,\n    154,154,154,154,155,155,155,155,155,156,156,156,157,157,158,158,158,159,159,160,160,161,161,162,163,163,164,165,165,166,167,167,\n    168,169,170,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,190,191,192,193,194,196,197,198,200,201,\n    202,204,205,207,208,210,211,213,214,216,217,219,221,222,224,226,227,229,231,232,234,236,238,240,241,243,245,247,249,251,253,255\n};\n\nstatic uint8_t ApplyUserRightTriggerFix(uint8_t raw) {\n  if (raw <= 128) return 0;\n  return static_cast<uint8_t>((static_cast<uint32_t>(raw - 128) * 255u) / 127u);\n}\n\nenum class CalibrationState {\n''')
replace(libpad,
'''              g_fn_parseSenseInputReport(padContext, pSingleReport, static_cast<uint32_t>(reportStride), isBt, &controllerState);\n\n              uint64_t currentHostTime = GetHostTimestamp();\n''',
'''              g_fn_parseSenseInputReport(padContext, pSingleReport, static_cast<uint32_t>(reportStride), isBt, &controllerState);\n\n              // Exact prior DLL behavior: only the two axes belonging to the active controller.\n              if (isLeft) {\n                controllerState.leftStickX = kUserStickCurveLut[controllerState.leftStickX];\n                controllerState.leftStickY = kUserStickCurveLut[controllerState.leftStickY];\n              } else {\n                controllerState.rightStickX = kUserStickCurveLut[controllerState.rightStickX];\n                controllerState.rightStickY = kUserStickCurveLut[controllerState.rightStickY];\n                controllerState.rightTrigger = ApplyUserRightTriggerFix(controllerState.rightTrigger);\n              }\n\n              uint64_t currentHostTime = GetHostTimestamp();\n''')

print("PSVR2Toolkit custom patch applied successfully")
