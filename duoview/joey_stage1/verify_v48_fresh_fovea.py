#!/usr/bin/env python3
"""Fail-closed v48 audit of the actual generated Joey constructor hook.

This is a SOURCE and test gate, not proof that the game will run correctly.
No UE5.5 raw SceneView byte offsets, GPU history memory writes, or SDK edits.
"""
from pathlib import Path
import json, sys

def require(ok, message):
    if not ok: raise RuntimeError(message)

def main():
    require(len(sys.argv)==3,"usage: verify_v48_fresh_fovea.py BACKEND EVIDENCE")
    root,evidence=map(Path,sys.argv[1:])
    hook=(root/"src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
    vr=(root/"src/mods/VR.cpp").read_text(encoding="utf-8")
    state=(root/"src/mods/vr/DuoViewState.hpp").read_text(encoding="utf-8")
    config=(root/"src/mods/vr/DuoViewConfig.hpp").read_text(encoding="utf-8")
    require(hook.count("duoview_begin_frame(true)")==5,
            "All frame creation hooks must permit v48 gaze (independent of UE5.6 temporal ABI)")
    require("is_ue5 && !is_ue_5_6_or_newer()" in hook and
            "init_options_ue5->scene_view_state==init_options_scene_state" in hook,
            "No-history override must use typed UE5.4/5.5 init-options field and identity guard")
    require("duo_saved_fovea_state=init_options_ue5->scene_view_state;" in hook and
            "init_options_ue5->scene_view_state=nullptr;" in hook and
            "init_options_ue5->scene_view_state=duo_saved_fovea_state;" in hook,
            "The foveal state must be withheld only during construction then restored")
    disable=hook.index("init_options_ue5->scene_view_state=nullptr;")
    constructor=hook.index("g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>",disable)
    restore=hook.index("init_options_ue5->scene_view_state=duo_saved_fovea_state;")
    require(disable<constructor<restore,"The no-history override must surround the constructor call")
    require("index==frozen->config.settings.fovea_view" in hook and
            "duoview_producer_key()" in hook and
            "init_options_view_family->get_render_target()==rtm->get_view_family_render_target()" in hook,
            "No-history must apply only to the correct frozen foveal view in the main family")
    require("mark_fovea_history_disabled(key,index)" in hook and
            "slot->fovea_history_disabled" in state and
            "if (slot->config.settings.fresh_fovea_no_history && !slot->fovea_history_disabled) return {};" in state,
            "A frame must fail without confirmed no-history foveal constructor input")
    require("fresh_fovea_no_history=true" in vr and
            "current.fresh_fovea_no_history==candidate.fresh_fovea_no_history" in vr and
            "bool fresh_fovea_no_history{};" in config,
            "Fresh fovea setting not connected to immutable DuoView frame")
    require("vr->duoview_eye_tracking_enabled() &&" in hook and
            "is_ue_5_6_or_newer()" in hook,
            "The UE5.6 raw temporal writer must remain version gated")
    gaze=(root/"src/mods/vr/DuoViewCropStability.hpp").read_text(encoding="utf-8")
    require("m_duo_smoothing->draw(" in vr and
            ".smoothing_ms=m_duo_smoothing->value()" in vr and
            "current.smoothing_ms==candidate.smoothing_ms" in vr,
            "User's smoothing slider is missing or is not connected to live DuoView settings")
    require("s.smoothing_ms>0.f" in gaze and "std::expm1(" in gaze and
            "current_.u+(sample.uv->u-current_.u)*alpha" in gaze and
            "last_filter_ms_=now;" in gaze and
            "last_valid_=last_filter_ms_=0" in gaze,
            "Gaze smoothing must be applied to source position with clock-based EMA and stale reset")
    require("m_duoview_quarantined.store(false" not in vr,
            "Re-selection must not clear a fault quarantine")
    evidence.mkdir(parents=True,exist_ok=True)
    policy={
        "target":"STALKER 2, UE5.5.4",
        "experiment":"v48 fresh fovea, no persistent FSceneViewState",
        "eye_tracking_requested":True,
        "foveal_state_cleared_every_producer_frame":True,
        "crop_change_resets_foveal_temporal_history":True,
        "peripheral_state_unchanged":True,
        "ue55_raw_sceneview_offsets_written":False,
        "headset_validated":False,
        "limitations":"UE render/TSR/Lumen behavior requires in-game validation"
    }
    (evidence/"duoview-v48-fresh-fovea-policy.json").write_text(json.dumps(policy,indent=2)+"\n")
    print("v48 typed UE5.5 foveal state isolation, frame guard, and peripheral protection: PASS")

if __name__=="__main__":main()
