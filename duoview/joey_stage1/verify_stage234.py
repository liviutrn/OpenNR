#!/usr/bin/env python3
"""Verify exact v46 added/edited source and unchanged original SDK."""
import argparse, hashlib, json, subprocess
from pathlib import Path

EDITED_BACKEND = {
 "src/mods/vr/MonoRenderingPolicy.hpp", "src/mods/vr/CompatibilityPolicy.hpp",
 "src/mods/VR.hpp", "src/mods/VR.cpp", "src/mods/vr/RenderingMethodSetting.hpp",
 "src/mods/vr/runtimes/OpenXR.hpp", "src/mods/vr/runtimes/OpenXR.cpp",
 "src/mods/vr/FFakeStereoRenderingHook.cpp", "src/mods/vr/D3D12Component.hpp",
 "src/mods/vr/D3D12Component.cpp", "tests/MonoRenderingTests.hpp",
}
ADDED_BACKEND = {
 "src/mods/vr/DuoViewGeometry.hpp", "src/mods/vr/DuoViewGaze.hpp",
 "src/mods/vr/DuoViewCropMotion.hpp",
 "src/mods/vr/DuoViewPSVR2Gaze.hpp", "src/mods/vr/DuoViewCropStability.hpp",
 "src/mods/vr/DuoViewHistoryCorrection.hpp",
 "src/mods/vr/DuoViewFrame.hpp", "src/mods/vr/DuoViewConfig.hpp",
 "src/mods/vr/DuoViewState.hpp", "src/mods/vr/DuoViewD3D12.hpp",
 "src/mods/vr/DuoViewTemporalMath.hpp", "src/mods/vr/DuoViewUE56Layout.hpp",
 "src/mods/vr/DuoViewSceneViewTemporal.hpp",
 "src/mods/vr/DuoViewMonoCopyD3D12.hpp", "src/mods/vr/DuoViewShaderSource.hpp",
}
EDITED_FRONTEND = {"UEVR/RenderingModeOptions.cs", "tests/RenderingModes/Program.cs"}
GENERATED_FRONTEND = {"UEVR/FilteredExecutables.json"}

def git(root,*args):
 return subprocess.check_output(["git","-C",str(root),*args],text=True).strip()
def sha(p):
 return hashlib.sha256(p.read_bytes()).hexdigest()
def tracked(root):
 return set(git(root,"diff","--name-only","HEAD").splitlines())
def untracked(root):
 return set(git(root,"ls-files","--others","--exclude-standard").splitlines())

def main():
 p=argparse.ArgumentParser()
 p.add_argument("backend",type=Path)
 p.add_argument("frontend",type=Path)
 p.add_argument("evidence",type=Path)
 p.add_argument("--final",action="store_true")
 a=p.parse_args()
 assert git(a.backend,"rev-parse","HEAD")=="5ac7edc207866569334175e4ed8a7517971547f6"
 assert git(a.frontend,"rev-parse","HEAD")=="60be4b0f9a646109fd9fdf448bacd41477234091"
 sdk=a.backend/"dependencies/submodules/UESDK"
 assert git(sdk,"rev-parse","HEAD")=="3cffbc82429b6165ceec2714f0f0d9ae48f55596"
 if git(sdk,"status","--porcelain"): raise RuntimeError("SDK source not clean")
 bdiff=tracked(a.backend)
 if bdiff!=EDITED_BACKEND: raise RuntimeError(f"Wrong backend edited paths: {bdiff ^ EDITED_BACKEND}")
 buntracked=untracked(a.backend)
 if buntracked!=ADDED_BACKEND: raise RuntimeError(f"Unexpected added backend paths: {buntracked ^ ADDED_BACKEND}")
 fdiff=tracked(a.frontend)
 if fdiff - (EDITED_FRONTEND|GENERATED_FRONTEND) or not EDITED_FRONTEND.issubset(fdiff):
  raise RuntimeError(f"Unexpected frontend tracked changes: {fdiff}")
 if untracked(a.frontend): raise RuntimeError("Unexpected untracked frontend source")
 geometry=(a.backend/"src/mods/vr/DuoViewGeometry.hpp").read_text(encoding="utf-8")
 if '.fovea = {0, 0, fw, fh}' not in geometry or '.periphery = {fw, 0, pw, ph}' not in geometry:
  raise RuntimeError("Legacy atlas order must be preserved in applied source")
 # A shipping DuoView must never compile shaders on the OpenXR copy path.
 compositor=(a.backend/"src/mods/vr/DuoViewD3D12.hpp").read_text(encoding="utf-8")
 shaders=(a.backend/"src/mods/vr/DuoViewShaderSource.hpp").read_text(encoding="utf-8")
 if "D3DCompile(" in compositor or "shader_source" in compositor:
  raise RuntimeError("Runtime shader compiler still in production compositor")
 setting=(a.backend/"src/mods/vr/RenderingMethodSetting.hpp").read_text(encoding="utf-8")
 vrh=(a.backend/"src/mods/VR.hpp").read_text(encoding="utf-8")
 vr=(a.backend/"src/mods/VR.cpp").read_text(encoding="utf-8")
 xr=(a.backend/"src/mods/vr/runtimes/OpenXR.cpp").read_text(encoding="utf-8")
 d3d=(a.backend/"src/mods/vr/D3D12Component.cpp").read_text(encoding="utf-8")
 for token in ("m_selection.initialize(0)", "complete_duoview_bootstrap()", "m_bootstrap_released"):
  if token not in setting: raise RuntimeError("Native0 bootstrap selection is missing "+token)
 for token in ("m_duoview_low_resolution_applied", "m_duoview_bootstrap_composed_frames", "restore_duoview_bootstrap_scale", "std::chrono::seconds(3)"):
  if token not in vr: raise RuntimeError("Guarded native boot scale transition missing "+token)
 if 'm_openxr->resolution_scale->value() = 0.30f;' not in vr:
  raise RuntimeError("Low-resolution bootstrap is not armed BEFORE initial XR initialization")
 if "note_duoview_bootstrap_composite()" not in d3d:
  raise RuntimeError("Restore is not gated on true compositor success")
 if "on_openxr_resolution_scale_changed(old_width,old_height,new_width,new_height)" not in xr:
  raise RuntimeError("Restore must reuse original UEVR guarded scale callback")
 hooked=(a.backend/"src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
 if "if (!vr->is_using_duoview_mono() && !vr->is_ghosting_fix_enabled()" not in hooked:
  raise RuntimeError("ID6 requires SceneView constructor hook regardless of Native Fix")
 if "DuoViewSceneLayout.hpp" in vrh or "duoview_scene_extent" in vrh:
  raise RuntimeError("Compact startup atlas accidentally enabled")
 if "DuoViewDlssHistory" in vrh or "DuoViewDlssHistory" in vr:
  raise RuntimeError("Unsafe NVIDIA NGX interception unexpectedly restored")
 if "DuoViewPSVR2Gaze.hpp" not in vrh:
  raise RuntimeError("Production VR headers missing native PSVR2 gaze integration")
 correction=(a.backend/"src/mods/vr/DuoViewHistoryCorrection.hpp").read_text(encoding="utf-8")
 if "previous.key.frame + 1u != current.key.frame" not in correction or (
     "current.layout.u0-previous.layout.u0" not in correction):
  raise RuntimeError("History compensation does not check strict prev key / Cheeky sign")
 if "accept_composite(frame->config.key)" not in d3d:
  raise RuntimeError("DuoView does not record only successful XR source copies")
 if "{frame.history_sample_offset.u, frame.history_sample_offset.v}" in compositor:
  raise RuntimeError("Current color must not receive the temporal history displacement")
 if "fovea_uv_rows" in compositor or "frame.steering" in compositor:
  raise RuntimeError("Obsolete gaze-camera homography must not reach moving-crop renderer")
 if "m_duo_history_shift" in vr or "m_duo_history_strength" in vr:
  raise RuntimeError("Invalid final-color displacement controls must not be exposed")
 if ".history_sample_correction=false" not in vr:
  raise RuntimeError("Legacy saved settings must not reenable current-color displacement")
 state=(a.backend/"src/mods/vr/DuoViewState.hpp").read_text(encoding="utf-8")
 if "compositor_history_shift(" in state:
  raise RuntimeError("Temporal crop vector cannot be applied to current color packets")
 crop_motion=(a.backend/"src/mods/vr/DuoViewCropMotion.hpp").read_text(encoding="utf-8")
 if "apply_foveal_crop(matrix,frame.config.layout)" not in state or (
     "expected_crop_motion(last_completed_->config,slot->config)" not in state):
  raise RuntimeError("Tracked fovea must use the moving projection crop and audit its expected vector")
 if "previous.key.frame + 1u != current.key.frame" not in crop_motion or (
     "double(now.u0) - old.u0" not in crop_motion):
  raise RuntimeError("Crop-vector diagnostic must have a strict frame key and current-to-previous origin sign")
 if "output->pitch=rendered->rotation[0]" not in hooked or (
     "output->yaw=rendered->rotation[1]" not in hooked):
  raise RuntimeError("View0 actual renderer output does not consume the gaze camera")
 if "steering_camera" in state or "source_cameras" in state or "DuoViewSteering" in state:
  raise RuntimeError("Tracked gaze must leave both source camera poses unchanged")
 if "result.history_gate_pass=result.distinct_view_states" not in state or (
     "result.history_gap" not in state or "stable_projection_history" not in state or
     "!result.history_gate_pass" not in state):
  raise RuntimeError("Unreal's per-view history must be distinct, stable, layout-compatible and gap-gated")
 if "temporal_bridge_ready" not in state or (
     "temporal_override_attempted[0]" not in state or
     "temporal_override_applied[1]" not in state or
     "same_current_source_transform" not in state):
  raise RuntimeError("Eye-tracked composition is not fail-closed on the UE temporal bridge")
 temporal_math=(a.backend/"src/mods/vr/DuoViewTemporalMath.hpp").read_text(encoding="utf-8")
 layout=(a.backend/"src/mods/vr/DuoViewUE56Layout.hpp").read_text(encoding="utf-8")
 bridge=(a.backend/"src/mods/vr/DuoViewSceneViewTemporal.hpp").read_text(encoding="utf-8")
 if "make_clip_to_prev_clip" not in temporal_math or "inverse_current" not in temporal_math:
  raise RuntimeError("v46 source does not construct the full current-to-previous clip transform")
 for token in ("ClipToPrevClipOverride", "get_view_family_offset",
               "apply_clip_to_prev_clip_override", "readback"):
  if token not in bridge:
   raise RuntimeError("UE5.6 temporal bridge validation is incomplete: "+token)
 for token in ("static_assert(offsetof(SceneView, ClipToPrevClipOverride) == 0x12a0)",
               "static_assert(sizeof(SceneView) == 0x1330)",
               "scene_view_init_options_offset"):
  if token not in layout:
   raise RuntimeError("UE5.6 SceneView ABI layout proof is incomplete: "+token)
 if "vr->duoview_state().view_transform" not in hooked or (
     "vr->duoview_state().temporal_contract" not in hooked or
     "apply_clip_to_prev_clip_override" not in hooked):
  raise RuntimeError("Generated hook does not latch source transforms and apply the UE5.6 bridge")
 sensor=(a.backend/"src/mods/vr/DuoViewPSVR2Gaze.hpp").read_text(encoding="utf-8")
 if "const bool fresh=sequence_.observe(candidate)" not in sensor:
  raise RuntimeError("CAPI sample freshness must be local to this reader, not shared notification state")
 if ("struct GazeObservation" not in sensor or
     "status.raw.timestamp,status.raw.frame_counter" not in sensor or
     "last_observation_=describe_gaze_sample(candidate,now,uv.has_value())" not in sensor):
  raise RuntimeError("Real CAPI sensor sample metadata is not recorded from producer frame")
 if ("GazeSample read_sample" not in sensor or
     "return GazeSample{cached_uv_,fresh_time_,fresh,false}" not in sensor or
     "sample.host_arrival_ms" not in (a.backend/"src/mods/vr/DuoViewCropStability.hpp").read_text(encoding="utf-8")):
  raise RuntimeError("CAPI reuse must preserve original sample age through crop stability")
 if "m_duoview_gaze.observation()" not in vr:
  raise RuntimeError("Bounded UI-only gaze sensor audit not present in generated production source")
 vr_cpp=(a.backend/"src/mods/VR.cpp").read_text(encoding="utf-8")
 vr_header=(a.backend/"src/mods/VR.hpp").read_text(encoding="utf-8")
 if (".eye_tracked=m_duo_gaze->value()" not in vr_cpp or
     "m_duoview_gaze.read_sample(frozen,optical)" not in vr_cpp or
     "-> uevr::duoview::GazeSample" not in vr_cpp or
     ".temporal_audit=m_duo_history_audit->value()" not in vr_cpp or
     ".smoothing_ms=0.f" not in vr_cpp):
  raise RuntimeError("Stage5 gaze control is not connected to frame source")
 for token in ('m_duo_history_audit->draw(', 'm_duo_shading->draw(', 'm_duo_width->draw(', 'm_duo_height->draw(', 'm_duo_periphery->draw(',
               'm_duo_density->draw(', 'm_duo_feather->draw(', 'm_duo_debug_source->draw('):
  if token not in vr_cpp: raise RuntimeError("DuoView quality UI missing "+token)
 for token in ('"DuoViewCropWidth"', '"DuoViewPeripheralScale"', '"DuoViewFovealDensity"',
               '"DuoViewFoveaSourceView"', '"DuoViewCropSmoothingMs"', '"DuoViewTemporalAudit"'):
  if token not in vr_header: raise RuntimeError("Persisted DuoView setting missing "+token)
 hook=(a.backend/"src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
 if "frame->config.settings.fovea_view" not in hook or "duo_frame->config.settings.fovea_view" not in hook:
  raise RuntimeError("Actual source index and UE projection must follow frozen source-view selection")
 if ("apply_frame_projection(double_matrix,*frame" not in hook or
    "reconcile(init_options_ue5->projection_matrix)" not in hook or
    "can_independent_shading(key,state)" not in hook):
  raise RuntimeError("Actual SceneView constructor must receive the frozen projection")
  raise RuntimeError("Frozen producer projection and guarded shading constructor are required")
 if ".fovea_view=static_cast<uint32_t>(m_duo_fovea_view->value())" not in vr_cpp:
  raise RuntimeError("UE source selector must be connected to immutable frame settings")
 if "vertex_shader_bytecode[]" not in shaders or "pixel_shader_bytecode[]" not in shaders:
  raise RuntimeError("Precompiled DXBC shader arrays missing")
 inputs = sorted(EDITED_BACKEND | ADDED_BACKEND)
 hashes = {"backend":{k:sha(a.backend/k) for k in inputs},
           "frontend":{k:sha(a.frontend/k) for k in sorted(EDITED_FRONTEND)}}
 lock=a.evidence/"duoview-stage234-hashes.json"
 if a.final:
  if json.loads(lock.read_text())!=hashes: raise RuntimeError("Stage 2-4 source mutated during compile")
 else:
  lock.write_text(json.dumps(hashes,indent=2)+"\n")
 print("v46 exact source, UE5.6 temporal bridge, proprietary SDK isolation and source hashes verified.")

if __name__=="__main__":
 main()
