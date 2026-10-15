#!/usr/bin/env python3
"""Adversarial source-level checks for DuoView v49; never claims headset proof."""
from pathlib import Path
import json,sys
def require(cond,desc):
    if not cond: raise RuntimeError("v49 diagnosis contract: "+desc)
def main():
    root,evidence=map(Path,sys.argv[1:])
    vr=(root/"src/mods/VR.cpp").read_text(encoding="utf8")
    hook=(root/"src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf8")
    com=(root/"src/mods/vr/DuoViewD3D12.hpp").read_text(encoding="utf8")
    state=(root/"src/mods/vr/DuoViewState.hpp").read_text(encoding="utf8")
    diag=(root/"src/mods/vr/DuoViewDiagnostic.hpp").read_text(encoding="utf8")
    gpu=(root/"src/mods/vr/DuoViewImageProbe.hpp").read_text(encoding="utf8")
    dx=(root/"src/mods/vr/D3D12Component.cpp").read_text(encoding="utf8")
    checks={
      "source_gaze_frozen_once_per_source_frame":'source_gaze(key, m_duoview_gaze.read_sample(frozen,optical))' in vr,
      "independent_uevr_log":'[DuoView][V49]' in vr,
      "cpu_new_frame_stage":'recorder.cpu(0,0,*result' in vr,
      "engine_constructor_pre_and_post":'Recorder::get().cpu(1,idx' in hook and 'Recorder::get().cpu(2,idx' in hook,
      "xr_submission_and_fault":'Recorder::get().cpu(3,0,*frame' in dx and
          '(submitted && recorded && duo_recorded) ? 4u : 7u' in dx,
      "gpu_crop_source_and_final":'capture(cmd,0,atlas' in gpu and 'capture(cmd,1,atlas' in gpu and
          'capture(cmd,2,composite' in gpu,
      "gpu_slot_retirement":'probe_.harvest();' in com and
          'probe_.schedule(device, cmd, atlas, output_.Get(), frame);' in com,
      "no_gpu_stall":all(x not in gpu for x in ('WaitForSingleObject','WaitForSingleObjectEx','SetEventOnCompletion','Sleep(')),
      "bounded_queues":'queue_.size()<20000' in diag and 'images_.size()<20' in diag,
      "separate_file_evidence":all(x in diag for x in ('frame_trace.csv','image_manifest.csv','health.txt')),
      "phase_fixed_step_sweep_live":all(x in diag for x in ('n < 120','n < 240','n < 360','n < 480','Phase::live')),
      "preserve_v48_foveal_state":'fresh_fovea_no_history=true' in vr and
          'fovea_history_disabled' in state and 'init_options_ue5->scene_view_state=nullptr;' in hook,
      "no_raw_ue55_memory_write":'ClipToPrevClipOverride' not in gpu and 'D3DCompile(' not in com,
      "mode_isolation":'is_duoview_renderer_active()' in hook,
    }
    for label,ok in checks.items():require(ok,label)
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/"duoview-v49-source-policy.json").write_text(json.dumps({
        "target":"STALKER 2 UE5.5 DX12 SteamVR OpenXR",
        "source_contracts":checks,"device_proof":False,
        "limitations":"No direct access to user's runtime or headset. GPU readback becomes safe only when the command slot has retired. Missing GPU images is an explicit incomplete evidence channel."
    },indent=2)+"\n")
    print("v49 three-channel instrumented source: all static gates passed (not headset validated).")
if __name__=="__main__":main()
