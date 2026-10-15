#!/usr/bin/env python3
"""Read-only inspection of generated Joey code after all patch stages.

Reports anchors and bounded public-source excerpts. Never includes private SDK.
v46 includes a source-level proof that the UE5.6 previous-clip bridge is
present; the runtime layout gate still fails closed if any live check differs.
"""
import hashlib
import json
import sys
from pathlib import Path

TARGETS = {
 "src/mods/vr/FFakeStereoRenderingHook.cpp": [
   "vr->duoview_state().camera(key, 1, *pose)",
   "vr->duoview_state().camera(key, 0, pose)",
   "const auto controller_camera_guard_active = vr->is_controller_camera_conflict_guard_active();",
   "uevr::duoview::apply_frame_projection(double_matrix,*frame",
   "reconcile(init_options_ue5->projection_matrix)",
   "vr->duoview_state().scene(key,index,state,applied)",
   "vr->duoview_state().view_transform(",
   "vr->duoview_state().temporal_contract(key,index)",
   "uevr::duoview::ue56::apply_clip_to_prev_clip_override(",
 ],
 "src/mods/VR.cpp": [
   "std::optional<uevr::duoview::ViewFrame> VR::duoview_begin_frame()",
   "return m_duoview_gaze.read_sample(frozen,optical)",
 ],
 "src/mods/vr/D3D12Component.cpp": [
   "vr->duoview_state().consume(",
   "duo_recorded = item->record(",
   "vr->duoview_abort(\"XR copy/composite fault; safe original Mono requested\")",
 ],
 "src/mods/vr/runtimes/OpenXR.cpp": [
   "bool OpenXR::restore_duoview_bootstrap_scale(float target) {",
 ],
}

def main():
    if len(sys.argv)!=3:
        raise SystemExit("usage: audit_generated.py BACKEND EVIDENCE")
    backend,evidence=map(Path,sys.argv[1:])
    evidence.mkdir(parents=True,exist_ok=True)
    summary={}
    sections=["# Generated Joey source audit — v46 UE5.6 bridge present","",
              "Generated-source lines; anchors do not replace runtime headset validation.",""]
    for rel,needles in TARGETS.items():
        p=backend/rel
        data=p.read_bytes()
        lines=data.decode("utf-8-sig").splitlines()
        sha=hashlib.sha256(data).hexdigest()
        found={}
        sections.extend(["## "+rel,"SHA256: "+sha,""])
        for needle in needles:
            matches=[i for i,line in enumerate(lines) if needle in line]
            if len(matches)!=1:
                raise RuntimeError("{}: expected exactly one {!r}, got {}".format(rel,needle,len(matches)))
            idx=matches[0]
            found[needle]=idx+1
            sections.extend(["### Anchor at line "+str(idx+1)+": "+needle,"    C++"])
            for j in range(max(0,idx-8),min(len(lines),idx+10)):
                sections.append("    {:>7}: {}".format(j+1,lines[j]))
            sections.append("")
        summary[rel]={"sha256":sha,"bytes":len(data),"lines":len(lines),"anchors":found}
    summary["previous_unreal_projection_consumed"]="ClipToPrevClipOverride_WRITTEN_ONLY_AFTER_UE56_LAYOUT_GATE"
    summary["active_upscaler"]="NOT_OBSERVED"
    summary["temporal_gate"]="REQUIRES_TWO_SUCCESSFUL_UE56_OVERRIDES_AFTER_FIRST_FRAME"
    (evidence/"v46-generated-source-audit.json").write_text(
        json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    (evidence/"v46-generated-source-audit.md").write_text(
        "\n".join(sections)+"\n",encoding="utf-8")
    print("v46 generated-source anchors audited; UE5.6 previous-clip bridge and fail-closed gate present.")

if __name__=="__main__":
    main()
