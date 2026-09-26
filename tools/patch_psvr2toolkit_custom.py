from pathlib import Path

ROOT = Path("psvr2toolkit")


def replace(path, old, new):
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Pattern not found in {path}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")

# ---------------------------------------------------------------------------
# 1) SteamVR settings: independent pre-crop recommended render target override.
#    Defaults are pre-compensated for the user's current Advanced FOV crop:
#      horizontal remaining = 80% of total binocular HFOV
#      top removed = 10% of total VFOV
#      bottom removed = 25% of total VFOV
#    Native PSVR2 recommendation reference: 3400 x 3468.
#    Desired post-crop angular-density target: ~2568 x 1844.
#    SteamVR's letterbox/aspect correction is ~0.65/0.80 = 0.8125 vertically,
#    so advertise 2568 x 2268 pre-crop -> expected ~2568 x 1844 post-crop.
# ---------------------------------------------------------------------------
settings = "projects/psvr2_openvr_driver_ex/utils/driver_settings.h"
replace(settings,
'''#define STEAMVR_SETTINGS_DISABLE_HIDDEN_AREA_MESH "disableHiddenAreaMesh"\n''',
'''#define STEAMVR_SETTINGS_DISABLE_HIDDEN_AREA_MESH "disableHiddenAreaMesh"\n#define STEAMVR_SETTINGS_RENDER_TARGET_OVERRIDE "renderTargetOverride"\n#define STEAMVR_SETTINGS_RENDER_TARGET_WIDTH "renderTargetWidth"\n#define STEAMVR_SETTINGS_RENDER_TARGET_HEIGHT "renderTargetHeight"\n''')
replace(settings,
'''#define SETTING_DISABLE_HIDDEN_AREA_MESH_DEFAULT_VALUE false\n''',
'''#define SETTING_DISABLE_HIDDEN_AREA_MESH_DEFAULT_VALUE false\n#define SETTING_RENDER_TARGET_OVERRIDE_DEFAULT_VALUE true\n#define SETTING_RENDER_TARGET_WIDTH_DEFAULT_VALUE 2568\n#define SETTING_RENDER_TARGET_HEIGHT_DEFAULT_VALUE 2268\n''')

# ---------------------------------------------------------------------------
# 2) Enforce the driver-level recommendation whenever Sony's driver updates it.
# ---------------------------------------------------------------------------
host = "projects/psvr2_openvr_driver_ex/driver_host_proxy.cpp"
replace(host,
'''void DriverHostProxy::SetRecommendedRenderTargetSize(uint32_t unWhichDevice, uint32_t nWidth, uint32_t nHeight) {\n  m_pDriverHost->SetRecommendedRenderTargetSize(unWhichDevice, nWidth, nHeight);\n}\n''',
'''void DriverHostProxy::SetRecommendedRenderTargetSize(uint32_t unWhichDevice, uint32_t nWidth, uint32_t nHeight) {\n  if (DriverSettings::GetBool(STEAMVR_SETTINGS_RENDER_TARGET_OVERRIDE, SETTING_RENDER_TARGET_OVERRIDE_DEFAULT_VALUE)) {\n    int width = DriverSettings::GetInt32(STEAMVR_SETTINGS_RENDER_TARGET_WIDTH, SETTING_RENDER_TARGET_WIDTH_DEFAULT_VALUE);\n    int height = DriverSettings::GetInt32(STEAMVR_SETTINGS_RENDER_TARGET_HEIGHT, SETTING_RENDER_TARGET_HEIGHT_DEFAULT_VALUE);\n    if (width > 0 && height > 0) {\n      nWidth = static_cast<uint32_t>(width);\n      nHeight = static_cast<uint32_t>(height);\n    }\n  }\n  m_pDriverHost->SetRecommendedRenderTargetSize(unWhichDevice, nWidth, nHeight);\n}\n''')

# Also push the configured value once after HMD activation, in case the Sony
# display component does not emit SetRecommendedRenderTargetSize itself.
hmd = "projects/psvr2_openvr_driver_ex/driver_hooks/hmd_device_hooks.cpp"
replace(hmd,
'''  DriverHostProxy::Instance()->SetDevice(DeviceType::HMD, ulPropertyContainer, unObjectId);\n\n  // Sony driver only defines the standard hidden area mesh.\n''',
'''  DriverHostProxy::Instance()->SetDevice(DeviceType::HMD, ulPropertyContainer, unObjectId);\n\n  if (result == vr::VRInitError_None &&\n      DriverSettings::GetBool(STEAMVR_SETTINGS_RENDER_TARGET_OVERRIDE, SETTING_RENDER_TARGET_OVERRIDE_DEFAULT_VALUE)) {\n    int width = DriverSettings::GetInt32(STEAMVR_SETTINGS_RENDER_TARGET_WIDTH, SETTING_RENDER_TARGET_WIDTH_DEFAULT_VALUE);\n    int height = DriverSettings::GetInt32(STEAMVR_SETTINGS_RENDER_TARGET_HEIGHT, SETTING_RENDER_TARGET_HEIGHT_DEFAULT_VALUE);\n    if (width > 0 && height > 0) {\n      DriverHostProxy::Instance()->SetRecommendedRenderTargetSize(unObjectId, static_cast<uint32_t>(width), static_cast<uint32_t>(height));\n    }\n  }\n\n  // Sony driver only defines the standard hidden area mesh.\n''')

# ---------------------------------------------------------------------------
# 3) Preserve user's custom 3x PCM haptics gain.
#    Apply after all PCM/generated haptics are mixed, before timestamp/CRC/send.
# ---------------------------------------------------------------------------
sense = "projects/psvr2_openvr_driver_ex/sense_controller.cpp"
replace(sense,
'''    buffer.settings.timeStampMicrosecondsLastSend = static_cast<uint32_t>(GetHostTimestamp());\n''',
'''    // User custom: fixed 3x gain on the final signed 8-bit PCM block.\n    // Saturate rather than wrap so clipping is deterministic.\n    for (int i = 0; i < sizeof(buffer.hapticPCM); ++i) {\n      int sample = static_cast<int>(static_cast<int8_t>(buffer.hapticPCM[i]));\n      sample = std::clamp(sample * 3, -128, 127);\n      buffer.hapticPCM[i] = static_cast<uint8_t>(static_cast<int8_t>(sample));\n    }\n\n    buffer.settings.timeStampMicrosecondsLastSend = static_cast<uint32_t>(GetHostTimestamp());\n''')

# ---------------------------------------------------------------------------
# 4) Preserve user's current stick curve + right-R2 half-range remap.
#    Stick curve: linear through first 20% magnitude, then quadratic:
#      f(m)=m                                      for m <= .20
#      f(m)=.20+.80*((m-.20)/.80)^2               above .20
# ---------------------------------------------------------------------------
libpad = "projects/psvr2_openvr_driver_ex/driver_hooks/libpad_hooks.cpp"
replace(libpad,
'''const int32_t k_stablePhasePeriod = 9;\n\nenum class CalibrationState {\n''',
'''const int32_t k_stablePhasePeriod = 9;\n\nstatic uint8_t ApplyUserStickCurve(uint8_t raw) {\n  int centered = static_cast<int>(raw) - 128;\n  if (centered == 0) {\n    return 128;\n  }\n\n  const bool positive = centered > 0;\n  const int maxMagnitude = positive ? 127 : 128;\n  double magnitude = static_cast<double>(std::abs(centered)) / static_cast<double>(maxMagnitude);\n  double curved = magnitude;\n  if (magnitude > 0.20) {\n    const double t = (magnitude - 0.20) / 0.80;\n    curved = 0.20 + 0.80 * t * t;\n  }\n\n  int outputMagnitude = static_cast<int>(std::lround(curved * static_cast<double>(maxMagnitude)));\n  int output = 128 + (positive ? outputMagnitude : -outputMagnitude);\n  return static_cast<uint8_t>(std::clamp(output, 0, 255));\n}\n\nstatic uint8_t ApplyUserRightTriggerFix(uint8_t raw) {\n  // User custom: raw 0..128 => 0, raw 129..255 => 2..255.\n  if (raw <= 128) {\n    return 0;\n  }\n  return static_cast<uint8_t>((static_cast<uint32_t>(raw - 128) * 255u) / 127u);\n}\n\nenum class CalibrationState {\n''')
# std::abs/lround need <cmath>/<cstdlib> availability; <cmath> is sufficient.
replace(libpad,
'''#include <cstdint>\n#include <hidsdi.h>\n''',
'''#include <cstdint>\n#include <cmath>\n#include <algorithm>\n#include <hidsdi.h>\n''')
replace(libpad,
'''              g_fn_parseSenseInputReport(padContext, pSingleReport, static_cast<uint32_t>(reportStride), isBt, &controllerState);\n\n              uint64_t currentHostTime = GetHostTimestamp();\n''',
'''              g_fn_parseSenseInputReport(padContext, pSingleReport, static_cast<uint32_t>(reportStride), isBt, &controllerState);\n\n              // User custom stick response curve. Apply to both stick axes carried by the parsed state.\n              controllerState.leftStickX = ApplyUserStickCurve(controllerState.leftStickX);\n              controllerState.leftStickY = ApplyUserStickCurve(controllerState.leftStickY);\n              controllerState.rightStickX = ApplyUserStickCurve(controllerState.rightStickX);\n              controllerState.rightStickY = ApplyUserStickCurve(controllerState.rightStickY);\n\n              // User custom R2 semi-press fix: only alter the right controller's right trigger.\n              if (!isLeft) {\n                controllerState.rightTrigger = ApplyUserRightTriggerFix(controllerState.rightTrigger);\n              }\n\n              uint64_t currentHostTime = GetHostTimestamp();\n''')

print("PSVR2Toolkit custom patch applied successfully")
