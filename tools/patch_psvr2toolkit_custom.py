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
#
# Current Advanced FOV crop:
#   horizontal remaining = 80% of total binocular HFOV
#   top removed = 10% of total VFOV
#   bottom removed = 25% of total VFOV
#
# Measured/modelled projection-span ratios for that crop:
#   H = 0.755013
#   V = 0.531673
#
# Native PSVR2 recommendation reference: 3400 x 3468.
# Desired final crop-matched recommendation:
#   3400*0.755013 ~= 2567
#   3468*0.531673 ~= 1844
#
# SteamVR Advanced FOV letterboxing keeps the less-cropped axis at scale 1 and
# reduces the other by relative UI-FOV fraction. Current relative V factor is
# 0.65/0.80 = 0.8125. Therefore a pre-crop HMD recommendation of ~2568x2268
# should become ~2568x1843/1844 after SteamVR's crop transform.
# ---------------------------------------------------------------------------
settings = "projects/psvr2_openvr_driver_ex/utils/driver_settings.h"
replace(settings,
'''#define STEAMVR_SETTINGS_DISABLE_HIDDEN_AREA_MESH "disableHiddenAreaMesh"\n''',
'''#define STEAMVR_SETTINGS_DISABLE_HIDDEN_AREA_MESH "disableHiddenAreaMesh"\n#define STEAMVR_SETTINGS_RENDER_TARGET_OVERRIDE "renderTargetOverride"\n#define STEAMVR_SETTINGS_RENDER_TARGET_WIDTH "renderTargetWidth"\n#define STEAMVR_SETTINGS_RENDER_TARGET_HEIGHT "renderTargetHeight"\n''')
replace(settings,
'''#define SETTING_DISABLE_HIDDEN_AREA_MESH_DEFAULT_VALUE false\n''',
'''#define SETTING_DISABLE_HIDDEN_AREA_MESH_DEFAULT_VALUE false\n#define SETTING_RENDER_TARGET_OVERRIDE_DEFAULT_VALUE true\n#define SETTING_RENDER_TARGET_WIDTH_DEFAULT_VALUE 2568\n#define SETTING_RENDER_TARGET_HEIGHT_DEFAULT_VALUE 2268\n''')

# ---------------------------------------------------------------------------
# 2) Hook the AUTHORITATIVE IVRDisplayComponent method SteamVR calls at startup.
#    Previous attempt used IVRServerDriverHost::SetRecommendedRenderTargetSize;
#    that only notifies the runtime of a later change and did not replace the
#    Sony display component's initial recommendation. We now intercept vtable
#    slot 3: IVRDisplayComponent::GetRecommendedRenderTargetSize.
# ---------------------------------------------------------------------------
hmd = "projects/psvr2_openvr_driver_ex/driver_hooks/hmd_device_hooks.cpp"
replace(hmd,
'''void *(*sie__psvr2__HmdDevice__GetComponent)(void *, char *) = nullptr;\nvoid *sie__psvr2__HmdDevice__GetComponentHook(void *thisptr, char *pchComponentNameAndVersion) {\n''',
'''using DisplayGetRecommendedRenderTargetSizeFn = void (*)(void *, uint32_t *, uint32_t *);\nstatic DisplayGetRecommendedRenderTargetSizeFn g_originalDisplayGetRecommendedRenderTargetSize = nullptr;\nstatic bool g_displayRenderTargetHookInstalled = false;\n\nvoid DisplayGetRecommendedRenderTargetSizeHook(void *thisptr, uint32_t *pnWidth, uint32_t *pnHeight) {\n  g_originalDisplayGetRecommendedRenderTargetSize(thisptr, pnWidth, pnHeight);\n\n  if (!pnWidth || !pnHeight) {\n    return;\n  }\n\n  if (DriverSettings::GetBool(STEAMVR_SETTINGS_RENDER_TARGET_OVERRIDE, SETTING_RENDER_TARGET_OVERRIDE_DEFAULT_VALUE)) {\n    int width = DriverSettings::GetInt32(STEAMVR_SETTINGS_RENDER_TARGET_WIDTH, SETTING_RENDER_TARGET_WIDTH_DEFAULT_VALUE);\n    int height = DriverSettings::GetInt32(STEAMVR_SETTINGS_RENDER_TARGET_HEIGHT, SETTING_RENDER_TARGET_HEIGHT_DEFAULT_VALUE);\n    if (width > 0 && height > 0) {\n      *pnWidth = static_cast<uint32_t>(width);\n      *pnHeight = static_cast<uint32_t>(height);\n    }\n  }\n}\n\nvoid *(*sie__psvr2__HmdDevice__GetComponent)(void *, char *) = nullptr;\nvoid *sie__psvr2__HmdDevice__GetComponentHook(void *thisptr, char *pchComponentNameAndVersion) {\n''')
replace(hmd,
'''  return sie__psvr2__HmdDevice__GetComponent(thisptr, pchComponentNameAndVersion);\n}\n\ninline const int64_t GetHostTimestamp() {\n''',
'''  void *component = sie__psvr2__HmdDevice__GetComponent(thisptr, pchComponentNameAndVersion);\n\n  if (component && strcmp(pchComponentNameAndVersion, vr::IVRDisplayComponent_Version) == 0 && !g_displayRenderTargetHookInstalled) {\n    // IVRDisplayComponent vtable order:\n    // 0 GetWindowBounds, 1 IsDisplayOnDesktop, 2 IsDisplayRealDisplay,\n    // 3 GetRecommendedRenderTargetSize.\n    void **vtable = *reinterpret_cast<void ***>(component);\n    if (vtable && vtable[3]) {\n      HookLib::InstallHook(vtable[3], reinterpret_cast<void *>(DisplayGetRecommendedRenderTargetSizeHook),\n                           reinterpret_cast<void **>(&g_originalDisplayGetRecommendedRenderTargetSize));\n      g_displayRenderTargetHookInstalled = true;\n      Util::DriverLog("Installed direct IVRDisplayComponent render-target override hook.");\n    }\n  }\n\n  return component;\n}\n\ninline const int64_t GetHostTimestamp() {\n''')

# ---------------------------------------------------------------------------
# 3) Preserve user's custom 3x PCM haptics gain.
# ---------------------------------------------------------------------------
sense = "projects/psvr2_openvr_driver_ex/sense_controller.cpp"
replace(sense,
'''    buffer.settings.timeStampMicrosecondsLastSend = static_cast<uint32_t>(GetHostTimestamp());\n''',
'''    // User custom: fixed 3x gain on the final signed 8-bit PCM block.\n    for (int i = 0; i < sizeof(buffer.hapticPCM); ++i) {\n      int sample = static_cast<int>(static_cast<int8_t>(buffer.hapticPCM[i]));\n      sample = std::clamp(sample * 3, -128, 127);\n      buffer.hapticPCM[i] = static_cast<uint8_t>(static_cast<int8_t>(sample));\n    }\n\n    buffer.settings.timeStampMicrosecondsLastSend = static_cast<uint32_t>(GetHostTimestamp());\n''')

# ---------------------------------------------------------------------------
# 4) Preserve user's current stick curve + right-R2 half-range remap.
# ---------------------------------------------------------------------------
libpad = "projects/psvr2_openvr_driver_ex/driver_hooks/libpad_hooks.cpp"
replace(libpad,
'''const int32_t k_stablePhasePeriod = 9;\n\nenum class CalibrationState {\n''',
'''const int32_t k_stablePhasePeriod = 9;\n\nstatic uint8_t ApplyUserStickCurve(uint8_t raw) {\n  int centered = static_cast<int>(raw) - 128;\n  if (centered == 0) {\n    return 128;\n  }\n\n  const bool positive = centered > 0;\n  const int maxMagnitude = positive ? 127 : 128;\n  double magnitude = static_cast<double>(std::abs(centered)) / static_cast<double>(maxMagnitude);\n  double curved = magnitude;\n  if (magnitude > 0.20) {\n    const double t = (magnitude - 0.20) / 0.80;\n    curved = 0.20 + 0.80 * t * t;\n  }\n\n  int outputMagnitude = static_cast<int>(std::lround(curved * static_cast<double>(maxMagnitude)));\n  int output = 128 + (positive ? outputMagnitude : -outputMagnitude);\n  return static_cast<uint8_t>(std::clamp(output, 0, 255));\n}\n\nstatic uint8_t ApplyUserRightTriggerFix(uint8_t raw) {\n  if (raw <= 128) {\n    return 0;\n  }\n  return static_cast<uint8_t>((static_cast<uint32_t>(raw - 128) * 255u) / 127u);\n}\n\nenum class CalibrationState {\n''')
replace(libpad,
'''#include <cstdint>\n#include <hidsdi.h>\n''',
'''#include <cstdint>\n#include <cmath>\n#include <algorithm>\n#include <hidsdi.h>\n''')
replace(libpad,
'''              g_fn_parseSenseInputReport(padContext, pSingleReport, static_cast<uint32_t>(reportStride), isBt, &controllerState);\n\n              uint64_t currentHostTime = GetHostTimestamp();\n''',
'''              g_fn_parseSenseInputReport(padContext, pSingleReport, static_cast<uint32_t>(reportStride), isBt, &controllerState);\n\n              controllerState.leftStickX = ApplyUserStickCurve(controllerState.leftStickX);\n              controllerState.leftStickY = ApplyUserStickCurve(controllerState.leftStickY);\n              controllerState.rightStickX = ApplyUserStickCurve(controllerState.rightStickX);\n              controllerState.rightStickY = ApplyUserStickCurve(controllerState.rightStickY);\n\n              if (!isLeft) {\n                controllerState.rightTrigger = ApplyUserRightTriggerFix(controllerState.rightTrigger);\n              }\n\n              uint64_t currentHostTime = GetHostTimestamp();\n''')

print("PSVR2Toolkit custom patch applied successfully")
