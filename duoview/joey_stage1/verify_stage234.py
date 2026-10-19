#!/usr/bin/env python3
"""Verify exact Stage 2-4 added/edited source and unchanged original SDK."""
import argparse, hashlib, json, subprocess
from pathlib import Path

EDITED_BACKEND = {
 "src/mods/vr/MonoRenderingPolicy.hpp", "src/mods/vr/CompatibilityPolicy.hpp",
 "src/mods/VR.hpp", "src/mods/VR.cpp",
 "src/mods/vr/FFakeStereoRenderingHook.cpp", "src/mods/vr/FFakeStereoRenderingHook.hpp",
 "src/mods/vr/runtimes/OpenXR.cpp", "src/mods/vr/runtimes/OpenXR.hpp",
 "src/mods/vr/D3D12Component.hpp", "src/mods/vr/D3D12Component.cpp", "tests/MonoRenderingTests.hpp",
 "tests/CadenceReplayTests.cpp",
}
ADDED_BACKEND = {
 "src/mods/vr/DuoViewGeometry.hpp", "src/mods/vr/DuoViewGaze.hpp",
 "src/mods/vr/DuoViewPSVR2Gaze.hpp", "src/mods/vr/DuoViewCropStability.hpp",
 "src/mods/vr/DuoViewFrame.hpp", "src/mods/vr/DuoViewConfig.hpp",
 "src/mods/vr/DuoViewState.hpp", "src/mods/vr/DuoViewD3D12.hpp",
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
 state=(a.backend/"src/mods/vr/DuoViewState.hpp").read_text(encoding="utf-8")
 if "native_frame_binding" not in state or "std::optional<uint32_t> mono_source_frame" not in state:
  raise RuntimeError("Production frame state must bind the explicit OpenXR Mono pose token")
 contract=(Path(__file__).parent/"ProductionContractTests.cpp").read_text(encoding="utf-8")
 if "packet_mono_source=37" not in contract or "native_frame_binding(*immutable_packet)" not in contract:
  raise RuntimeError("Production state contract must cover immutable Native packet pose binding")
 shaders=(a.backend/"src/mods/vr/DuoViewShaderSource.hpp").read_text(encoding="utf-8")
 if "D3DCompile(" in compositor or "shader_source" in compositor:
  raise RuntimeError("Runtime shader compiler still in production compositor")
 if "DuoViewPSVR2Gaze.hpp" not in (a.backend/"src/mods/VR.hpp").read_text(encoding="utf-8"):
  raise RuntimeError("Production VR headers missing native PSVR2 gaze integration")
 if "note_duoview_output_path" not in (a.backend/"src/mods/VR.hpp").read_text(encoding="utf-8"):
  raise RuntimeError("XR output path diagnostic is not exposed to the DuoView UI")
 if "note_duoview_source_extents" not in (a.backend/"src/mods/vr/D3D12Component.cpp").read_text(encoding="utf-8"):
  raise RuntimeError("Native source allocation extents are not reported")
 vr_cpp=(a.backend/"src/mods/VR.cpp").read_text(encoding="utf-8")
 vr_header=(a.backend/"src/mods/VR.hpp").read_text(encoding="utf-8")
 if ".eye_tracked=m_duo_gaze->value()" not in vr_cpp or "m_duoview_gaze.read_uv(frozen,optical)" not in vr_cpp:
  raise RuntimeError("Stage5 gaze control is not connected to frame source")
 for token in ('m_duo_stabilize->draw(', 'm_duo_width->draw(', 'm_duo_height->draw(', 'm_duo_periphery->draw(',
               'm_duo_density->draw(', 'm_duo_feather->draw(', 'm_duo_debug_source->draw('):
  if token not in vr_cpp: raise RuntimeError("DuoView quality UI missing "+token)
 for token in ('"DuoViewCropWidth"', '"DuoViewPeripheralScale"', '"DuoViewFovealDensity"',
               '"DuoViewFoveaSourceView"'):
  if token not in vr_header: raise RuntimeError("Persisted DuoView setting missing "+token)
 hook=(a.backend/"src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
 if "frame->config.settings.fovea_view" not in hook or "duo_frame->config.settings.fovea_view" not in hook:
  raise RuntimeError("Actual source index and UE projection must follow frozen source-view selection")
 if "apply_frame_projection(double_matrix,*frame" not in hook or "can_independent_shading(key,state)" not in hook:
  raise RuntimeError("Frozen producer projection and guarded shading constructor are required")
 if ".fovea_view=static_cast<uint32_t>(m_duo_fovea_view->value())" not in vr_cpp:
  raise RuntimeError("UE source selector must be connected to immutable frame settings")
 if "if (is_duoview_renderer_active()) { return true; }" not in vr_header:
  raise RuntimeError("DuoView must force Joey Native Stereo Fix on while active")
 if "if (is_duoview_renderer_active()) {\n        if (!m_duoview.settings().native_fix_same_pass ||" not in vr_cpp:
  raise RuntimeError("DuoView Native Fix relabeling must be opt-in, preserving stock secondary shading when OFF")
 for token in ("m_duoview.settings().native_fix_same_pass",
               "is_native_stereo_fix_preserve_secondary_pass_enabled() const",
               "!m_duoview.settings().native_fix_same_pass) return true"):
  if token not in vr_header: raise RuntimeError("Native fix / stock SECONDARY shading path missing "+token)
 for token in ("DuoViewNativeFixSamePass", "DuoViewQuantizationPixels", "DuoViewGazeHoldMs",
               "DuoViewGazeReacquireSamples", "DuoViewGazeOffsetX", "DuoViewGazeOffsetY"):
  if token not in vr_header: raise RuntimeError("Persisted runtime control missing "+token)
 for token in ("m_duo_native_fix->draw(", "m_duo_quant->draw(", "m_duo_hold->draw(",
               "m_duo_reacquire->draw(", "m_duo_offset_x->draw(", "m_duo_offset_y->draw(",
               "m_duoview_gaze.set_recovery_controls("):
  if token not in vr_cpp: raise RuntimeError("Gaze recovery controls not wired "+token)
 for token in ("uevr::duoview::reconcile_ui_settings(candidate,current)",
               "m_duo_ui_rejected_mask.store(checked.rejected",
               "m_duo_ui_rejected_mask.load(std::memory_order_acquire)",
               "Control warning: one or more requested sliders are invalid",
               "Active Eye Tracking: %s, Native shading: %s"):
  if token not in vr_cpp: raise RuntimeError("General settings validation/status wiring missing: "+token)
 for token in ("m_duo_ui_rejected_mask{0}",):
  if token not in vr_header: raise RuntimeError("General controls audit counter missing: "+token)
 ui_config=(a.backend/"src/mods/vr/DuoViewConfig.hpp").read_text(encoding="utf-8")
 for token in ("UiReconciled reconcile_ui_settings", "reject_width", "reject_still",
               "out.native_fix_same_pass=requested.native_fix_same_pass",
               "out.eye_tracked=requested.eye_tracked"):
  if token not in ui_config: raise RuntimeError("Renderer-wide independent UI validation missing: "+token)
 crop_path=(a.backend/"src/mods/vr/DuoViewCropStability.hpp")
 crop_code=crop_path.read_text(encoding="utf-8")
 for token in ("std::clamp(.5f+s.gaze_offset_u", "std::clamp(.5f+s.gaze_offset_v",
               "if (!s.eye_tracked)"):
  if token not in crop_code: raise RuntimeError("Fixed fovea manual positioning missing "+token)
 for token in ("m_duo_micro_gain->draw(", "m_duo_breakout->draw(",
               "m_duo_stillness->draw(", "m_duo_relock->draw(",
               ".gaze_micro_gain=m_duo_micro_gain->value()",
               ".gaze_breakout_radius=m_duo_breakout->value()",
               ".gaze_still_radius=m_duo_stillness->value()",
               ".gaze_relock_samples=static_cast<uint32_t>(m_duo_relock->value())"):
  if token not in vr_cpp: raise RuntimeError("Adaptive gaze response missing from producer "+token)
 for token in ("DuoViewGazeMicroGain", "DuoViewGazeBreakout",
               "DuoViewGazeStillness", "DuoViewGazeRelockSamples"):
  if token not in vr_header: raise RuntimeError("Adaptive gaze option not persisted "+token)
 crop=(a.backend/"src/mods/vr/DuoViewCropStability.hpp").read_text(encoding="utf-8")
 for token in ("fast_tracking_", "gaze_breakout_radius", "gaze_micro_gain", "gaze_relock_samples", "gaze_still_radius"):
  if token not in crop: raise RuntimeError("Nonlinear gaze breakout/relock contract missing "+token)
 if "bool VR::is_stalker2_native_fix_experiment_enabled() const {\n    if (is_duoview_renderer_active()) { return false; }" not in vr_cpp:
  raise RuntimeError("Unrelated experimental pair submission must stay out of DuoView")
 if "duo_main_target = rtm ? rtm->get_view_family_render_target()" not in hook or "duo_views_readable" not in hook:
  raise RuntimeError("Native split must latch the readable original main pair before one-view callbacks")
 d3d=(a.backend/"src/mods/vr/D3D12Component.cpp").read_text(encoding="utf-8")
 for token in ("native_packet_frame_count = duo_native_active ? vr->m_render_frame_count",
               "get_native_stereo_frame_packet_for_submit(native_packet_frame_count",
               "packet_frame->config.key.generation == vr->mono_generation()",
               "compositor.record_native(", "note_duoview_copy(std::move(pose),packet_frame->config.key.generation)",
               "note_mono_frame_ready(m_mono_generation)"):
  if token not in d3d: raise RuntimeError("Native packet / Mono submit binding missing "+token)
 xr=(a.backend/"src/mods/vr/runtimes/OpenXR.cpp").read_text(encoding="utf-8")
 for token in ("capture_duoview_pose", "duoview_pending_pose", "duoview_continuity.can_hold",
               "duoview_continuity.submitted", "duoview_holding", "selected.frame_state=this->frame_state"):
  if token not in xr: raise RuntimeError("DuoView submit continuity missing "+token)
 auxiliary=hook.index("if (!duo_main_target_present)")
 if not auxiliary < hook.index("capture target is not published",auxiliary) < hook.index("no exact main-family eye pair was proven",auxiliary):
  raise RuntimeError("Auxiliary renderer calls must bypass main-pair invalidation")
 if "packet->main_target!=rtm->get_view_family_render_target()" not in hook:
  raise RuntimeError("Retained DuoView packets must still match the current main target")
 if "note_native_stereo_frame_packet_consumed(packet->serial)" not in d3d:
  raise RuntimeError("DuoView must acknowledge successful Native packet consumption")
 for token in ("duoview_copy_submits", "duoview_hold_submits", "duoview_empty_submits"):
  if token not in xr or token not in vr_cpp: raise RuntimeError("Missing visible delivery counter "+token)
 if "m_duoview_draw_serial.fetch_add(1" not in vr_header or "const auto key = duoview_key();" not in vr_cpp:
  raise RuntimeError("DuoView draw identity must advance independently of XR pose identity")
 if "duoview_key(source_frame" in vr_cpp:
  raise RuntimeError("Repeated XR poses must not alias distinct draw transactions")
 pose_publish=xr.index("if (vr->is_duoview_renderer_active()) pipeline_state.frame_count=frame_count;")
 if not pose_publish < xr.index("mono.pose_frame = frame_count",pose_publish):
  raise RuntimeError("DuoView pipeline token must be published with the located pose")
 capture=hook.index("const auto duo_packet_pose")
 publish=hook.index("const auto publish_native_packet")
 split=hook.index("const auto runtime_frame_count = runtime->internal_frame_count",publish)
 if not capture < publish < split: raise RuntimeError("DuoView pose snapshot must precede renderer split")
 if "packet->duoview_pose_valid" not in d3d or "has_mono_frame(*packet_source)" in d3d:
  raise RuntimeError("DuoView consumer must use the immutable producer pose")
 copy=d3d[d3d.index("bool D3D12Component::OpenXR::copy("):]
 if not copy.index("invalidate_duoview_scene()") < copy.index("xrAcquireSwapchainImage("):
  raise RuntimeError("DuoView history must invalidate before acquiring another scene image")
 pre_acquire=d3d[d3d.index("bool D3D12Component::OpenXR::pre_acquire("):d3d.index("bool D3D12Component::OpenXR::copy(")]
 if not pre_acquire.index("invalidate_duoview_scene()") < pre_acquire.index("xrAcquireSwapchainImage("):
  raise RuntimeError("DuoView history must invalidate before pre-acquisition")
 if "duoview_state().consume(" in d3d:
  raise RuntimeError("Native packet submission must reuse its immutable validated snapshot across Presents")
 # Regression: ID6 may be selected AFTER OpenXR created its swapchains.
 # The command slots must be prepared during the later mode-switch setup.
 for token in ("Prepared {}/{} OpenXR command slots on ID6 entry",
               "if (vr->is_duoview_renderer_active() && vr->get_runtime()->is_openxr())",
               "comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height()",
               "Missing prewarmed compositor for XR command slot",
               "Native compositing rejected: {}"):
  if token not in d3d: raise RuntimeError("Late-activation / failure diagnostic regression: "+token)
 if "Missing prewarmed Native gather atlas" not in compositor:
  raise RuntimeError("Missing Native prewarm failure cannot be diagnosed")
 for token in ("m_duo_direct_xr->draw(", ".direct_xr_output=m_duo_direct_xr->value()",
               "current.direct_xr_output==candidate.direct_xr_output", "Last submitted XR output path"):
  if token not in vr_cpp: raise RuntimeError("Output A/B control/diagnostics missing "+token)
 destroy=d3d[d3d.index("void D3D12Component::OpenXR::destroy_swapchains()"):
              d3d.index("bool D3D12Component::OpenXR::pre_acquire(")]
 if not (destroy.index("commands->poisoned") < destroy.index("this->wait_for_all_copies()") <
         destroy.index("commands->references_retired()") < destroy.index("this->duoview_compositors.clear()") <
         destroy.index("xrDestroySwapchain(")):
  raise RuntimeError("DuoView resources must retire before swapchain destruction")
 if "DuoView command-slot retirement pending; swapchains retained" not in d3d:
  raise RuntimeError("Failed retirement must stop swapchain reconstruction")
 native_warp=(Path(__file__).parent/"ProductionWarpPinned.cpp").read_text(encoding="utf-8")
 for token in ("record_native(", "for (bool srgb : {false,true})", "for (uint32_t fovea_view : {0u,1u})",
               "ID3D12InfoQueue", "oversized_layout"):
  if token not in native_warp: raise RuntimeError("Native compositor WARP coverage missing "+token)
 if ("vertex_shader_bytecode[]" not in shaders or "pixel_shader_bytecode[]" not in shaders or
     "native_pixel_shader_bytecode[]" not in shaders):
  raise RuntimeError("Precompiled DXBC shader arrays missing")
 native_shader=(Path(__file__).parents[1]/"DuoViewNativeCompositeRaster.hlsl").read_text(encoding="utf-8")
 if "outputPixel.x >= OutputSize.x" not in native_shader or "outputPixel.x -= OutputSize.x" not in native_shader:
  raise RuntimeError("Direct-XR double-wide coordinate mapping is missing")
 if compositor.count("DrawInstanced(3,1,0,0)") != 2:
  raise RuntimeError("The direct-XR route must use one draw and the compatibility route one draw")
 for token in ("srv_descriptors_valid_", "srv_first_reference_", "srv_second_reference_",
               "xr_rtv_reference_", "srv_descriptor_refresh_count_", "xr_rtv_refresh_count_",
               "srv_gpu_start_", "direct_xr_rtv_cpu_", "srv_descriptor_increment_"):
  if token not in compositor: raise RuntimeError("Per-slot compositor descriptor reuse missing "+token)
 for token in ("Stable compatibility atlas SRVs were rewritten",
               "Stable Native source/XR descriptors were rewritten",
               "Changed XR target refreshed the wrong descriptor set",
               "Typed Native source mismatch did not use the gather fallback",
               "Repeated Native gather rewrote its cached atlas descriptors",
               "Invalid Native destination recorded GPU commands",
               "Invalid gather destination recorded GPU commands",
               "Route switch reused old GPU timing",
               "Disabled GPU timing retained an old sample"):
  if token not in native_warp: raise RuntimeError("Native descriptor cache WARP coverage missing "+token)
 inputs = sorted(EDITED_BACKEND | ADDED_BACKEND)
 hashes = {"backend":{k:sha(a.backend/k) for k in inputs},
           "frontend":{k:sha(a.frontend/k) for k in sorted(EDITED_FRONTEND)}}
 lock=a.evidence/"duoview-stage234-hashes.json"
 if a.final:
  if json.loads(lock.read_text())!=hashes: raise RuntimeError("Stage 2-4 source mutated during compile")
 else:
  lock.write_text(json.dumps(hashes,indent=2)+"\n")
 print("Stage 2-4 exact source, proprietary SDK isolation and source hashes verified.")

if __name__=="__main__":
 main()

