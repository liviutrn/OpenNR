#!/usr/bin/env python3
"""Audit v50 startup activation, true temporal-policy distinction, and CI source hooks."""
from pathlib import Path
import json,sys
def need(cond,msg):
    if not cond: raise RuntimeError("v50 activation gate: "+msg)
def main():
    if len(sys.argv)!=3: raise RuntimeError("usage: verify_v50_activation.py BACKEND EVIDENCE")
    root,evidence=map(Path,sys.argv[1:])
    vr=(root/"src/mods/VR.cpp").read_text(encoding="utf-8")
    vrh=(root/"src/mods/VR.hpp").read_text(encoding="utf-8")
    dx=(root/"src/mods/vr/D3D12Component.cpp").read_text(encoding="utf-8")
    state=(root/"src/mods/vr/DuoViewState.hpp").read_text(encoding="utf-8")
    cfg=(root/"src/mods/vr/DuoViewConfig.hpp").read_text(encoding="utf-8")
    hook=(root/"src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
    checks={
        "user_option_defaults_history_on":
            'DuoViewFreshFoveaNoHistory"), false' in vrh and
            '.fresh_fovea_no_history=m_duo_no_history->value()' in vr,
        "option_is_persisted_and_visible":
            '*m_duo_history_audit, *m_duo_no_history,' in vrh and
            'm_duo_no_history->draw(' in vr,
        "uncorrected_gaze_explicitly_diagnostic":
            '.allow_uncorrected_gaze_history=!m_duo_no_history->value()' in vr and
            'bool allow_uncorrected_gaze_history{}' in cfg and
            'slot->config.settings.allow_uncorrected_gaze_history ||' in state and
            'current.allow_uncorrected_gaze_history==candidate.allow_uncorrected_gaze_history' in vr,
        "strict_default_policy_retained":
            'bool allow_uncorrected_gaze_history{}' in cfg and
            'if (slot->config.settings.eye_tracked && !result.history_gate_pass) return {};' in state,
        "no_history_opt_in_keeps_fail_closed":
            'if (slot->config.settings.fresh_fovea_no_history && !slot->fovea_history_disabled) return {};' in state and
            'init_options_ue5->scene_view_state=nullptr;' in hook,
        "first_incomplete_pair_retries":
            'if (!frame) {' in dx and
            '[DuoView][Activation] incomplete pair' in dx and
            'retry next producer frame' in dx,
        "real_compositor_fault_still_quarantines":
            'else if (duo_failed || !submitted || !recorded)' in dx and
            'vr->duoview_abort("DuoView compositor/XR copy failed with complete pair' in dx,
        "render_mode_5_untouched":
            'else if (vr->is_using_mono()) {' in dx,
        "preserve_user_openxr_scale":
            'DO NOT clobber resolution_scale before profile values are loaded.' in vr and
            'm_duoview_saved_resolution_scale=m_openxr->resolution_scale->value();' in vr and
            'm_openxr->resolution_scale->value() = 0.30f;' in vr and
            'm_duoview->resolution_scale' not in vr,
        "still_uses_real_duoview":
            'duoview_state().consume(' in dx and
            'duo_recorded = item->record(' in dx and
            'vr->note_duoview_bootstrap_composite()' in dx,
    }
    for label,valid in checks.items():need(valid,label)
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/"duoview-v50-activation-policy.json").write_text(json.dumps({
        "target":"STALKER 2 UE5.5.4 DX12 SteamVR OpenXR",
        "observed_v49":"ID6 committed, two UE constructors, 3 producer frames, no GPU composite, one startup quarantine",
        "claims":checks,"eye_tracking_smoothing_fix_claimed":False,
        "new_headset_test_passed":False,
        "fresh_fovea_disabled_by_default":True,
        "uncorrected_gaze_history_risk":"UE5.5 temporal accumulation can still tremble when crop moves",
        "cold_start_snapshot_missing":"Retry next producer frame instead of permanent quarantine",
        "real_gpu_fault":"Latched quarantine remains",
    },indent=2)+"\n",encoding="utf-8")
    print("v50 activation recovery, diagnostic temporal opt-in, and bootstrap scale source checks: PASS")
if __name__=="__main__":main()
