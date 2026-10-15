#!/usr/bin/env python3
"""Verify the v47 target-safe eye-tracking and fault-quarantine guards."""
from pathlib import Path
import sys

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def main():
    if len(sys.argv) != 3:
        raise RuntimeError("usage: verify_v47_target_policy.py BACKEND_DIR EVIDENCE_DIR")
    root = Path(sys.argv[1])
    evidence = Path(sys.argv[2])
    vrh = (root / "src/mods/VR.hpp").read_text(encoding="utf-8")
    vr = (root / "src/mods/VR.cpp").read_text(encoding="utf-8")
    hook = (root / "src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")

    require("std::atomic<bool> m_duoview_temporal_abi_supported{false};" in vrh,
            "Engine-layout capability must be explicit and default closed")
    require("duoview_begin_frame(bool temporal_abi_supported)" in vrh and
            "set_duoview_temporal_abi_supported(temporal_abi_supported);" in vr,
            "Frame setup must receive the engine temporal-layout capability")
    require("candidate.eye_tracked = candidate.eye_tracked &&" in vr and
            "m_duoview_temporal_abi_supported.load(std::memory_order_acquire)" in vr,
            "Unsupported engine layouts must freeze DuoView as a fixed crop")
    require("m_duo_gaze->value()=false;" in vr and
            "UE previous-clip layout is unverified; fixed-center crop remains active" in vr,
            "Unsupported eye tracking must be turned off with a clear runtime reason")
    require("Eye tracking unavailable on this UE layout" in vr and
            "fixed-crop DuoView remains active" in vr,
            "UI must explain the fixed-crop fallback")
    require(hook.count("duoview_begin_frame(is_ue_5_6_or_newer())") == 5,
            "All five render hook paths must pass the same engine-layout capability")
    writer = hook.find("apply_clip_to_prev_clip_override(")
    require(writer >= 0, "Existing UE5.6 temporal bridge should remain available behind its gates")
    writer_guard = hook[max(0, writer - 1800):writer]
    require("duoview_eye_tracking_enabled()" in writer_guard and
            "is_ue_5_6_or_newer()" in writer_guard,
            "Raw SceneView write must require gaze opt-in and the UE5.6 version guard")
    require("m_duoview_quarantined.store(false" not in vr,
            "Mode reselection must not clear a same-session GPU fault quarantine")
    require("restart UEVR/game before retrying" in vr,
            "Fault status must tell the user how to safely recover")
    evidence.mkdir(parents=True, exist_ok=True)
    report = {
        "engine_target": "UE 5.5.4",
        "eye_tracked_crop_enabled": False,
        "fixed_crop_fallback": True,
        "unverified_ue55_sceneview_write": False,
        "fault_quarantine_retryable_by_mode_reselect": False,
        "ue56_temporal_bridge_still_guarded": True,
    }
    (evidence / "duoview-v47-target-policy.json").write_text(
        __import__("json").dumps(report, indent=2) + "\n", encoding="utf-8")
    print("v47 UE5.5 fixed-crop, temporal-write guard, and session quarantine policy: PASS")

if __name__ == "__main__":
    main()
