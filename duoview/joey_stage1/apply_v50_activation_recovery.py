#!/usr/bin/env python3
"""v50: remove a proven first-frame activation dead-end without bypassing safety.

Apply after v49 diagnostics against the exact pinned Joey source tree.
Preserve true two-view compositing and automatic synthetic/live gaze trace.
"""
from pathlib import Path
import sys

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"v50 {label}: expected exactly one anchor, saw {count}")
    return text.replace(old, new, 1)

def patch(path, replacements):
    old = path.read_text(encoding="utf-8-sig")
    new = old
    for before, after, label in replacements:
        new = replace_once(new, before, after, label)
    path.write_text(new, encoding="utf-8", newline="")

def main():
    if len(sys.argv) != 2:
        raise RuntimeError("usage: apply_v50_activation_recovery.py BACKEND_DIR")
    root = Path(sys.argv[1])

    patch(root/"src/mods/VR.hpp", [
        (
            '    const ModToggle::Ptr m_duo_history_audit{ModToggle::create(generate_name("DuoViewTemporalAudit"), false)};',
            '    const ModToggle::Ptr m_duo_history_audit{ModToggle::create(generate_name("DuoViewTemporalAudit"), false)};\n'
            '    const ModToggle::Ptr m_duo_no_history{ModToggle::create(generate_name("DuoViewFreshFoveaNoHistory"), false)};',
            "no-history off by default, explicit opt-in"
        ),
        (
            '*m_duo_smoothing, *m_duo_history_audit,',
            '*m_duo_smoothing, *m_duo_history_audit, *m_duo_no_history,',
            "persist no-history option"
        ),
    ])

    patch(root/"src/mods/VR.cpp", [
        (
            '.fresh_fovea_no_history=true, // v48: withhold foveal UE SceneViewState EVERY frame; crop changes always start fresh',
            '.fresh_fovea_no_history=m_duo_no_history->value(), // v50: optional experiment; OFF during startup/recovery',
            "remove forced startup no-history contract"
        ),
        (
            'm_duo_history_audit->draw("Diagnostic: projection/history continuity (logs, OFF by default)");',
            'm_duo_no_history->draw("Experimental: fovea without UE SceneViewState history");\n'
            '                ImGui::TextWrapped("OFF by default for reliable startup. ON enforces the v48 typed UE5.5 constructor override; if it cannot be applied, that frame will safely use Mono.");\n'
            '                m_duo_history_audit->draw("Diagnostic: projection/history continuity (logs, OFF by default)");',
            "user-visible no-history control"
        ),
        (
            'ImGui::TextWrapped("v48 test: adjustable gaze smoothing occurs BEFORE projection. Foveal FSceneViewState stays disabled on every UE5.5 frame. Peripheral history remains independent.");',
            'ImGui::TextWrapped("v50 activation recovery: normal foveal history at startup; v48 history bypass is an opt-in experiment. Synthetic gaze and diagnostic traces remain enabled.");',
            "correct UI label"
        ),
        (
            'ImGui::TextWrapped("Fresh-fovea mode requires the validated UE5.5 typed init options; the frame is rejected if foveal state could not be disabled.");',
            'ImGui::TextWrapped("The optional fresh-fovea experiment requires verified UE5.5 typed init options; unsupported layouts are not modified.");',
            "correct unsupported ABI explanation"
        ),
        (
            'm_duo_debug_source->value()=0;',
            'm_duo_debug_source->value()=0; m_duo_no_history->value()=false;',
            "reset opt-in when restoring defaults"
        ),
    ])

    patch(root/"src/mods/vr/D3D12Component.cpp", [
        (
            '''                        if (duo_failed || !submitted || !recorded)
                            vr->duoview_abort("XR copy/composite fault; safe original Mono requested");''',
            '''                        // Cold-start frames may lack a complete pair while UE builds its
                        // scene states and constructors. The original Joey Mono copy has
                        // already been attempted; do not permanently quarantine ID6 just
                        // because the FIRST frame has no consumable DuoView snapshot.
                        // An actual compositor failure with a valid complete pair still
                        // enters the existing session-latched safety quarantine.
                        if (!frame) {
                            const auto diagnostic_key=vr->duoview_key(static_cast<uint32_t>(frame_count));
                            if (const auto snap=vr->duoview_state().snapshot(diagnostic_key)) {
                                SPDLOG_WARNING_EVERY_N_SEC(1,
                                    "[DuoView][Activation] incomplete pair frame={} nativeCopy={} xrSubmitted={} "
                                    "mainFamily={} invalid={} rect=({},{}) proj=({},{}) cameras=({},{}) "
                                    "cameraValid={} states=({:#x},{:#x}) freshRequired={} freshApplied={} gaze={} historyGate={}",
                                    frame_count,recorded,submitted,snap->main_family,snap->invalid,
                                    snap->rectangles[0],snap->rectangles[1],
                                    snap->projections[0],snap->projections[1],
                                    snap->cameras[0],snap->cameras[1],snap->camera_valid,
                                    snap->scene_states[0],snap->scene_states[1],
                                    snap->config.settings.fresh_fovea_no_history,
                                    snap->fovea_history_disabled,
                                    snap->config.settings.eye_tracked,snap->history_gate_pass);
                            } else {
                                SPDLOG_WARNING_EVERY_N_SEC(1,
                                    "[DuoView][Activation] missing immutable frame={} nativeCopy={} xrSubmitted={}; retry next producer frame",
                                    frame_count,recorded,submitted);
                            }
                        } else if (duo_failed || !submitted || !recorded) {
                            vr->duoview_abort("DuoView compositor/XR copy failed with complete pair; original Mono requested");
                        }''',
            "startup incomplete pair must not quarantine"
        ),
    ])

    patch(root/"src/mods/VR.cpp", [
        (
            '''    m_openxr = std::make_shared<runtimes::OpenXR>();
    if (!m_duoview_restore_attempted) {
        m_openxr->resolution_scale->value() = 0.30f;
    }

    spdlog::info("[VR] Initializing OpenXR");''',
            '''    m_openxr = std::make_shared<runtimes::OpenXR>();
    // v50: DO NOT clobber resolution_scale before profile values are loaded.
    // The bootstrap code after on_config_load captures the user's requested
    // scale first and only THEN applies 0.30 for initial XR swapchains.
    spdlog::info("[VR] Initializing OpenXR");''',
            "preserve desired OpenXR scale before startup override"
        ),
    ])
    print("v50 activation recovery applied: optional fresh-fovea, retry incomplete pair, preserve user resolution.")

if __name__ == "__main__":
    main()
